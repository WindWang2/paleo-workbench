"""Geometry façade for the mapping editor.

Python implementation first; optional map_edit_core C++ extension later.
"""

from __future__ import annotations

from typing import Any


def hit_test(
    records: list[dict[str, Any]] | None,
    x: float,
    y: float,
    tolerance: float = 0.0,
) -> str | None:
    """Return the feature id under (x, y), or None.

    Stub for Task 3 — full spatial hit-test arrives with select/move tools.
    """
    return None


def move_features(
    records_by_id: dict[str, dict[str, Any]],
    ids: list[str] | tuple[str, ...],
    dx: float,
    dy: float,
) -> None:
    """Mutate coordinate lists for the given feature ids by (dx, dy).

    Supports point coordinates ``[x, y]`` and ring/line ``[[x, y], ...]``.
    """
    dx_f = float(dx)
    dy_f = float(dy)
    for fid in ids:
        record = records_by_id.get(fid)
        if not record:
            continue
        coords = record.get("coordinates")
        if not isinstance(coords, list) or not coords:
            continue
        # Point: [x, y] — first element is a scalar number.
        first = coords[0]
        if isinstance(first, (int, float)):
            if len(coords) >= 2:
                coords[0] = float(coords[0]) + dx_f
                coords[1] = float(coords[1]) + dy_f
            continue
        # Ring / line: list of [x, y]
        for point in coords:
            if isinstance(point, list) and len(point) >= 2:
                point[0] = float(point[0]) + dx_f
                point[1] = float(point[1]) + dy_f
