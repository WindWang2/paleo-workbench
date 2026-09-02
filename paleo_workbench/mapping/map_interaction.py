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


def _project_to_segment(point: Point, start: Point, end: Point) -> Point | None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return None
    factor = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
    return (start[0] + factor * dx, start[1] + factor * dy)


def _segment_intersection(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    """Return one proper segment crossing; shared endpoints are vertex snaps."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    cdx, cdy = d[0] - c[0], d[1] - c[1]
    denom = abx * cdy - aby * cdx
    if abs(denom) <= 1e-15:
        return None
    acx, acy = c[0] - a[0], c[1] - a[1]
    left = (acx * cdy - acy * cdx) / denom
    right = (acx * aby - acy * abx) / denom
    if 0.0 < left < 1.0 and 0.0 < right < 1.0:
        return (a[0] + left * abx, a[1] + left * aby)
    return None


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


def _contains_polygon(point: Point, geometry: Mapping[str, object]) -> bool:
    """Even-odd across a polygon's rings: inside the outer ring and no hole.

    GeoJSON stores holes as subsequent rings, so a point inside any hole must
    NOT identify the feature.
    """
    geometry_type = str(geometry.get("type") or "")
    coords = geometry.get("coordinates")
    polygons: list[object] = []
    if geometry_type == "Polygon" and isinstance(coords, (list, tuple)):
        polygons = [coords]
    elif geometry_type == "MultiPolygon" and isinstance(coords, (list, tuple)):
        polygons = [polygon for polygon in coords if isinstance(polygon, (list, tuple))]
    for polygon in polygons:
        hit = False
        for ring in polygon:
            if isinstance(ring, (list, tuple)) and _contains(point, ring):
                hit = not hit
        if hit:
            return True
    return False


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


_MAX_QUERY_CELLS = 4096


class FeatureSpatialIndex:
    """Revision-cached, cell-indexed feature/vertex/segment candidates."""

    def __init__(self, layer: VectorLayer) -> None:
        self.layer = layer
        self._revision: tuple[int, int] | None = None
        self._features: tuple[VectorFeature, ...] = ()
        self._by_id: dict[str, VectorFeature] = {}
        self._draw_order: dict[str, int] = {}
        self._bounds: dict[str, Bounds] = {}
        self._vertices: dict[str, tuple[tuple[Point, tuple[int, ...]], ...]] = {}
        self._cell_size = 1.0
        self._feature_cells: dict[tuple[int, int], set[str]] = {}
        self._vertex_cells: dict[tuple[int, int], list[tuple[str, Point, tuple[int, ...], bool]]] = {}
        self._segment_cells: dict[tuple[int, int], list[tuple[str, Point, Point]]] = {}

    def _current_revision(self) -> tuple[int, int]:
        session = self.layer.edit_session
        return self.layer.data_revision, session.revision if session is not None else -1

    def _ensure(self) -> None:
        revision = self._current_revision()
        if revision == self._revision:
            return
        session = self.layer.edit_session
        self._features = session.features() if session is not None else self.layer.features()
        self._by_id = {feature.feature_id: feature for feature in self._features}
        self._draw_order = {feature.feature_id: index for index, feature in enumerate(self._features)}
        self._bounds = {feature.feature_id: _bounds(feature) for feature in self._features}
        self._vertices = {
            feature.feature_id: tuple(_vertices(feature.geometry["coordinates"]))
            for feature in self._features
        }
        all_bounds = tuple(self._bounds.values())
        if all_bounds:
            span = max(
                max(bound[2] for bound in all_bounds) - min(bound[0] for bound in all_bounds),
                max(bound[3] for bound in all_bounds) - min(bound[1] for bound in all_bounds),
            )
            # A degenerate span (all features coincident) must not shrink the
            # cell size to ~0: query ranges would map to billions of cells.
            self._cell_size = span / 64.0 if span > 0.0 else 1.0
        else:
            self._cell_size = 1.0
        self._feature_cells = {}
        self._vertex_cells = {}
        self._segment_cells = {}
        for feature in self._features:
            feature_id = feature.feature_id
            self._insert(self._feature_cells, self._bounds[feature_id], feature_id)
            geometry_type = str(feature.geometry.get("type") or "")
            endpoint_points: set[Point] = set()
            if geometry_type in {"Point", "MultiPoint"}:
                endpoint_points = {point for point, _path in self._vertices[feature_id]}
            elif geometry_type in {"LineString", "MultiLineString"}:
                for ring in _rings(feature.geometry):
                    if ring:
                        endpoint_points.update((ring[0], ring[-1]))
            for point, path in self._vertices[feature_id]:
                cell = self._cell(point)
                self._vertex_cells.setdefault(cell, []).append(
                    (feature_id, point, path, point in endpoint_points)
                )
            for ring in _rings(feature.geometry):
                for start, end in zip(ring, ring[1:]):
                    self._insert(self._segment_cells, self._bounds_for_points(start, end), (feature_id, start, end))
        self._revision = revision

    @staticmethod
    def _bounds_for_points(start: Point, end: Point) -> Bounds:
        return (min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1]))

    def _cell(self, point: Point) -> tuple[int, int]:
        return (math.floor(point[0] / self._cell_size), math.floor(point[1] / self._cell_size))

    def _cells(self, bounds: Bounds) -> Iterable[tuple[int, int]]:
        left, bottom = self._cell((bounds[0], bounds[1]))
        right, top = self._cell((bounds[2], bounds[3]))
        for x in range(left, right + 1):
            for y in range(bottom, top + 1):
                yield (x, y)

    def _insert(self, table: dict, bounds: Bounds, value: object) -> None:
        for cell in self._cells(bounds):
            bucket = table.setdefault(cell, set() if table is self._feature_cells else [])
            if isinstance(bucket, set):
                bucket.add(value)
            else:
                bucket.append(value)

    def _query_cells(self, bounds: Bounds) -> tuple[tuple[int, int], ...] | None:
        """Cells covered by ``bounds``.

        Returns ``None`` when the range spans more than ``_MAX_QUERY_CELLS``
        cells (tolerance large relative to the layer's cell size); callers
        then fall back to scanning every bucket, mirroring
        ``FeatureQueryIndex._MAX_QUERY_CELLS``.
        """
        left, bottom = self._cell((bounds[0], bounds[1]))
        right, top = self._cell((bounds[2], bounds[3]))
        if (right - left + 1) * (top - bottom + 1) > _MAX_QUERY_CELLS:
            return None
        return tuple((x, y) for x in range(left, right + 1) for y in range(bottom, top + 1))

    def _feature_candidates(self, bounds: Bounds) -> tuple[VectorFeature, ...]:
        cells = self._query_cells(bounds)
        if cells is None:
            ids = set(self._by_id)
        else:
            ids = {
                feature_id
                for cell in cells
                for feature_id in self._feature_cells.get(cell, ())
            }
        return tuple(sorted((self._by_id[feature_id] for feature_id in ids), key=lambda feature: self._draw_order[feature.feature_id], reverse=True))

    def _vertex_candidates(self, bounds: Bounds) -> tuple[tuple[str, Point, tuple[int, ...], bool], ...]:
        cells = self._query_cells(bounds)
        if cells is None:
            buckets = self._vertex_cells.values()
        else:
            buckets = (self._vertex_cells.get(cell, ()) for cell in cells)
        return tuple(
            candidate
            for bucket in buckets
            for candidate in bucket
        )

    def _segment_candidates(self, bounds: Bounds) -> tuple[tuple[str, Point, Point], ...]:
        cells = self._query_cells(bounds)
        if cells is None:
            buckets = self._segment_cells.values()
        else:
            buckets = (self._segment_cells.get(cell, ()) for cell in cells)
        return tuple({candidate for bucket in buckets for candidate in bucket})

    def identify(self, point: Point, tolerance: float) -> str | None:
        self._ensure()
        px, py = point
        # Reverse draw order means top-most compatible vector is found first.
        search_bounds = (point[0] - tolerance, point[1] - tolerance, point[0] + tolerance, point[1] + tolerance)
        for feature in self._feature_candidates(search_bounds):
            xmin, ymin, xmax, ymax = self._bounds[feature.feature_id]
            if px < xmin - tolerance or px > xmax + tolerance or py < ymin - tolerance or py > ymax + tolerance:
                continue
            geometry = feature.geometry
            geometry_type = str(geometry["type"])
            if geometry_type in {"Polygon", "MultiPolygon"}:
                if _contains_polygon(point, geometry):
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
        search_bounds = (point[0] - tolerance, point[1] - tolerance, point[0] + tolerance, point[1] + tolerance)
        for feature_id, vertex, path, _endpoint in self._vertex_candidates(search_bounds):
            distance = math.dist(point, vertex)
            if distance <= tolerance and (candidate is None or distance < candidate[0]):
                feature = self._by_id[feature_id]
                # Point geometry's coordinate itself is the special empty path
                # accepted by VectorEditSession.set_vertex.
                candidate = (distance, feature_id, () if feature.geometry["type"] == "Point" else path)
        return None if candidate is None else (candidate[1], candidate[2])

    def select_rectangle(self, start: Point, end: Point) -> set[str]:
        self._ensure()
        xmin, xmax = sorted((start[0], end[0]))
        ymin, ymax = sorted((start[1], end[1]))
        return {
            feature.feature_id
            for feature in self._feature_candidates((xmin, ymin, xmax, ymax))
            if not (
                self._bounds[feature.feature_id][2] < xmin
                or self._bounds[feature.feature_id][0] > xmax
                or self._bounds[feature.feature_id][3] < ymin
                or self._bounds[feature.feature_id][1] > ymax
            )
        }

    def snap(self, point: Point, tolerance: float, modes: Iterable[str] = ("vertex", "segment", "midpoint")) -> SnapMatch | None:
        self._ensure()
        enabled = {str(mode) for mode in modes}
        candidates: list[SnapMatch] = []
        search_bounds = (point[0] - tolerance, point[1] - tolerance, point[0] + tolerance, point[1] + tolerance)
        for feature_id, vertex, _path, endpoint in self._vertex_candidates(search_bounds):
            distance = math.dist(point, vertex)
            if distance <= tolerance and ("vertex" in enabled or ("endpoint" in enabled and endpoint)):
                candidates.append(SnapMatch(feature_id, vertex, "endpoint" if endpoint and "vertex" not in enabled else "vertex", distance))
        segments = self._segment_candidates(search_bounds)
        for feature_id, start, end in segments:
            if "midpoint" in enabled:
                midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
                distance = math.dist(point, midpoint)
                if distance <= tolerance:
                    candidates.append(SnapMatch(feature_id, midpoint, "midpoint", distance))
            if "segment" in enabled and (projected := _project_to_segment(point, start, end)) is not None:
                distance = math.dist(point, projected)
                if distance <= tolerance:
                    candidates.append(SnapMatch(feature_id, projected, "segment", distance))
        if "intersection" in enabled:
            for index, (feature_id, start, end) in enumerate(segments):
                for other_id, other_start, other_end in segments[index + 1:]:
                    crossing = _segment_intersection(start, end, other_start, other_end)
                    if crossing is not None and (distance := math.dist(point, crossing)) <= tolerance:
                        candidates.append(SnapMatch(feature_id if feature_id <= other_id else other_id, crossing, "intersection", distance))
        return min(candidates, key=lambda candidate: candidate.distance) if candidates else None


class SnappingService:
    """Map-level configurable snapping facade sharing cached layer indexes."""

    def __init__(self, *, pixel_tolerance: float = 10.0) -> None:
        self.enabled = False
        self.pixel_tolerance = max(0.0, float(pixel_tolerance))
        self.modes: set[str] = {"vertex", "segment", "midpoint"}
        self.current_layer_only = False
        self.layer_enabled: dict[str, bool] = {}
        self.layer_modes: dict[str, set[str]] = {}
        # 每图层覆盖：容差（像素）与优先级（数值小者优先，仅作等距平手裁决）。
        self.layer_tolerance: dict[str, float] = {}
        self.layer_priority: dict[str, int] = {}
        self.grid_origin: Point = (0.0, 0.0)
        self.grid_spacing: Point | None = None
        self.reference_points: tuple[Point, ...] = ()
        self._indexes: dict[str, FeatureSpatialIndex] = {}
        self.last_match: SnapMatch | None = None

    def index_for(self, layer: VectorLayer) -> FeatureSpatialIndex:
        index = self._indexes.get(layer.id)
        if index is None or index.layer is not layer:
            index = FeatureSpatialIndex(layer)
            self._indexes[layer.id] = index
        return index

    def set_reference_points(self, points: Iterable[Point]) -> None:
        self.reference_points = tuple(
            candidate
            for value in points
            if (candidate := _point(value)) is not None
        )

    def set_grid(self, spacing: Point | None, *, origin: Point = (0.0, 0.0)) -> None:
        if spacing is None:
            self.grid_spacing = None
            return
        sx, sy = float(spacing[0]), float(spacing[1])
        if sx <= 0.0 or sy <= 0.0:
            raise ValueError("grid snap spacing must be positive")
        self.grid_spacing = (sx, sy)
        parsed_origin = _point(origin)
        if parsed_origin is None:
            raise ValueError("grid snap origin must be finite")
        self.grid_origin = parsed_origin

    def snap(
        self,
        point: Point,
        *,
        tolerance: float,
        layers: Iterable[VectorLayer],
        map_units_per_pixel: float = 1.0,
    ) -> Point:
        """按全局容差（调用方换算为地图单位）与每图层像素覆盖捕捉。

        ``layer_tolerance`` 以像素存储（配置 UI 语义）；消费时乘
        ``map_units_per_pixel`` 换算为地图单位。不传该参数的旧调用方
        没有每图层覆盖，行为与历史一致。
        """
        self.last_match = None
        if not self.enabled:
            return point
        ranked: list[tuple[float, int, SnapMatch]] = []
        for layer in layers:
            if not self.layer_enabled.get(layer.id, True):
                continue
            override = self.layer_tolerance.get(layer.id)
            layer_tolerance = (
                max(0.0, override) * max(1e-12, map_units_per_pixel)
                if override is not None
                else tolerance
            )
            priority = self.layer_priority.get(layer.id, 0)
            match = self.index_for(layer).snap(
                point, layer_tolerance, self.layer_modes.get(layer.id, self.modes)
            )
            if match is not None:
                ranked.append((match.distance, priority, match))
        if "reference" in self.modes:
            for reference in self.reference_points:
                distance = math.dist(point, reference)
                if distance <= tolerance:
                    ranked.append((distance, 0, SnapMatch("__reference__", reference, "reference", distance)))
        if "grid" in self.modes and self.grid_spacing is not None:
            sx, sy = self.grid_spacing
            ox, oy = self.grid_origin
            grid_point = (ox + round((point[0] - ox) / sx) * sx, oy + round((point[1] - oy) / sy) * sy)
            distance = math.dist(point, grid_point)
            if distance <= tolerance:
                ranked.append((distance, 0, SnapMatch("__grid__", grid_point, "grid", distance)))
        if ranked:
            # 距离优先；等距时按每图层优先级（小值优先）裁决。
            ranked.sort(key=lambda item: (item[0], item[1]))
            self.last_match = ranked[0][2]
            return self.last_match.point
        return point
