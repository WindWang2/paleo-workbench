"""GLImageLutItem texture packing must match pyqtgraph GLImageItem axes."""

from __future__ import annotations

import numpy as np

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()


def test_prepare_r8_upload_matches_pyqtgraph_transpose():
    """shape (sx, sy) → upload (sy, sx) with width=sx height=sy."""
    from geoviz_seismic.renderer_3d import GLImageLutItem

    # Time-plane style: axis0 = IL (local X), axis1 = XL (local Y)
    # Unique value per cell so packing errors are obvious.
    sx, sy = 7, 4
    index = np.arange(sx * sy, dtype=np.uint8).reshape(sx, sy)
    upload, width, height = GLImageLutItem.prepare_r8_upload(index)

    assert width == sx and height == sy
    assert upload.shape == (height, width) == (sy, sx)
    # OpenGL row r is continuous in X (width=sx); row 0 is index[:, 0]
    np.testing.assert_array_equal(upload[0, :], index[:, 0])
    np.testing.assert_array_equal(upload[:, 0], index[0, :])
    # Without .T the first GL row would be index[0, :] padded/wrong length
    wrong = np.ascontiguousarray(index).ravel()[:sx]  # first C-order row of (sx,sy)
    assert not np.array_equal(upload[0, :], wrong) or sy == 1


def test_prepare_r8_upload_inline_plane_shape():
    """Inline plane is (nx, nt) — local X=XL, Y=Time after scale(sx, st)."""
    from geoviz_seismic.renderer_3d import GLImageLutItem

    nx, nt = 11, 9
    index = np.arange(nx * nt, dtype=np.uint8).reshape(nx, nt)
    upload, w, h = GLImageLutItem.prepare_r8_upload(index)
    assert (w, h) == (nx, nt)
    assert upload.shape == (nt, nx)
    # Sample at local (x=3, y=5) must land at upload[5, 3]
    assert upload[5, 3] == index[3, 5]


def test_broken_upload_without_transpose_scrambles_map():
    """Document the bug: C-order upload as width=sx height=sy scrambles axes."""
    sx, sy = 8, 5
    index = np.arange(sx * sy, dtype=np.uint8).reshape(sx, sy)
    # Buggy path (old GLImageLutItem)
    flat = np.ascontiguousarray(index).ravel()
    gl_buggy = flat.reshape(sy, sx)  # reinterpret with wrong row length
    # Fixed path
    from geoviz_seismic.renderer_3d import GLImageLutItem

    fixed, _, _ = GLImageLutItem.prepare_r8_upload(index)
    assert not np.array_equal(gl_buggy, fixed)
    assert np.array_equal(fixed, index.T)
