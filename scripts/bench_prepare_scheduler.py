#!/usr/bin/env python3
"""Local benchmark for Stage-5 prepare scheduler (not part of unit CI).

Usage:
  python scripts/bench_prepare_scheduler.py
  PALEO_PREPARE_WORKERS=2 python scripts/bench_prepare_scheduler.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paleo_workbench.project.models import FactorMapTask, ProjectDocument, ResourceItem
from paleo_workbench.workflow.factor_interpolation import (
    batch_prepare_factor_maps,
    interpolation_execution_count,
    reset_interpolation_execution_counter,
)
from paleo_workbench.workflow.factor_prepare_scheduler import (
    build_prepare_snapshot,
    prepare_worker_count,
    run_factor_prepare_schedule,
)


def _points(n: int, seed: int) -> list[dict]:
    import numpy as np

    rng = np.random.default_rng(seed)
    return [
        {
            "x": float(rng.uniform(0, 100)),
            "y": float(rng.uniform(0, 100)),
            "value": float(rng.uniform(0.1, 1.0)),
        }
        for _ in range(n)
    ]


def make_project(
    *,
    n_tasks: int,
    n_points: int,
    n_resources: int = 0,
    shared_xy: bool = True,
) -> ProjectDocument:
    project = ProjectDocument.new("bench")
    project.stratigraphy.target_horizon = "H1"
    for i in range(n_resources):
        project.resources.append(
            ResourceItem(
                name=f"r{i}",
                path=f"/tmp/bench/{i}/" + ("z" * 200),
                type="well",
                format="las",
            )
        )
    base = _points(n_points, seed=1)
    for i in range(n_tasks):
        pts = (
            [{**p, "value": float(p["value"]) + 0.01 * i} for p in base]
            if shared_xy
            else _points(n_points, seed=100 + i)
        )
        project.factor_map_tasks.append(
            FactorMapTask(
                name=f"f{i}",
                target_horizon="H1",
                factor_type=f"t{i}",
                method="IDW",
                parameters={"sample_points": pts},
                status="pending",
            )
        )
    return project


def bench_deep_copy(project: ProjectDocument) -> dict:
    tracemalloc.start()
    t0 = time.perf_counter()
    _ = project.model_copy(deep=True)
    ms = (time.perf_counter() - t0) * 1000.0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"deep_copy_ms": ms, "deep_copy_peak_bytes": peak}


def bench_snapshot(project: ProjectDocument) -> dict:
    tracemalloc.start()
    t0 = time.perf_counter()
    snap = build_prepare_snapshot(project, generation=1, method="IDW", grid_n=64)
    ms = (time.perf_counter() - t0) * 1000.0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "snapshot_ms": ms,
        "snapshot_peak_bytes": peak,
        "snapshot_tasks": len(snap.tasks),
        "build_ms_field": snap.build_ms,
    }


def bench_schedule(project: ProjectDocument, *, label: str, force: bool = False) -> dict:
    workers = prepare_worker_count()
    reset_interpolation_execution_counter()
    snap = build_prepare_snapshot(
        project, generation=1, method="IDW", grid_n=64, force=force
    )
    t0 = time.perf_counter()
    result = run_factor_prepare_schedule(snap, workers=workers)
    wall = (time.perf_counter() - t0) * 1000.0
    return {
        "label": label,
        "workers": workers,
        "wall_ms": wall,
        "snapshot_ms": result.snapshot_ms,
        "classify_ms": result.classify_ms,
        "execute_ms": result.execute_ms,
        "clean": result.clean_count,
        "dirty": result.dirty_count,
        "executed": result.executed_count,
        "interp_executions": interpolation_execution_count(),
    }


def main() -> None:
    rows: list[dict] = []

    fat = make_project(n_tasks=8, n_points=128, n_resources=500)
    rows.append({"scenario": "copy_vs_snapshot_fat", **bench_deep_copy(fat), **bench_snapshot(fat)})

    lean = make_project(n_tasks=8, n_points=128, n_resources=0)
    rows.append({"scenario": "copy_vs_snapshot_lean", **bench_deep_copy(lean), **bench_snapshot(lean)})

    # All dirty same geometry
    p = make_project(n_tasks=8, n_points=100, shared_xy=True)
    rows.append({"scenario": "8_dirty_same_geom", **bench_schedule(p, label="8_dirty")})

    # CLEAN after warm
    batch_prepare_factor_maps(p, method="IDW", grid_n=64)
    rows.append({"scenario": "8_clean", **bench_schedule(p, label="8_clean")})

    # One dirty
    pts = list(p.factor_map_tasks[0].parameters["sample_points"])
    pts[0] = {**pts[0], "value": float(pts[0]["value"]) + 1.0}
    p.factor_map_tasks[0].parameters = {
        **p.factor_map_tasks[0].parameters,
        "sample_points": pts,
    }
    rows.append({"scenario": "1_dirty", **bench_schedule(p, label="1_dirty")})

    print(json.dumps({"prepare_workers": prepare_worker_count(), "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
