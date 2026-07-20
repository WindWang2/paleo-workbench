from __future__ import annotations

from typing import Any

from paleo_workbench.mapping.geometry_schema import canonical_facies_geometry
from paleo_workbench.ui.pages.map_edit_items import (
    FaciesPolygonItem,
    FeatureItemMixin,
    LabelItem,
    LineItem,
    WellPointItem,
)


def item_from_record(record: dict[str, Any]) -> FeatureItemMixin | None:
    """Construct a graphics item from a feature record dict."""
    kind = record.get("kind")
    feature_id = record.get("id")
    if not feature_id:
        return None
    if kind == "facies":
        return make_facies(record)
    if kind == "well":
        return make_well(record)
    if kind == "line":
        return make_line(record)
    if kind == "label":
        return make_label(record)
    return None


def make_facies(record: dict[str, Any]) -> FaciesPolygonItem | None:
    geometry_type, polygons = canonical_facies_geometry(record)
    if not polygons or not polygons[0] or len(polygons[0][0]) < 4:
        return None
    if any(len(ring) < 4 for polygon in polygons for ring in polygon):
        return None
    geometry_coordinates = polygons[0] if geometry_type == "Polygon" else polygons
    extras = {}
    for key in ("facies", "probability", "region_id", "properties"):
        if key in record and record[key] is not None:
            extras[key] = record[key]
    return FaciesPolygonItem(
        feature_id=str(record["id"]),
        coordinates=polygons[0][0],
        name=str(record.get("name") or ""),
        style=record.get("style") or {},
        extras=extras,
        geometry_type=geometry_type,
        geometry_coordinates=geometry_coordinates,
    )


def make_well(record: dict[str, Any]) -> WellPointItem | None:
    coords = record.get("coordinates") or [0, 0]
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        x = float(coords[0])
        y = float(coords[1])
    except (TypeError, ValueError):
        return None
    return WellPointItem(
        feature_id=str(record["id"]),
        x=x,
        y=y,
        name=str(record.get("name") or ""),
    )


def make_line(record: dict[str, Any]) -> LineItem | None:
    coords = record.get("coordinates") or []
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    points: list[list[float]] = []
    for p in coords:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return None
        try:
            points.append([float(p[0]), float(p[1])])
        except (TypeError, ValueError):
            return None
    return LineItem(
        feature_id=str(record["id"]),
        coordinates=points,
        name=str(record.get("name") or ""),
    )


def make_label(record: dict[str, Any]) -> LabelItem | None:
    coords = record.get("coordinates") or [0, 0]
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        x = float(coords[0])
        y = float(coords[1])
    except (TypeError, ValueError):
        return None
    text = str(record.get("text") or record.get("name") or "")
    name = str(record.get("name") or text)
    return LabelItem(
        feature_id=str(record["id"]),
        x=x,
        y=y,
        text=text,
        name=name,
    )
