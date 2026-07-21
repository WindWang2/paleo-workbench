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


def test_simplify_curve_screen_space_performance():
    # Dense curve with 20,000 points
    y_px = np.linspace(0, 1080, 20000)
    x_px = 100 + 50 * np.sin(y_px * 0.1) + np.random.randn(20000) * 0.1  # jitter < 0.5px
    
    t0 = time.perf_counter()
    simp_x, simp_y = simplify_curve_screen_space(x_px, y_px, epsilon=0.5)
    t1 = time.perf_counter()
    
    elapsed_ms = (t1 - t0) * 1000.0
    
    # Compression: 20,000 points down to < 1000 points (> 95% reduction) in < 3ms
    assert len(simp_x) < 1000
    assert elapsed_ms < 3.0
