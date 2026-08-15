"""Regression tests for cpp-core-review findings in seismic_3d_core.

Each test exercises a degenerate / adversarial input the passing parity
suite would not catch, and asserts the C++ path and the Python fallback
behave identically (both raise, or both return the same result).
Findings reference .superpowers/sdd/cpp-core-review.md §1.
"""
from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.native_backend import disabled_acceleration
from paleo_workbench.viz.seismic_3d_api import (
    HAS_CPP_SEISMIC,
    compute_coherence_3d,
    fast_resample_volume_3d,
    fast_slice_extract,
)

# Defer the hard C++ import so missing extensions skip via pytestmark below
# instead of crashing collection. ``seismic_3d_core`` is only referenced inside
# test bodies guarded by ``HAS_CPP_SEISMIC``.
try:
    import seismic_3d_core  # noqa: F401
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not HAS_CPP_SEISMIC,
    reason="seismic_3d_core C++ extension not installed",
)


def _both_paths(fn, *args, **kwargs):
    """Return (cpp_result, py_result); exceptions are returned, not raised."""
    try:
        cpp = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — parity test wants any error
        cpp = exc
    # Force the Python fallback via the native_backend seam. The old
    # patch.object(HAS_CPP_SEISMIC, False) idiom was dead after the façade
    # migrated to native_backend.dispatch (which reads is_accelerated, not
    # the module flag) — it ran the C++ path twice.
    with disabled_acceleration():
        try:
            py = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            py = exc
    return cpp, py


def _both_raise(fn, *args, **kwargs) -> None:
    """Assert fn raises on BOTH the C++ and Python-fallback paths."""
    cpp, py = _both_paths(fn, *args, **kwargs)
    assert isinstance(cpp, Exception), f"C++ path did not raise (got {type(cpp)})"
    assert isinstance(py, Exception), f"Python path did not raise (got {type(py)})"


# ---------------------------------------------------------------------------
# C1 — zero-sized axis OOB read in fast_slice_extract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_c1_zero_sized_axis_raises_on_both_paths(axis):
    shape = [4, 4, 4]
    shape[axis] = 0
    vol = np.zeros(shape, dtype=np.float32)
    _both_raise(fast_slice_extract, vol, axis, 0)


# ---------------------------------------------------------------------------
# I1 — out-of-range index now raises instead of silently clamping
# ---------------------------------------------------------------------------


def test_i1_out_of_range_index_raises_on_both_paths():
    vol = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    _both_raise(fast_slice_extract, vol, 0, 10 ** 9)


def test_i1_negative_index_raises_on_both_paths():
    vol = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    _both_raise(fast_slice_extract, vol, 0, -1)


def test_i1_in_range_index_still_works():
    vol = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    cpp, py = _both_paths(fast_slice_extract, vol, 0, 1)
    assert not isinstance(cpp, Exception)
    np.testing.assert_array_equal(cpp, py)


# ---------------------------------------------------------------------------
# C2 — size_t underflow on empty source in fast_resample_volume_3d
# I3 — negative target_shape element
# ---------------------------------------------------------------------------


def test_c2_empty_source_dimension_raises_on_both_paths():
    vol = np.zeros((0, 4, 5), dtype=np.float32)
    _both_raise(fast_resample_volume_3d, vol, (2, 2, 2))


def test_i3_negative_target_shape_raises_on_both_paths():
    vol = np.arange(4 * 5 * 6, dtype=np.float32).reshape(4, 5, 6)
    _both_raise(fast_resample_volume_3d, vol, (2, -1, 2))


def test_i3_zero_target_shape_raises_on_both_paths():
    vol = np.arange(4 * 5 * 6, dtype=np.float32).reshape(4, 5, 6)
    _both_raise(fast_resample_volume_3d, vol, (2, 0, 2))


# ---------------------------------------------------------------------------
# C3 — negative / zero / even window params in compute_coherence_3d
# M3 — even windows now rejected (previously silently floored)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_window", [-2, 0, 4])
def test_c3_invalid_window_raises_on_both_paths(bad_window):
    vol = np.random.randn(8, 8, 10).astype(np.float32)
    _both_raise(compute_coherence_3d, vol, bad_window, 3, 3)


def test_c3_odd_window_parity_preserved_after_size_t_rewrite():
    """Regression guard: the size_t loop rewrite must not change results."""
    np.random.seed(123)
    vol = np.random.randn(8, 8, 10).astype(np.float32)
    cpp, py = _both_paths(compute_coherence_3d, vol, 3, 3, 5)
    assert not isinstance(cpp, Exception)
    np.testing.assert_allclose(cpp, py, rtol=1e-4, atol=1e-4)


# ---------------------------------------------------------------------------
# I2 — NaN voxels must not poison isosurface mesh vertices
# ---------------------------------------------------------------------------


