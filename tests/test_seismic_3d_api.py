from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.seismic_3d_api import (
    HAS_CPP_SEISMIC,
    compute_coherence_3d,
    fast_slice_extract,
    marching_cubes_3d,
)


def test_has_cpp_seismic_flag_is_bool():
    assert isinstance(HAS_CPP_SEISMIC, bool)


def test_fast_slice_extract_inline_crossline_time():
    # Volume shape: 10 x 20 x 30
    vol = np.arange(10 * 20 * 30, dtype=np.float32).reshape(10, 20, 30)

    # Inline slice (axis 0, index 3)
    slice_in = fast_slice_extract(vol, axis=0, index=3)
    assert slice_in.shape == (20, 30)
    np.testing.assert_array_equal(slice_in, vol[3, :, :])

    # Crossline slice (axis 1, index 5)
    slice_xl = fast_slice_extract(vol, axis=1, index=5)
    assert slice_xl.shape == (10, 30)
    np.testing.assert_array_equal(slice_xl, vol[:, 5, :])

    # Time slice (axis 2, index 12)
    slice_t = fast_slice_extract(vol, axis=2, index=12)
    assert slice_t.shape == (10, 20)
    np.testing.assert_array_equal(slice_t, vol[:, :, 12])


def test_compute_coherence_3d_bounds_and_shape():
    np.random.seed(42)
    vol = np.random.randn(12, 12, 16).astype(np.float32)

    coh = compute_coherence_3d(vol, inline_window=3, crossline_window=3, sample_window=3)
    assert coh.shape == vol.shape
    # Coherence values must be within [0.0, 1.0]
    assert np.all(coh >= 0.0)
    assert np.all(coh <= 1.0)


def test_marching_cubes_3d_sphere_mesh():
    # Create a 3D grid with a sphere of radius 5 at center (10, 10, 10)
    x, y, z = np.ogrid[:20, :20, :20]
    dist_sq = (x - 10) ** 2 + (y - 10) ** 2 + (z - 10) ** 2
    vol = (25.0 - dist_sq).astype(np.float32)

    vertices, faces = marching_cubes_3d(vol, isovalue=0.0)

    assert isinstance(vertices, np.ndarray)
    assert isinstance(faces, np.ndarray)
    assert vertices.ndim == 2 and vertices.shape[1] == 3
    assert faces.ndim == 2 and faces.shape[1] == 3
    assert vertices.shape[0] > 0
    assert faces.shape[0] > 0
