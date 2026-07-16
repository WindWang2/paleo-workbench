"""Real single-factor map interpolation using geo-viz-engine plots (IDW / SciPy).

Preparation page → FactorMapTask.parameters grid + quality_metrics → mapping factor shelf.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any

import numpy as np

from paleo_workbench.project.models import FactorMapTask, ProjectDocument

GENERATOR_VERSION = "factor-interp-v1"
DEFAULT_FACTOR_TYPES = ("地层厚度", "砂岩含量", "砂地比", "泥岩含量")
DEFAULT_GRID_N = 50

# UI labels (tokens.INTERPOLATION_METHODS) → engine backends
_METHOD_BACKEND = {
    "IDW": "idw",
    "idw": "idw",
    "克里金": "linear",  # SciPy linear as practical stand-in for kriging MVP
    "样条": "cubic",
    "mock": "idw",
}


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def extract_xy_values(
    sample_points: list[dict[str, Any]] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pull (x, y, value) arrays from factor sample_points records."""
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for pt in sample_points or []:
        if not isinstance(pt, dict):
            continue
        try:
            if "x" in pt and "y" in pt:
                x = float(pt["x"])
                y = float(pt["y"])
            elif "lng" in pt and "lat" in pt:
                x = float(pt["lng"])
                y = float(pt["lat"])
            else:
                continue
            z = float(pt.get("value", pt.get("z", pt.get("v"))))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        xs.append(x)
        ys.append(y)
        zs.append(z)
    return (
        np.asarray(xs, dtype=np.float64),
        np.asarray(ys, dtype=np.float64),
        np.asarray(zs, dtype=np.float64),
    )


def _grid_axes(
    x: np.ndarray, y: np.ndarray, grid_n: int
) -> tuple[np.ndarray, np.ndarray]:
    n = max(2, int(grid_n))
    if len(x) == 0:
        return np.linspace(0.0, 1.0, n), np.linspace(0.0, 1.0, n)
    pad_x = max((float(x.max()) - float(x.min())) * 0.05, 1e-6)
    pad_y = max((float(y.max()) - float(y.min())) * 0.05, 1e-6)
    grid_x = np.linspace(float(x.min()) - pad_x, float(x.max()) + pad_x, n)
    grid_y = np.linspace(float(y.min()) - pad_y, float(y.max()) + pad_y, n)
    return grid_x, grid_y


def _run_grid(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    backend: str,
    power: float,
    fault_polylines: list[list[tuple[float, float]]] | None = None,
) -> np.ndarray:
    if backend == "idw":
        from geoviz import interpolate_idw

        kwargs: dict[str, Any] = {"power": power}
        if fault_polylines:
            kwargs["fault_polylines"] = fault_polylines
        return interpolate_idw(x, y, z, grid_x, grid_y, **kwargs)
    from geoviz import interpolate_scipy

    method = backend if backend in {"linear", "cubic", "nearest", "rbf"} else "linear"
    return interpolate_scipy(x, y, z, grid_x, grid_y, method=method)


def _leave_one_out_r2(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    *,
    backend: str,
    power: float,
    fault_polylines: list[list[tuple[float, float]]] | None = None,
) -> float | None:
    """Rough LOO R² for sparse control points (None when N < 3)."""
    n = len(z)
    if n < 3:
        return None
    preds = np.empty(n, dtype=np.float64)
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        try:
            grid = _run_grid(
                x[mask],
                y[mask],
                z[mask],
                np.asarray([x[i]]),
                np.asarray([y[i]]),
                backend=backend,
                power=power,
                fault_polylines=fault_polylines,
            )
            val = float(grid[0, 0])
        except Exception:
            return None
        if not math.isfinite(val):
            return None
        preds[i] = val
    ss_res = float(np.sum((z - preds) ** 2))
    ss_tot = float(np.sum((z - np.mean(z)) ** 2))
    if ss_tot <= 1e-12:
        return 1.0 if ss_res <= 1e-12 else 0.0
    return max(0.0, min(1.0, 1.0 - ss_res / ss_tot))


def interpolate_factor_grid(
    sample_points: list[dict[str, Any]] | None,
    *,
    method: str = "IDW",
    grid_n: int = DEFAULT_GRID_N,
    power: float = 2.0,
    fault_polylines: list[list[tuple[float, float]]] | None = None,
) -> dict[str, Any]:
    """Interpolate scattered sample_points onto a regular grid.

    Returns a JSON-serializable dict with axes, values, and quality stats.
    Optional *fault_polylines* are passed to IDW as break barriers (ISS-ALG-03).
    """
    x, y, z = extract_xy_values(sample_points)
    if len(z) < 2:
        raise ValueError("插值至少需要 2 个有效采样点")
    backend = _METHOD_BACKEND.get(method, "idw")
    grid_x, grid_y = _grid_axes(x, y, grid_n)
    grid_z = _run_grid(
        x,
        y,
        z,
        grid_x,
        grid_y,
        backend=backend,
        power=power,
        fault_polylines=fault_polylines,
    )
    finite = grid_z[np.isfinite(grid_z)]
    if finite.size == 0:
        raise ValueError("插值结果全为无效值")
    r2 = _leave_one_out_r2(
        x, y, z, backend=backend, power=power, fault_polylines=fault_polylines
    )
    return {
        "grid_x": [float(v) for v in grid_x],
        "grid_y": [float(v) for v in grid_y],
        "grid_z": [[None if not math.isfinite(float(v)) else float(v) for v in row] for row in grid_z],
        "backend": backend,
        "method": method,
        "grid_n": int(grid_n),
        "n_points": int(len(z)),
        "n_break_lines": int(len(fault_polylines or [])),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "r_squared": None if r2 is None else round(float(r2), 4),
    }


