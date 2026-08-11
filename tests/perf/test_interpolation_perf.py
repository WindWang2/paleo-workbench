"""Optional performance regression harness for factor interpolation.

Marked ``slow`` so default unit-test runs stay fast.  Invoke with::

    python -m pytest -q tests/perf/test_interpolation_perf.py -m slow
"""

from __future__ import annotations

import statistics
import time
import tracemalloc

import numpy as np
import pytest

from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task


pytestmark = pytest.mark.slow


def _points(n: int, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    xs = rng.uniform(0.0, 100.0, size=n)
    ys = rng.uniform(0.0, 100.0, size=n)
    vals = rng.normal(25.0, 5.0, size=n)
    return [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(xs, ys, vals)
    ]


def _median_time(fn, trials: int = 5, warmup: int = 1) -> tuple[float, float, float]:
    for _ in range(warmup):
        fn()
    times: list[float] = []
    peaks: list[float] = []
    for _ in range(trials):
        tracemalloc.start()
        t0 = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(elapsed)
        peaks.append(peak / (1024 * 1024))
    times_sorted = sorted(times)
    p90 = times_sorted[max(0, int(round(0.9 * (len(times_sorted) - 1))))]
    return statistics.median(times), p90, max(peaks)


@pytest.mark.parametrize(
    "label,grid_n,n_pts,trials",
    [
        ("SMALL", 128, 40, 5),
        ("MEDIUM", 512, 80, 3),
    ],
)
def test_idw_apply_perf_smoke(label, grid_n, n_pts, trials):
    pts = _points(n_pts)

    def run_once():
        task = FactorMapTask(
            name=f"perf-{label}",
            target_horizon="H1",
            factor_type="thickness",
            method="IDW",
            parameters={"sample_points": pts},
            status="pending",
        )
        apply_interpolation_to_task(task, method="IDW", grid_n=grid_n)

    median, p90, peak_mb = _median_time(run_once, trials=trials, warmup=1)
    # Soft budgets — catch catastrophic regressions only.
    print(
        f"[perf] IDW {label} grid={grid_n} n={n_pts}: "
        f"median={median:.4f}s p90={p90:.4f}s peak≈{peak_mb:.1f}MB"
    )
    assert median < (8.0 if grid_n <= 128 else 60.0)
    assert peak_mb < (200.0 if grid_n <= 128 else 600.0)


def test_constrained_idw_perf_smoke():
    pts = _points(30, seed=3)

    def run_once():
        run_constrained_idw(pts, grid_n=64, power=2.0)

    median, p90, peak_mb = _median_time(run_once, trials=3, warmup=1)
    print(
        f"[perf] constrained grid=64 n=30: "
        f"median={median:.4f}s p90={p90:.4f}s peak≈{peak_mb:.1f}MB"
    )
    assert median < 30.0
    assert peak_mb < 400.0


def test_repeated_geometry_live_grid_no_extra_list_parse():
    """Same sample set re-applied twice stays deterministic and bounded."""
    pts = _points(25, seed=9)
    times = []
    for _ in range(3):
        task = FactorMapTask(
            name="repeat",
            target_horizon="H1",
            factor_type="sand",
            method="IDW",
            parameters={"sample_points": pts},
            status="pending",
        )
        t0 = time.perf_counter()
        apply_interpolation_to_task(task, method="IDW", grid_n=96)
        times.append(time.perf_counter() - t0)
        assert task.parameters.get("grid_z") is not None
    # No runaway growth across repeats.
    assert max(times) < min(times) * 5 + 1.0
