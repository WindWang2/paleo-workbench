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
    fast_slice_to_indexed8,
    marching_cubes_3d,
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


# ---------------------------------------------------------------------------
# Issue #446 — fast_slice_extract native/fallback boundary parity
# ---------------------------------------------------------------------------


def test_fse_float64_input_downcasts_to_float32_on_both_paths():
    """The C++ forcecast silently downcasts float64 to float32; the fallback
    must do the same (previously it preserved float64, so the dtype of the
    returned slice depended on which backend was active)."""
    vol = np.arange(2 * 3 * 4, dtype=np.float64).reshape(2, 3, 4)
    cpp, py = _both_paths(fast_slice_extract, vol, 0, 1)
    assert not isinstance(cpp, Exception)
    assert cpp.dtype == np.float32 and py.dtype == np.float32
    np.testing.assert_array_equal(cpp, py)
    np.testing.assert_array_equal(py, vol[1].astype(np.float32))


def test_fse_2d_input_raises_runtime_error_on_both_paths():
    """2-D input: the C++ path raises RuntimeError; the fallback previously
    sliced it silently."""
    _both_raise(fast_slice_extract, np.zeros((5, 4), dtype=np.float32), 0, 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(axis=2**33, index=0),
        dict(axis=0, index=2**33),
        dict(axis=-(2**33), index=0),
        dict(axis=0, index=-(2**33)),
    ],
)
def test_fse_out_of_int_range_axis_index_raise_type_error_on_both_paths(kwargs):
    """Values that overflow the C++ int parameter raise TypeError on the native
    path (pybind int caster); the fallback must match instead of silently
    reducing modulo the axis count."""
    cpp, py = _both_paths(fast_slice_extract, np.zeros((2, 3, 4), dtype=np.float32), **kwargs)
    assert isinstance(cpp, TypeError), f"C++ path raised {type(cpp)}"
    assert isinstance(py, TypeError), f"Python path raised {type(py)}"


def test_fse_in_range_out_of_bounds_index_raises_index_error_on_both_paths():
    _both_raise(fast_slice_extract, np.zeros((2, 3, 4), dtype=np.float32), 0, 7)


def test_fse_large_in_range_axis_matches_on_both_paths():
    """axis = 2**20 fits in a C++ int and reduces modulo 3; both paths agree."""
    vol = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    cpp, py = _both_paths(fast_slice_extract, vol, 2**20, 1)
    assert not isinstance(cpp, Exception)
    np.testing.assert_array_equal(cpp, py)


# ---------------------------------------------------------------------------
# Non-finite coherence parity hardening: ±Inf data and float-overflow of the
# float v*v in sum_sq poison the running sums exactly like NaN (Inf - Inf and
# NaN - x are both NaN). The C++ rebuild-on-recovery must cover any non-finite
# sample in either accumulator, not just NaN mean_sq.
# ---------------------------------------------------------------------------


def test_coherence_inf_recovers_and_matches_fallback():
    """A +Inf sample zeroes exactly the window-overlapping samples; deeper
    samples recover to the fallback's values (no sticky tail)."""
    vol = np.arange(5 * 5 * 12, dtype=np.float32).reshape(5, 5, 12) / 100.0
    vol[2, 2, 6] = np.inf
    cpp, py = _nan_parity(vol, 3, 3, 3)
    np.testing.assert_allclose(cpp, py, rtol=1e-6, atol=1e-6)
    np.testing.assert_array_equal(cpp == 0.0, py == 0.0)
    # Same footprint as the NaN case: 3x3 columns x 3 vertical samples.
    assert (cpp == 0.0).sum() == 9 * 3
    assert cpp[2, 2, 8:].min() > 0.0


def test_coherence_mixed_inf_signs_recover_and_match_fallback():
    """+Inf and -Inf in the same spatial window make trace_sum NaN while
    sum_sq is +Inf — both accumulators go non-finite via different routes;
    recovery and per-window semantics must still match the fallback."""
    vol = np.arange(5 * 5 * 12, dtype=np.float32).reshape(5, 5, 12) / 100.0
    vol[2, 2, 6] = np.inf
    vol[3, 3, 6] = -np.inf
    cpp, py = _nan_parity(vol, 3, 3, 3)
    np.testing.assert_allclose(cpp, py, rtol=1e-6, atol=1e-6)
    np.testing.assert_array_equal(cpp == 0.0, py == 0.0)
    assert cpp[2, 2, 8:].min() > 0.0


