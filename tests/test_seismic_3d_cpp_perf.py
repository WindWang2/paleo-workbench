from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.seismic_3d_api import (
    fast_resample_volume_3d,
    fast_slice_to_indexed8,
)


def test_fast_slice_to_indexed8_parity():
    # 3D test volume: 20 x 30 x 40
    np.random.seed(42)
    volume = np.random.randn(20, 30, 40).astype(np.float32)

    # Test axis=0
    slice_u8, v_min, v_max = fast_slice_to_indexed8(volume, axis=0, index=10)
    assert slice_u8.dtype == np.uint8
    assert slice_u8.shape == (30, 40)
    assert slice_u8.min() == 0
    assert slice_u8.max() == 255
    assert v_min < v_max

    # Test axis=2
    slice_u8_t, _, _ = fast_slice_to_indexed8(volume, axis=2, index=15)
    assert slice_u8_t.shape == (20, 30)


def test_fast_resample_volume_3d_parity():
    volume = np.ones((100, 100, 100), dtype=np.float32) * 5.0
    resampled = fast_resample_volume_3d(volume, target_shape=(32, 32, 32))
    assert resampled.shape == (32, 32, 32)
    assert np.allclose(resampled, 5.0)
