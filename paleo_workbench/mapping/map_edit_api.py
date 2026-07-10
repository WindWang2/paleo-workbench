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


def snap_point(
    candidates: list[tuple[float, float]] | list[list[float]] | None,
    x: float,
    y: float,
    tol: float = 0.5,
) -> tuple[float, float]:
    """Snap (x, y) to the nearest candidate within ``tol`` (map units).

    Returns the original point when no candidate is within tolerance.
    """
    px, py = float(x), float(y)
    if not candidates:
        return px, py
    tol_f = max(0.0, float(tol))
    best: tuple[float, float] | None = None
    best_d2 = tol_f * tol_f
    for raw in candidates:
        if raw is None or len(raw) < 2:
            continue
        try:
            cx, cy = float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            continue
        d2 = (cx - px) * (cx - px) + (cy - py) * (cy - py)
        if d2 <= best_d2:
            best_d2 = d2
            best = (cx, cy)
    return best if best is not None else (px, py)


def _segments_properly_intersect(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> bool:
    """True if segments ab and cd properly intersect (not mere endpoint touch)."""

    def orient(p, q, r) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p, q, r) -> bool:
        return (
            min(p[0], r[0]) - 1e-12 <= q[0] <= max(p[0], r[0]) + 1e-12
            and min(p[1], r[1]) - 1e-12 <= q[1] <= max(p[1], r[1]) + 1e-12
        )

    o1 = orient(a1, a2, b1)
    o2 = orient(a1, a2, b2)
    o3 = orient(b1, b2, a1)
    o4 = orient(b1, b2, a2)

    # General case: proper crossing (orientations differ, not collinear).
    if (o1 * o2 < 0.0) and (o3 * o4 < 0.0):
        return True

    # Collinear overlaps count as self-intersection for topology warnings.
    eps = 1e-12
    if abs(o1) <= eps and on_segment(a1, b1, a2) and b1 not in (a1, a2):
        return True
    if abs(o2) <= eps and on_segment(a1, b2, a2) and b2 not in (a1, a2):
        return True
    if abs(o3) <= eps and on_segment(b1, a1, b2) and a1 not in (b1, b2):
        return True
    if abs(o4) <= eps and on_segment(b1, a2, b2) and a2 not in (b1, b2):
        return True
    return False


def validate_ring(ring: list[list[float]] | None) -> list[dict[str, Any]]:
    """Return topology issues for a polygon ring (closed or open).

    Detects self-intersections between non-adjacent edges. Issues look like
    ``{"code": "self_intersection", "message": "..."}``.
    """
    if not isinstance(ring, list) or len(ring) < 4:
        return []
    pts: list[tuple[float, float]] = []
    for p in ring:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return []
        try:
            pts.append((float(p[0]), float(p[1])))
        except (TypeError, ValueError):
            return []

    closed = pts[0] == pts[-1]
    # Unique vertex count for segment iteration (exclude closing duplicate).
    n = len(pts) - 1 if closed else len(pts)
    if n < 3:
        return []

    # Build segment list over unique vertices; for closed rings add closing edge.
    edges: list[tuple[int, int]] = []
    for i in range(n - 1):
        edges.append((i, i + 1))
    if closed:
        edges.append((n - 1, 0))

    issues: list[dict[str, Any]] = []
    for ei, (i0, i1) in enumerate(edges):
        for ej in range(ei + 1, len(edges)):
            j0, j1 = edges[ej]
            # Skip adjacent edges (share a vertex) and the first/last pair on closed rings.
            shared = {i0, i1} & {j0, j1}
            if shared:
                continue
            a1, a2 = pts[i0], pts[i1]
            b1, b2 = pts[j0], pts[j1]
            if _segments_properly_intersect(a1, a2, b1, b2):
                issues.append({
                    "code": "self_intersection",
                    "message": f"Edges {i0}-{i1} and {j0}-{j1} intersect",
                    "edges": ((i0, i1), (j0, j1)),
                })
                return issues  # one is enough for V1 warnings
    return issues


def validate_adjacency(
    rings: list[list[list[float]]] | None,
    gap_tol: float = 0.5,
) -> list[dict[str, Any]]:
    """Optional simple adjacency heuristic: bbox overlap without shared boundary.

    Returns issues with code ``adjacency_gap`` or ``adjacency_overlap`` when two
    rings' bboxes are close/overlapping but no ring vertices lie within
    ``gap_tol`` of the other ring's vertices (rough V1 signal only).
    """
    if not rings or len(rings) < 2:
        return []
    prepared: list[tuple[list[tuple[float, float]], tuple[float, float, float, float]]] = []
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 2:
            continue
        pts: list[tuple[float, float]] = []
        for p in ring:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                try:
                    pts.append((float(p[0]), float(p[1])))
                except (TypeError, ValueError):
                    continue
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        prepared.append((pts, (min(xs), min(ys), max(xs), max(ys))))

    issues: list[dict[str, Any]] = []
    tol = max(0.0, float(gap_tol))
    for i in range(len(prepared)):
        pts_i, bb_i = prepared[i]
        for j in range(i + 1, len(prepared)):
            pts_j, bb_j = prepared[j]
            # Expand bboxes by tol and test overlap.
            if (
                bb_i[2] + tol < bb_j[0]
                or bb_j[2] + tol < bb_i[0]
                or bb_i[3] + tol < bb_j[1]
                or bb_j[3] + tol < bb_i[1]
            ):
                continue
            # If any vertex pair is within tol, treat as connected/adjacent-ok.
            connected = False
            for ax, ay in pts_i:
                for bx, by in pts_j:
                    if (ax - bx) * (ax - bx) + (ay - by) * (ay - by) <= tol * tol:
                        connected = True
                        break
                if connected:
                    break
            # Core bbox overlap without expansion.
            core_overlap = not (
                bb_i[2] < bb_j[0]
                or bb_j[2] < bb_i[0]
                or bb_i[3] < bb_j[1]
                or bb_j[3] < bb_i[1]
            )
            if core_overlap and not connected:
                issues.append({
                    "code": "adjacency_overlap",
                    "message": f"Rings {i} and {j} may overlap without shared nodes",
                    "pair": (i, j),
                })
            elif not core_overlap and not connected:
                issues.append({
                    "code": "adjacency_gap",
                    "message": f"Rings {i} and {j} are near but not connected",
                    "pair": (i, j),
                })
    return issues
