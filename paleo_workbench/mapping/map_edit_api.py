"""Geometry façade for the mapping editor.

Tries optional ``map_edit_core`` (C++ / pybind11) for hot paths; falls back to
pure Python. Public call signatures stay stable so UI and tests do not care
which backend is active. See ``CPP_EXTENSION.md`` for native signatures.
"""

from __future__ import annotations

from typing import Any

try:
    import map_edit_core as _map_edit_core  # type: ignore
    HAS_CPP = True
except ImportError:
    _map_edit_core = None  # type: ignore[assignment]
    HAS_CPP = False


def _cpp_fn(name: str):
    """Return a callable from map_edit_core if present, else None."""
    if not HAS_CPP or _map_edit_core is None:
        return None
    return getattr(_map_edit_core, name, None)


# ---------------------------------------------------------------------------
# hit_test
# ---------------------------------------------------------------------------


def _point_dist2(ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = ax - bx, ay - by
    return dx * dx + dy * dy


def _point_to_segment_dist2(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return _point_dist2(px, py, ax, ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return _point_dist2(px, py, ax + t * dx, ay + t * dy)


def _point_in_ring(px: float, py: float, ring: list[list[float]]) -> bool:
    """Ray-cast point-in-polygon. Ring may be open or closed."""
    n = len(ring)
    if n < 3:
        return False
    # Drop closing duplicate for iteration.
    pts = ring
    if (
        isinstance(ring[0], list)
        and isinstance(ring[-1], list)
        and len(ring[0]) >= 2
        and len(ring[-1]) >= 2
        and float(ring[0][0]) == float(ring[-1][0])
        and float(ring[0][1]) == float(ring[-1][1])
    ):
        n = n - 1
        if n < 3:
            return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = float(pts[i][0]), float(pts[i][1])
        xj, yj = float(pts[j][0]), float(pts[j][1])
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-30) + xi
        ):
            inside = not inside
        j = i
    return inside


def _hit_test_python(
    records: list[dict[str, Any]] | None,
    x: float,
    y: float,
    tolerance: float = 0.0,
) -> str | None:
    """Return the first feature id under (x, y), or None.

    Points: within ``tolerance`` (default 0 uses a tiny epsilon).
    Rings (closed polygons): point-in-polygon or edge within tolerance.
    Lines (open rings): edge within tolerance.
    """
    if not records:
        return None
    px, py = float(x), float(y)
    tol = max(0.0, float(tolerance))
    # Default small hit radius for bare points when tol is 0.
    point_tol = tol if tol > 0.0 else 1e-9
    tol2 = point_tol * point_tol

    for record in records:
        if not isinstance(record, dict):
            continue
        fid = record.get("id")
        if fid is None:
            continue
        coords = record.get("coordinates")
        if not isinstance(coords, list) or not coords:
            continue
        first = coords[0]
        # Point: [x, y]
        if isinstance(first, (int, float)):
            if len(coords) >= 2:
                if _point_dist2(px, py, float(coords[0]), float(coords[1])) <= tol2:
                    return str(fid)
            continue
        # Ring / line: list of [x, y]
        ring = [p for p in coords if isinstance(p, list) and len(p) >= 2]
        if len(ring) < 2:
            continue
        closed = _is_closed_ring(ring)
        if closed and _point_in_ring(px, py, ring):
            return str(fid)
        # Edge proximity
        edge_tol2 = (tol if tol > 0.0 else 0.0) ** 2
        if edge_tol2 <= 0.0 and not closed:
            # Open lines with zero tol: only exact vertex hits
            for p in ring:
                if _point_dist2(px, py, float(p[0]), float(p[1])) <= 1e-18:
                    return str(fid)
            continue
        seg_count = len(ring) - 1
        for i in range(seg_count):
            ax, ay = float(ring[i][0]), float(ring[i][1])
            bx, by = float(ring[i + 1][0]), float(ring[i + 1][1])
            if _point_to_segment_dist2(px, py, ax, ay, bx, by) <= max(edge_tol2, 1e-18):
                return str(fid)
    return None


def hit_test(
    records: list[dict[str, Any]] | None,
    x: float,
    y: float,
    tolerance: float = 0.0,
) -> str | None:
    """Return the feature id under (x, y), or None.

    When ``map_edit_core`` is available, prefers the C++ implementation.
    Accepts feature dicts with ``id`` + ``coordinates`` (point or ring).
    """
    cpp = _cpp_fn("hit_test")
    if cpp is not None:
        # Compact payload: list of (id, coordinates)
        payload: list[tuple[str, list]] = []
        for record in records or []:
            if not isinstance(record, dict):
                continue
            fid = record.get("id")
            coords = record.get("coordinates")
            if fid is None or not isinstance(coords, list):
                continue
            payload.append((str(fid), coords))
        try:
            return cpp(payload, float(x), float(y), float(tolerance))
        except Exception:
            # Fall through to pure Python on any native error.
            pass
    return _hit_test_python(records, x, y, tolerance)


# ---------------------------------------------------------------------------
# move / vertex ops
# ---------------------------------------------------------------------------


def move_features(
    records_by_id: dict[str, dict[str, Any]],
    ids: list[str] | tuple[str, ...],
    dx: float,
    dy: float,
) -> None:
    """Mutate coordinate lists for the given feature ids by (dx, dy).

    Supports point coordinates ``[x, y]`` and ring/line ``[[x, y], ...]``.
    """
    cpp = _cpp_fn("move_feature")
    dx_f = float(dx)
    dy_f = float(dy)
    for fid in ids:
        record = records_by_id.get(fid)
        if not record:
            continue
        coords = record.get("coordinates")
        if not isinstance(coords, list) or not coords:
            continue
        if cpp is not None:
            try:
                cpp(coords, dx_f, dy_f)
                continue
            except Exception:
                pass
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
    cpp = _cpp_fn("set_vertex")
    if cpp is not None:
        try:
            cpp(ring, int(index), float(x), float(y))
            return
        except Exception:
            pass
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
    cpp = _cpp_fn("insert_vertex")
    if cpp is not None:
        try:
            cpp(ring, int(index), float(x), float(y))
            return
        except Exception:
            pass
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
    cpp = _cpp_fn("delete_vertex")
    if cpp is not None:
        try:
            return bool(cpp(ring, int(index)))
        except Exception:
            pass
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


# ---------------------------------------------------------------------------
# snap
# ---------------------------------------------------------------------------


def _snap_point_python(
    candidates: list[tuple[float, float]] | list[list[float]] | None,
    x: float,
    y: float,
    tol: float = 0.5,
) -> tuple[float, float]:
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


def snap_point(
    candidates: list[tuple[float, float]] | list[list[float]] | None,
    x: float,
    y: float,
    tol: float = 0.5,
) -> tuple[float, float]:
    """Snap (x, y) to the nearest candidate within ``tol`` (map units).

    Returns the original point when no candidate is within tolerance.
    """
    cpp = _cpp_fn("snap")
    if cpp is not None:
        try:
            result = cpp(list(candidates or []), float(x), float(y), float(tol))
            if result is not None and len(result) >= 2:
                return float(result[0]), float(result[1])
        except Exception:
            pass
    return _snap_point_python(candidates, x, y, tol)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


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


def _validate_ring_python(ring: list[list[float]] | None) -> list[dict[str, Any]]:
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


def validate_ring(ring: list[list[float]] | None) -> list[dict[str, Any]]:
    """Return topology issues for a polygon ring (closed or open).

    Detects self-intersections between non-adjacent edges. Issues look like
    ``{"code": "self_intersection", "message": "..."}``.
    """
    cpp = _cpp_fn("validate")
    if cpp is not None:
        try:
            result = cpp(ring if ring is not None else [])
            if isinstance(result, list):
                return list(result)
        except Exception:
            pass
    return _validate_ring_python(ring)


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
