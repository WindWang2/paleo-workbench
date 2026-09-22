#!/usr/bin/env python3
"""Structured interpolation benchmark (not part of default pytest).

Usage:
  PYTHONPATH=.:geo-viz-engine:geo-viz-engine/packages/geoviz_common:geo-viz-engine/packages/geoviz_plots \\
    python scripts/bench_interpolation.py --out /tmp/interp_bench.json

Compares single-factor cold runs, multi-factor shared geometry, constrained-IDW,
and live-cache access.  Fixed RNG seed for reproducibility.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import tracemalloc
from typing import Any, Callable

import numpy as np

from paleo_workbench.project.factor_grid_artifacts import (
    factor_grid_result_for_task,
    live_factor_grid_cache_stats,
)
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    batch_prepare_factor_maps,
)


def _points(n: int, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0.0, 100.0, size=n)
    ys = rng.uniform(0.0, 100.0, size=n)
    vals = rng.normal(25.0, 5.0, size=n)
    return [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(xs, ys, vals)
    ]


def _shared_factor_points(n_wells: int, n_factors: int, seed: int = 1) -> list[list[dict]]:
    """Same XY for every factor; values differ."""
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


def _median_peak(fn: Callable[[], Any], trials: int = 5, warmup: int = 1) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    times: list[float] = []
    peaks: list[float] = []
    for _ in range(trials):
        tracemalloc.start()
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(dt)
        peaks.append(peak / (1024 * 1024))
    times_sorted = sorted(times)
    p95 = times_sorted[min(len(times_sorted) - 1, int(round(0.95 * (len(times_sorted) - 1))))]
    return {
        "median_s": float(statistics.median(times)),
        "p95_s": float(p95),
        "peak_mb": float(max(peaks)),
    }


def scenario_single_idw(grid_n: int, n_obs: int, trials: int) -> dict[str, Any]:
    pts = _points(n_obs)

    def run():
        task = FactorMapTask(
            name="s",
            target_horizon="H",
            factor_type="t",
            method="IDW",
            parameters={"sample_points": pts},
            status="pending",
        )
        apply_interpolation_to_task(task, method="IDW", grid_n=grid_n)

    metrics = _median_peak(run, trials=trials)
    return {
        "scenario": "S1_single_cold_idw",
        "method": "IDW",
        "grid_n": grid_n,
        "n_obs": n_obs,
        "n_factors": 1,
        **metrics,
    }


def scenario_multi_batch(grid_n: int, n_obs: int, n_factors: int, trials: int) -> dict[str, Any]:
    factor_pts = _shared_factor_points(n_obs, n_factors)

    def run():
        project = ProjectDocument.new("bench")
        project.stratigraphy.target_horizon = "H1"
        for i, pts in enumerate(factor_pts):
            project.factor_map_tasks.append(
                FactorMapTask(
                    name=f"f{i}",
                    target_horizon="H1",
                    factor_type=f"type{i}",
                    method="IDW",
                    parameters={"sample_points": pts},
                    status="pending",
                )
            )
        batch_prepare_factor_maps(project, method="IDW", grid_n=grid_n)
        # touch live results
        for t in project.factor_map_tasks:
            factor_grid_result_for_task(t)

    metrics = _median_peak(run, trials=trials, warmup=1)
    stats = live_factor_grid_cache_stats()
    return {
        "scenario": f"S_multi_batch_{n_factors}f",
        "method": "IDW",
        "grid_n": grid_n,
        "n_obs": n_obs,
        "n_factors": n_factors,
        "cache_entries": stats["entries"],
        "cache_bytes": stats["total_bytes"],
        **metrics,
    }


def scenario_constrained(grid_n: int, n_obs: int, trials: int) -> dict[str, Any]:
    pts = _points(n_obs, seed=3)

    def run():
        run_constrained_idw(pts, grid_n=grid_n)

    metrics = _median_peak(run, trials=trials)
    return {
        "scenario": "S6_constrained",
        "method": "constrained_idw",
        "grid_n": grid_n,
        "n_obs": n_obs,
        "n_factors": 1,
        **metrics,
    }


def scenario_cache_hits(grid_n: int, n_obs: int, hits: int = 50) -> dict[str, Any]:
    pts = _points(n_obs, seed=4)
    task = FactorMapTask(
        name="cache",
        target_horizon="H",
        factor_type="t",
        method="IDW",
        parameters={"sample_points": pts},
        status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=grid_n)

    def run():
        for _ in range(hits):
            factor_grid_result_for_task(task)

    t0 = time.perf_counter()
    run()
    elapsed = time.perf_counter() - t0
    return {
        "scenario": "S5_live_cache_hits",
        "method": "IDW",
        "grid_n": grid_n,
        "n_obs": n_obs,
        "n_factors": 1,
        "hits": hits,
        "total_s": elapsed,
        "per_hit_ms": (elapsed / hits) * 1000.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="", help="Write JSON results to this path")
    parser.add_argument("--quick", action="store_true", help="Fewer scenarios / trials")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    if args.quick:
        results.append(scenario_single_idw(128, 40, trials=3))
        results.append(scenario_multi_batch(128, 40, 4, trials=3))
        results.append(scenario_constrained(40, 30, trials=2))
        results.append(scenario_cache_hits(64, 25, hits=30))
    else:
        for g, n in ((128, 40), (512, 80)):
            results.append(scenario_single_idw(g, n, trials=4 if g <= 128 else 2))
        for nf in (4, 8, 16):
            results.append(scenario_multi_batch(128, 40, nf, trials=3))
            results.append(scenario_multi_batch(256, 60, nf, trials=2))
        results.append(scenario_constrained(64, 30, trials=3))
        results.append(scenario_constrained(128, 40, trials=2))
        results.append(scenario_cache_hits(128, 40, hits=50))
        # large single
        results.append(scenario_single_idw(1024, 80, trials=1))

    payload = {
        "seed_policy": "fixed numpy Generator seeds per scenario",
        "results": results,
    }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.write("\n")


if __name__ == "__main__":
    main()
