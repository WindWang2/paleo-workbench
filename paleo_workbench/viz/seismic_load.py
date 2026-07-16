from __future__ import annotations

import math
from pathlib import Path

import numpy as np

# Cap total voxels when building a ndarray for prediction / load_demo fallback.
MAX_DIM = 128
MAX_BUDGET = MAX_DIM * MAX_DIM * MAX_DIM


def load_seismic_volume_from_path(path: str) -> tuple[np.ndarray | None, str]:
    """Load a bounded 3-D volume via public ``geoviz.SeismicLoader`` when possible.

    Visualization prefers ``SeismicView.load_segy(path)``; this volume path
    remains for prediction mocks and load_demo fallbacks.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None, "SEGY 文件不存在"

    try:
        from geoviz import SeismicLoader

        loader = SeismicLoader(str(file_path))
        try:
            meta = loader.inspect()
            fi = max(1, math.ceil(meta.n_inlines / MAX_DIM))
            fx = max(1, math.ceil(meta.n_crosslines / MAX_DIM))
            ft = max(1, math.ceil(meta.n_samples / MAX_DIM))
            volume = loader.get_volume_downsampled(factor=(fi, fx, ft))
            volume, further = _bound_volume(np.asarray(volume, dtype=np.float32))
            truncated = fi > 1 or fx > 1 or ft > 1 or further
            warning = ""
            if truncated:
                warning = (
                    f"SEGY 已按下采样加载 "
                    f"(shape={tuple(int(x) for x in volume.shape)}, via SeismicLoader)"
                )
            return volume, warning
        finally:
            loader.close()
    except Exception:
        pass

    return _load_pseudo_3d_ignore_geometry(str(file_path))


def _load_pseudo_3d_ignore_geometry(path: str) -> tuple[np.ndarray | None, str]:
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


def _bound_volume(volume: np.ndarray) -> tuple[np.ndarray, bool]:
    vol = np.asarray(volume, dtype=np.float32)
    if vol.ndim == 1:
        vol = vol.reshape(1, 1, -1)
    elif vol.ndim == 2:
        vol = vol.reshape(1, vol.shape[0], vol.shape[1])
    elif vol.ndim > 3:
        vol = vol.reshape(-1, vol.shape[-2], vol.shape[-1])

    truncated = False
    slices: list[slice] = []
    for dim in vol.shape:
        if dim > MAX_DIM:
            step = max(1, math.ceil(dim / MAX_DIM))
            slices.append(slice(None, None, step))
            truncated = True
        else:
            slices.append(slice(None))
    out = vol[tuple(slices)]
    while int(np.prod(out.shape)) > MAX_BUDGET and out.size > 1:
        axis = int(np.argmax(out.shape))
        indexer = [slice(None)] * out.ndim
        indexer[axis] = slice(None, None, 2)
        out = out[tuple(indexer)]
        truncated = True
    if any(d > MAX_DIM for d in out.shape):
        out = out[tuple(slice(0, MAX_DIM) for _ in out.shape)]
        truncated = True
    return out.astype(np.float32, copy=False), truncated
