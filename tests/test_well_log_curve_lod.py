"""TDD Benchmark Tests for Well Log Curve Track LOD & Viewport Y-Clipping (Refactor)."""
import time
import numpy as np
import pytest

from geoviz_well_log.renderer.curve_track import (
    clip_curve_depth_range,
    simplify_curve_screen_space,
)


def test_clip_curve_depth_range():
    depths = np.linspace(0.0, 5000.0, 10000)
    values = np.sin(depths * 0.05)
    
    # Viewport visible range: [1000.0, 2000.0]
    clipped_depths, clipped_values = clip_curve_depth_range(
        depths, values, top_depth=1000.0, bottom_depth=2000.0
    )
    
    # Excludes 80% offscreen points, leaving ~2000 points
    assert len(clipped_depths) < 2100
    assert len(clipped_depths) > 1900
    assert np.min(clipped_depths) >= 1000.0
    assert np.max(clipped_depths) <= 2000.0


def _median_ms(fn, trials: int = 5, warmup: int = 1) -> float:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(trials):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return float(np.median(samples))


def test_simplify_curve_screen_space_performance():
    # Dense curve with 20,000 points
    rng = np.random.default_rng(0)
    y_px = np.linspace(0, 1080, 20000)
    x_px = 100 + 50 * np.sin(y_px * 0.1) + rng.normal(0.0, 0.1, 20000)  # jitter < 0.5px

    def _run():
        return simplify_curve_screen_space(x_px, y_px, epsilon=0.5)

    simp_x, simp_y = _run()
    elapsed_ms = _median_ms(_run)

    # Compression: 20,000 points down to < 1000 points (> 95% reduction) in < 3ms
    assert len(simp_x) < 1000
    assert elapsed_ms < 3.0
