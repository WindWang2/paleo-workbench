"""QGIS-backed vector geometry operations routed through edit commands.

Professional GIS computation runs in the vendored QGIS geometry engine
(``qgis_render_bridge.geometry``); Paleo keeps transaction authority: every
operation here produces plain GeoJSON results that are recorded through
:class:`VectorEditSession` commands (undo/redo/audit/DataVersion), never by
mutating QGIS or raw resources directly.

The previous Shapely implementations remain in ``vector_operations`` as the
explicit fallback for hosts without the QGIS bridge.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.mapping.qgis_style import qgis_bridge_available
from paleo_workbench.mapping.vector_layer import VectorEditSession, VectorFeature

__all__ = [
    "make_geometry_valid",
    "merge_selected_polygons",
    "qgis_geometry_available",
    "split_polygon_by_line",
]


def qgis_geometry_available() -> bool:
    return qgis_bridge_available()


def _native_geometry():
    if not qgis_bridge_available():
        raise RuntimeError("QGIS geometry service requires the qgis_render_bridge")
    import qgis_render_bridge as native

    return native.geometry


def _geometry_json(feature: VectorFeature) -> str:
    return json.dumps(feature.as_record()["geometry"], ensure_ascii=False)


def _feature_from_geojson(
    feature_id: str, geometry_json: str, attributes
) -> VectorFeature:
    geometry = json.loads(geometry_json)
    return VectorFeature(feature_id, geometry, attributes)


def merge_selected_polygons(session: VectorEditSession, feature_ids: Iterable[str]) -> str:
    """Union polygons through QGIS and record one merge command."""
    ids = tuple(dict.fromkeys(str(feature_id) for feature_id in feature_ids))
    if len(ids) < 2:
        raise ValueError("select at least two polygons to merge")
    features = [session.feature(feature_id) for feature_id in ids]
    if any(feature.geometry["type"] not in {"Polygon", "MultiPolygon"} for feature in features):
        raise ValueError("only polygon features can be merged")
    geometry = _native_geometry().union([_geometry_json(feature) for feature in features])
    feature_id = new_feature_id("merge")
    merged = _feature_from_geojson(feature_id, geometry, features[0].attributes)
    session.merge_features(ids, merged)
    return feature_id


def split_polygon_by_line(
    polygon_session: VectorEditSession,
    polygon_feature_id: str,
    line_feature: VectorFeature,
) -> tuple[str, ...]:
    """Split a polygon with a cutter line through QGIS split semantics."""
    polygon_feature = polygon_session.feature(polygon_feature_id)
    if polygon_feature.geometry["type"] not in {"Polygon", "MultiPolygon"}:
        raise ValueError("split target must be a polygon")
    if line_feature.geometry["type"] not in {"LineString", "MultiLineString"}:
        raise ValueError("split cutter must be a line")
    pieces = _native_geometry().split_by_line(
        _geometry_json(polygon_feature), _geometry_json(line_feature)
    )
    if len(pieces) < 2:
        raise ValueError("the cutter does not split the selected polygon")
    replacements = tuple(
        _feature_from_geojson(new_feature_id("split"), piece, polygon_feature.attributes)
        for piece in pieces
    )
    polygon_session.split_feature(polygon_feature_id, replacements)
    return tuple(feature.feature_id for feature in replacements)


def make_geometry_valid(geometry: Mapping[str, object]) -> dict[str, object]:
    """Repair an invalid polygon geometry: QGIS engine first, shapely fallback."""
    if not isinstance(geometry, Mapping):
        return dict(geometry or {})
    if str(geometry.get("type") or "") not in {"Polygon", "MultiPolygon"}:
        return dict(geometry)
    if qgis_bridge_available():
        try:
            repaired = _native_geometry().make_valid(json.dumps(geometry))
            if repaired:
                return json.loads(repaired)
        except (RuntimeError, ValueError):
            pass  # fall through to the shapely repair below
    from paleo_workbench.mapping.topology import repair_invalid_geometry

    return repair_invalid_geometry(dict(geometry))
