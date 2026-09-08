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
from typing import Any, Mapping

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
from paleo_workbench.workflow.sample_normalization import (
    SampleNormalizationReport,
    duplicate_policy_from_params,
    normalize_factor_samples,
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
    raw_points: list | None = None,
    grid_n: int,
    breaks: list | None,
    engine_method: str,
    fingerprints: FactorFingerprints | None = None,
    constraint_eval=None,
    normalization: SampleNormalizationReport | None = None,
    project: ProjectDocument | None = None,
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

    # V8 M3: the RAW sample set stays the provenance record; the duplicate
    # policy + merge accounting travel beside it so twin wells can neither
    # double-vote nor silently vanish.
    if normalization is not None:
        params["sample_normalization"] = normalization.to_dict()
    params["sample_points"] = list(raw_points if raw_points is not None else points)
    # V8 M2: pin the constraint state this surface was computed against
    # (content hashes; version ids bind at commit time). Freshness compares
    # pins against later commits — a changed constraint marks exactly the
    # tasks that consumed it.
    if project is not None:
        try:
            from paleo_workbench.workflow.constraint_versions import (
                constraint_pins_for_task,
            )

            pins = constraint_pins_for_task(task, project)
            if pins:
                params["constraint_pins"] = pins
            else:
                params.pop("constraint_pins", None)
        except Exception:  # noqa: BLE001 — pinning must never break an interp
            logger.debug("constraint pinning skipped", exc_info=True)
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
    if normalization is not None and normalization.duplicates_present:
        task.quality_metrics["duplicate_locations_merged"] = (
            normalization.n_duplicate_groups
        )
        task.quality_metrics["duplicate_samples_merged"] = (
            normalization.n_duplicates_merged
        )
        task.quality_metrics["duplicate_policy"] = normalization.policy
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


def variogram_settings_from_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """Explicit variogram controls recorded on a task (single authority).

    Returns the ``interpolate_factor_grid`` vocabulary
    (``variogram_model`` / ``variogram_range`` / ``variogram_nugget``);
    empty dict = auto-fit. Production interpolation AND cross-validation
    both read this — CV must score the same variogram the surface used.
    """
    settings: dict[str, Any] = {}
    for src_key, dst_key in (
        ("variogram_model", "variogram_model"),
        ("variogram_range", "variogram_range"),
        ("variogram_nugget", "variogram_nugget"),
        ("range_m", "variogram_range"),
        ("nugget", "variogram_nugget"),
    ):
        value = (params or {}).get(src_key)
        if value is not None:
            settings[dst_key] = value
    return settings


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
    raw_points = params.get("sample_points") or []
    # V8 M3: one duplicate policy, applied before ANY consumer (engine,
    # fingerprints, CV, constraints) — twin wells no longer double-vote in
    # plain IDW, and CV scores exactly the sample set production uses.
    normalization: SampleNormalizationReport | None
    points, normalization = normalize_factor_samples(
        raw_points, policy=duplicate_policy_from_params(params)
    )
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
            raw_points=raw_points,
            grid_n=grid_n,
            breaks=breaks,
            engine_method="IDW",
            fingerprints=fps,
            constraint_eval=constraint_eval,
            normalization=normalization,
            project=project,
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
        variogram_kwargs = variogram_settings_from_params(params)
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
        raw_points=raw_points,
        grid_n=grid_n,
        breaks=breaks,
        engine_method=engine_method,
        fingerprints=fps,
        constraint_eval=constraint_eval,
        normalization=normalization,
        project=project,
    )


