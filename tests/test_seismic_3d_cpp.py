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


def test_cpp_extension_is_loaded():
    assert HAS_CPP_SEISMIC is True


def test_fast_slice_extract_parity_with_python():
    vol = np.arange(8 * 12 * 16, dtype=np.float32).reshape(8, 12, 16)

    # C++ path
    slice_cpp = fast_slice_extract(vol, axis=0, index=2)

    # Force Python fallback path
    with patch.object(seismic_3d_api, "HAS_CPP_SEISMIC", False):
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

    # Force Python fallback path
    with patch.object(seismic_3d_api, "HAS_CPP_SEISMIC", False):
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