def apply_interpolation_to_task(
    task: FactorMapTask,
    *,
    method: str = "IDW",
    grid_n: int = DEFAULT_GRID_N,
    power: float = 2.0,
    project: ProjectDocument | None = None,
    fault_polylines: list[list[tuple[float, float]]] | None = None,
) -> FactorMapTask:
    """Mutate a FactorMapTask with a real interpolation grid and quality metrics.

    When *project* is provided, active break lines for the task horizon are
    collected as IDW fault barriers unless *fault_polylines* is passed explicitly.
    """
    params = dict(task.parameters or {})
    points = params.get("sample_points") or []
    breaks = fault_polylines
    if breaks is None and project is not None:
        from paleo_workbench.workflow.constraints import (
            break_polylines_for_idw,
            constraint_layers_for_project,
        )

        breaks = break_polylines_for_idw(
            constraint_layers_for_project(project, target_horizon=task.target_horizon),
            target_horizon=task.target_horizon,
        )
    result = interpolate_factor_grid(
        points,
        method=method,
        grid_n=grid_n,
        power=power,
        fault_polylines=breaks,
    )

    params["sample_points"] = list(points)
    params["grid"] = f"{result['grid_n']}×{result['grid_n']}"
    params["grid_x"] = result["grid_x"]
    params["grid_y"] = result["grid_y"]
    params["grid_z"] = result["grid_z"]
    params["interp_backend"] = result["backend"]
    params["power"] = power
    params["n_break_lines"] = result.get("n_break_lines", 0)
    if breaks:
        params["break_polylines"] = [
            [[float(x), float(y)] for x, y in poly] for poly in breaks
        ]

    task.parameters = params
    task.method = method if method != "mock" else "IDW"
    task.status = "complete"
    if task.source_kind == "mock":
        task.source_kind = "mixed"
    task.generator_version = GENERATOR_VERSION
    task.quality_metrics = {
        "range": f"{result['min']:.2f} – {result['max']:.2f}",
        "r_squared": result["r_squared"],
        "grid": f"{result['grid_n']}×{result['grid_n']}",
        "n_points": result["n_points"],
        "backend": result["backend"],
        "mean": round(result["mean"], 4),
    }
    snapshot = {
        "target_horizon": task.target_horizon,
        "factor_type": task.factor_type,
        "method": task.method,
        "generator_version": GENERATOR_VERSION,
        "sample_points": points,
        "grid_n": grid_n,
    }
    task.input_snapshot_hash = _snapshot_hash(snapshot)
    return task


def synthetic_sample_points(
    *,
    seed: int,
    factor_type: str,
    count: int = 8,
) -> list[dict[str, Any]]:
    """Deterministic control points when no well-derived samples exist yet."""
    rng = random.Random(f"{seed}:{factor_type}")
    base = 10.0 + (abs(hash(factor_type)) % 20)
    return [
        {
            "well": f"A{i + 1}",
            "x": round(114.0 + rng.random() * 0.3, 6),
            "y": round(22.5 + rng.random() * 0.3, 6),
            "value": round(base + rng.random() * 40.0, 3),
        }
        for i in range(count)
    ]


def batch_prepare_factor_maps(
    project: ProjectDocument,
    *,
    method: str = "IDW",
    target_horizon: str | None = None,
    factor_types: list[str] | tuple[str, ...] | None = None,
    grid_n: int = DEFAULT_GRID_N,
    seed: int = 0,
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

    if not project.factor_map_tasks:
        types = list(factor_types or DEFAULT_FACTOR_TYPES)
        for index, factor_type in enumerate(types):
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
                task, method=method, grid_n=grid_n, project=project
            )
            project.factor_map_tasks.append(task)
            prepared.append(task)
        return prepared

    for task in project.factor_map_tasks:
        params = task.parameters or {}
        points = params.get("sample_points") or []
        if not points:
            points = synthetic_sample_points(
                seed=(task.seed if task.seed is not None else seed),
                factor_type=task.factor_type or task.name,
            )
            task.parameters = {**params, "sample_points": points}
        apply_interpolation_to_task(
            task, method=method, grid_n=grid_n, project=project
        )
        prepared.append(task)
    return prepared
