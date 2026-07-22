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
    """Compute 3D seismic coherence/similarity volume (per-sample vertical window)."""
    if HAS_CPP_SEISMIC and hasattr(seismic_3d_core, "compute_coherence_3d"):
        return seismic_3d_core.compute_coherence_3d(
            volume, int(inline_window), int(crossline_window), int(sample_window)
        )

    vol = np.asarray(volume, dtype=np.float32)
    ni, nx, nt = vol.shape
    coh = np.ones_like(vol, dtype=np.float32)

    half_i = inline_window // 2
    half_x = crossline_window // 2
    half_t = sample_window // 2

    ks = np.arange(nt)
    k0 = np.maximum(0, ks - half_t)
    k1 = np.minimum(nt, ks + half_t + 1)  # exclusive upper bound
    win_len = (k1 - k0).astype(np.float64)

    for i in range(half_i, ni - half_i):
        for j in range(half_x, nx - half_x):
            sub = vol[
                i - half_i : i + half_i + 1,
                j - half_x : j + half_x + 1,
                :,
            ].astype(np.float64)
            mean_sq = np.mean(sub, axis=(0, 1)) ** 2  # (nt,)
            sum_sq = np.sum(sub**2, axis=(0, 1))      # (nt,)
            cs_num = np.concatenate([[0.0], np.cumsum(mean_sq)])
            cs_den = np.concatenate([[0.0], np.cumsum(sum_sq)])
            num = cs_num[k1] - cs_num[k0]
            den = (cs_den[k1] - cs_den[k0]) / win_len + 1e-12
            coh[i, j, :] = np.clip(num / den, 0.0, 1.0)

    return coh


def marching_cubes_3d(
    volume: np.ndarray,
    isovalue: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract 3D isosurface mesh (vertices, faces) at isovalue.

    C++ path uses marching tetrahedra (watertight). Falls back to
    scikit-image when available; raises ImportError otherwise.
    """
    if HAS_CPP_SEISMIC and hasattr(seismic_3d_core, "marching_cubes_3d"):
        return seismic_3d_core.marching_cubes_3d(volume, float(isovalue))

    try:
        from skimage.measure import marching_cubes
    except ImportError as exc:
        raise ImportError(
            "marching_cubes_3d requires the seismic_3d_core C++ extension "
            "or scikit-image"
        ) from exc

    verts, faces, _normals, _values = marching_cubes(volume, level=float(isovalue))
    return verts.astype(np.float32), faces.astype(np.int32)
