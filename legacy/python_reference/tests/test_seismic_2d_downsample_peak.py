"""SEIS-8: 2D seismic LOD decimation must be peak-preserving.

A strided ``data[::step, ::step]`` slice drops thin reflections that fall
between stride points; the decimated cell keeps the largest-magnitude sample.
"""
from __future__ import annotations

import numpy as np

from paleo_workbench.viz.seismic_volume_source import _downsample_2d


def test_thin_reflection_between_stride_points_survives():
    data = np.zeros((32, 32), dtype=np.float32)
    # Strong event on an off-grid trace (row 5, col 5) with step 4; the old
    # strided slice sampled rows/cols {0,4,8,...} and missed (5, 5) entirely.
    data[5, 5] = -2.5
    out = _downsample_2d(data, step=4)
    assert out.shape == (8, 8)
    assert float(np.abs(out).max()) == 2.5
    # Sign preserved (a trough stays a trough).
    assert out[1, 1] == -2.5


def test_peak_magnitude_wins_per_cell_with_sign_preserved():
    data = np.zeros((8, 8), dtype=np.float32)
    data[0:2, 0:2] = [[0.1, -0.9], [3.0, 0.2]]
    out = _downsample_2d(data, step=2)
    assert out.shape == (4, 4)
    assert out[0, 0] == 3.0


def test_nan_cell_keeps_first_nan():
    data = np.zeros((8, 8), dtype=np.float32)
    data[1, 0] = 5.0
    data[1, 1] = np.nan
    out = _downsample_2d(data, step=2)
    assert np.isnan(out[0, 0])


def test_step_one_and_unchanged_values():
    data = np.arange(16, dtype=np.float32).reshape(4, 4)
    out = _downsample_2d(data, step=1)
    np.testing.assert_array_equal(out, data)
    # Flat data is unaffected by the peak-picking rule.
    flat = np.full((9, 9), 1.7, dtype=np.float32)
    np.testing.assert_array_equal(_downsample_2d(flat, step=3), np.full((3, 3), 1.7, dtype=np.float32))


def test_non_divisible_shape_truncates():
    data = np.ones((10, 7), dtype=np.float32)
    data[9, 6] = 4.0  # falls in the truncated remainder region
    out = _downsample_2d(data, step=4)
    assert out.shape == (2, 1)
    assert (out == 1.0).all()