def test_coherence_float_overflow_recovers_after_window():
    """|v| ~ 1e20 overflows the float ``v * v`` so sum_sq alone goes +Inf while
    mean_sq stays finite — the running denominator was poisoned and could never
    recover (only isnan(run_num) was checked). Once the sample slides out of
    the window both backends must agree again. (While the window overlaps the
    sample the C++ Inf-denominator clamps to 0.0 versus the fallback's small
    finite ratio — a known residual in-window gap, out of scope here.)"""
    vol = np.arange(5 * 5 * 12, dtype=np.float32).reshape(5, 5, 12) / 100.0
    vol[2, 2, 6] = 1e20
    cpp, py = _nan_parity(vol, 3, 3, 3)
    np.testing.assert_allclose(cpp[:, :, :5], py[:, :, :5], rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(cpp[:, :, 8:], py[:, :, 8:], rtol=1e-5, atol=1e-6)
    assert cpp[2, 2, 8:].min() > 0.0


# ---------------------------------------------------------------------------
# fast_slice_to_indexed8 boundary parity (inherits _py_fast_slice_extract's
# validation, plus its own float64 downcast contract)
# ---------------------------------------------------------------------------


def test_indexed8_non_3d_input_raises_runtime_error_on_both_paths():
    """ndim != 3: C++ throws std::runtime_error (-> RuntimeError); the fallback
    must raise the same type instead of silently slicing via axis % ndim."""
    cpp, py = _both_paths(fast_slice_to_indexed8, np.zeros((5, 4), dtype=np.float32), 0, 1)
    assert isinstance(cpp, RuntimeError), f"C++ path raised {type(cpp)}"
    assert type(py) is type(cpp), f"fallback raised {type(py)}"


def test_fse_non_3d_input_raises_same_exception_type_on_both_paths():
    """Same-type check for fast_slice_extract itself, 2-D and 4-D inputs."""
    for bad in (
        np.zeros((5, 4), dtype=np.float32),
        np.zeros((2, 3, 4, 5), dtype=np.float32),
    ):
        cpp, py = _both_paths(fast_slice_extract, bad, 0, 1)
        assert isinstance(cpp, RuntimeError), f"C++ path raised {type(cpp)}"
        assert type(py) is type(cpp), f"fallback raised {type(py)}"


def test_indexed8_float64_input_downcasts_and_matches_on_both_paths():
    """float64 input: both paths downcast to float32 before stretching, so the
    uint8 pixels and the reported (v_min, v_max) are identical."""
    vol = np.arange(2 * 3 * 4, dtype=np.float64).reshape(2, 3, 4) / 7.0
    cpp, py = _both_paths(fast_slice_to_indexed8, vol, 0, 1)
    assert not isinstance(cpp, Exception)
    assert cpp[0].dtype == np.uint8 and py[0].dtype == np.uint8
    np.testing.assert_array_equal(cpp[0], py[0])
    assert cpp[1] == py[1] and cpp[2] == py[2]


# ---------------------------------------------------------------------------
# marching_cubes_3d fallback NaN/Inf guard: non-finite voxels are replaced by a
# strictly-below-range sentinel before calling skimage, so no non-finite value
# can interpolate into a vertex (the C++ path skips those cubes entirely).
# ---------------------------------------------------------------------------


def test_marching_cubes_fallback_non_finite_volume_emits_only_finite_vertices():
    pytest.importorskip("skimage", reason="fallback marching cubes engine")
    vol = np.zeros((5, 5, 5), dtype=np.float32)
    vol[1:4, 1:4, 1:4] = 1.0
    vol[2, 2, 2] = np.nan
    vol[3, 3, 3] = np.inf
    with disabled_acceleration():
        verts, faces = marching_cubes_3d(vol, 0.5)
    assert len(verts) > 0, "expected a surface around the non-finite voxels"
    assert np.isfinite(verts).all(), "non-finite vertices leaked into the mesh"
    assert faces.min() >= 0 and faces.max() < len(verts)
