from __future__ import annotations

from typing import Any

import numpy as np
from geoviz import WellTieCanvas

from paleo_workbench.viz.models import VizPayload

# Common LAS mnemonics for sonic (µs/m or µs/ft) and bulk density (g/cm³).
_SONIC_NAMES = frozenset(
    {"DT", "DTCO", "AC", "DTC", "SONIC", "DTP", "DT4P", "DTSM", "DTME"}
)
_DENSITY_NAMES = frozenset(
    {"RHOB", "RHOZ", "DEN", "DENS", "RHO", "ZDEN", "RHOM"}
)


def _curve_arrays(
    well_log: Any, names: frozenset[str]
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (depth, values) for the first curve matching *names* (case-insensitive)."""
    curves = list(getattr(well_log, "curves", None) or [])
    for curve in curves:
        name = str(getattr(curve, "name", "") or "").strip().upper()
        if name not in names:
            continue
        depth = np.asarray(getattr(curve, "depth", []), dtype=np.float64)
        values = np.asarray(getattr(curve, "values", []), dtype=np.float64)
        if depth.size < 2 or values.size < 2:
            continue
        n = min(depth.size, values.size)
        return depth[:n], values[:n]
    return None


def _depth_axis(well_log: Any, n: int = 100) -> np.ndarray:
    top = float(getattr(well_log, "top_depth", 0.0) or 0.0)
    bottom = float(getattr(well_log, "bottom_depth", 100.0) or 100.0)
    if bottom <= top:
        bottom = top + 100.0
    curves = list(getattr(well_log, "curves", None) or [])
    if curves:
        depth = np.asarray(getattr(curves[0], "depth", []), dtype=np.float64)
        if depth.size >= 2:
            return depth
    return np.linspace(top, bottom, max(n, 2), dtype=np.float64)


def _twt_from_sonic(depths: np.ndarray, sonic: np.ndarray) -> np.ndarray:
    """Integrate sonic (µs/m) to two-way time in ms (same math as WellTieCalibration)."""
    depths = np.asarray(depths, dtype=np.float64)
    sonic = np.asarray(sonic, dtype=np.float64)
    if depths.size < 2:
        return np.zeros_like(depths)
    dz = np.diff(depths)
    owt_us = dz * (sonic[:-1] + sonic[1:]) / 2.0
    twt = np.zeros_like(depths)
    twt[1:] = 2.0 * np.cumsum(owt_us) / 1000.0
    return twt


def _seismic_trace(
    volume: np.ndarray | None, n: int, seed: int = 0
) -> np.ndarray:
    """Extract or synthesize a 1-D seismic trace of length *n*."""
    if volume is not None:
        arr = np.asarray(volume, dtype=np.float64)
        if arr.ndim == 3 and arr.size > 0:
            # Prefer last axis as samples (IL, XL, T).
            il = arr.shape[0] // 2
            xl = arr.shape[1] // 2
            trace = arr[il, xl, :].astype(np.float64, copy=False)
            if trace.size >= 2:
                src = np.linspace(0.0, 1.0, trace.size)
                dst = np.linspace(0.0, 1.0, n)
                return np.interp(dst, src, trace)
        if arr.ndim == 1 and arr.size >= 2:
            src = np.linspace(0.0, 1.0, arr.size)
            dst = np.linspace(0.0, 1.0, n)
            return np.interp(dst, src, arr.astype(np.float64))
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 4.0 * np.pi, n, dtype=np.float64)
    return np.sin(t) * np.exp(-0.15 * t) + 0.08 * rng.standard_normal(n)


def build_tie_arrays(
    well_log: Any | None,
    seismic_volume: np.ndarray | None = None,
    *,
    n_fallback: int = 100,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Build (depths, twt, sonic, density, seismic) for ``WellTieCanvas.set_tie_data``.

    Returns ``None`` when neither a well log nor a seismic volume is available.
    Missing DT/RHOB curves are replaced with smooth synthetic proxies so the
    7-track workspace remains inspectable on partial assets.
    """
    if well_log is None and seismic_volume is None:
        return None

    if well_log is not None:
        depths = _depth_axis(well_log, n_fallback)
        sonic_pair = _curve_arrays(well_log, _SONIC_NAMES)
        dens_pair = _curve_arrays(well_log, _DENSITY_NAMES)
    else:
        depths = np.linspace(1000.0, 2000.0, n_fallback, dtype=np.float64)
        sonic_pair = None
        dens_pair = None

    n = int(depths.size)
    if n < 2:
        return None

    if sonic_pair is not None:
        d_src, v_src = sonic_pair
        sonic = np.interp(depths, d_src, v_src)
        # Heuristic: µs/ft values are typically ~40–140; convert rough ft→m scale.
        if float(np.nanmedian(np.abs(sonic))) < 150.0:
            sonic = sonic * 3.28084  # µs/ft → µs/m
    else:
        # Mild velocity increase with depth (µs/m).
        sonic = np.linspace(280.0, 220.0, n, dtype=np.float64)

    if dens_pair is not None:
        d_src, v_src = dens_pair
        density = np.interp(depths, d_src, v_src)
    else:
        density = np.linspace(2.15, 2.55, n, dtype=np.float64)

    twt = _twt_from_sonic(depths, sonic)
    seismic = _seismic_trace(seismic_volume, n, seed=seed)
    return depths, twt, sonic, density, seismic


class WellTieHost:
    """Host for ``geoviz_well_tie.WellTieCanvas`` (7-track well-seismic tie workspace).

    Thin workbench shell: extract DT/RHOB (or synthetic proxies) + optional seismic
    trace, then hand arrays to the engine canvas. No reimplementation of synthetic
    convolution or correlation math.
    """

    tab_title = "井震标定"

    def __init__(self) -> None:
        self.widget = WellTieCanvas()

    def clear(self) -> None:
        w = self.widget
        w._depths = None
        w._twt = None
        w._sonic = None
        w._density = None
        w._seismic = None
        w._ai = None
        w._rc = None
        w._synthetic = None
        w._pixmap_cache = None
        w._cache_dirty = True
        w.update()

    def apply(self, payload: VizPayload) -> bool:
        well_log = payload.well_log
        if well_log is None and payload.well_logs:
            well_log = payload.well_logs[0]
        arrays = build_tie_arrays(
            well_log,
            payload.seismic_volume,
            seed=abs(hash(payload.label or payload.kind)) % (2**31),
        )
        if arrays is None:
            return False
        depths, twt, sonic, density, seismic = arrays
        self.widget.set_tie_data(depths, twt, sonic, density, seismic)
        return True
