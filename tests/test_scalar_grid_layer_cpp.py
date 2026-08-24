"""Native `ScalarGridLayer` payload/style/cache contract."""

from __future__ import annotations

import numpy as np
import pytest

grid_render_core = pytest.importorskip("grid_render_core")


def _ramp() -> np.ndarray:
    return np.array(
        [[0, 0, 0, 255], [255, 0, 0, 255], [255, 255, 0, 255]], dtype=np.uint8
    )


def test_scalar_grid_layer_caches_native_raster_by_data_and_style_revision():
    layer = grid_render_core.ScalarGridLayer(
        np.array([[0.0, 0.5], [1.0, np.nan]], dtype=np.float32)
    )
    layer.set_color_ramp(_ramp())
    data0, style0 = layer.data_revision, layer.style_revision

    first = layer.rasterize()
    second = layer.rasterize()
    np.testing.assert_array_equal(first, second)
    assert layer.rasterize_count == 1
    assert first.shape == (2, 2, 4)
    assert first[1, 1, 3] == 0  # NaN remains nodata

    layer.set_gamma(2.0)
    assert layer.data_revision == data0
    assert layer.style_revision == style0 + 1
    styled = layer.rasterize()
    assert layer.rasterize_count == 2
    assert not np.shares_memory(first, styled)
    assert first[0, 1, 0] != styled[0, 1, 0]
    # The first Python-owned snapshot remains stable after the native cache changes.
    assert first[0, 1, 0] == 255

    layer.set_mask(np.array([[1, 0], [1, 1]], dtype=np.uint8))
    assert layer.data_revision == data0 + 1
    layer.rasterize()
    assert layer.rasterize_count == 3
    assert layer.rasterize()[0, 1, 3] == 0


def test_scalar_grid_layer_validates_payload_shapes_and_style_inputs():
    with pytest.raises(ValueError, match="2-D"):
        grid_render_core.ScalarGridLayer(np.array([1.0], dtype=np.float32))

    layer = grid_render_core.ScalarGridLayer(np.zeros((2, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="match grid_z shape"):
        layer.set_mask(np.ones((1, 2), dtype=np.uint8))
    with pytest.raises(ValueError, match="shape"):
        layer.set_grid(np.zeros((1, 4), dtype=np.float32))
    with pytest.raises(ValueError, match="RGBA"):
        layer.set_color_ramp(np.zeros((2, 3), dtype=np.uint8))
    with pytest.raises(RuntimeError, match="color ramp"):
        layer.rasterize()
