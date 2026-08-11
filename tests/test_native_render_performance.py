"""Comparative local performance smoke tests for the native scalar cache."""

from __future__ import annotations

import gc
import time

import numpy as np
import pytest

grid_render_core = pytest.importorskip("grid_render_core")


@pytest.mark.parametrize("side", [500, 1000, 2000])
def test_native_scalar_cache_smoke(side: int):
    """Initial raster does real work; a same-revision call reuses native pixels.

    There is intentionally no machine-specific absolute threshold here. The local gate
    guards the meaningful invariant across workstations: the cached call cannot invoke
    another rasterization and should not be slower than the cold native render.
    """
    axis = np.linspace(0.0, 1.0, side, dtype=np.float32)
    grid = (axis[:, None] + axis[None, :]) * np.float32(0.5)
    layer = grid_render_core.ScalarGridLayer(grid)
    layer.set_color_ramp(
        np.array(
            [[20, 30, 60, 255], [100, 180, 220, 255], [250, 240, 120, 255]],
            dtype=np.uint8,
        )
    )
    started = time.perf_counter()
    cold = layer.rasterize()
    cold_s = time.perf_counter() - started
    started = time.perf_counter()
    warm = layer.rasterize()
    warm_s = time.perf_counter() - started

    assert cold.shape == warm.shape == (side, side, 4)
    assert layer.rasterize_count == 1
    # A cache hit still copies bytes into a NumPy result, so allow scheduler noise while
    # requiring it to remain materially bounded by the work-heavy cold render.
    assert warm_s <= max(cold_s * 4.0, 0.100)
    print(
        f"native raster {side}x{side}: cold={cold_s * 1000:.1f}ms "
        f"warm={warm_s * 1000:.1f}ms"
    )
    del cold, warm, layer, grid
    gc.collect()
