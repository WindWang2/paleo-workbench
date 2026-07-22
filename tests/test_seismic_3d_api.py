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


def test_compute_coherence_3d_sample_window_takes_effect():
    np.random.seed(7)
    vol = np.random.randn(8, 8, 12).astype(np.float32)

    coh_w1 = compute_coherence_3d(vol, inline_window=3, crossline_window=3, sample_window=1)
    coh_w5 = compute_coherence_3d(vol, inline_window=3, crossline_window=3, sample_window=5)

    assert coh_w1.shape == coh_w5.shape == vol.shape
    # sample_window 生效后，不同垂直窗的结果必须不同
    assert not np.allclose(coh_w1, coh_w5)


def _sphere_volume() -> np.ndarray:
    x, y, z = np.ogrid[:20, :20, :20]
    return (25.0 - ((x - 10) ** 2 + (y - 10) ** 2 + (z - 10) ** 2)).astype(np.float32)


def test_marching_cubes_3d_sphere_surface_radius():
    vol = _sphere_volume()
    verts, faces = marching_cubes_3d(vol, isovalue=0.0)
    assert verts.shape[0] > 0 and faces.shape[0] > 0
    dist = np.linalg.norm(
        verts.astype(np.float64) - np.array([10.0, 10.0, 10.0]), axis=1
    )
    # 真实等值面顶点必须落在 r=5 球面附近；点汤实现含内部格点会失败
    assert np.all(dist >= 4.5)
    assert np.all(dist <= 5.5)


def test_marching_cubes_3d_faces_within_bounds():
    vol = _sphere_volume()
    verts, faces = marching_cubes_3d(vol, isovalue=0.0)
    assert faces.min() >= 0
    assert faces.max() < verts.shape[0]


def test_marching_cubes_3d_sphere_mesh_is_watertight():
    from collections import Counter

    vol = _sphere_volume()
    verts, faces = marching_cubes_3d(vol, isovalue=0.0)
    # 无顶点去重：先按坐标（1e-4 量化）归并再统计棱共享次数
    keys = np.round(verts.astype(np.float64), decimals=4)
    _uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    faces_u = inv[faces]
    edge_count: Counter = Counter()
    for a, b, c in faces_u:
        for e in ((a, b), (b, c), (c, a)):
            edge_count[tuple(sorted((int(e[0]), int(e[1]))))] += 1
    assert edge_count, "mesh is empty"
    assert all(v == 2 for v in edge_count.values())


def test_marching_cubes_3d_empty_when_threshold_out_of_range():
    vol = _sphere_volume()
    verts, faces = marching_cubes_3d(vol, isovalue=1.0e9)
    assert verts.shape == (0, 3)
    assert faces.shape == (0, 3)


def test_marching_cubes_3d_parity_with_skimage():
    skm = pytest.importorskip("skimage.measure")
    vol = _sphere_volume()
    verts_cpp, faces_cpp = marching_cubes_3d(vol, isovalue=0.0)
    verts_sk, faces_sk, _n, _v = skm.marching_cubes(vol, level=0.0)
    # 算法不同（tetra vs lewiner），只验顶点数同量级与 bbox 一致
    assert 0.5 < verts_cpp.shape[0] / max(1, verts_sk.shape[0]) < 4.0
    np.testing.assert_allclose(verts_cpp.min(axis=0), verts_sk.min(axis=0), atol=0.6)
    np.testing.assert_allclose(verts_cpp.max(axis=0), verts_sk.max(axis=0), atol=0.6)
