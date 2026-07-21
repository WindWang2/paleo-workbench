from __future__ import annotations

import numpy as np

try:
    import seismic_3d_core
    HAS_CPP_SEISMIC = True
except ImportError:  # pragma: no cover
    seismic_3d_core = None
    HAS_CPP_SEISMIC = False

__all__ = [
    "HAS_CPP_SEISMIC",
    "compute_coherence_3d",
    "fast_resample_volume_3d",
    "fast_slice_extract",
    "fast_slice_to_indexed8",
    "marching_cubes_3d",
]


def fast_slice_extract(volume: np.ndarray, axis: int, index: int) -> np.ndarray:
    """Extract a 2D slice along axis (0=inline, 1=crossline, 2=time/sample)."""
    if HAS_CPP_SEISMIC and hasattr(seismic_3d_core, "fast_slice_extract"):
        return seismic_3d_core.fast_slice_extract(volume, int(axis), int(index))

    vol = np.asarray(volume)
    axis_idx = int(axis) % vol.ndim
    idx = max(0, min(int(index), vol.shape[axis_idx] - 1))
    indexer = [slice(None)] * vol.ndim
    indexer[axis_idx] = idx
    return vol[tuple(indexer)].copy()


def fast_slice_to_indexed8(
    volume: np.ndarray, axis: int, index: int
) -> tuple[np.ndarray, float, float]:
    """Extract a 2D slice and normalize it to Indexed8 uint8 in one fast pass."""
    if HAS_CPP_SEISMIC and hasattr(seismic_3d_core, "fast_slice_to_indexed8"):
        res = seismic_3d_core.fast_slice_to_indexed8(volume, int(axis), int(index))
        return res[0], float(res[1]), float(res[2])

    slice_data = fast_slice_extract(volume, axis, index)
    slice_clean = np.nan_to_num(slice_data, nan=0.0, posinf=0.0, neginf=0.0)
    v_min = float(slice_clean.min()) if slice_clean.size > 0 else 0.0
    v_max = float(slice_clean.max()) if slice_clean.size > 0 else 0.0
    if v_max > v_min:
        norm = ((slice_clean - v_min) / (v_max - v_min) * 255.0).astype(np.uint8)
    else:
        norm = np.zeros(slice_clean.shape, dtype=np.uint8)
    return norm, v_min, v_max


def fast_resample_volume_3d(
    volume: np.ndarray, target_shape: tuple[int, int, int]
) -> np.ndarray:
    """Fast 3D volume downsampling / resampling for LOD visualization."""
    if HAS_CPP_SEISMIC and hasattr(seismic_3d_core, "fast_resample_volume_3d"):
        return seismic_3d_core.fast_resample_volume_3d(volume, target_shape)

    vol = np.asarray(volume, dtype=np.float32)
    s0, s1, s2 = vol.shape
    t0, t1, t2 = target_shape
    idx0 = np.linspace(0, s0 - 1, t0, dtype=np.int32)
    idx1 = np.linspace(0, s1 - 1, t1, dtype=np.int32)
    idx2 = np.linspace(0, s2 - 1, t2, dtype=np.int32)
    return vol[np.ix_(idx0, idx1, idx2)]


def compute_coherence_3d(
    volume: np.ndarray,
    inline_window: int = 3,
    crossline_window: int = 3,
    sample_window: int = 3,
) -> np.ndarray:
    """Compute 3D seismic coherence/similarity volume."""
    if HAS_CPP_SEISMIC and hasattr(seismic_3d_core, "compute_coherence_3d"):
        return seismic_3d_core.compute_coherence_3d(
            volume, int(inline_window), int(crossline_window), int(sample_window)
        )

    vol = np.asarray(volume, dtype=np.float32)
    ni, nx, nt = vol.shape
    coh = np.ones_like(vol, dtype=np.float32)

    half_i = inline_window // 2
    half_x = crossline_window // 2

    for i in range(half_i, ni - half_i):
        for j in range(half_x, nx - half_x):
            sub = vol[
                i - half_i : i + half_i + 1,
                j - half_x : j + half_x + 1,
                :,
            ]
            num = np.sum(np.mean(sub, axis=(0, 1)) ** 2)
            den = np.mean(np.sum(sub**2, axis=(0, 1))) + 1e-12
            val = float(np.clip(num / den, 0.0, 1.0))
            coh[i, j, :] = val

    return coh


def marching_cubes_3d(
    volume: np.ndarray,
    isovalue: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract 3D isosurface mesh (vertices, faces) at isovalue."""
    if HAS_CPP_SEISMIC and hasattr(seismic_3d_core, "marching_cubes_3d"):
        return seismic_3d_core.marching_cubes_3d(volume, float(isovalue))

    try:
        from skimage.measure import marching_cubes

        verts, faces, _normals, _values = marching_cubes(volume, level=float(isovalue))
        return verts.astype(np.float32), faces.astype(np.int32)
    except ImportError:  # Fallback simplified grid mesh generator for testing environment
        vol = np.asarray(volume, dtype=np.float32)
        grid_x, grid_y, grid_z = np.where(vol >= float(isovalue))
        if grid_x.size == 0:
            return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.int32)
        pts = np.column_stack([grid_x, grid_y, grid_z]).astype(np.float32)
        n_pts = pts.shape[0]
        faces_list = []
        for i in range(0, n_pts - 2, 3):
            faces_list.append([i, i + 1, i + 2])
        faces = np.array(faces_list, dtype=np.int32) if faces_list else np.zeros((0, 3), dtype=np.int32)
        return pts, faces
