"""Real single-factor map interpolation using geo-viz-engine plots (IDW / SciPy).

Phase-2 promote-down (map #244 / PR-A #256): the pure interpolation core
(``extract_xy_values`` / ``interpolate_factor_grid`` / ``synthetic_sample_points``
/ ``_grid_axes`` / ``_run_grid`` / ``_leave_one_out_r2``) was promoted to
``geoviz_plots.factor`` and is consumed here through the ``geoviz`` facade.
This module keeps only the ``FactorMapTask`` / ``ProjectDocument``-coupled
adapters (T10: ``project/models.py`` is NOT promoted).

Stage-2 multi-factor path: when several tasks share source XY + grid config +
plain IDW, a single :class:`~paleo_workbench.workflow.interpolation_plan.InterpolationPlan`
is built and values are applied per factor (geometry reuse).

Stage-3 artifact-first ownership:
* ``FactorGridResult`` (live session cache) is the canonical numerical payload
  after interpolation — **not** nested lists on ``task.parameters``.
* Project save externalises the live grid to a managed NPZ artifact; reopen
  uses a warm artifact-backed cache.
* Legacy inline ``parameters[grid_*]`` remains a **read/migrate** path only.

Stage-4 incremental recompute:
* Deterministic scientific fingerprints decide CLEAN vs DIRTY.
* ``batch_prepare_factor_maps(..., force=False)`` skips CLEAN tasks.
* NO CHANGE ⇒ no interpolation, no new artifact rewrite on save of clean outputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any

import logging

import numpy as np

logger = logging.getLogger(__name__)

from geoviz import (  # re-exported for tests / callers — facade only
    extract_xy_values,
    interpolate_factor_grid,
    JobCancelled,
    resolve_anisotropy_params,
    synthetic_sample_points,
)
from paleo_workbench.project.factor_grid_artifacts import (
    GRID_ARRAY_PARAMETER_KEYS,
    clear_live_factor_grid,
    intern_grid_axes,
    peek_live_factor_grid,
    store_live_factor_grid,
)
from paleo_workbench.project.models import (
    FACTOR_TASK_STATUS_COMPLETE,
    FactorMapTask,
    ProjectDocument,
)
from paleo_workbench.workflow.constrained_idw_adapter import (
    CONSTRAINED_IDW_ENGINE_LABEL,
    run_constrained_idw,
)
from paleo_workbench.workflow.constraint_capabilities import (
    ConstraintKind,
    evaluate_request,
)
from paleo_workbench.workflow.constraints import (
    break_polylines_for_idw,
    constraint_layers_for_project,
    direction_line_params,
)
from paleo_workbench.workflow.crs_policy import resolve_distance_policy
from paleo_workbench.workflow.factor_grid_result import (
    FactorGridResult,
    encode_legacy_axis_list,
    encode_legacy_grid_lists,
)
from paleo_workbench.workflow.factor_units import unit_for_factor
from paleo_workbench.workflow.interpolation_evaluation import (
    CrossValidationReport,
    cross_validate_surface,
    kriging_diagnostics,
    kriging_leave_one_out,
    surface_residuals,
)
from paleo_workbench.workflow.interpolation_fingerprint import (
    FactorDirtyState,
    FactorFingerprints,
    classify_factor_recompute,
    fingerprints_for_task,
    plan_cache_get,
    plan_cache_put,
    stamp_fingerprints_on_task,
)
from paleo_workbench.workflow.interpolation_plan import (
    InterpolationPlan,
    apply_idw_plan,
    apply_idw_plan_multi,
    build_idw_plan,
    extract_values_aligned,
    plan_key_from_arrays,
)

# Test / benchmark instrumentation: number of real interpolation executions.
_INTERPOLATION_EXECUTIONS = 0


def reset_interpolation_execution_counter() -> None:
    global _INTERPOLATION_EXECUTIONS
    _INTERPOLATION_EXECUTIONS = 0


def interpolation_execution_count() -> int:
    return int(_INTERPOLATION_EXECUTIONS)


def _count_interpolation_execution() -> None:
    global _INTERPOLATION_EXECUTIONS
    _INTERPOLATION_EXECUTIONS += 1

GENERATOR_VERSION = "factor-interp-v1"
DEFAULT_FACTOR_TYPES = ("地层厚度", "砂岩含量", "砂地比", "泥岩含量")
DEFAULT_GRID_N = 50
MAX_LOO_SAMPLES = 64

# UI label → geo-viz engine method name. 「克里金」now routes to the REAL
# variogram ordinary-kriging backend (geoviz_plots.factor.kriging); the legacy
# MVP label is kept as an alias so old task parameters keep working.
METHOD_LABEL_TO_ENGINE = {
    "克里金": "kriging",
    "克里金(MVP·线性)": "kriging",
    "IDW": "IDW",
    "样条": "样条",
    "方向趋势": "方向趋势",
    # Haiyou constrained-IDW (region barriers + direction corridors + well
    # re-anchoring) is dispatched host-side via run_constrained_idw; the engine
    # method id CONSTRAINED_IDW_ENGINE_LABEL keeps it distinct from plain IDW.
    "约束IDW": CONSTRAINED_IDW_ENGINE_LABEL,
}


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _declared_unit_for_task(task: FactorMapTask) -> str | None:
    """Unit travelling with this task's grid result (M1 unit propagation).

    An explicit ``parameters["unit"]`` declaration wins; otherwise the factor
    defaults authority resolves a known mnemonic. ``None`` means undeclared —
    never guessed from the value range.
    """
    params = task.parameters or {}
    declared = params.get("unit")
    if declared is not None:
        return str(declared) or None
    return unit_for_factor(task.factor_type or task.name)


def _legacy_params_from_grid_result(
    grid_result: FactorGridResult,
    *,
    use_nan_nodata: bool,
) -> dict[str, Any]:
    """Build JSON-friendly inline grid fields from the canonical FactorGridResult."""
    if use_nan_nodata:
        grid_z_lists = [
            [float(v) for v in row]
            for row in np.asarray(grid_result.grid_z, dtype=np.float64)
        ]
    else:
        grid_z_lists = encode_legacy_grid_lists(grid_result.grid_z)
    params: dict[str, Any] = {
        "grid_x": encode_legacy_axis_list(grid_result.grid_x),
        "grid_y": encode_legacy_axis_list(grid_result.grid_y),
        "grid_z": grid_z_lists,
    }
    if grid_result.variance_grid is not None:
        params["grid_var"] = encode_legacy_grid_lists(grid_result.variance_grid)
    if grid_result.boundary is not None:
        params["grid_boundary"] = [
            [float(x), float(y)] for x, y in grid_result.boundary
        ]
    return params


def _none_encode_grid(grid_z: np.ndarray) -> list[list[float | None]]:
    return [
        [None if not math.isfinite(float(v)) else float(v) for v in row]
        for row in np.asarray(grid_z)
    ]


def _attach_result_to_task(
    task: FactorMapTask,
    *,
    result: dict[str, Any],
    grid_result: FactorGridResult,
    method: str,
    power: float,
    points: list,
    grid_n: int,
    breaks: list | None,
    engine_method: str,
    fingerprints: FactorFingerprints | None = None,
    constraint_eval=None,
) -> FactorMapTask:
    """Write live cache + small metadata onto *task* (no full-grid lists).

    Stage-3 artifact-first contract:
    * ``FactorGridResult`` in the live session cache is the canonical numerical
      payload for unsaved tasks.
    * ``task.parameters`` holds only algorithm/input/quality metadata.
    * Full ``grid_x/y/z`` nested lists are *not* materialised on the hot path
      (legacy projects remain readable via ``from_legacy_task_parameters``).
    """
    # Stamp geometry_id for axis interning across multi-factor batches.
    if result.get("geometry_id"):
        grid_result.algorithm_parameters["geometry_id"] = result["geometry_id"]
        # Share frozen axes when already present on result.
        if isinstance(result.get("grid_x"), np.ndarray):
            gx, gy = intern_grid_axes(
                result["grid_x"],
                result["grid_y"],
                geometry_id=str(result["geometry_id"]),
            )
            grid_result.grid_x = gx
            grid_result.grid_y = gy

    if fingerprints is not None:
        for key, value in fingerprints.to_dict().items():
            grid_result.algorithm_parameters[key] = value

    # D5: the planar-distance assumption must travel with the result — a
    # geographic CRS silently treated as metres is exactly the failure mode
    # this annotation makes visible (task metrics + grid parameters + QA).
    policy = resolve_distance_policy(
        grid_result.crs, (task.parameters or {}).get("distance_policy")
    )
    grid_result.algorithm_parameters["distance_policy"] = policy["policy"]
    grid_result.algorithm_parameters["distance_policy_annotation"] = policy["annotation"]

    # V6 §10: the requested/applied/ignored constraint record travels with
    # the grid (algorithm parameters → artifact metadata) AND the task
    # (parameters → provenance) — a dropped constraint can never disappear.
    if constraint_eval is not None:
        grid_result.algorithm_parameters["constraint_diagnostics"] = (
            constraint_eval.as_dict()
        )

    clear_live_factor_grid(task.id)
    store_live_factor_grid(task.id, grid_result)

    params = dict(task.parameters or {})
    # Drop any previous inline grid payload (re-interp or legacy residue).
    for key in GRID_ARRAY_PARAMETER_KEYS:
        params.pop(key, None)
    params.pop("grid_boundary", None)

    params["sample_points"] = list(points)
    params["grid"] = f"{result['grid_n']}×{result['grid_n']}"
    params["interp_backend"] = result["backend"]
    # Prefer the values that actually produced the surface (plan-backed path).
    params["power"] = float(result["power"]) if result.get("power") is not None else power
    if result.get("grid_n") is not None:
        params["grid_n"] = int(result["grid_n"])
    if constraint_eval is not None:
        record = constraint_eval.as_dict()
        # Merge backend-reported ignorances (engine may drop constraints
        # the host routing believed were consumed — V6 §10 single record).
        for entry in result.get("ignored_constraints") or []:
            if entry not in record["constraint_diagnostics"]:
                record["constraint_diagnostics"].append(f"engine:{entry}")
        params["constraint_diagnostics"] = record
        if result.get("kriging_diagnostics"):
            # V6 §11 (review R2-P1): which variogram produced this surface
            # and HOW its parameters were chosen must reach task provenance.
            params["kriging_diagnostics"] = result["kriging_diagnostics"]
    params["n_break_lines"] = result.get("n_break_lines", 0)
    if result.get("n_direction_lines") is not None:
        params["n_direction_lines"] = result.get("n_direction_lines")
    if result.get("grid_var") is not None:
        params["variance_min"] = result.get("variance_min")
        params["variance_max"] = result.get("variance_max")
    if result.get("backend") == "directional":
        params["azimuth_deg"] = result.get("azimuth_deg")
        params["semi_major"] = result.get("semi_major")
        params["semi_minor"] = result.get("semi_minor")
    if breaks and result.get("backend") in ("idw", CONSTRAINED_IDW_ENGINE_LABEL):
        params["break_polylines"] = [
            [[float(x), float(y)] for x, y in poly] for poly in breaks
        ]
    # Small domain ring only (not a full grid).
    if grid_result.boundary is not None:
        params["grid_boundary"] = [
            [float(x), float(y)] for x, y in grid_result.boundary
        ]

    task.parameters = params
    task.method = method if method != "mock" else "IDW"
    task.status = FACTOR_TASK_STATUS_COMPLETE
    # Honesty (audit #848): a synthetic/mock task stays ``mock`` — completing
    # the interpolation must not relabel it ``mixed`` (laundering pure
    # synthetic input as production data for QC/编图 without annotation).
    task.generator_version = GENERATOR_VERSION
    task.grid_metadata = grid_result.to_descriptor()
    # Re-interp invalidates any previous artifact; next project save re-externalises.
    task.grid_artifact_path = None
    task.grid_artifact_version_id = None
    task.quality_metrics = {
        "range": f"{result['min']:.2f} – {result['max']:.2f}",
        "r_squared": result["r_squared"],
        "grid": f"{result['grid_n']}×{result['grid_n']}",
        "n_points": result["n_points"],
        "backend": result["backend"],
        "mean": round(result["mean"], 4),
        "distance_policy": policy["policy"],
    }
    if policy["warning"]:
        task.quality_metrics["distance_warning"] = policy["warning"]
    declared_unit = grid_result.unit
    if declared_unit is not None:
        task.quality_metrics["unit"] = declared_unit
    if result.get("duplicate_wells_dropped"):
        task.quality_metrics["duplicate_wells_dropped"] = int(
            result["duplicate_wells_dropped"]
        )
    if result.get("variance_min") is not None:
        task.quality_metrics["variance_min"] = round(result["variance_min"], 4)
        task.quality_metrics["variance_max"] = round(result["variance_max"], 4)
    if fingerprints is not None:
        stamp_fingerprints_on_task(task, fingerprints)
    else:
        # Fallback: legacy-style hash (should be rare; callers pass fingerprints).
        snapshot = {
            "target_horizon": task.target_horizon,
            "factor_type": task.factor_type,
            "method": task.method,
            "generator_version": GENERATOR_VERSION,
            "sample_points": points,
            "grid_n": grid_n,
            "power": power,
        }
        task.input_snapshot_hash = _snapshot_hash(snapshot)
    return task


def _apply_interpolation_isolated(
    task: FactorMapTask,
    *,
    method: str,
    grid_n: int,
    power: float,
    project: ProjectDocument | None,
    cancellation_token,
    plan: InterpolationPlan | None = None,
    fingerprint_memo: dict | None = None,
) -> FactorMapTask:
    """Run one task's interpolation, isolating engine failures to that task.

    A degenerate task (e.g. fewer sample points than the engine requires) marks
    only itself ``failed`` with a ``last_error`` diagnostic instead of raising
    through the batch and discarding every successfully interpolated task.
    """
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    try:
        return apply_interpolation_to_task(
            task,
            method=method,
            grid_n=grid_n,
            power=power,
            project=project,
            cancellation_token=cancellation_token,
            plan=plan,
            fingerprint_memo=fingerprint_memo,
        )
    except JobCancelled:
        raise
    except Exception as exc:
        task.status = "failed"
        params = dict(task.parameters or {})
        params["last_error"] = f"{type(exc).__name__}: {exc}"
        task.parameters = params
        return task


def interpolation_params_from_task(task: "FactorMapTask") -> tuple[str, int, float]:
    """Recover ``(method, grid_n, power)`` previously recorded on *task*.

    Recompute entry points must re-run a task with ITS OWN algorithm
    parameters, not the function defaults (#919): ``task.method`` and the
    ``grid_n``/``power`` keys written by :func:`_attach_result_to_task` are
    the recorded truth; anything missing falls back to the same defaults the
    preparation page starts from.
    """
    params = dict(getattr(task, "parameters", None) or {})
    method = str(
        params.get("method")
        or getattr(task, "method", None)
        or "IDW"
    )
    try:
        grid_n = max(8, int(params.get("grid_n") or DEFAULT_GRID_N))
    except (TypeError, ValueError):
        grid_n = DEFAULT_GRID_N
    try:
        power = float(params.get("power") or 2.0)
    except (TypeError, ValueError):
        power = 2.0
    return method, grid_n, power


def _requested_constraint_kinds(
    *,
    layers,
    breaks,
    directions,
    points: list,
    task: FactorMapTask,
) -> list[ConstraintKind]:
    """Which geological constraints the user actually asked for (V6 §10)."""
    from paleo_workbench.workflow.constraints import boundary_rings_for_engine

    kinds: list[ConstraintKind] = []
    if breaks:
        kinds.append(ConstraintKind.BARRIER)
    if directions:
        kinds.append(ConstraintKind.DIRECTION)
        kinds.append(ConstraintKind.ANISOTROPY)
    if layers is not None and boundary_rings_for_engine(
        layers, target_horizon=task.target_horizon
    ):
        kinds.append(ConstraintKind.BOUNDARY_MASK)
    params = task.parameters or {}
    if params.get("azimuth_deg") is not None and not directions:
        kinds.append(ConstraintKind.ANISOTROPY)
    if any(
        isinstance(pt, dict) and (pt.get("q") is not None or pt.get("b_i") is not None)
        for pt in points
    ):
        kinds.append(ConstraintKind.TREND)
    seen: set[ConstraintKind] = set()
    unique: list[ConstraintKind] = []
    for kind in kinds:
        if kind not in seen:
            seen.add(kind)
            unique.append(kind)
    return unique


def apply_interpolation_to_task(
    task: FactorMapTask,
    *,
    method: str = "IDW",
    grid_n: int = DEFAULT_GRID_N,
    power: float = 2.0,
    project: ProjectDocument | None = None,
    fault_polylines: list[list[tuple[float, float]]] | None = None,
    cancellation_token=None,
    plan: InterpolationPlan | None = None,
    fingerprint_memo: dict | None = None,
) -> FactorMapTask:
    """Mutate a FactorMapTask with a real interpolation grid and quality metrics.

    When *project* is provided:
      - active break lines → IDW fault barriers (unless *fault_polylines* given)
      - active direction lines → anisotropy for method 「方向趋势」

    Optional *plan* reuses a pre-built plain-IDW spatial plan (batch multi-factor).
    Single-task calls leave *plan* as ``None`` and keep the original simple path.
    """
    params = dict(task.parameters or {})
    points = params.get("sample_points") or []
    breaks = fault_polylines
    az, a_axis, b_axis = 0.0, 1.0, 0.4
    layers = None
    if project is not None:
        layers = constraint_layers_for_project(
            project, target_horizon=task.target_horizon
        )
        if breaks is None:
            breaks = break_polylines_for_idw(layers, target_horizon=task.target_horizon)
        az, a_axis, b_axis = resolve_anisotropy_params(
            direction_line_params(layers, target_horizon=task.target_horizon)
        )
    if params.get("azimuth_deg") is not None:
        try:
            az = float(params["azimuth_deg"])
        except (TypeError, ValueError):
            pass
    if params.get("semi_major") is not None:
        try:
            a_axis = float(params["semi_major"])
        except (TypeError, ValueError):
            pass
    if params.get("semi_minor") is not None:
        try:
            b_axis = float(params["semi_minor"])
        except (TypeError, ValueError):
            pass

    engine_method = METHOD_LABEL_TO_ENGINE.get(method, method)
    crs = project.coordinate.project_crs if project is not None else None
    directions = (
        direction_line_params(layers, target_horizon=task.target_horizon)
        if layers is not None
        else None
    )
    # V6 §10: evaluate the REQUESTED constraints against the method's
    # capability matrix BEFORE interpolating — a constraint the backend
    # drops (faults + kriging, boundary + plain IDW, …) is reported on the
    # result, never silent (audit P0-6).
    requested_kinds = _requested_constraint_kinds(
        layers=layers, breaks=breaks, directions=directions, points=points, task=task
    )
    constraint_eval = evaluate_request(engine_method, requested_kinds)
    for diagnostic in constraint_eval.diagnostics:
        logger.warning("factor interpolation %s [%s]: %s", task.name, method, diagnostic)
    fps = fingerprints_for_task(
        task,
        project=project,
        method=method,
        grid_n=grid_n,
        power=power,
        fault_polylines=breaks,
        generator_version=GENERATOR_VERSION,
        memo=fingerprint_memo,
    )

    _count_interpolation_execution()

    # --- plan-backed plain IDW (geometry shared across factors) ---------------
    if plan is not None and engine_method in ("IDW", "idw", "mock"):
        values = extract_values_aligned(points, plan)
        # Plan path prioritises multi-factor throughput; LOO R² is omitted
        # (None), matching the documented InterpolationPlan contract.
        result = apply_idw_plan(plan, values, cancellation_token=cancellation_token)
        grid_result = FactorGridResult.from_engine_dict(
            {
                **result,
                "grid_x": np.asarray(result["grid_x"]),
                "grid_y": np.asarray(result["grid_y"]),
                "grid_z": result["grid_z"],
            },
            factor_name=task.factor_type or task.name,
            crs=crs,
            unit=_declared_unit_for_task(task),
            generator_version=GENERATOR_VERSION,
            source_refs=task.input_resource_ids,
        )
        return _attach_result_to_task(
            task,
            result=result,
            grid_result=grid_result,
            method=method,
            power=power,
            points=points,
            grid_n=grid_n,
            breaks=breaks,
            engine_method="IDW",
            fingerprints=fps,
            constraint_eval=constraint_eval,
        )

    if engine_method == CONSTRAINED_IDW_ENGINE_LABEL:
        result = run_constrained_idw(
            points,
            grid_n=grid_n,
            power=power,
            layers=layers,
            target_horizon=task.target_horizon,
            break_polylines=breaks,
            cancellation_token=cancellation_token,
            crs=crs,
        )
        grid_result = FactorGridResult.from_constrained_idw_dict(
            result,
            factor_name=task.factor_type or task.name,
            crs=crs,
            unit=_declared_unit_for_task(task),
            generator_version=GENERATOR_VERSION,
            source_refs=task.input_resource_ids,
        )
    else:
        # V6 §11: explicit variogram controls travel from the task/UI —
        # model choice, range, nugget (None = auto-fit, which the engine
        # now REPORTS instead of silently performing).
        variogram_kwargs: dict[str, Any] = {}
        for src_key, dst_key in (
            ("variogram_model", "variogram_model"),
            ("variogram_range", "variogram_range"),
            ("variogram_nugget", "variogram_nugget"),
            ("range_m", "variogram_range"),
            ("nugget", "variogram_nugget"),
        ):
            value = params.get(src_key)
            if value is not None:
                variogram_kwargs[dst_key] = value
        result = interpolate_factor_grid(
            points,
            method=engine_method,
            grid_n=grid_n,
            power=power,
            fault_polylines=breaks,
            azimuth_deg=az,
            semi_major=a_axis,
            semi_minor=b_axis,
            cancellation_token=cancellation_token,
            **variogram_kwargs,
        )
        grid_result = FactorGridResult.from_engine_dict(
            result,
            factor_name=task.factor_type or task.name,
            crs=crs,
            unit=_declared_unit_for_task(task),
            generator_version=GENERATOR_VERSION,
            source_refs=task.input_resource_ids,
        )

    return _attach_result_to_task(
        task,
        result=result,
        grid_result=grid_result,
        method=method,
        power=power,
        points=points,
        grid_n=grid_n,
        breaks=breaks,
        engine_method=engine_method,
        fingerprints=fps,
        constraint_eval=constraint_eval,
    )


def _task_plan_group_key(
    task: FactorMapTask,
    *,
    method: str,
    grid_n: int,
    power: float,
    project: ProjectDocument | None,
) -> str | None:
    """Return a plan digest for plain-IDW tasks that can share geometry, else None."""
    engine_method = METHOD_LABEL_TO_ENGINE.get(method, method)
    if engine_method not in ("IDW", "idw", "mock"):
        return None
    points = (task.parameters or {}).get("sample_points") or []
    x, y, z = extract_xy_values(points)
    if len(z) < 2:
        return None
    breaks = None
    if project is not None:
        layers = constraint_layers_for_project(
            project, target_horizon=task.target_horizon
        )
        breaks = break_polylines_for_idw(layers, target_horizon=task.target_horizon)
    key = plan_key_from_arrays(
        method="idw",
        x=x,
        y=y,
        grid_n=grid_n,
        power=power,
        fault_polylines=breaks,
    )
    return key.digest()


def batch_prepare_factor_maps(
    project: ProjectDocument,
    *,
    method: str = "IDW",
    target_horizon: str | None = None,
    factor_types: list[str] | tuple[str, ...] | None = None,
    grid_n: int = DEFAULT_GRID_N,
    seed: int = 0,
    power: float = 2.0,
    force: bool = False,
    cancellation_token=None,
    fingerprint_memo: dict | None = None,
) -> list[FactorMapTask]:
    """Run real interpolation for existing tasks or create default factor maps.

    Stage-4 incremental behaviour (``force=False``, default):
    * build scientific fingerprints per task;
    * skip CLEAN tasks (no interpolation, artifact left intact);
    * recompute only DIRTY / MISSING / UNKNOWN tasks;
    * dirty plain-IDW tasks still share :class:`InterpolationPlan` / multi-value path.

    ``force=True`` recomputes every prepared task (debug / migration escape hatch).

    ``fingerprint_memo`` (optional, request-scoped dict) lets a caller share
    one per-task fingerprint derivation across the classify / plan-key / apply
    phases instead of re-serializing and re-hashing every sample 3x per task.

    Returns the list of tasks considered by this call (clean + dirty).
    """
    fp_memo = fingerprint_memo if fingerprint_memo is not None else {}
    horizon = (
        target_horizon
        or project.stratigraphy.target_horizon
        or (project.factor_map_tasks[0].target_horizon if project.factor_map_tasks else "")
        or "未指定层位"
    )
    prepared: list[FactorMapTask] = []

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    if not project.factor_map_tasks:
        types = list(factor_types or DEFAULT_FACTOR_TYPES)
        for index, factor_type in enumerate(types):
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            points = synthetic_sample_points(
                seed=seed + index, factor_type=factor_type
            )
            task = FactorMapTask(
                name=f"{horizon} {factor_type}",
                target_horizon=horizon,
                factor_type=factor_type,
                method=method,
                parameters={"sample_points": points},
                status="pending",
                source_kind="mock",  # pure synthetic input — never "mixed" (audit #848)
                seed=seed + index,
            )
            project.factor_map_tasks.append(task)
            prepared.append(task)
        # Fall through to group-based prepare below
    else:
        for task in project.factor_map_tasks:
            params = task.parameters or {}
            points = params.get("sample_points") or []
            if not points:
                points = synthetic_sample_points(
                    seed=(task.seed if task.seed is not None else seed),
                    factor_type=task.factor_type or task.name,
                )
                task.parameters = {**params, "sample_points": points}
            prepared.append(task)

    # --- Classify CLEAN vs DIRTY before any interpolation --------------------
    dirty: list[FactorMapTask] = []
    for task in prepared:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        fps = fingerprints_for_task(
            task,
            project=project,
            method=method,
            grid_n=grid_n,
            power=power,
            generator_version=GENERATOR_VERSION,
            memo=fp_memo,
        )
        state = classify_factor_recompute(task, fps, force=force)
        if state is FactorDirtyState.CLEAN:
            continue
        dirty.append(task)

    if not dirty:
        return prepared

    # Group *dirty* plain-IDW tasks that share geometry; others run independently.
    groups: dict[str | None, list[FactorMapTask]] = defaultdict(list)
    for task in dirty:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        gkey = _task_plan_group_key(
            task, method=method, grid_n=grid_n, power=power, project=project
        )
        groups[gkey].append(task)

    for gkey, tasks in groups.items():
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        plan: InterpolationPlan | None = None
        if gkey is not None and len(tasks) >= 1:
            # Build plan from the first task's samples + project breaks.
            first = tasks[0]
            pts = (first.parameters or {}).get("sample_points") or []
            breaks = None
            if project is not None:
                layers = constraint_layers_for_project(
                    project, target_horizon=first.target_horizon
                )
                breaks = break_polylines_for_idw(
                    layers, target_horizon=first.target_horizon
                )
            # Session plan cache keyed by geometry + algorithm fingerprints of
            # the first dirty task. Power lives in the ALGORITHM fingerprint
            # (not geometry), so including both is what makes a power change
            # rebuild the plan instead of silently reusing the old-power grid.
            geo_key = None
            try:
                fingerprints = fingerprints_for_task(
                    first,
                    project=project,
                    method=method,
                    grid_n=grid_n,
                    power=power,
                    generator_version=GENERATOR_VERSION,
                    memo=fp_memo,
                )
                geo_key = f"{fingerprints.geometry}:{fingerprints.algorithm}"
                plan = plan_cache_get(geo_key)
            except Exception:
                plan = None
            if plan is None:
                try:
                    plan = build_idw_plan(
                        pts, grid_n=grid_n, power=power, fault_polylines=breaks
                    )
                    if geo_key:
                        plan_cache_put(geo_key, plan)
                except ValueError:
                    plan = None

        # Multi-factor vectorised path: one distance/weight pass for the group.
        if (
            plan is not None
            and len(tasks) >= 2
            and METHOD_LABEL_TO_ENGINE.get(method, method) in ("IDW", "idw", "mock")
        ):
            stack_rows: list[np.ndarray] = []
            aligned_tasks: list[FactorMapTask] = []
            for task in tasks:
                try:
                    vals = extract_values_aligned(
                        (task.parameters or {}).get("sample_points") or [], plan
                    )
                except ValueError:
                    _apply_interpolation_isolated(
                        task,
                        method=method,
                        grid_n=grid_n,
                        power=power,
                        project=project,
                        cancellation_token=cancellation_token,
                        fingerprint_memo=fp_memo,
                    )
                    continue
                stack_rows.append(vals)
                aligned_tasks.append(task)
            if aligned_tasks:
                _count_interpolation_execution()
                results = apply_idw_plan_multi(
                    plan,
                    np.stack(stack_rows, axis=0),
                    cancellation_token=cancellation_token,
                )
                crs = project.coordinate.project_crs
                for task, result in zip(aligned_tasks, results):
                    if cancellation_token is not None:
                        cancellation_token.raise_if_cancelled()
                    fps = fingerprints_for_task(
                        task,
                        project=project,
                        method=method,
                        grid_n=grid_n,
                        power=power,
                        generator_version=GENERATOR_VERSION,
                        memo=fp_memo,
                    )
                    grid_result = FactorGridResult.from_engine_dict(
                        {
                            **result,
                            "grid_x": np.asarray(result["grid_x"]),
                            "grid_y": np.asarray(result["grid_y"]),
                            "grid_z": result["grid_z"],
                        },
                        factor_name=task.factor_type or task.name,
                        crs=crs,
                        unit=_declared_unit_for_task(task),
                        generator_version=GENERATOR_VERSION,
                        source_refs=task.input_resource_ids,
                    )
                    batch_layers = (
                        constraint_layers_for_project(
                            project, target_horizon=task.target_horizon
                        )
                        if project is not None
                        else None
                    )
                    batch_eval = evaluate_request(
                        "IDW",
                        _requested_constraint_kinds(
                            layers=batch_layers,
                            breaks=plan.fault_polylines,
                            directions=(
                                direction_line_params(
                                    batch_layers, target_horizon=task.target_horizon
                                )
                                if batch_layers is not None
                                else None
                            ),
                            points=(task.parameters or {}).get("sample_points") or [],
                            task=task,
                        ),
                    )
                    _attach_result_to_task(
                        task,
                        result=result,
                        grid_result=grid_result,
                        method=method,
                        power=power,
                        points=(task.parameters or {}).get("sample_points") or [],
                        grid_n=grid_n,
                        breaks=plan.fault_polylines,
                        engine_method="IDW",
                        fingerprints=fps,
                        constraint_eval=batch_eval,
                    )
            continue

        for task in tasks:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            use_plan = plan
            if use_plan is not None:
                try:
                    extract_values_aligned(
                        (task.parameters or {}).get("sample_points") or [], use_plan
                    )
                except ValueError:
                    use_plan = None
            _apply_interpolation_isolated(
                task,
                method=method,
                grid_n=grid_n,
                power=power,
                project=project,
                cancellation_token=cancellation_token,
                plan=use_plan if METHOD_LABEL_TO_ENGINE.get(method, method) in (
                    "IDW", "idw", "mock"
                ) else None,
                fingerprint_memo=fp_memo,
            )
    return prepared


# --------------------------------------------------------------------------- #
# M2 workstation V2 — accuracy evaluation attached to a prepared task
# --------------------------------------------------------------------------- #


def _engine_run_fold_for_task(
    task: FactorMapTask,
    *,
    engine_method: str,
    grid_n: int,
    power: float,
    breaks: list | None,
    az: float,
    a_axis: float,
    b_axis: float,
    layers,
    target_horizon: str | None,
    cancellation_token,
):
    """Build the production-mirroring ``run_fold(points)`` closure for CV.

    The closure routes through the SAME engine entry the real interpolation
    uses, so cross-validation scores the production maths, never a lookalike.
    """
    if engine_method == CONSTRAINED_IDW_ENGINE_LABEL:
        # Local import keeps the heavy vendored engine off the module path
        # unless a constrained task is actually cross-validated.
        from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw

        def run_fold(train_points):
            result = run_constrained_idw(
                list(train_points),
                grid_n=grid_n,
                power=power,
                layers=layers,
                target_horizon=target_horizon,
                break_polylines=breaks,
                cancellation_token=cancellation_token,
            )
            return result["grid_x"], result["grid_y"], result["grid_z"]

        return run_fold

    def run_fold(train_points):
        result = interpolate_factor_grid(
            list(train_points),
            method=engine_method,
            grid_n=grid_n,
            power=power,
            fault_polylines=breaks,
            azimuth_deg=az,
            semi_major=a_axis,
            semi_minor=b_axis,
            cancellation_token=cancellation_token,
        )
        return result["grid_x"], result["grid_y"], result["grid_z"]

    return run_fold


def cross_validate_factor_task(
    task: FactorMapTask,
    *,
    project: ProjectDocument | None = None,
    k: int = 4,
    cancellation_token=None,
    include_diagnostics: bool = False,
) -> tuple[CrossValidationReport | None, dict[str, Any] | None]:
    """Cross-validate ONE task's factor surface with its own production settings.

    Kriging uses the exact closed-form LOO (scheme ``loo_exact``); every other
    method uses deterministic spatial K-fold surface CV through the production
    engine path. Returns ``(report, kriging_diagnostics)``; ``report`` is
    ``None`` when there is too little data to evaluate honestly.
    """
    params = dict(task.parameters or {})
    points = params.get("sample_points") or []
    method, recorded_grid_n, power = interpolation_params_from_task(task)
    engine_method = METHOD_LABEL_TO_ENGINE.get(method, method)
    grid_n = recorded_grid_n if recorded_grid_n else DEFAULT_GRID_N

    breaks = None
    az, a_axis, b_axis = 0.0, 1.0, 0.4
    layers = None
    if project is not None:
        layers = constraint_layers_for_project(
            project, target_horizon=task.target_horizon
        )
        breaks = break_polylines_for_idw(layers, target_horizon=task.target_horizon)
        az, a_axis, b_axis = resolve_anisotropy_params(
            direction_line_params(layers, target_horizon=task.target_horizon)
        )

    diagnostics: dict[str, Any] | None = None
    if engine_method == "kriging":
        report = kriging_leave_one_out(
            points, cancellation_token=cancellation_token
        )
        if report is not None:
            report.method = method
        if include_diagnostics:
            diagnostics = kriging_diagnostics(points)
        return report, diagnostics

    report = cross_validate_surface(
        points,
        run_fold=_engine_run_fold_for_task(
            task,
            engine_method=engine_method,
            grid_n=grid_n,
            power=power,
            breaks=breaks,
            az=az,
            a_axis=a_axis,
            b_axis=b_axis,
            layers=layers,
            target_horizon=task.target_horizon,
            cancellation_token=cancellation_token,
        ),
        k=k,
        method_label=method,
        engine=engine_method,
        cancellation_token=cancellation_token,
    )
    return report, None


def attach_surface_check(
    task: FactorMapTask,
) -> dict[str, Any] | None:
    """Record how the delivered surface reproduces its own sample points.

    In-sample by definition (anchoring fidelity for re-anchoring engines) —
    stored under ``surface_check`` and never presented as cross-validated
    accuracy.
    """
    grid = peek_live_factor_grid(task.id)
    if grid is None:
        return None
    points = (task.parameters or {}).get("sample_points") or []
    records, metrics = surface_residuals(points, grid.grid_x, grid.grid_y, grid.grid_z)
    payload = {
        "kind": "in_sample_surface_check",
        **metrics.to_dict(),
        "residuals": records,
    }
    task.quality_metrics["surface_check"] = {
        key: value for key, value in payload.items() if key != "residuals"
    }
    task.quality_metrics["surface_residuals"] = records
    return payload


def attach_cross_validation(
    task: FactorMapTask,
    *,
    project: ProjectDocument | None = None,
    k: int = 4,
    cancellation_token=None,
    include_diagnostics: bool = False,
) -> CrossValidationReport | None:
    """Evaluate a prepared task and write RMSE/MAE/bias + CV into its metrics.

    The production ``r_squared`` key keeps its existing meaning (whoever set
    it wins); cross-validated metrics land under ``cv`` / ``cv_rmse`` /
    ``cv_mae`` / ``cv_bias`` so the two are never conflated.
    """
    report, diagnostics = cross_validate_factor_task(
        task,
        project=project,
        k=k,
        cancellation_token=cancellation_token,
        include_diagnostics=include_diagnostics,
    )
    if report is not None:
        task.quality_metrics["cv"] = report.to_dict()
        metrics = report.metrics.to_dict()
        for key in ("rmse", "mae", "bias"):
            if metrics.get(key) is not None:
                task.quality_metrics[f"cv_{key}"] = round(metrics[key], 6)
    if diagnostics is not None:
        task.quality_metrics["kriging_diagnostics"] = diagnostics
    attach_surface_check(task)
    return report