def _normalized_points_for(task: FactorMapTask) -> tuple[list[dict[str, Any]], SampleNormalizationReport]:
    """Apply the task's duplicate policy to its raw sample set."""
    params = task.parameters or {}
    return normalize_factor_samples(
        params.get("sample_points") or [],
        policy=duplicate_policy_from_params(params),
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
    params = task.parameters or {}
    points, _report = normalize_factor_samples(
        params.get("sample_points") or [],
        policy=duplicate_policy_from_params(params),
    )
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
        try:
            fps = fingerprints_for_task(
                task,
                project=project,
                method=method,
                grid_n=grid_n,
                power=power,
                generator_version=GENERATOR_VERSION,
                memo=fp_memo,
            )
        except ValueError as exc:
            # e.g. duplicate_policy='error' met real duplicates: fail ONLY
            # this task (review R1-P1) — one strict task must not abort the
            # whole batch before any interpolation happens.
            task.status = "failed"
            task.parameters = {
                **(task.parameters or {}),
                "last_error": f"{type(exc).__name__}: {exc}",
            }
            continue
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
        try:
            gkey = _task_plan_group_key(
                task, method=method, grid_n=grid_n, power=power, project=project
            )
        except ValueError as exc:
            task.status = "failed"
            task.parameters = {
                **(task.parameters or {}),
                "last_error": f"{type(exc).__name__}: {exc}",
            }
            continue
        groups[gkey].append(task)

    for gkey, tasks in groups.items():
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        plan: InterpolationPlan | None = None
        if gkey is not None and len(tasks) >= 1:
            # Build plan from the first task's samples + project breaks.
            first = tasks[0]
            first_params = first.parameters or {}
            pts, _norm = normalize_factor_samples(
                first_params.get("sample_points") or [],
                policy=duplicate_policy_from_params(first_params),
            )
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
            aligned_tasks: list[tuple[FactorMapTask, list, Any]] = []
            for task in tasks:
                try:
                    pts, norm = _normalized_points_for(task)
                    vals = extract_values_aligned(pts, plan)
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
                # keep EACH task's own normalized points + report — the
                # attach loop used to stamp the LAST task's pair on every
                # task (review R1-P1: wrong duplicate accounting + trend
                # detection against the wrong sample set).
                aligned_tasks.append((task, pts, norm))
            if aligned_tasks:
                _count_interpolation_execution()
                results = apply_idw_plan_multi(
                    plan,
                    np.stack(stack_rows, axis=0),
                    cancellation_token=cancellation_token,
                )
                crs = project.coordinate.project_crs
                for (task, pts, norm), result in zip(aligned_tasks, results):
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
                            points=pts,
                            task=task,
                        ),
                    )
                    _attach_result_to_task(
                        task,
                        result=result,
                        grid_result=grid_result,
                        method=method,
                        power=power,
                        points=pts,
                        raw_points=(task.parameters or {}).get("sample_points") or [],
                        grid_n=grid_n,
                        breaks=plan.fault_polylines,
                        engine_method="IDW",
                        fingerprints=fps,
                        constraint_eval=batch_eval,
                        normalization=norm,
                        project=project,
                    )
            continue

        for task in tasks:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            use_plan = plan
            if use_plan is not None:
                try:
                    pts, _norm = _normalized_points_for(task)
                    extract_values_aligned(pts, use_plan)
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
    crs: str | None = None,
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
                # V8 M4: crs travels with the fold exactly as with production —
                # a geographic CRS converts the barrier buffer in BOTH paths or
                # the CV scores a different surface than the delivered one.
                crs=crs,
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

    Kriging uses the exact closed-form LOO (scheme ``loo_exact``) with the
    SAME variogram model/range/nugget and anisotropy the production surface
    used; every other method uses deterministic spatial K-fold surface CV
    through the production engine path. Returns ``(report,
    kriging_diagnostics)``; ``report`` is ``None`` when there is too little
    data to evaluate honestly.
    """
    params = dict(task.parameters or {})
    raw_points = params.get("sample_points") or []
    # CV must score the SAME normalized sample set production interpolates.
    points, _norm = normalize_factor_samples(
        raw_points, policy=duplicate_policy_from_params(params)
    )
    method, recorded_grid_n, power = interpolation_params_from_task(task)
    engine_method = METHOD_LABEL_TO_ENGINE.get(method, method)
    grid_n = recorded_grid_n if recorded_grid_n else DEFAULT_GRID_N

    breaks = None
    az, a_axis, b_axis = 0.0, 1.0, 0.4
    layers = None
    crs = project.coordinate.project_crs if project is not None else None
    if project is not None:
        layers = constraint_layers_for_project(
            project, target_horizon=task.target_horizon
        )
        breaks = break_polylines_for_idw(layers, target_horizon=task.target_horizon)
        az, a_axis, b_axis = resolve_anisotropy_params(
            direction_line_params(layers, target_horizon=task.target_horizon)
        )
    # Explicit per-task anisotropy overrides (production parity).
    for key, setter in (("azimuth_deg", "az"), ("semi_major", "a"), ("semi_minor", "b")):
        value = params.get(key)
        if value is None:
            continue
        try:
            if setter == "az":
                az = float(value)
            elif setter == "a":
                a_axis = float(value)
            else:
                b_axis = float(value)
        except (TypeError, ValueError):
            pass

    diagnostics: dict[str, Any] | None = None
    if engine_method == "kriging":
        # V8 M4: the LOO scores the production variogram — same model, same
        # explicit range/nugget, same geometric anisotropy (coordinate frame
        # transform), NOT the engine defaults.
        settings = variogram_settings_from_params(params)
        variogram_kwargs: dict[str, Any] = {}
        if "variogram_model" in settings:
            variogram_kwargs["variogram_model"] = settings["variogram_model"]
        if settings.get("variogram_range") is not None:
            variogram_kwargs["range_"] = float(settings["variogram_range"])
        if settings.get("variogram_nugget") is not None:
            variogram_kwargs["nugget"] = float(settings["variogram_nugget"])
        # Mirror the engine's anisotropy_requested gate exactly: the
        # DEFAULTS (az=0, axes 1.0/0.4) mean "unset" — production runs
        # ISOTROPIC kriging then, and the LOO must score that same model
        # (review R1-P0: the raw ratio 2.5 stretched the CV frame while the
        # delivered surface was isotropic).
        anisotropy_requested = (
            az not in (None, 0.0)
            or (float(a_axis), float(b_axis)) != (1.0, 0.4)
        )
        anisotropy_kwargs: dict[str, Any] = {}
        if anisotropy_requested:
            ratio = float(a_axis) / float(b_axis) if b_axis else 1.0
            if ratio > 1.0 + 1e-9:
                anisotropy_kwargs = {
                    "azimuth_deg": float(az or 0.0),
                    "anisotropy_ratio": ratio,
                }
        report = kriging_leave_one_out(
            points,
            cancellation_token=cancellation_token,
            **variogram_kwargs,
            **anisotropy_kwargs,
        )
        if report is not None:
            report.method = method
        if include_diagnostics:
            diagnostics = kriging_diagnostics(
                points,
                variogram_model=str(
                    variogram_kwargs.get("variogram_model", "spherical")
                ),
            )
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
            crs=crs,
        ),
        k=k,
        method_label=method,
        engine=engine_method,
        cancellation_token=cancellation_token,
    )
    return report, None


def evaluate_methods_for_task(
    task: FactorMapTask,
    *,
    project: ProjectDocument | None = None,
    methods: list[str] | None = None,
    k: int = 4,
    requested_constraints: list[str] | None = None,
    cancellation_token=None,
) -> dict[str, Any]:
    """Real per-method evaluation with EACH method's production settings (V8 M4).

    Unlike the V6 proxy action (one IDW fold engine for every method), every
    method is scored through its own production path: kriging via exact LOO
    with the production variogram + anisotropy, constrained-IDW / IDW /
    others via spatial K-fold through the same engine entries the delivered
    surface uses. The report carries the V8 fail-closed gates (unknown unit,
    invalid CRS, unknown constraint names) and honest scheme caveats when
    methods were evaluated under different protocols (LOO vs K-fold).
    """
    from paleo_workbench.workflow.interpolation_evaluation import (
        _validate_recommendation_context,
    )
    from paleo_workbench.workflow.constraint_capabilities import (
        ConstraintKind,
        evaluate_request,
    )

    params = dict(task.parameters or {})
    if methods is None:
        methods = ["IDW", "克里金", "约束IDW"]
    unit = _declared_unit_for_task(task)
    crs = project.coordinate.project_crs if project is not None else None

    requested = [str(c) for c in (requested_constraints or [])]
    kinds: list[ConstraintKind] = []
    unknown_constraints: list[str] = []
    for name in requested:
        try:
            kinds.append(ConstraintKind(name))
        except ValueError:
            unknown_constraints.append(name)

    gate_warnings, gate = _validate_recommendation_context(unit, crs)
    entries: list[dict[str, Any]] = []
    schemes: set[str] = set()
    for method_label in methods:
        probe = task.model_copy(
            update={
                "method": method_label,
                "parameters": {**params, "method": method_label},
            }
        )
        report, _diag = cross_validate_factor_task(
            probe,
            project=project,
            k=k,
            cancellation_token=cancellation_token,
        )
        capability_warnings = list(gate_warnings)
        capability_warnings.extend(
            f"unknown constraint {name!r} — cannot certify honoring it"
            for name in unknown_constraints
        )
        if kinds:
            engine_method = METHOD_LABEL_TO_ENGINE.get(method_label, method_label)
            capability_warnings.extend(
                evaluate_request(engine_method, kinds).diagnostics
            )
        if report is None:
            entries.append(
                {
                    "method": method_label,
                    "scheme": "unavailable",
                    "metrics": None,
                    "capability_warnings": capability_warnings
                    or ["evaluation unavailable: too few scorable samples"],
                    "recommended": False,
                    "rationale": "cross-validation could not run honestly "
                    "(insufficient samples for the fold scheme)",
                }
            )
            continue
        schemes.add(report.scheme)
        entries.append(
            {
                "method": method_label,
                "scheme": report.scheme,
                "metrics": report.metrics.to_dict(),
                "n_folds": report.k,
                "capability_warnings": capability_warnings,
            }
        )

    def _score(entry: dict[str, Any]) -> float:
        metrics = entry.get("metrics") or {}
        rmse = metrics.get("rmse")
        return float(rmse) if rmse is not None else float("inf")

    def _eligible(entry: dict[str, Any]) -> bool:
        return entry.get("metrics") is not None and not any(
            ":unsupported:" in w for w in entry.get("capability_warnings") or []
        )

    best: str | None = None
    scorable = [e for e in entries if _eligible(e)]
    if scorable:
        best = min(scorable, key=_score)["method"]

    gate_rationale = {
        "unit_unknown": (
            "no recommendation: measurement unit is unknown — cross-method "
            "ranking on ununitized data is not a defensible comparison"
        ),
        "crs_invalid": (
            "no recommendation: declared CRS is invalid/unparseable — "
            "distances and folds cannot be trusted"
        ),
    }.get(gate)
    if gate_rationale is None and unknown_constraints:
        gate_rationale = (
            "no recommendation: requested constraint(s) "
            f"{unknown_constraints!r} are unknown to the capability matrix — "
            "no method can be certified as honoring them"
        )
    scheme_caveat = (
        "schemes differ across methods (loo_exact vs kfold_surface) — RMSE "
        "comparison is indicative, not a controlled experiment"
        if len(schemes) > 1
        else ""
    )

    for entry in entries:
        warnings = entry.get("capability_warnings") or []
        unsupported = any(":unsupported:" in w for w in warnings)
        if entry.get("metrics") is None:
            continue
        if gate_rationale is not None:
            entry["recommended"] = False
            entry["rationale"] = gate_rationale
        elif unsupported:
            entry["recommended"] = False
            entry["rationale"] = (
                "disqualified: requested constraints ignored by this method "
                "(capability matrix) — metrics alone cannot justify it"
            )
        elif entry["method"] == best:
            entry["recommended"] = True
            entry["rationale"] = (
                "best cross-validated RMSE among methods that honor every "
                "requested constraint"
                + (f"; caveat: {scheme_caveat}" if scheme_caveat else "")
            )
        else:
            entry["recommended"] = False
            entry["rationale"] = (
                f"higher cross-validated RMSE than {best!r}"
                + (f"; caveat: {scheme_caveat}" if scheme_caveat else "")
            )
    return {
        "scheme": "per_method_production_cv",
        "k": k,
        "requested_constraints": requested,
        "unit": unit,
        "crs": crs,
        "recommendation_gate": gate
        or ("unknown_constraints" if unknown_constraints else None),
        "methods": entries,
        "recommended_method": (
            None
            if gate_rationale is not None
            else next((e["method"] for e in entries if e.get("recommended")), None)
        ),
    }


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
    params = task.parameters or {}
    # Normalized samples: a held-in twin well must not score a free zero
    # residual against a surface that merged it (V8 M3).
    points, _norm = normalize_factor_samples(
        params.get("sample_points") or [],
        policy=duplicate_policy_from_params(params),
    )
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
