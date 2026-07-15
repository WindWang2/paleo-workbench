from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

MAX_CURVES = 12
MAX_SAMPLES = 2000

# Skip common depth/index mnemonics when building curve tracks.
_DEPTH_MNEMONICS = {
    "DEPT",
    "DEPTH",
    "MD",
    "TVD",
    "TVDSS",
    "INDEX",
    "TIME",
}


def load_well_log_from_path(path: str) -> Any | None:
    """Return WellLogData or None on failure. Uses lasio; stride samples if long."""
    try:
        import lasio
        from geoviz import CurveData, WellLogData
    except Exception:
        return None

    file_path = Path(path)
    if not file_path.is_file():
        return None

    try:
        las = lasio.read(str(file_path), ignore_header_errors=True)
    except Exception:
        return None

    try:
        depth = _depth_array(las)
        if depth.size < 2:
            return None

        stride = 1
        if depth.size > MAX_SAMPLES:
            stride = max(1, math.ceil(depth.size / MAX_SAMPLES))
        depth_list = depth[::stride].astype(float).tolist()

        curves: list[Any] = []
        for curve in list(getattr(las, "curves", []) or []):
            mnemonic = str(getattr(curve, "mnemonic", "") or "").strip()
            if not mnemonic or mnemonic.upper() in _DEPTH_MNEMONICS:
                continue
            try:
                raw = np.asarray(las[mnemonic], dtype=float)
            except Exception:
                continue
            if raw.size != depth.size:
                n = min(raw.size, depth.size)
                if n < 2:
                    continue
                values = raw[:n:stride]
                curve_depth = depth[:n:stride].astype(float).tolist()
            else:
                values = raw[::stride]
                curve_depth = depth_list
            values = np.asarray(values, dtype=float)
            if values.size < 2:
                continue
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                lo, hi = 0.0, 100.0
            else:
                lo = float(np.nanmin(finite))
                hi = float(np.nanmax(finite))
                if not math.isfinite(lo) or not math.isfinite(hi) or lo == hi:
                    lo, hi = (lo if math.isfinite(lo) else 0.0), (hi if math.isfinite(hi) else 100.0)
                    if lo == hi:
                        hi = lo + 1.0
            unit = str(getattr(curve, "unit", "") or "")
            curves.append(
                CurveData(
                    name=mnemonic,
                    unit=unit,
                    depth=curve_depth if len(curve_depth) == values.size else depth_list[: values.size],
                    values=[float(v) if math.isfinite(float(v)) else float("nan") for v in values.tolist()],
                    display_range=(lo, hi),
                )
            )
            if len(curves) >= MAX_CURVES:
                break

        if not curves:
            # Provide a single placeholder curve from depth so canvas has data.
            curves.append(
                CurveData(
                    name="INDEX",
                    unit="",
                    depth=depth_list,
                    values=list(depth_list),
                    display_range=(float(depth_list[0]), float(depth_list[-1])),
                )
            )

        well_name = _well_name(las) or file_path.stem
        top = float(depth_list[0])
        bottom = float(depth_list[-1])
        if top > bottom:
            top, bottom = bottom, top
        return WellLogData(
            well_name=str(well_name),
            top_depth=top,
            bottom_depth=bottom,
            curves=curves,
        )
    except Exception:
        return None


def _depth_array(las: Any) -> np.ndarray:
    index = getattr(las, "index", None)
    if index is not None:
        arr = np.asarray(index, dtype=float)
        if arr.size >= 2:
            return arr
    for mnemonic in ("DEPT", "DEPTH", "MD"):
        try:
            arr = np.asarray(las[mnemonic], dtype=float)
            if arr.size >= 2:
                return arr
        except Exception:
            continue
    curves = list(getattr(las, "curves", []) or [])
    if curves:
        try:
            return np.asarray(las[curves[0].mnemonic], dtype=float)
        except Exception:
            pass
    return np.asarray([], dtype=float)


def _well_name(las: Any) -> str:
    well = getattr(las, "well", None)
    if well is None:
        return ""
    for key in ("WELL", "WN", "UWI"):
        item = None
        try:
            item = well[key]
        except Exception:
            item = getattr(well, key, None)
        if item is None:
            continue
        value = getattr(item, "value", item)
        text = str(value).strip() if value is not None else ""
        if text and text.lower() not in {"", "none", "nan"}:
            return text
    return ""
