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
    # V8 M4：shapely 兜底改经 facade union（同一引擎链 + 披露）；本模块
    # 不再直接 import shapely——unavailable 环境的错误信息也由 facade 统一。
    from paleo_workbench.mapping.geometry_operations import union

    merged = union([feature.as_record()["geometry"] for feature in features])
    geometry = merged.geometry
    if (
        str(geometry.get("type")) not in {"Polygon", "MultiPolygon"}
        or not geometry.get("coordinates")
    ):
        raise ValueError("selected polygons cannot form a valid merged polygon")
    feature_id = new_feature_id("merge")
    merged_feature = VectorFeature(feature_id, geometry, features[0].attributes)
    session.merge_features(ids, merged_feature)
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
    # V8 M4：shapely 兜底改经 facade split_by_line（同一引擎链 + 披露）。
    from paleo_workbench.mapping.geometry_operations import split_by_line

    result = split_by_line(
        polygon_feature.as_record()["geometry"],
        line_feature.as_record()["geometry"],
    )
    pieces = [
        piece
        for piece in (result.geometries or [])
        if str(piece.get("type")) in {"Polygon", "MultiPolygon"}
        and bool(piece.get("coordinates"))
    ]
    if len(pieces) < 2:
        raise ValueError("the cutter does not split the selected polygon")
    replacements = tuple(
        VectorFeature(new_feature_id("split"), piece, polygon_feature.attributes)
        for piece in pieces
    )
    polygon_session.split_feature(polygon_feature_id, replacements)
    return tuple(feature.feature_id for feature in replacements)