def test_i2_nan_voxel_does_not_emit_nan_vertices():
    # Solid block with a NaN hole: cubes touching the NaN voxel are skipped.
    vol = np.zeros((5, 5, 5), dtype=np.float32)
    vol[1:4, 1:4, 1:4] = 1.0
    vol[2, 2, 2] = np.nan
    verts, _faces = seismic_3d_core.marching_cubes_3d(vol, 0.5)
    assert len(verts) > 0, "expected a non-empty surface around the hole"
    assert not np.isnan(verts).any(), "NaN vertices leaked into the mesh"


def test_i2_clean_volume_unchanged():
    vol = np.zeros((10, 10, 10), dtype=np.float32)
    vol[3:7, 3:7, 3:7] = 1.0
    verts, faces = seismic_3d_core.marching_cubes_3d(vol, 0.5)
    assert verts.shape[1] == 3 and faces.shape[1] == 3
    assert not np.isnan(verts).any()


# ---------------------------------------------------------------------------
# Issue #385 — a NaN sample permanently poisons the C++ coherence running
# sums (NaN - x == NaN), forcing every deeper sample of the affected trace
# columns to 0.0 ("fake faults"). The window sums must recover once the NaN
# slides out of the window, exactly like the Python fallback's per-window
# recompute.
# ---------------------------------------------------------------------------


def _nan_parity(volume, iw, xw, sw):
    cpp, py = _both_paths(compute_coherence_3d, volume, iw, xw, sw)
    assert not isinstance(cpp, Exception)
    return cpp, py


def test_coherence_single_nan_recovers_and_matches_fallback():
    """Minimal case from the issue: NaN at [2,2,6] in a (5,5,12) volume with a
    (3,3,3) window. Before the fix every sample at k >= 8 of the 9 affected
    trace columns was clamped to 0.0; now only window-overlapping samples are
    zero and deeper samples recover to the fallback's values."""
    vol = np.arange(5 * 5 * 12, dtype=np.float32).reshape(5, 5, 12) / 100.0
    vol[2, 2, 6] = np.nan
    cpp, py = _nan_parity(vol, 3, 3, 3)

    np.testing.assert_allclose(cpp, py, rtol=1e-6, atol=1e-6)
    np.testing.assert_array_equal(cpp == 0.0, py == 0.0)
    # The 3x3 spatial window at i=j=2 covers 9 trace columns; with half_t=1
    # the NaN overlaps samples k in [5, 7] -> 3 zero samples per column.
    assert (cpp == 0.0).sum() == 9 * 3
    # Deeper samples must have recovered (not forced to zero).
    assert cpp[2, 2, 8:].min() > 0.0


def test_coherence_multiple_nans_recover_and_match_fallback():
    rng = np.random.default_rng(5)
    vol = rng.standard_normal((7, 7, 16)).astype(np.float32)
    vol[2, 3, 4] = np.nan
    vol[2, 3, 9] = np.nan
    vol[5, 1, 12] = np.nan
    cpp, py = _nan_parity(vol, 3, 3, 3)
    np.testing.assert_allclose(cpp, py, rtol=1e-6, atol=1e-6)
    np.testing.assert_array_equal(cpp == 0.0, py == 0.0)
    # Recovery below the last NaN: the tail of the affected columns is clean.
    assert cpp[2, 3, 13:].min() > 0.0


def test_coherence_sparse_nan_zero_fraction_matches_fallback():
    """The 64x64x120 @ 0.1% NaN scenario: the fraction of forced-zero samples
    must equal the fallback's (only windows overlapping a NaN), not 36%."""
    rng = np.random.default_rng(11)
    vol = rng.standard_normal((64, 64, 120)).astype(np.float32)
    n_nan = int(vol.size * 0.001)
    idx = rng.choice(vol.size, size=n_nan, replace=False)
    vol.ravel()[idx] = np.nan
    cpp, py = _nan_parity(vol, 3, 3, 3)
    np.testing.assert_allclose(cpp, py, rtol=1e-6, atol=1e-6)
    assert (cpp == 0.0).sum() == (py == 0.0).sum()
    # Each NaN poisons only its 3x3 spatial window x 3 vertical samples
    # (~2.7% of cells here); nowhere near the pre-fix 36.4% tail poison.
    assert (cpp == 0.0).mean() < 0.10


def test_coherence_nan_free_parity_not_regressed():
    rng = np.random.default_rng(13)
    vol = rng.standard_normal((9, 9, 20)).astype(np.float32)
    cpp, py = _nan_parity(vol, 3, 3, 5)
    np.testing.assert_allclose(cpp, py, rtol=1e-6, atol=1e-6)
    assert (cpp == 0.0).sum() == 0
