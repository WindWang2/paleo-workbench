"""Shared planar-geometry kernels (v7 §4 de-duplication).

Single implementations for the operations that previously existed in
triplicate across the mapping stack:

* point-in-polygon ray-cast — was duplicated in
  ``geological_pipeline/polygonization.py`` (scalar), ``geological_pipeline/
  interpolator.py`` (vectorized grid mask) and ``map_interaction.py``
  (scalar with holes).  One even-odd ray-cast semantics for all callers.
* extent-of-geometries — was five per-module bbox builders.

Scalar + vectorized forms share the same winding convention (even-odd,
boundary-inclusive by ray-crossing parity).
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

__all__ = [
    "distance_to_segment",
    "extent_of_coordinates",
    "extent_of_geometries",
    "point_in_polygon_scalar",
    "point_in_ring_scalar",
    "point_in_ring_scalar_inclusive",
    "points_in_polygon_vectorized",
]


def distance_to_segment(point, start, end) -> float:
    """Planar point-to-segment distance（V8 M4 唯一内核）。

    原 map_interaction / composite_editing 各自内联的同式投影距离已删；
    零长度段按点到端点处理。
    """
    px, py = float(point[0]), float(point[1])
    x1, y1 = float(start[0]), float(start[1])
    x2, y2 = float(end[0]), float(end[1])
    dx, dy = x2 - x1, y2 - y1
    norm = dx * dx + dy * dy
    if norm <= 1e-18:
        return math.dist((px, py), (x1, y1))
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / norm))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def point_in_ring_scalar(x: float, y: float, ring) -> bool:
    """Ray-cast containment for ONE ring (no holes).  Shared kernel for the
    former polygonization/map_interaction/interpolator duplicates."""
    return _ray_crosses(float(x), float(y), ring)


def point_in_ring_scalar_inclusive(x: float, y: float, ring, *,
                                   epsilon: float = 1e-9) -> bool:
    """Even-odd containment with an explicit on-edge test（V8 M4 唯一内核）。

    边界包含语义用于安全相关分类（井位是否属工区——边界井不得在两次
    分类间振荡）：on-edge 判据是叉积面积阈值（等效距离 epsilon 约为
    ``epsilon / 边长``，与原 project/domain.py 实现逐字一致——语义保持，
    措辞按 review-1 P2-12 修正），不依赖射线奇偶在边界点上的未定义行
    为。共享内核族的显式语义变体，不再是调用方各自的复刻。
    """
    x = float(x)
    y = float(y)
    points = [(float(p[0]), float(p[1])) for p in ring]
    if len(points) < 3:
        return False
    previous_x, previous_y = points[-1]
    inside = False
    for current_x, current_y in points:
        cross = (current_x - previous_x) * (y - previous_y) - (
            current_y - previous_y
        ) * (x - previous_x)
        segment_len = math.hypot(current_x - previous_x, current_y - previous_y)
        if (
            abs(cross) <= epsilon * max(1.0, segment_len)
            and min(previous_x, current_x) - epsilon <= x <= max(previous_x, current_x) + epsilon
            and min(previous_y, current_y) - epsilon <= y <= max(previous_y, current_y) + epsilon
        ):
            return True
        if (current_y > y) != (previous_y > y):
            crossing_x = (
                (previous_x - current_x) * (y - current_y) / (previous_y - current_y)
                + current_x
            )
            if x < crossing_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def _polygons_of(polygon: dict[str, Any]) -> list:
    """GeoJSON Polygon/MultiPolygon → list of ring-lists (R1-F1)."""
    geom_type = str(polygon.get("type") or "")
    if geom_type == "Polygon":
        return [polygon.get("coordinates") or []]
    if geom_type == "MultiPolygon":
        return [poly for poly in polygon.get("coordinates") or []]
    raise ValueError(f"point_in_polygon needs a polygon, got {geom_type!r}")


def point_in_polygon_scalar(point: Sequence[float], polygon: dict[str, Any]) -> bool:
    """Even-odd ray-cast with hole support (GeoJSON Polygon/MultiPolygon).

    Each part is tested independently: inside the part's exterior and not
    inside any of ITS holes (R1-F1: the former flattened rings[0]/rings[1:]
    model broke every MultiPolygon).
    """
    x, y = float(point[0]), float(point[1])
    for rings in _polygons_of(polygon):
        if not rings:
            continue
        if not _ray_crosses(x, y, rings[0]):
            continue
        if any(_ray_crosses(x, y, hole) for hole in rings[1:]):
            continue
        return True
    return False


def _ray_crosses(x: float, y: float, ring: Sequence[Sequence[float]]) -> bool:
    crosses = False
    count = len(ring)
    for index in range(count):
        x1, y1 = float(ring[index][0]), float(ring[index][1])
        x2, y2 = float(ring[(index + 1) % count][0]), float(
            ring[(index + 1) % count][1])
        if (y1 > y) != (y2 > y):
            t = (y - y1) / (y2 - y1)
            if x < x1 + t * (x2 - x1):
                crosses = not crosses
    return crosses


def points_in_polygon_vectorized(xs, ys, polygon: dict[str, Any]):
    """Vectorized even-odd containment for grids of points.

    ``xs``/``ys`` are broadcast-compatible arrays; returns a boolean array
    of the broadcast shape.  Holes subtract exactly like the scalar form.
    """
    import numpy as np

    polys = _polygons_of(polygon)
    xs_b = np.broadcast_to(np.asarray(xs, dtype=float),
                           np.broadcast(np.asarray(xs), np.asarray(ys)).shape)
    ys_b = np.broadcast_to(np.asarray(ys, dtype=float), xs_b.shape)
    inside = np.zeros(xs_b.shape, dtype=bool)
    for rings in polys:
        if not rings:
            continue
        part = _ring_crossings_vectorized(xs_b, ys_b, rings[0])
        for hole in rings[1:]:
            part &= ~_ring_crossings_vectorized(xs_b, ys_b, hole)
        inside |= part
    return inside


def _ring_crossings_vectorized(xs, ys, ring):
    import numpy as np

    crossings = np.zeros(xs.shape, dtype=bool)
    count = len(ring)
    for index in range(count):
        x1, y1 = float(ring[index][0]), float(ring[index][1])
        x2, y2 = float(ring[(index + 1) % count][0]), float(
            ring[(index + 1) % count][1])
        if y1 == y2:
            continue
        straddles = (y1 > ys) != (y2 > ys)
        t = (ys - y1) / (y2 - y1)
        hits = straddles & (xs < x1 + t * (x2 - x1))
        crossings ^= hits
    return crossings


def extent_of_coordinates(coordinates: Iterable[Sequence[float]],
                          ) -> tuple[float, float, float, float] | None:
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    found = False
    for coordinate in coordinates:
        x, y = float(coordinate[0]), float(coordinate[1])
        found = True
        xmin = min(xmin, x)
        ymin = min(ymin, y)
        xmax = max(xmax, x)
        ymax = max(ymax, y)
    if not found:
        return None
    return (xmin, ymin, xmax, ymax)


def _iter_positions(node: Any):
    """Yield [x, y] positions from arbitrarily nested GeoJSON coordinates."""
    if isinstance(node, (list, tuple)) and len(node) >= 2 and isinstance(
            node[0], (int, float)) and isinstance(node[1], (int, float)):
        yield node
        return
    if isinstance(node, (list, tuple)):
        for child in node:
            yield from _iter_positions(child)


def extent_of_geometries(geometries: Iterable[dict[str, Any]],
                         ) -> tuple[float, float, float, float]:
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    found = False
    for geometry in geometries:
        for x, y in _iter_positions(geometry.get("coordinates")):
            found = True
            xmin = min(xmin, x)
            ymin = min(ymin, y)
            xmax = max(xmax, x)
            ymax = max(ymax, y)
    if not found:
        raise ValueError("extent_of_geometries received no coordinates")
    return (xmin, ymin, xmax, ymax)

