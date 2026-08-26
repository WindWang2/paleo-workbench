"""Map-layer topology validation and opt-in shared-vertex propagation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from paleo_workbench.mapping.vector_layer import VectorLayer

__all__ = ["TopologyEditResult", "TopologyService", "repair_invalid_geometry"]

Point = tuple[float, float]


def _point(value: object) -> Point | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _vertices(value: object, path: tuple[int, ...] = ()):
    point = _point(value)
    if point is not None:
        yield point, path
    elif isinstance(value, (tuple, list)):
        for index, child in enumerate(value):
            yield from _vertices(child, path + (index,))


@dataclass(frozen=True, slots=True)
class TopologyEditResult:
    changed: tuple[tuple[str, str, tuple[int, ...]], ...] = ()
    issues: tuple[dict[str, object], ...] = ()


class TopologyService:
    """Validate host geometry and update logically shared vertices only when enabled."""

    def __init__(self, *, enabled: bool = False, tolerance: float = 1e-9) -> None:
        self.enabled = bool(enabled)
        self.tolerance = max(0.0, float(tolerance))

    def validate(self, layers: Iterable[VectorLayer]) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []
        try:
            from shapely.geometry import shape
            from shapely.validation import explain_validity
        except ImportError:
            return [
                {
                    "severity": "error",
                    "layer_id": "",
                    "feature_id": "",
                    "code": "shapely_unavailable",
                    "message": "拓扑检查需要 Shapely/GEOS，当前不可用",
                }
            ]
        for layer in layers:
            session = layer.edit_session
            features = session.features() if session is not None else layer.features()
            for feature in features:
                geometry = feature.as_record()["geometry"]
                if shape is not None and geometry["type"] in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
                    candidate = shape(geometry)
                    if not candidate.is_valid:
                        issues.append(
                            {
                                "severity": "error",
                                "layer_id": layer.id,
                                "feature_id": feature.feature_id,
                                "message": explain_validity(candidate) if explain_validity else "invalid geometry",
                            }
                        )
                if geometry["type"] == "Polygon":
                    for ring_index, ring in enumerate(geometry["coordinates"]):
                        points = [point for point, _path in _vertices(ring)]
                        if len(points) < 4 or points[0] != points[-1]:
                            issues.append(
                                {
                                    "severity": "error",
                                    "layer_id": layer.id,
                                    "feature_id": feature.feature_id,
                                    "message": f"polygon ring {ring_index} is not closed",
                                }
                            )
        return issues

    def propagate_shared_vertex(
        self,
        layers: Iterable[VectorLayer],
        *,
        origin: Point,
        replacement: Point,
        skip: tuple[str, str, tuple[int, ...]] | None = None,
    ) -> TopologyEditResult:
        """Update exact shared nodes in opted-in map layers, never raw sources."""
        if not self.enabled:
            return TopologyEditResult()
        changed: list[tuple[str, str, tuple[int, ...]]] = []
        for layer in layers:
            # Snapshot paths before mutation; it makes duplicate closing nodes and
            # adjacent polygons deterministic even as individual commands change data.
            session = layer.edit_session
            source = session.features() if session is not None else layer.features()
            candidates = [
                (feature.feature_id, path)
                for feature in source
                for point, path in _vertices(feature.geometry["coordinates"])
                if math.dist(point, origin) <= self.tolerance
            ]
            # Do not create dirty edit sessions for unrelated layers merely because
            # topological editing is enabled. A working buffer appears only for a
            # layer that actually owns a logically shared node.
            if not candidates:
                continue
            session = session or layer.start_editing()
            for feature_id, path in candidates:
                if skip == (layer.id, feature_id, path):
                    continue
                session.set_vertex(feature_id, path, replacement)
                changed.append((layer.id, feature_id, path))
        return TopologyEditResult(changed=tuple(changed))


def repair_invalid_geometry(geometry: dict[str, object]) -> dict[str, object]:
    """Auto-heal invalid Polygon / MultiPolygon geometries (self-intersection, ring unclosed)."""
    if not isinstance(geometry, dict):
        return geometry
    geom_type = geometry.get("type")
    if geom_type not in {"Polygon", "MultiPolygon"}:
        return geometry

    # First ensure ring closure in coordinates
    coords = geometry.get("coordinates")
    if geom_type == "Polygon" and isinstance(coords, list):
        fixed_coords = []
        for ring in coords:
            if isinstance(ring, (list, tuple)) and len(ring) >= 3:
                r = [list(pt) for pt in ring]
                if r[0] != r[-1]:
                    r.append(list(r[0]))
                fixed_coords.append(r)
            else:
                fixed_coords.append(ring)
        geometry = {"type": "Polygon", "coordinates": fixed_coords}

    try:
        from shapely.geometry import MultiPolygon, Polygon, mapping, shape
        from shapely.geometry.polygon import orient
        from shapely.validation import make_valid

        cand = shape(geometry)
        if not cand.is_valid:
            repaired = make_valid(cand) if make_valid is not None else cand.buffer(0)
        else:
            repaired = cand

        if not repaired.is_empty:
            if repaired.geom_type == "Polygon":
                repaired = orient(repaired, sign=1.0)
            elif repaired.geom_type == "MultiPolygon":
                repaired = MultiPolygon([orient(p, sign=1.0) for p in repaired.geoms if p.geom_type == "Polygon"])
            elif repaired.geom_type == "GeometryCollection":
                polys = [orient(p, sign=1.0) for p in repaired.geoms if p.geom_type == "Polygon"]
                if len(polys) == 1:
                    repaired = polys[0]
                elif len(polys) > 1:
                    repaired = MultiPolygon(polys)
            res = mapping(repaired)
            return dict(res)
    except Exception:
        pass

    return geometry


