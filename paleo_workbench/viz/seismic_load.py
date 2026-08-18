from __future__ import annotations

import math
from pathlib import Path

import numpy as np

# Cap total voxels when building a dense ndarray for prediction / joint preview.
# Full-resolution SEGY is never materialised through this path; consumers that
# need interactive 2D slices should use SeismicVolumeSource.read_inline/etc.
MAX_DIM = 128
MAX_BUDGET = MAX_DIM * MAX_DIM * MAX_DIM


def load_seismic_volume_from_path(path: str) -> tuple[np.ndarray | None, str]:
    """Load a **bounded preview** volume via :class:`SeismicVolumeSource`.

    Visualization prefers ``SeismicView.load_segy(path)`` (native async).
    This helper remains for prediction mocks, joint-host preview LOD, and
    load_demo fallbacks — it must **not** build a full native-resolution cube.

    Flow::

        path → SeismicVolumeSource.metadata()  # headers only
            → read_preview(max_budget=MAX_BUDGET)  # strided / cached
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None, "SEGY 文件不存在"

    try:
        from paleo_workbench.viz.seismic_volume_source import get_shared_seismic_source

        source = get_shared_seismic_source(file_path)
        meta = source.metadata()
        # Time-to-metadata is recorded on meta.metadata_ms for benchmarks.
        volume, warning = source.read_preview(
            max_dim=MAX_DIM, max_budget=MAX_BUDGET, lod=0
        )
        if volume is None:
            return None, warning or "SEGY 预览加载失败"
        if meta.is_pseudo and not warning:
            warning = "SEGY 无完整三维几何，已按伪三维预览"
        return volume, warning
    except Exception:
        # Last-resort independent pseudo path (no shared source).
        return _load_pseudo_3d_ignore_geometry(str(file_path))


def _load_pseudo_3d_ignore_geometry(path: str) -> tuple[np.ndarray | None, str]:
    """Fallback when structured geometry is unavailable (explicit pseudo path)."""
    try:
        import segyio
    except Exception:
        return None, "segyio 不可用，无法加载 SEGY"

    try:
        with segyio.open(path, "r", ignore_geometry=True) as cube:
            n_traces = int(getattr(cube, "tracecount", 0) or 0)
            samples = getattr(cube, "samples", None) or ()
            n_samples = len(samples)
            if n_traces <= 0 or n_samples <= 0:
                return None, "SEGY 无有效道或采样"

            target_side = 48
            needed = target_side * target_side
            t_step = max(1, math.ceil(n_traces / needed))
            s_step = max(1, math.ceil(n_samples / MAX_DIM))
            t_indices = list(range(0, n_traces, t_step))[:needed]
            sample_slice = slice(None, None, s_step)

            rows: list[np.ndarray] = []
            for ti in t_indices:
                trace = np.asarray(cube.trace[ti], dtype=np.float32)[sample_slice]
                if trace.size > MAX_DIM:
                    stride = max(1, math.ceil(trace.size / MAX_DIM))
                    trace = trace[::stride][:MAX_DIM]
                rows.append(trace.astype(np.float32, copy=False))
            if not rows:
                return None, "SEGY 读取结果为空"
            min_len = min(r.size for r in rows)
            if min_len < 1:
                return None, "SEGY 采样长度为 0"
            stacked = np.stack([r[:min_len] for r in rows], axis=0)
            actual_side = int(math.isqrt(stacked.shape[0]))
            usable = actual_side * actual_side
            if usable < 1:
                return None, "SEGY 2D 读取结果为空"
            stacked = stacked[:usable]
            volume = stacked.reshape(actual_side, actual_side, min_len).astype(np.float32)
            volume, further = _bound_volume(volume)
            warning = (
                f"SEGY 无完整三维几何，已按伪三维预览 "
                f"(shape={tuple(int(x) for x in volume.shape)})"
            )
            if further:
                warning += " · 已截断至预览预算"
            return volume, warning
    except Exception as exc:
        return None, f"SEGY 加载失败: {exc.__class__.__name__}"


def _bound_volume(
    volume: np.ndarray,
    *,
    max_dim: int = MAX_DIM,
) -> tuple[np.ndarray, bool]:
    """Safety-bound a volume to ``max_dim`` per axis.

    The bound must match the caller's budget (#825): read_preview computes
    strides for its own (max_dim, max_budget), so a post-read clamp against
    the module-default 128 would silently truncate LOD1/LOD2 cubes whose
    strided axes legitimately exceed 128, breaking the shape-vs-strides
    contract that read_lod_volume_with_strides validates.
    """
    from paleo_workbench.viz.seismic_3d_api import fast_resample_volume_3d

    vol = np.asarray(volume, dtype=np.float32)
    if vol.ndim == 1:
        vol = vol.reshape(1, 1, -1)
    elif vol.ndim == 2:
        vol = vol.reshape(1, vol.shape[0], vol.shape[-1])
    elif vol.ndim > 3:
        vol = vol.reshape(-1, vol.shape[-2], vol.shape[-1])

    s0, s1, s2 = vol.shape
    truncated = s0 > max_dim or s1 > max_dim or s2 > max_dim
    if truncated:
        t0 = min(s0, max_dim)
        t1 = min(s1, max_dim)
        t2 = min(s2, max_dim)
        out = fast_resample_volume_3d(vol, (t0, t1, t2))
    else:
        out = vol

    return out.astype(np.float32, copy=False), truncated
