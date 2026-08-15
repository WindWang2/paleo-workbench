"""Audit regression tests for native C++ defects and Python parity alignment.

Covers: grid_render_core empty-LUT validation (I1), seismic_3d_core zero-dim
coherence (I2), +Inf marching-cubes vertices (I5), and the pure-Python parity
fallbacks realigned with the C++ sampling grids (A1/A6/I3/I4).
"""
from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.native_backend import disabled_acceleration
from paleo_workbench.viz.seismic_3d_api import (
    HAS_CPP_SEISMIC,
    compute_coherence_3d,
    fast_resample_volume_3d,
    fast_slice_to_indexed8,
    marching_cubes_3d,
)

grid_render_core = pytest.importorskip("grid_render_core")


def test_render_grid_rgba_rejects_empty_lut():
    """Audit I1: an empty LUT must raise, never return heap garbage."""
    lut = np.zeros((0, 4), dtype=np.uint8)
    grid = np.linspace(0.0, 1.0, 16, dtype=np.float32).reshape(4, 4)
    with pytest.raises(Exception):
        grid_render_core.render_grid_rgba(grid, lut, 0.0, 1.0)


@pytest.mark.skipif(not HAS_CPP_SEISMIC, reason="seismic_3d_core not built")
def test_compute_coherence_zero_dim_volume_does_not_crash():
    """Audit I2: nt==0 previously underflowed `nt - 1` and segfaulted."""
    volume = np.zeros((4, 4, 0), dtype=np.float32)
    result = compute_coherence_3d(volume)
    assert result.shape == (4, 4, 0)


@pytest.mark.skipif(not HAS_CPP_SEISMIC, reason="seismic_3d_core not built")
def test_marching_cubes_infinite_voxel_yields_no_nan_vertices():
    """Audit I5: +Inf corners previously produced NaN interpolated vertices."""
    volume = np.zeros((4, 4, 4), dtype=np.float32)
    volume[1:3, 1:3, 1:3] = 1.0
    volume[2, 2, 2] = np.inf  # inside the surface, non-finite
    verts, faces = marching_cubes_3d(volume, isovalue=0.5)
    assert verts.size > 0
    assert np.isfinite(verts).all()


@pytest.mark.skipif(not HAS_CPP_SEISMIC, reason="seismic_3d_core not built")
def test_resample_parity_between_cpp_and_python_sampling_grid():
    """Audit A1/I4: the Python fallback must use the C++ trunc(i*s/t) grid."""
    rng = np.random.default_rng(5)
    volume = rng.uniform(-1.0, 1.0, size=(37, 23, 41)).astype(np.float32)
    target = (16, 8, 32)

    native = fast_resample_volume_3d(volume, target)
    with disabled_acceleration():
        fallback = fast_resample_volume_3d(volume, target)

    assert fallback.shape == native.shape
    np.testing.assert_array_equal(fallback, native)


@pytest.mark.skipif(not HAS_CPP_SEISMIC, reason="seismic_3d_core not built")
@pytest.mark.parametrize("axis", [0, 1, 2])
def test_slice_to_indexed8_parity_including_nan(axis):
    """Audit A6/I3: fallback stretch must exclude non-finite values like C++.

    Pixel equality is asserted within 1 LSB: the native build uses
    -ffast-math, and the compiler may contract (v-min)*inv_range into an FMA,
    which can round the boundary pixel by one ulp relative to the numpy chain.
    The contract under test — non-finite samples excluded from the stretch,
    non-finite pixels rendered as 0, and identical reported ranges — must hold
    exactly.
    """
    rng = np.random.default_rng(9)
    volume = rng.uniform(-10.0, 10.0, size=(9, 12, 15)).astype(np.float32)
    volume[3, 4, 5] = np.nan
    volume[2, 2, 2] = np.inf
    index = 4

    native_u8, native_lo, native_hi = fast_slice_to_indexed8(volume, axis, index)
    with disabled_acceleration():
        py_u8, py_lo, py_hi = fast_slice_to_indexed8(volume, axis, index)

    assert native_lo == py_lo
    assert native_hi == py_hi
    assert np.max(np.abs(native_u8.astype(np.int16) - py_u8.astype(np.int16))) <= 1
    slice_data = np.take(volume, index, axis=axis)
    non_finite = ~np.isfinite(slice_data)
    if non_finite.any():
        assert (native_u8[non_finite] == 0).all()
        assert (py_u8[non_finite] == 0).all()


@pytest.mark.skipif(not HAS_CPP_SEISMIC, reason="seismic_3d_core not built")
def test_slice_to_indexed8_constant_slice_reports_zero_range():
    """Constant slices: C++ returns (0.0, 0.0) — the fallback must match."""
    volume = np.full((4, 5, 6), 3.25, dtype=np.float32)

    native_u8, native_lo, native_hi = fast_slice_to_indexed8(volume, 2, 1)
    with disabled_acceleration():
        py_u8, py_lo, py_hi = fast_slice_to_indexed8(volume, 2, 1)

    assert (native_lo, native_hi) == (0.0, 0.0)
    assert (py_lo, py_hi) == (0.0, 0.0)
    np.testing.assert_array_equal(native_u8, py_u8)


@pytest.mark.skipif(not HAS_CPP_SEISMIC, reason="seismic_3d_core not built")
def test_slice_to_indexed8_large_time_slice_preserves_true_extrema():
    """Audit C44: the axis-2 min/max pass must be min/max-preserving.

    The old stride-4 sample (total > 65536 cells) skipped the true maximum at
    flat index 1506 (≡ 2 mod 4) and reported (0, 0), black-screening the
    slice. Every element must contribute to the extrema.
    """
    volume = np.zeros((300, 300, 3), dtype=np.float32)
    volume[5, 6, 1] = 9.5  # flat index 1506 of the axis-2 slice, ≡ 2 (mod 4)

    native_u8, native_lo, native_hi = fast_slice_to_indexed8(volume, 2, 1)
    with disabled_acceleration():
        py_u8, py_lo, py_hi = fast_slice_to_indexed8(volume, 2, 1)

    assert (native_lo, native_hi) == (0.0, 9.5)
    assert (py_lo, py_hi) == (0.0, 9.5)
    assert native_u8[5, 6] == 255
    assert py_u8[5, 6] == 255


@pytest.mark.skipif(not HAS_CPP_SEISMIC, reason="seismic_3d_core not built")
def test_slice_to_indexed8_value_range_parity():
    """A caller-supplied (vmin, vmax) overrides the per-slice stretch in both
    backends and keeps slice-to-slice color mapping stable (C44)."""
    rng = np.random.default_rng(11)
    volume = rng.uniform(-10.0, 10.0, size=(9, 12, 15)).astype(np.float32)
    volume[3, 4, 5] = np.nan

    native_u8, native_lo, native_hi = fast_slice_to_indexed8(
        volume, 1, 4, value_range=(-2.0, 2.0)
    )
    with disabled_acceleration():
        py_u8, py_lo, py_hi = fast_slice_to_indexed8(
            volume, 1, 4, value_range=(-2.0, 2.0)
        )

    assert (native_lo, native_hi) == (-2.0, 2.0)
    assert (py_lo, py_hi) == (-2.0, 2.0)
    np.testing.assert_array_equal(native_u8, py_u8)
    # Values beyond the range clamp instead of re-stretching.
    assert native_u8.min() == 0
    assert native_u8.max() == 255
    assert native_u8[3, 5] == 0  # NaN pixel still renders as 0
