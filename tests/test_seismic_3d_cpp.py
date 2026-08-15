from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from paleo_workbench.viz import seismic_3d_api
from paleo_workbench.viz.seismic_3d_api import (
    HAS_CPP_SEISMIC,
    compute_coherence_3d,
    fast_slice_extract,
    marching_cubes_3d,
)


from paleo_workbench.native_backend import disabled_acceleration

# These tests assert C++ seismic_3d_core behaviour; CI only builds map_edit_core,
# so skip the whole module when the seismic extension is absent.
pytestmark = pytest.mark.skipif(
    not HAS_CPP_SEISMIC,
    reason="seismic_3d_core C++ extension not built in this environment",
)


def test_cpp_extension_is_loaded():
    assert HAS_CPP_SEISMIC is True


def test_fast_slice_extract_parity_with_python():
    vol = np.arange(8 * 12 * 16, dtype=np.float32).reshape(8, 12, 16)

    # C++ path
    slice_cpp = fast_slice_extract(vol, axis=0, index=2)

    # Force Python fallback path via disabled_acceleration seam
    with disabled_acceleration():
        slice_py = fast_slice_extract(vol, axis=0, index=2)

    np.testing.assert_array_equal(slice_cpp, slice_py)


@pytest.mark.parametrize("sample_window", [1, 3, 5])
def test_compute_coherence_3d_parity_with_python(sample_window):
    np.random.seed(123)
    vol = np.random.randn(8, 8, 10).astype(np.float32)

    # C++ path
    coh_cpp = compute_coherence_3d(
        vol, inline_window=3, crossline_window=3, sample_window=sample_window
    )

    # Force Python fallback path via disabled_acceleration seam
    with disabled_acceleration():
        coh_py = compute_coherence_3d(
            vol, inline_window=3, crossline_window=3, sample_window=sample_window
        )

    np.testing.assert_allclose(coh_cpp, coh_py, rtol=1e-4, atol=1e-4)


def test_marching_cubes_3d_output_types():
    vol = np.zeros((10, 10, 10), dtype=np.float32)
    vol[3:7, 3:7, 3:7] = 1.0

    verts, faces = marching_cubes_3d(vol, isovalue=0.5)

    assert isinstance(verts, np.ndarray)
    assert isinstance(faces, np.ndarray)
    assert verts.ndim == 2 and verts.shape[1] == 3
    assert faces.ndim == 2 and faces.shape[1] == 3


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_c1_fast_slice_extract_zero_dim_axis_raises(axis):
    shapes = [(0, 4, 4), (4, 0, 4), (4, 4, 0)]
    vol = np.zeros(shapes[axis], dtype=np.float32)

    with pytest.raises(IndexError):
        fast_slice_extract(vol, axis=axis, index=0)

    # Python fallback must enforce the same contract
    with disabled_acceleration():
        with pytest.raises(IndexError):
            fast_slice_extract(vol, axis=axis, index=0)


def test_c2_fast_resample_volume_3d_empty_source_raises():
    vol = np.zeros((0, 4, 4), dtype=np.float32)

    with pytest.raises((ValueError, std_err := Exception)):
        seismic_3d_api.fast_resample_volume_3d(vol, (4, 4, 4))

    with disabled_acceleration():
        with pytest.raises(ValueError):
            seismic_3d_api.fast_resample_volume_3d(vol, (4, 4, 4))


@pytest.mark.parametrize("target_shape", [(-1, 4, 4), (4, 0, 4), (4, 4, -2)])
def test_i3_fast_resample_volume_3d_invalid_target_shape_raises(target_shape):
    vol = np.zeros((4, 4, 4), dtype=np.float32)

    with pytest.raises(ValueError):
        seismic_3d_api.fast_resample_volume_3d(vol, target_shape)

    with disabled_acceleration():
        with pytest.raises(ValueError):
            seismic_3d_api.fast_resample_volume_3d(vol, target_shape)


@pytest.mark.parametrize("win", [0, -1, 2, 4])
def test_c3_m3_compute_coherence_3d_invalid_windows_raise(win):
    vol = np.zeros((8, 8, 10), dtype=np.float32)

    with pytest.raises(ValueError):
        compute_coherence_3d(vol, inline_window=win)

    with disabled_acceleration():
        with pytest.raises(ValueError):
            compute_coherence_3d(vol, inline_window=win)




