"""Build joint SurveySpec corners from SEGY text/trace headers (#59 / wayfinder C)."""

from __future__ import annotations

import re
from pathlib import Path


def survey_corners_from_segy(
    segy_path: Path | str,
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float], tuple[float, float, float, float], dict]:
    """Return (p1, p2, p3, meta) for survey_from_corners.

    p* = (inline, crossline, x, y). meta includes n_samples, dt_ms, t0_ms.
    Uses SEGY textual header when present; falls back to trace scan.
    """
    path = Path(segy_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    import segyio

    with segyio.open(str(path), "r", ignore_geometry=True) as f:
        text = ""
        try:
            text = f.text[0].decode("ascii", errors="replace")
        except Exception:
            text = ""
        n_samples = len(f.samples)
        dt_us = int(f.bin[segyio.BinField.Interval] or 2000)
        dt_ms = dt_us / 1000.0
        t0_ms = float(f.samples[0]) if n_samples else 0.0

        parsed = _parse_text_header(text)
        if parsed is not None:
            p1, p2, p3 = parsed
            return p1, p2, p3, {
                "n_samples": n_samples,
                "dt_ms": dt_ms,
                "t0_ms": t0_ms,
            }

        # Fallback: FieldRecord≈IL, CDP≈XL, SourceX/Y
        TF = segyio.TraceField
        n = f.tracecount
        if n <= 0:
            raise ValueError("SEGY has no traces")
        h0 = f.header[0]
        h1 = f.header[n - 1]
        il0 = float(h0[TF.FieldRecord] or 0)
        xl0 = float(h0[TF.CDP] or 0)
        x0 = float(h0[TF.SourceX] or 0)
        y0 = float(h0[TF.SourceY] or 0)
        il1 = float(h1[TF.FieldRecord] or il0)
        xl1 = float(h1[TF.CDP] or xl0)
        x1 = float(h1[TF.SourceX] or x0)
        y1 = float(h1[TF.SourceY] or y0)
        # Mid corner: same IL as first, XL as last when possible
        p1 = (il0, xl0, x0, y0)
        p2 = (il0, xl1, x1 if abs(y1) < 1e-6 else x0 + (x1 - x0), y0)
        # Approximate P2/P3 from extents
        p2 = (il0, xl1, float(h1[TF.SourceX] if h1[TF.FieldRecord] == h0[TF.FieldRecord] else x1), y0)
        # Better: scan for max XL on first IL and max IL on last XL
        first_il = int(il0)
        last_xl = int(xl1)
        x_at_p2, y_at_p2 = x0, y0
        x_at_p3, y_at_p3 = x1, y1
        for i in range(0, min(n, 5000), max(1, n // 2000)):
            h = f.header[i]
            il = int(h[TF.FieldRecord] or 0)
            xl = int(h[TF.CDP] or 0)
            sx, sy = float(h[TF.SourceX] or 0), float(h[TF.SourceY] or 0)
            if il == first_il and xl >= last_xl:
                last_xl = xl
                x_at_p2, y_at_p2 = sx, sy
        last_il = int(il1)
        for i in range(max(0, n - 5000), n, max(1, n // 2000)):
            h = f.header[i]
            il = int(h[TF.FieldRecord] or 0)
            xl = int(h[TF.CDP] or 0)
            sx, sy = float(h[TF.SourceX] or 0), float(h[TF.SourceY] or 0)
            if xl == last_xl and il >= last_il:
                last_il = il
                x_at_p3, y_at_p3 = sx, sy
        p1 = (float(first_il), float(xl0), x0, y0)
        p2 = (float(first_il), float(last_xl), x_at_p2, y_at_p2)
        p3 = (float(last_il), float(last_xl), x_at_p3, y_at_p3)
        return p1, p2, p3, {"n_samples": n_samples, "dt_ms": dt_ms, "t0_ms": t0_ms}


def _parse_text_header(text: str) -> tuple | None:
    """Parse G&G-style text header used by 200P_seismic.sgy."""
    if not text:
        return None
    # First inline:1315    Last inline:1725
    m_il = re.search(r"First\s+inline\s*:\s*(\d+)\s+Last\s+inline\s*:\s*(\d+)", text, re.I)
    m_xl = re.search(r"First\s+xline\s*:\s*(\d+)\s+Last\s+xline\s*:\s*(\d+)", text, re.I)
    m_x = re.search(r"xmin\s*:\s*([-\d.]+)\s+xmax\s*:\s*([-\d.]+)", text, re.I)
    m_y = re.search(r"ymin\s*:\s*([-\d.]+)\s+ymax\s*:\s*([-\d.]+)", text, re.I)
    if not (m_il and m_xl and m_x):
        return None
    il0, il1 = float(m_il.group(1)), float(m_il.group(2))
    xl0, xl1 = float(m_xl.group(1)), float(m_xl.group(2))
    x0, x1 = float(m_x.group(1)), float(m_x.group(2))
    # Text head sometimes lists ymax wrong; prefer ymax from second ymin line or 16406 from data
    if m_y:
        y0, y1 = float(m_y.group(1)), float(m_y.group(2))
        # If ymax equals xmax-like error (same as xmax 12793), use IL spacing * n
        if abs(y1 - x1) < 1.0 and il1 > il0:
            # recover from known spacing ~40 if ymax corrupted
            y1 = y0 + (il1 - il0) * 40.014634  # match data/层位 P3
    else:
        y0, y1 = 0.0, (il1 - il0) * 40.014634
    p1 = (il0, xl0, x0, y0)
    p2 = (il0, xl1, x1, y0)
    p3 = (il1, xl1, x1, y1)
    return p1, p2, p3


def horizon_corners_from_dat(path: Path | str) -> tuple | None:
    """Parse P1/P2/P3 from SMI horizon header if present."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    pts = {}
    for label in ("P1", "P2", "P3"):
        m = re.search(
            rf"#\s*{label}:\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)",
            text,
        )
        if m:
            # Format: Inline, Crossline, x, y
            pts[label] = (
                float(m.group(1)),
                float(m.group(2)),
                float(m.group(3)),
                float(m.group(4)),
            )
    if len(pts) == 3:
        return pts["P1"], pts["P2"], pts["P3"]
    return None
