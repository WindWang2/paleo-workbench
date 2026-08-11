"""Cached host-side hit testing, selection and snapping for map tools.

The index is deliberately a small reusable geometry service.  It caches feature
bounds per data/edit revision and never asks a renderer (or a graphics item) to
answer authoritative selection or snapping questions.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer

__all__ = ["FeatureSpatialIndex", "SnapMatch", "SnappingService"]

Point = tuple[float, float]
Bounds = tuple[float, float, float, float]


def _point(value: object) -> Point | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _vertices(value: object, path: tuple[int, ...] = ()) -> Iterable[tuple[Point, tuple[int, ...]]]:
    point = _point(value)
    if point is not None:
        yield point, path
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _vertices(child, path + (index,))


def _bounds(feature: VectorFeature) -> Bounds:
    vertices = [point for point, _path in _vertices(feature.geometry["coordinates"])]
    if not vertices:
        return (0.0, 0.0, 0.0, 0.0)
    xs, ys = zip(*vertices)
    return min(xs), min(ys), max(xs), max(ys)


def _distance_to_segment(point: Point, start: Point, end: Point) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    norm = dx * dx + dy * dy
    if norm <= 1e-18:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / norm))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _contains(point: Point, ring: object) -> bool:
    vertices = [vertex for vertex, _path in _vertices(ring)]
    if len(vertices) < 3:
        return False
    inside = False
    px, py = point
    previous = vertices[-1]
    for current in vertices:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


def _rings(geometry: Mapping[str, object]) -> Iterable[tuple[Point, ...]]:
    geometry_type = str(geometry.get("type") or "")
    coords = geometry.get("coordinates")
    if geometry_type == "LineString" and isinstance(coords, (list, tuple)):
        yield tuple(point for value in coords if (point := _point(value)) is not None)
    elif geometry_type == "MultiLineString" and isinstance(coords, (list, tuple)):
        for line in coords:
            if isinstance(line, (list, tuple)):
                yield tuple(point for value in line if (point := _point(value)) is not None)
    elif geometry_type == "Polygon" and isinstance(coords, (list, tuple)):
        for ring in coords:
            if isinstance(ring, (list, tuple)):
                yield tuple(point for value in ring if (point := _point(value)) is not None)
    elif geometry_type == "MultiPolygon" and isinstance(coords, (list, tuple)):
        for polygon in coords:
            if isinstance(polygon, (list, tuple)):
                for ring in polygon:
                    if isinstance(ring, (list, tuple)):
                        yield tuple(point for value in ring if (point := _point(value)) is not None)


@dataclass(frozen=True, slots=True)
class SnapMatch:
    feature_id: str
    point: Point
    mode: str
    distance: float


class FeatureSpatialIndex:
    """Revision-cached feature bounds, vertex and segment candidates."""

    def __init__(self, layer: VectorLayer) -> None:
        self.layer = layer
        self._revision: tuple[int, int] | None = None
        self._features: tuple[VectorFeature, ...] = ()
        self._bounds: dict[str, Bounds] = {}
        self._vertices: dict[str, tuple[tuple[Point, tuple[int, ...]], ...]] = {}

    def _current_revision(self) -> tuple[int, int]:
        session = self.layer.edit_session
        return self.layer.data_revision, session.revision if session is not None else -1

    def _ensure(self) -> None:
        revision = self._current_revision()
        if revision == self._revision:
            return
        session = self.layer.edit_session
        self._features = session.features() if session is not None else self.layer.features()
        self._bounds = {feature.feature_id: _bounds(feature) for feature in self._features}
        self._vertices = {
            feature.feature_id: tuple(_vertices(feature.geometry["coordinates"]))
            for feature in self._features
        }
        self._revision = revision

    def identify(self, point: Point, tolerance: float) -> str | None:
        self._ensure()
        px, py = point
        # Reverse draw order means top-most compatible vector is found first.
        for feature in reversed(self._features):
            xmin, ymin, xmax, ymax = self._bounds[feature.feature_id]
            if px < xmin - tolerance or px > xmax + tolerance or py < ymin - tolerance or py > ymax + tolerance:
                continue
            geometry = feature.geometry
            geometry_type = str(geometry["type"])
            if geometry_type in {"Polygon", "MultiPolygon"}:
                if any(_contains(point, ring) for ring in _rings(geometry)):
                    return feature.feature_id
            for ring in _rings(geometry):
                if any(_distance_to_segment(point, start, end) <= tolerance for start, end in zip(ring, ring[1:])):
                    return feature.feature_id
            if any(math.dist(point, candidate) <= tolerance for candidate, _path in self._vertices[feature.feature_id]):
                return feature.feature_id
        return None

    def identify_vertex(self, point: Point, tolerance: float) -> tuple[str, tuple[int, ...]] | None:
        self._ensure()
        candidate: tuple[float, str, tuple[int, ...]] | None = None
        for feature in self._features:
            for vertex, path in self._vertices[feature.feature_id]:
                distance = math.dist(point, vertex)
                if distance <= tolerance and (candidate is None or distance < candidate[0]):
                    # Point geometry's coordinate itself is the special empty path
                    # accepted by VectorEditSession.set_vertex.
                    candidate = (distance, feature.feature_id, () if feature.geometry["type"] == "Point" else path)
        return None if candidate is None else (candidate[1], candidate[2])

    def select_rectangle(self, start: Point, end: Point) -> set[str]:
        self._ensure()
        xmin, xmax = sorted((start[0], end[0]))
        ymin, ymax = sorted((start[1], end[1]))
        return {
            feature_id
            for feature_id, (left, bottom, right, top) in self._bounds.items()
            if not (right < xmin or left > xmax or top < ymin or bottom > ymax)
        }

    def snap(self, point: Point, tolerance: float, modes: Iterable[str] = ("vertex", "segment", "midpoint")) -> SnapMatch | None:
        self._ensure()
        enabled = {str(mode) for mode in modes}
        candidates: list[SnapMatch] = []
        for feature in self._features:
            if "vertex" in enabled or "endpoint" in enabled:
                for vertex, _path in self._vertices[feature.feature_id]:
                    distance = math.dist(point, vertex)
                    if distance <= tolerance:
                        candidates.append(SnapMatch(feature.feature_id, vertex, "vertex", distance))
            for ring in _rings(feature.geometry):
                for start, end in zip(ring, ring[1:]):
                    if "midpoint" in enabled:
                        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
                        distance = math.dist(point, midpoint)
                        if distance <= tolerance:
                            candidates.append(SnapMatch(feature.feature_id, midpoint, "midpoint", distance))
                    if "segment" in enabled:
                        dx, dy = end[0] - start[0], end[1] - start[1]
                        length_sq = dx * dx + dy * dy
                        if length_sq <= 1e-18:
                            continue
                        factor = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
                        projected = (start[0] + factor * dx, start[1] + factor * dy)
                        distance = math.dist(point, projected)
                        if distance <= tolerance:
                            candidates.append(SnapMatch(feature.feature_id, projected, "segment", distance))
        return min(candidates, key=lambda candidate: candidate.distance) if candidates else None


class SnappingService:
    """Map-level configurable snapping facade sharing cached layer indexes."""

    def __init__(self, *, pixel_tolerance: float = 10.0) -> None:
        self.enabled = False
        self.pixel_tolerance = max(0.0, float(pixel_tolerance))
        self.modes: set[str] = {"vertex", "segment", "midpoint"}
        self.current_layer_only = False
        self._indexes: dict[str, FeatureSpatialIndex] = {}
        self.last_match: SnapMatch | None = None

    def index_for(self, layer: VectorLayer) -> FeatureSpatialIndex:
        index = self._indexes.get(layer.id)
        if index is None or index.layer is not layer:
            index = FeatureSpatialIndex(layer)
            self._indexes[layer.id] = index
        return index

    def snap(self, point: Point, *, tolerance: float, layers: Iterable[VectorLayer]) -> Point:
        self.last_match = None
        if not self.enabled:
            return point
        matches = [
            match
            for layer in layers
            if (match := self.index_for(layer).snap(point, tolerance, self.modes)) is not None
        ]
        if matches:
            self.last_match = min(matches, key=lambda match: match.distance)
            return self.last_match.point
        return point
