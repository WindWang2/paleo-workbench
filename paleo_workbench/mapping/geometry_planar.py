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
    "extent_of_coordinates",
    "extent_of_geometries",
    "point_in_polygon_scalar",
    "point_in_ring_scalar",
    "points_in_polygon_vectorized",
]


def point_in_ring_scalar(x: float, y: float, ring) -> bool:
    """Ray-cast containment for ONE ring (no holes).  Shared kernel for the
    former polygonization/map_interaction/interpolator duplicates."""
    return _ray_crosses(float(x), float(y), ring)


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

