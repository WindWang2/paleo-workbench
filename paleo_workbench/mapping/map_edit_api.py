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


def _is_closed_ring(ring: list[list[float]]) -> bool:
    if len(ring) < 2:
        return False
    a, b = ring[0], ring[-1]
    if not (isinstance(a, list) and isinstance(b, list) and len(a) >= 2 and len(b) >= 2):
        return False
    return float(a[0]) == float(b[0]) and float(a[1]) == float(b[1])


def set_vertex(ring: list[list[float]], index: int, x: float, y: float) -> None:
    """Set ring[index] to (x, y). Syncs closing point when the ring is closed."""
    if not isinstance(ring, list):
        raise TypeError("ring must be a list")
    n = len(ring)
    if index < 0 or index >= n:
        raise IndexError(f"vertex index {index} out of range for ring of length {n}")
    closed = _is_closed_ring(ring)
    ring[index][0] = float(x)
    ring[index][1] = float(y)
    if closed:
        if index == 0:
            ring[-1][0] = float(x)
            ring[-1][1] = float(y)
        elif index == n - 1:
            ring[0][0] = float(x)
            ring[0][1] = float(y)


def insert_vertex(ring: list[list[float]], index: int, x: float, y: float) -> None:
    """Insert a vertex at ``index`` (list.insert semantics)."""
    if not isinstance(ring, list):
        raise TypeError("ring must be a list")
    if index < 0 or index > len(ring):
        raise IndexError(f"insert index {index} out of range for ring of length {len(ring)}")
    ring.insert(index, [float(x), float(y)])


def delete_vertex(ring: list[list[float]], index: int) -> bool:
    """Delete ring[index] if the result stays above minimum size.

    Closed rings require at least 3 unique vertices (4 points including close).
    Open rings/lines require at least 2 vertices.
    Returns True if a vertex was removed.
    """
    if not isinstance(ring, list):
        raise TypeError("ring must be a list")
    n = len(ring)
    if index < 0 or index >= n:
        return False
    closed = _is_closed_ring(ring)
    if closed:
        unique = n - 1
        if unique <= 3:
            return False
        # Closing duplicate is the same geometric vertex as index 0.
        if index == n - 1:
            index = 0
        del ring[index]
        if ring:
            # Keep ring closed on the (possibly new) first vertex.
            ring[-1][0] = float(ring[0][0])
            ring[-1][1] = float(ring[0][1])
        return True
    if n <= 2:
        return False
    del ring[index]
    return True


def closest_edge(
    ring: list[list[float]],
    x: float,
    y: float,
) -> tuple[int, float, float, float] | None:
    """Return (edge_start_index, proj_x, proj_y, distance2) for the nearest edge.

    ``edge_start_index`` is the ring index of the edge start; the new vertex
    should be inserted at ``edge_start_index + 1``.
    """
    if not isinstance(ring, list) or len(ring) < 2:
        return None
    # Closed rings store a duplicate close point; segment count is len-1 either way
    # for a sequential ring of points (open: n-1 segments among n points).
    seg_count = len(ring) - 1
    best: tuple[int, float, float, float] | None = None
    px, py = float(x), float(y)
    for i in range(seg_count):
        j = i + 1
        ax, ay = float(ring[i][0]), float(ring[i][1])
        bx, by = float(ring[j][0]), float(ring[j][1])
        dx, dy = bx - ax, by - ay
        if dx == 0.0 and dy == 0.0:
            qx, qy = ax, ay
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
            t = max(0.0, min(1.0, t))
            qx, qy = ax + t * dx, ay + t * dy
        dist2 = (px - qx) * (px - qx) + (py - qy) * (py - qy)
        if best is None or dist2 < best[3]:
            best = (i, qx, qy, dist2)
    return best
