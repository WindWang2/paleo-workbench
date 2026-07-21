from __future__ import annotations

import math
import numpy as np

try:
    import well_log_core
    HAS_CPP_WELL_LOG = True
except ImportError:  # pragma: no cover
    well_log_core = None
    HAS_CPP_WELL_LOG = False

__all__ = [
    "HAS_CPP_WELL_LOG",
    "fast_las_parse_data",
    "minmax_downsample",
]


def minmax_downsample(
    depth: np.ndarray,
    values: np.ndarray,
    target_pixels: int = 1000,
) -> tuple[np.ndarray, np.ndarray]:
    """Perform Min-Max 4-Point LOD downsampling for 60 FPS well log rendering."""
    if HAS_CPP_WELL_LOG and hasattr(well_log_core, "minmax_downsample"):
        return well_log_core.minmax_downsample(depth, values, int(target_pixels))

    d = np.asarray(depth, dtype=np.float32)
    v = np.asarray(values, dtype=np.float32)

    n_pts = len(d)
    if n_pts <= target_pixels * 2:
        return d.copy(), v.copy()

    bin_size = max(1, math.ceil(n_pts / float(target_pixels)))
    out_d = []
    out_v = []

    for i in range(0, n_pts, bin_size):
        chunk_d = d[i : i + bin_size]
        chunk_v = v[i : i + bin_size]
        if len(chunk_v) == 0:
            continue

        min_idx = int(np.argmin(chunk_v))
        max_idx = int(np.argmax(chunk_v))

        if min_idx <= max_idx:
            out_d.append(chunk_d[min_idx])
            out_v.append(chunk_v[min_idx])
            if min_idx != max_idx:
                out_d.append(chunk_d[max_idx])
                out_v.append(chunk_v[max_idx])
        else:
            out_d.append(chunk_d[max_idx])
            out_v.append(chunk_v[max_idx])
            out_d.append(chunk_d[min_idx])
            out_v.append(chunk_v[min_idx])

    return np.array(out_d, dtype=np.float32), np.array(out_v, dtype=np.float32)


def fast_las_parse_data(content: str, null_value: float = -999.0) -> tuple[tuple[str, ...], np.ndarray]:
    """Parse ASCII LAS data section (~A block) into headers and 2D float64 numpy array."""
    if HAS_CPP_WELL_LOG and hasattr(well_log_core, "fast_las_parse_data"):
        return well_log_core.fast_las_parse_data(content, float(null_value))

    lines = content.splitlines()
    in_data = False
    headers: list[str] = []
    rows: list[list[float]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("~A") or stripped.startswith("~a"):
            # Marks the start of the data section. Inline tokens only count as
            # column headers when separated from `~A` by whitespace
            # (`~A DEPT GR DEN`); a directly-attached suffix is part of the
            # section name (`~Ascii` must not yield "scii").
            in_data = True
            rest = stripped[2:]
            if rest and rest[0] in " \t":
                headers = rest.split()
            else:
                headers = []
            continue
        if in_data:
            tokens = stripped.split()
            row = []
            for tok in tokens:
                try:
                    val = float(tok)
                    if math.isnan(val) or val <= -999.0 or val == null_value:
                        row.append(np.nan)
                    else:
                        row.append(val)
                except ValueError:
                    row.append(np.nan)
            if row:
                rows.append(row)

    if not headers and rows:
        headers = [f"COL_{i}" for i in range(len(rows[0]))]

    arr = np.array(rows, dtype=np.float64) if rows else np.zeros((0, len(headers)), dtype=np.float64)
    return tuple(headers), arr
