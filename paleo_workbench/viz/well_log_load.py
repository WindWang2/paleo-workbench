from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from paleo_workbench.viz.well_log_api import fast_las_parse_data

# Align bounds with geo-viz-engine WellLogPreviewBackend defaults.
MAX_CURVES = 30
MAX_SAMPLES = 100_000


def _load_las_fast(file_path: Path) -> Any | None:
    """Fast LAS channel: engine header parse + C++ data-block parse.

    Returns ``None`` on any inconsistency so the caller can fall back to the
    engine's bounded ``load_las_preview``.
    """
    from geoviz import curve_data_from_arrays, inspect_las_file

    # header_only=True: skip the O(n_rows) Python data-row scan in inspect_las_file
    # (303ms on a 50k-row file) — _load_las_fast parses the data itself via
    # fast_las_parse_data, so it only needs the header metadata (curve names,
    # null value, depth index). This keeps the header parse under 5ms.
    header = inspect_las_file(str(file_path), header_only=True)
    if header.wrapped:
        return None  # wrapped LAS: fall back to the engine loader
    selected = header.non_depth_curves[:MAX_CURVES]
    if not selected:
        return None
    content = file_path.read_text(encoding="utf-8", errors="replace")
    _headers, arr = fast_las_parse_data(content, header.null_value)
    if arr.ndim != 2 or arr.shape[0] < 2:
        return None
    max_index = max(item.index for item in selected + (header.curves[header.depth_index],))
    if arr.shape[1] <= max_index:
        return None

    depth = arr[:, header.depth_index].astype(np.float64)
    valid = np.isfinite(depth)
    if int(valid.sum()) < 2:
        return None
    arr = arr[valid]
    depth = depth[valid]

    n = len(depth)
    stride = max(1, math.ceil(n / MAX_SAMPLES))
    idx = np.arange(0, n, stride)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    depth_s = depth[idx]

    from geoviz import WellLogData
    from geoviz_well_log.models import CurveData, LineStyle
    from geoviz_well_log.robust_scale import compute_robust_display_range

    # Convert depth to list ONCE (was converted per-curve inside
    # curve_data_from_arrays — 19x redundant tolist() on the same array).
    depth_list = depth_s.tolist()

    # Build curves with model_construct (skips per-element Pydantic validation
    # — the data is already float64 from the C++ parser, validation is pure
    # overhead here). This is the trusted-source fast path.
    curves = []
    for item in selected:
        vals = arr[idx, item.index].astype(np.float64)
        curves.append(CurveData.model_construct(
            name=item.mnemonic,
            unit=item.unit,
            depth=depth_list,
            values=vals.tolist(),
            display_range=compute_robust_display_range(vals, item.mnemonic),
            color="#63b3ed",
            line_style=LineStyle.SOLID,
        ))
    return WellLogData(
        well_name=header.well_name or file_path.stem,
        top_depth=float(np.nanmin(depth_s)),
        bottom_depth=float(np.nanmax(depth_s)),
        curves=curves,
    )


# File-level cache: parse each LAS/XML once, reuse on subsequent page switches
# or re-renders. Keyed on (path, mtime) so a file change invalidates. The parse
# is ~112ms (after header_only + model_construct optimizations) which is
# noticeable on the GUI thread; caching avoids re-paying it every time the user
# switches tabs or the visualization page refreshes.
_las_cache: dict[tuple[str, float], Any] = {}


def load_well_log_from_path(path: str) -> Any | None:
    """Return engine ``WellLogData``; LAS prefers the C++ fast channel.

    Supports both LAS and XML well log files. Falls back to the engine's
    bounded preview loader whenever the fast channel cannot handle a file.
    Results are cached per (path, mtime) to avoid re-parsing on repeat access.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None

    # Cache check: if we've parsed this file before and it hasn't changed,
    # return the cached result without touching disk again.
    cache_key = (str(file_path), file_path.stat().st_mtime)
    cached = _las_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from geoviz import load_las_preview, load_xml_preview
    except Exception:
        return None

    try:
        if file_path.suffix.lower() == ".xml":
            result = load_xml_preview(
                str(file_path),
                max_curves=MAX_CURVES,
                max_samples=MAX_SAMPLES,
            )
        else:
            try:
                fast = _load_las_fast(file_path)
            except Exception:
                fast = None
            if fast is not None:
                result = fast
            else:
                result = load_las_preview(
                    str(file_path),
                    max_curves=MAX_CURVES,
                    max_samples=MAX_SAMPLES,
                )
        if result is not None:
            _las_cache[cache_key] = result
        return result
    except Exception:
        return None
