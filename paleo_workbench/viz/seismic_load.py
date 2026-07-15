from __future__ import annotations

import math
from pathlib import Path

import numpy as np

MAX_DIM = 128  # was 64; increased for 2D lines that need more resolution
MAX_BUDGET = MAX_DIM * MAX_DIM * MAX_DIM


def load_seismic_volume_from_path(path: str) -> tuple[np.ndarray | None, str]:
    """Return (volume, warning). volume None on failure. Bound to MAX_DIM^3 budget."""
    file_path = Path(path)
    if not file_path.is_file():
        return None, "SEGY 文件不存在"

    try:
        import segyio
    except Exception:
        return None, "segyio 不可用，无法加载 SEGY"

    try:
        with segyio.open(str(file_path), "r", ignore_geometry=True) as cube:
            n_traces = int(getattr(cube, "tracecount", 0) or 0)
            samples = getattr(cube, "samples", None)
            if samples is None:
                samples = ()
            n_samples = len(samples)
            if n_traces <= 0 or n_samples <= 0:
                return None, "SEGY 无有效道或采样"

            # Stride traces and samples so each axis stays within MAX_DIM.
            t_step = max(1, math.ceil(n_traces / MAX_DIM))
            s_step = max(1, math.ceil(n_samples / MAX_DIM))
            t_indices = list(range(0, n_traces, t_step))
            # Cap to MAX_DIM after stride rounding
            t_indices = t_indices[:MAX_DIM]
            sample_slice = slice(None, None, s_step)

            rows: list[np.ndarray] = []
            for ti in t_indices:
                trace = np.asarray(cube.trace[ti], dtype=np.float32)[sample_slice]
                if trace.size > MAX_DIM:
                    # Extra safety if s_step underestimated
                    stride = max(1, math.ceil(trace.size / MAX_DIM))
                    trace = trace[::stride][:MAX_DIM]
                rows.append(trace.astype(np.float32, copy=False))

            if not rows:
                return None, "SEGY 读取结果为空"

            # Align length (last sample may vary rarely)
            min_len = min(r.size for r in rows)
            if min_len < 1:
                return None, "SEGY 采样长度为 0"
            stacked = np.stack([r[:min_len] for r in rows], axis=0)  # (traces, samples)

            # For 2D seismic lines (no 3D geometry), reshape as
            # (side, side, n_samples) so all three slice planes are meaningful.
            # Use a larger trace budget for 2D so the pseudo-3D grid is usable.
            n_samp = stacked.shape[1]
            target_side = min(48, int(math.isqrt(48 * 48)))  # 48x48 grid max
            # Re-stride traces to fill target_side^2
            needed = target_side * target_side
            t_step2 = max(1, math.ceil(n_traces / needed))
            t_indices2 = list(range(0, n_traces, t_step2))[:needed]
            rows2 = []
            for ti in t_indices2:
                trace = np.asarray(cube.trace[ti], dtype=np.float32)[sample_slice]
                if trace.size > MAX_DIM:
                    stride = max(1, math.ceil(trace.size / MAX_DIM))
                    trace = trace[::stride][:MAX_DIM]
                rows2.append(trace.astype(np.float32, copy=False))
            if not rows2:
                return None, "SEGY 2D 读取结果为空"
            min_len2 = min(r.size for r in rows2)
            stacked2 = np.stack([r[:min_len2] for r in rows2], axis=0)
            actual_side = int(math.isqrt(stacked2.shape[0]))
            usable = actual_side * actual_side
            stacked2 = stacked2[:usable]
            volume = stacked2.reshape(actual_side, actual_side, min_len2).astype(np.float32)

            truncated = t_step > 1 or s_step > 1 or n_traces > MAX_DIM or n_samples > MAX_DIM
            volume, further = _bound_volume(volume)
            truncated = truncated or further
            warning = ""
            if truncated:
                warning = (
                    f"SEGY 已按预览预算下采样 "
                    f"(shape={tuple(int(x) for x in volume.shape)}, budget={MAX_DIM}^3)"
                )
            return volume, warning
    except Exception as exc:
        return None, f"SEGY 加载失败: {exc.__class__.__name__}"


def _bound_volume(volume: np.ndarray) -> tuple[np.ndarray, bool]:
    """Ensure product of dimensions ≤ MAX_DIM^3 and each dim ≤ MAX_DIM."""
    vol = np.asarray(volume, dtype=np.float32)
    if vol.ndim == 1:
        vol = vol.reshape(1, 1, -1)
    elif vol.ndim == 2:
        vol = vol.reshape(1, vol.shape[0], vol.shape[1])
    elif vol.ndim > 3:
        # Flatten leading axes into first dimension
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
    # Final hard cap if product still exceeds budget (defensive)
    while int(np.prod(out.shape)) > MAX_BUDGET and out.size > 1:
        # Drop every other sample on the largest axis
        axis = int(np.argmax(out.shape))
        indexer = [slice(None)] * out.ndim
        indexer[axis] = slice(None, None, 2)
        out = out[tuple(indexer)]
        truncated = True
    if any(d > MAX_DIM for d in out.shape):
        out = out[tuple(slice(0, MAX_DIM) for _ in out.shape)]
        truncated = True
    return out.astype(np.float32, copy=False), truncated
