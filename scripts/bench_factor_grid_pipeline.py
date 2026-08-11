#!/usr/bin/env python3
"""End-to-end FactorGrid pipeline benchmark (Stage-3).

Phases measured:
  interpolation (+ attach, no legacy lists)
  artifact write (project save externalisation)
  reopen load
  20× repeated consumer reads (artifact warm cache)

Usage:
  PYTHONPATH=.:geo-viz-engine:geo-viz-engine/packages/geoviz_common:geo-viz-engine/packages/geoviz_plots \\
    python scripts/bench_factor_grid_pipeline.py --out /tmp/pipeline_bench.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

import numpy as np

from paleo_workbench.project.factor_grid_artifacts import (
    clear_live_factor_grid,
    factor_grid_result_for_task,
    live_factor_grid_cache_stats,
    reset_artifact_load_counter,
)
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    batch_prepare_factor_maps,
)


def _shared_factor_points(n_wells: int, n_factors: int, seed: int = 0) -> list[list[dict]]:
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0.0, 50.0, size=n_wells)
    ys = rng.uniform(0.0, 50.0, size=n_wells)
    out: list[list[dict]] = []
    for f in range(n_factors):
        vals = rng.normal(10.0 * (f + 1), 2.0, size=n_wells)
        out.append(
            [
                {"x": float(x), "y": float(y), "value": float(v)}
                for x, y, v in zip(xs, ys, vals)
            ]
        )
    return out


def _clear_all(tasks: list[FactorMapTask]) -> None:
    for t in tasks:
        clear_live_factor_grid(t.id)


def run_pipeline(
    *,
    grid_n: int,
    n_wells: int,
    n_factors: int,
    method: str = "IDW",
    repeats_read: int = 20,
) -> dict[str, Any]:
    factor_pts = _shared_factor_points(n_wells, n_factors)
    project = ProjectDocument.new("bench-pipe")
    project.stratigraphy.target_horizon = "H1"
    for i, pts in enumerate(factor_pts):
        project.factor_map_tasks.append(
            FactorMapTask(
                name=f"f{i}",
                target_horizon="H1",
                factor_type=f"type{i}",
                method=method,
                parameters={"sample_points": pts},
                status="pending",
            )
        )

    tracemalloc.start()
    t0 = time.perf_counter()
    if n_factors == 1:
        apply_interpolation_to_task(
            project.factor_map_tasks[0], method=method, grid_n=grid_n, project=project
        )
    else:
        batch_prepare_factor_maps(project, method=method, grid_n=grid_n)
    interp_s = time.perf_counter() - t0
    _, peak_interp = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Confirm no legacy lists
    for t in project.factor_map_tasks:
        assert "grid_z" not in (t.parameters or {})

    with tempfile.TemporaryDirectory() as tmp:
        project_path = Path(tmp) / "bench.paleo.json"
        tracemalloc.start()
        t0 = time.perf_counter()
        ProjectManager(project_path).save(project)
        save_s = time.perf_counter() - t0
        _, peak_save = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Cold reopen simulation: clear cache, reload document
        _clear_all(project.factor_map_tasks)
        reset_artifact_load_counter()
        loaded = ProjectManager(project_path).load()

        tracemalloc.start()
        t0 = time.perf_counter()
        first = [factor_grid_result_for_task(t) for t in loaded.factor_map_tasks]
        reopen_s = time.perf_counter() - t0
        _, peak_reopen = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        loads_after_reopen = live_factor_grid_cache_stats()["artifact_physical_loads"]

        t0 = time.perf_counter()
        for _ in range(repeats_read):
            for t in loaded.factor_map_tasks:
                factor_grid_result_for_task(t)
        repeat_s = time.perf_counter() - t0
        loads_after_repeat = live_factor_grid_cache_stats()["artifact_physical_loads"]

        art_sizes = []
        for t in loaded.factor_map_tasks:
            if t.grid_artifact_path:
                art_sizes.append(Path(t.grid_artifact_path).stat().st_size)

    return {
        "method": method,
        "grid_n": grid_n,
        "n_wells": n_wells,
        "n_factors": n_factors,
        "interp_s": interp_s,
        "save_s": save_s,
        "reopen_first_read_s": reopen_s,
        "repeat_reads_s": repeat_s,
        "repeat_count": repeats_read,
        "peak_interp_mb": peak_interp / 1e6,
        "peak_save_mb": peak_save / 1e6,
        "peak_reopen_mb": peak_reopen / 1e6,
        "artifact_physical_loads_after_reopen": loads_after_reopen,
        "artifact_physical_loads_after_repeats": loads_after_repeat,
        "artifact_bytes_total": int(sum(art_sizes)),
        "first_grid_shape": list(first[0].shape) if first else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    cases: list[dict[str, Any]] = []
    if args.quick:
        matrix = [(128, 40, 1), (128, 40, 4), (256, 60, 4)]
    else:
        matrix = [
            (128, 40, 1),
            (128, 40, 4),
            (128, 40, 8),
            (256, 60, 4),
            (256, 60, 8),
            (512, 80, 4),
            (512, 80, 8),
            (1024, 80, 1),
            (1024, 80, 4),
        ]
    for grid_n, n_wells, n_f in matrix:
        # Warm-up once
        run_pipeline(grid_n=min(grid_n, 64), n_wells=20, n_factors=1)
        trials = []
        for _ in range(2 if grid_n >= 512 else 3):
            trials.append(
                run_pipeline(grid_n=grid_n, n_wells=n_wells, n_factors=n_f)
            )
        # Median of key timings
        med = {
            "grid_n": grid_n,
            "n_wells": n_wells,
            "n_factors": n_f,
            "interp_s": statistics.median(t["interp_s"] for t in trials),
            "save_s": statistics.median(t["save_s"] for t in trials),
            "reopen_first_read_s": statistics.median(
                t["reopen_first_read_s"] for t in trials
            ),
            "repeat_reads_s": statistics.median(t["repeat_reads_s"] for t in trials),
            "peak_interp_mb": max(t["peak_interp_mb"] for t in trials),
            "peak_save_mb": max(t["peak_save_mb"] for t in trials),
            "artifact_physical_loads_after_reopen": trials[-1][
                "artifact_physical_loads_after_reopen"
            ],
            "artifact_physical_loads_after_repeats": trials[-1][
                "artifact_physical_loads_after_repeats"
            ],
            "artifact_bytes_total": trials[-1]["artifact_bytes_total"],
        }
        cases.append(med)
        print(json.dumps(med, indent=2))

    payload = {"cases": cases}
    text = json.dumps(payload, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
