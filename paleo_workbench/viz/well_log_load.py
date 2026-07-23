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

    curves = [
        curve_data_from_arrays(item, depth_s, arr[idx, item.index].astype(np.float64))
        for item in selected
    ]
    return WellLogData(
        well_name=header.well_name or file_path.stem,
        top_depth=float(np.nanmin(depth_s)),
        bottom_depth=float(np.nanmax(depth_s)),
        curves=curves,
    )


def load_well_log_from_path(path: str) -> Any | None:
    """Return engine ``WellLogData``; LAS prefers the C++ fast channel.

    Supports both LAS and XML well log files. Falls back to the engine's
    bounded preview loader whenever the fast channel cannot handle a file.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        from geoviz import load_las_preview, load_xml_preview
    except Exception:
        return None

    try:
        if file_path.suffix.lower() == ".xml":
            return load_xml_preview(
                str(file_path),
                max_curves=MAX_CURVES,
                max_samples=MAX_SAMPLES,
            )
        try:
            fast = _load_las_fast(file_path)
        except Exception:
            fast = None
        if fast is not None:
            return fast
        return load_las_preview(
            str(file_path),
            max_curves=MAX_CURVES,
            max_samples=MAX_SAMPLES,
        )
    except Exception:
        return None
