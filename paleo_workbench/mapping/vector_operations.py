"""Optional GEOS/Shapely vector operations applied through edit-buffer commands.

This is the FALLBACK geometry path for hosts without the QGIS bridge.  The
professional implementation lives in :mod:`paleo_workbench.mapping.geometry_service`
(vendored QGIS engine) and is preferred whenever the bridge is available.
"""

from __future__ import annotations

from collections.abc import Iterable

from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.mapping.qgis_style import qgis_bridge_available
from paleo_workbench.mapping.vector_layer import VectorEditSession, VectorFeature

__all__ = ["merge_selected_polygons", "split_polygon_by_line"]


def _shape(feature: VectorFeature):
    try:
        from shapely.geometry import shape
    except ImportError as exc:  # pragma: no cover - dependency/environment path
        raise RuntimeError("polygon operations require Shapely/GEOS") from exc
    return shape(feature.as_record()["geometry"])


def _feature_from_shape(feature_id: str, geometry, attributes) -> VectorFeature:
    from shapely.geometry import mapping

    return VectorFeature(feature_id, mapping(geometry), attributes)


def merge_selected_polygons(session: VectorEditSession, feature_ids: Iterable[str]) -> str:
    if qgis_bridge_available():
        from paleo_workbench.mapping.geometry_service import (
            merge_selected_polygons as qgis_merge,
        )

        return qgis_merge(session, feature_ids)
    return _shapely_merge(session, feature_ids)


def _shapely_merge(session: VectorEditSession, feature_ids: Iterable[str]) -> str:
    ids = tuple(dict.fromkeys(str(feature_id) for feature_id in feature_ids))
    if len(ids) < 2:
        raise ValueError("select at least two polygons to merge")
    features = [session.feature(feature_id) for feature_id in ids]
    if any(feature.geometry["type"] not in {"Polygon", "MultiPolygon"} for feature in features):
        raise ValueError("only polygon features can be merged")
    try:
        from shapely.ops import unary_union
    except ImportError as exc:  # pragma: no cover - dependency/environment path
        raise RuntimeError("polygon operations require Shapely/GEOS") from exc
    geometry = unary_union([_shape(feature) for feature in features])
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("selected polygons cannot form a valid merged polygon")
    feature_id = new_feature_id("merge")
    merged = _feature_from_shape(feature_id, geometry, features[0].attributes)
    session.merge_features(ids, merged)
    return feature_id


def split_polygon_by_line(
    polygon_session: VectorEditSession,
    polygon_feature_id: str,
    line_feature: VectorFeature,
) -> tuple[str, ...]:
    if qgis_bridge_available():
        from paleo_workbench.mapping.geometry_service import (
            split_polygon_by_line as qgis_split,
        )

        return qgis_split(polygon_session, polygon_feature_id, line_feature)
    return _shapely_split(polygon_session, polygon_feature_id, line_feature)


def _shapely_split(
    polygon_session: VectorEditSession,
    polygon_feature_id: str,
    line_feature: VectorFeature,
) -> tuple[str, ...]:
    polygon_feature = polygon_session.feature(polygon_feature_id)
    if polygon_feature.geometry["type"] not in {"Polygon", "MultiPolygon"}:
        raise ValueError("split target must be a polygon")
    if line_feature.geometry["type"] not in {"LineString", "MultiLineString"}:
        raise ValueError("split cutter must be a line")
    try:
        from shapely.ops import split
    except ImportError as exc:  # pragma: no cover - dependency/environment path
        raise RuntimeError("polygon operations require Shapely/GEOS") from exc
    pieces = list(split(_shape(polygon_feature), _shape(line_feature)).geoms)
    pieces = [piece for piece in pieces if piece.geom_type in {"Polygon", "MultiPolygon"} and not piece.is_empty]
    if len(pieces) < 2:
        raise ValueError("the cutter does not split the selected polygon")
    replacements = tuple(
        _feature_from_shape(new_feature_id("split"), piece, polygon_feature.attributes)
        for piece in pieces
    )
    polygon_session.split_feature(polygon_feature_id, replacements)
    return tuple(feature.feature_id for feature in replacements)
