"""Scalar-grid rasterisation facade for the native factor-map renderer.

Thin public API over ``grid_render_core.render_grid_rgba`` — the C++ per-pixel hot path
that must stay out of Python — with a byte-identical pure-Python fallback dispatched by
:class:`~paleo_workbench.native_backend.NativeEngineBackend`. Validates inputs, applies
defaults, and offers a :class:`FactorGridResult`-aware entry point.

Imports only numpy + the FactorGridResult contract so it can be unit-tested without
PySide6. The native backend is resolved lazily inside the call to avoid an import cycle.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from paleo_workbench.workflow.factor_grid_result import FactorGridResult

__all__ = ["render_grid_rgba", "render_factor_grid", "default_rgba_lut"]


def _lut_as_rgba(lut: np.ndarray) -> np.ndarray:
    """Coerce a colour ramp to a contiguous ``(N, 4)`` uint8 RGBA LUT.

    Accepts ``(N, 4)`` RGBA or ``(N, 3)`` RGB (alpha assumed 255).
    """
    arr = np.ascontiguousarray(lut, dtype=np.uint8)
    if arr.ndim == 2 and arr.shape[1] == 4:
        return arr
    if arr.ndim == 2 and arr.shape[1] == 3:
        out = np.empty((arr.shape[0], 4), dtype=np.uint8)
        out[:, 0:3] = arr
        out[:, 3] = 255
        return out
    raise ValueError(f"lut must be (N,4) RGBA or (N,3) RGB uint8, got shape {arr.shape}")


def default_rgba_lut(size: int = 256) -> np.ndarray:
    """A deterministic ``(size, 4)`` uint8 RGBA ramp for offline/test use.

    Workbench production code may import only the public ``geoviz`` facade, which does not
    expose a colormap builder; for a real named colormap, obtain a LUT through the
    ``geoviz`` facade (e.g. via ``SurfaceWidget``) and pass it to :func:`render_grid_rgba`.
    This helper returns a simple purple→teal→yellow ramp so callers always have a usable
    default without depending on engine internals.
    """
    t = np.linspace(0.0, 1.0, size, dtype=np.float32)
    ramp = np.empty((size, 4), dtype=np.uint8)
    ramp[:, 0] = (np.clip(0.267 + 0.5 * t, 0, 1) * 255).astype(np.uint8)
    ramp[:, 1] = (np.clip(0.0 + 0.9 * t, 0, 1) * 255).astype(np.uint8)
    ramp[:, 2] = (np.clip(0.33 + 0.5 * t, 0, 1) * 255).astype(np.uint8)
    ramp[:, 3] = 255
    return ramp


def render_grid_rgba(
    grid_z: np.ndarray,
    lut: np.ndarray,
    *,
    lo: float,
    hi: float,
    mask: Optional[np.ndarray] = None,
    gamma: float = 1.0,
    opacity: int = 255,
) -> np.ndarray:
    """Render a scalar grid to an ``(H, W, 4)`` uint8 RGBA buffer via the native hot path.

    Non-finite cells and masked cells become fully-transparent black. Values outside
    ``[lo, hi]`` clamp to the ramp endpoints (not transparent).
    """
    gz = np.ascontiguousarray(grid_z, dtype=np.float32)
    if gz.ndim != 2:
        raise ValueError(f"grid_z must be 2-D, got shape {gz.shape}")
    lut_buf = _lut_as_rgba(lut)
    mask_buf = None if mask is None else np.ascontiguousarray(mask, dtype=np.uint8)
    if mask_buf is not None and mask_buf.shape != gz.shape:
        raise ValueError(f"mask {mask_buf.shape} must match grid_z {gz.shape}")
    if int(opacity) < 0 or int(opacity) > 255:
        raise ValueError(f"opacity must be 0..255, got {opacity}")
    from paleo_workbench.native_backend import NativeEngineBackend

    return NativeEngineBackend().dispatch(
        "render_grid_rgba",
        gz,
        mask_buf,
        lut_buf,
        float(lo),
        float(hi),
        float(gamma),
        int(opacity),
    )


def render_factor_grid(
    result: FactorGridResult,
    lut: np.ndarray,
    *,
    lo: Optional[float] = None,
    hi: Optional[float] = None,
    mask: Optional[np.ndarray] = None,
    gamma: float = 1.0,
    opacity: int = 255,
) -> np.ndarray:
    """Render a :class:`FactorGridResult` using its finite min/max as the default range.

    The result's own NaN nodata cells are honoured automatically; an extra ``mask`` may
    hide further cells. Range defaults to ``statistics.min``/``statistics.max``.
    """
    if not isinstance(result, FactorGridResult):
        raise TypeError("result must be a FactorGridResult")
    if lo is None:
        lo = result.statistics.min
    if hi is None:
        hi = result.statistics.max
    return render_grid_rgba(
        result.grid_z,
        lut,
        lo=float(lo),
        hi=float(hi),
        mask=mask,
        gamma=gamma,
        opacity=opacity,
    )
