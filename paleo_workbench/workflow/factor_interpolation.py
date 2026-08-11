"""Real single-factor map interpolation using geo-viz-engine plots (IDW / SciPy).

Phase-2 promote-down (map #244 / PR-A #256): the pure interpolation core
(``extract_xy_values`` / ``interpolate_factor_grid`` / ``synthetic_sample_points``
/ ``_grid_axes`` / ``_run_grid`` / ``_leave_one_out_r2``) was promoted to
``geoviz_plots.factor`` and is consumed here through the ``geoviz`` facade.
This module keeps only the ``FactorMapTask`` / ``ProjectDocument``-coupled
adapters (T10: ``project/models.py`` is NOT promoted).
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

from geoviz import (
    extract_xy_values,
    extract_xy_z_weights,
    interpolate_factor_grid,
    resolve_anisotropy_params,
    synthetic_sample_points,
)
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.constrained_idw_adapter import (
    CONSTRAINED_IDW_ENGINE_LABEL,
    run_constrained_idw,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.workflow.constraints import (
    break_polylines_for_idw,
    constraint_layers_for_project,
    direction_line_params,
)

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


def apply_interpolation_to_task(
    task: FactorMapTask,
    *,
    method: str = "IDW",
    grid_n: int = DEFAULT_GRID_N,
    power: float = 2.0,
    project: ProjectDocument | None = None,
    fault_polylines: list[list[tuple[float, float]]] | None = None,
    cancellation_token=None,
) -> FactorMapTask:
    """Mutate a FactorMapTask with a real interpolation grid and quality metrics.

    When *project* is provided:
      - active break lines → IDW fault barriers (unless *fault_polylines* given)
      - active direction lines → anisotropy for method 「方向趋势」
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
    # Allow task parameters to override direction if set.
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
    if engine_method == CONSTRAINED_IDW_ENGINE_LABEL:
        # Host-side dispatch to the haiyou constrained-IDW algorithm. The host
        # owns this integration boundary so geo-viz-engine and haiyou stay
        # independent; the result dict matches interpolate_factor_grid's
        # contract so all downstream plumbing is method-agnostic.
        result = run_constrained_idw(
            points,
            grid_n=grid_n,
            power=power,
            layers=layers,
            target_horizon=task.target_horizon,
            break_polylines=breaks,
            cancellation_token=cancellation_token,
        )
    else:
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
        )

    crs = project.coordinate.project_crs if project is not None else None
    if engine_method == CONSTRAINED_IDW_ENGINE_LABEL:
        grid_result = FactorGridResult.from_constrained_idw_dict(
            result,
            factor_name=task.factor_type or task.name,
            crs=crs,
            generator_version=GENERATOR_VERSION,
            source_refs=task.input_resource_ids,
        )
    else:
        grid_result = FactorGridResult.from_engine_dict(
            result,
            factor_name=task.factor_type or task.name,
            crs=crs,
            generator_version=GENERATOR_VERSION,
            source_refs=task.input_resource_ids,
        )
    params["sample_points"] = list(points)
    params["grid"] = f"{result['grid_n']}×{result['grid_n']}"
    # Keep the established inline representation until ProjectManager persists the
    # artifact. In particular, constrained-IDW historically exposes float NaNs to
    # callers, while the engine uses JSON-safe None; FactorGridResult normalizes both
    # when it becomes the persisted/native payload.
    params["grid_x"] = result["grid_x"]
    params["grid_y"] = result["grid_y"]
    params["grid_z"] = result["grid_z"]
    if result.get("grid_var") is not None:
        params["grid_var"] = result["grid_var"]
    else:
        params.pop("grid_var", None)
    if result.get("boundary"):
        params["grid_boundary"] = result["boundary"]
    else:
        params.pop("grid_boundary", None)
    params["interp_backend"] = result["backend"]
    params["power"] = power
    params["n_break_lines"] = result.get("n_break_lines", 0)
    # Real kriging backend additionally returns the kriging variance grid —
    # pass it through so downstream consumers (and the UI) can show it.
    if result.get("grid_var") is not None:
        params["grid_var"] = result["grid_var"]
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

    task.parameters = params
    task.method = method if method != "mock" else "IDW"
    task.status = "complete"
    if task.source_kind == "mock":
        task.source_kind = "mixed"
    task.generator_version = GENERATOR_VERSION
    task.grid_metadata = grid_result.to_descriptor()
    # A scientific input change invalidates only this task's former grid artifact.
    # The next project save will atomically externalize and catalog the new result.
    task.grid_artifact_path = None
    task.grid_artifact_version_id = None
    task.quality_metrics = {
        "range": f"{result['min']:.2f} – {result['max']:.2f}",
        "r_squared": result["r_squared"],
        "grid": f"{result['grid_n']}×{result['grid_n']}",
        "n_points": result["n_points"],
        "backend": result["backend"],
        "mean": round(result["mean"], 4),
    }
    if result.get("variance_min") is not None:
        task.quality_metrics["variance_min"] = round(result["variance_min"], 4)
        task.quality_metrics["variance_max"] = round(result["variance_max"], 4)
    snapshot = {
        "target_horizon": task.target_horizon,
        "factor_type": task.factor_type,
        "method": task.method,
        "generator_version": GENERATOR_VERSION,
        "sample_points": points,
        "grid_n": grid_n,
    }
    task.input_snapshot_hash = _snapshot_hash(snapshot)
    # Project save externalizes this transient inline grid into the managed NPZ
    # artifact and registers the single catalog INTERMEDIATE version.  Do not create
    # an in-memory-only run here: it would duplicate the persisted run and make the
    # catalog incorrectly suggest that two scientific interpolations occurred.
    return task


def batch_prepare_factor_maps(
    project: ProjectDocument,
    *,
    method: str = "IDW",
    target_horizon: str | None = None,
    factor_types: list[str] | tuple[str, ...] | None = None,
    grid_n: int = DEFAULT_GRID_N,
    seed: int = 0,
    cancellation_token=None,
) -> list[FactorMapTask]:
    """Run real interpolation for existing tasks or create default factor maps.

    - Existing tasks with sample_points are re-interpolated with the chosen method.
    - When the project has no factor tasks, creates DEFAULT_FACTOR_TYPES entries
      (or ``factor_types``) with synthetic samples, then interpolates.
    - Returns the list of tasks that were prepared in this call.
    """
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
                source_kind="mixed",
                seed=seed + index,
            )
            apply_interpolation_to_task(
                task,
                method=method,
                grid_n=grid_n,
                project=project,
                cancellation_token=cancellation_token,
            )
            project.factor_map_tasks.append(task)
            prepared.append(task)
        return prepared

    for task in project.factor_map_tasks:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        params = task.parameters or {}
        points = params.get("sample_points") or []
        if not points:
            points = synthetic_sample_points(
                seed=(task.seed if task.seed is not None else seed),
                factor_type=task.factor_type or task.name,
            )
            task.parameters = {**params, "sample_points": points}
        apply_interpolation_to_task(
            task,
            method=method,
            grid_n=grid_n,
            project=project,
            cancellation_token=cancellation_token,
        )
        prepared.append(task)
    return prepared