# ---------------------------------------------------------------------------
# Issue #419 — peak-preserving stride-block decimation in
# fast_resample_volume_3d (nearest grid-point sampling dropped thin
# reflections between stride samples from LOD previews).
# ---------------------------------------------------------------------------


def test_resample_preserves_peak_between_stride_samples():
    """A strong reflection sitting between stride points must survive the
    decimation (the old nearest sampling never visited it)."""
    from paleo_workbench.viz.seismic_3d_api import fast_resample_volume_3d

    vol = np.zeros((40, 6, 6), dtype=np.float32)
    vol[2, 3, 3] = 9.0    # inside target block 0 (source [0..4])
    vol[20, 3, 3] = -7.0  # inside target block 4
    vol[39, 3, 3] = 5.0   # tail sample, last target block

    native = fast_resample_volume_3d(vol, (8, 6, 6))
    assert native[0, 3, 3] == 9.0
    assert native[4, 3, 3] == -7.0  # sign preserved
    assert native[7, 3, 3] == 5.0

    with disabled_acceleration():
        fallback = fast_resample_volume_3d(vol, (8, 6, 6))
    np.testing.assert_array_equal(native, fallback)


def test_resample_nan_block_is_conservatively_nan():
    """A stride block containing any NaN yields NaN on both paths."""
    from paleo_workbench.viz.seismic_3d_api import fast_resample_volume_3d

    vol = np.zeros((40, 6, 6), dtype=np.float32)
    vol[3, 1, 1] = np.nan  # inside target block 0
    native = fast_resample_volume_3d(vol, (8, 6, 6))
    assert np.isnan(native[0, 1, 1])
    with disabled_acceleration():
        fallback = fast_resample_volume_3d(vol, (8, 6, 6))
    assert np.array_equal(native, fallback, equal_nan=True)


def test_resample_peak_preserving_parity_random_volumes():
    """Downsample and upsample parity between the C++ path and the fallback,
    with NaN/Inf sprinkled in (equal_nan comparison)."""
    from paleo_workbench.viz.seismic_3d_api import fast_resample_volume_3d

    rng = np.random.default_rng(21)
    for shape, target in [
        ((37, 23, 41), (16, 8, 32)),
        ((64, 64, 64), (16, 16, 16)),
        ((4, 5, 6), (8, 9, 10)),   # upsampling
        ((2, 2, 2), (4, 4, 4)),    # upsampling
        ((200, 7, 7), (50, 7, 7)), # heavy axis-0 decimation
    ]:
        vol = rng.uniform(-1.0, 1.0, size=shape).astype(np.float32)
        vol.ravel()[::97] = np.nan
        vol.ravel()[::131] = np.inf
        native = fast_resample_volume_3d(vol, target)
        with disabled_acceleration():
            fallback = fast_resample_volume_3d(vol, target)
        assert np.array_equal(native, fallback, equal_nan=True)
def test_has_cpp_flag_patch_does_not_change_dispatch_routing():
    """Guard #438: native_backend.dispatch routes by is_accelerated(), never by
    the façade HAS_CPP_* constant. Flipping HAS_CPP_SEISMIC must not switch the
    fallback path, or the Python-fallback legs above silently re-run C++."""
    vol = np.zeros((4, 4, 4), dtype=np.float32)

    old_flag = seismic_3d_api.HAS_CPP_SEISMIC
    seismic_3d_api.HAS_CPP_SEISMIC = False
    try:
        with patch(
            "paleo_workbench.native_backend.seismic_3d_core.fast_slice_extract",
            return_value=vol,
        ) as cpp_spy:
            fast_slice_extract(vol, axis=0, index=0)
    finally:
        seismic_3d_api.HAS_CPP_SEISMIC = old_flag

    assert cpp_spy.called, (
        "dispatch must ignore HAS_CPP_SEISMIC; if it reads the flag, the "
        "fallback legs in this file silently re-run C++ again"
    )


