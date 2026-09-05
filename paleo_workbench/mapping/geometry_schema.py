from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import uuid4

from paleo_workbench.project.domain import CoordinateStatus

logger = logging.getLogger(__name__)

FeatureKind = Literal["facies", "well", "line", "label"]


def new_feature_id(prefix: str = "feat") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _is_point(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and not isinstance(value[0], (list, tuple))
        and not isinstance(value[1], (list, tuple))
    )


def _coerce_ring(value: object) -> list[list[float]]:
    if not isinstance(value, (list, tuple)):
        return []
    ring: list[list[float]] = []
    for point in value:
        if not _is_point(point):
            return []
        ring.append([float(point[0]), float(point[1])])
    if ring and ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def canonical_facies_geometry(
    raw: dict[str, Any],
) -> tuple[str, list[list[list[list[float]]]]]:
    """Return ``(type, polygons→rings→points)`` for legacy or GeoJSON input."""
    geometry = raw.get("geometry") if isinstance(raw.get("geometry"), dict) else {}
    geometry_type = str(raw.get("geometry_type") or geometry.get("type") or "")
    coordinates = geometry.get("coordinates") if geometry else raw.get("coordinates")
    coordinates = coordinates or []

    if geometry_type not in {"Polygon", "MultiPolygon"}:
        if isinstance(coordinates, (list, tuple)) and coordinates:
            first = coordinates[0]
            if _is_point(first):
                geometry_type = "Polygon"
            elif isinstance(first, (list, tuple)) and first and _is_point(first[0]):
                geometry_type = "Polygon"
            else:
                geometry_type = "MultiPolygon"
        else:
            geometry_type = "Polygon"

    if geometry_type == "Polygon":
        if isinstance(coordinates, (list, tuple)) and coordinates and _is_point(coordinates[0]):
            source_polygons = [[coordinates]]
        else:
            source_polygons = [[*(coordinates if isinstance(coordinates, (list, tuple)) else [])]]
    else:
        source_polygons = coordinates if isinstance(coordinates, (list, tuple)) else []

    polygons: list[list[list[list[float]]]] = []
    for source_polygon in source_polygons:
        if not isinstance(source_polygon, (list, tuple)):
            continue
        rings = [_coerce_ring(source_ring) for source_ring in source_polygon]
        rings = [ring for ring in rings if ring]
        if rings:
            polygons.append(rings)
    return geometry_type, polygons


def compact_facies_coordinates(
    geometry_type: str,
    polygons: list[list[list[list[float]]]],
) -> list:
    """Keep the historic single-ring shape while preserving complex geometry."""
    if geometry_type == "Polygon":
        rings = polygons[0] if polygons else []
        return [list(point) for point in rings[0]] if len(rings) == 1 else rings
    return polygons


def normalize_facies(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize facies without discarding holes or MultiPolygon parts."""
    geometry_type, polygons = canonical_facies_geometry(raw)
    canonical_coordinates = polygons[0] if geometry_type == "Polygon" and polygons else polygons
    props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    name = (
        raw.get("name")
        or raw.get("facies")
        or raw.get("label")
        or props.get("name")
        or props.get("facies")
        or props.get("label")
        or ""
    )
    out: dict[str, Any] = {
        "id": raw.get("id")
        or props.get("id")
        or props.get("region_id")
        or new_feature_id("facies"),
        "kind": "facies",
        "name": name,
        "coordinates": compact_facies_coordinates(geometry_type, polygons),
        "geometry_type": geometry_type,
        "geometry": {"type": geometry_type, "coordinates": canonical_coordinates},
        "style": dict(raw.get("style") or props.get("style") or {}),
    }
    # Preserve prediction / compiler attributes for editor round-trip.
    facies = raw.get("facies") or props.get("facies") or name
    if facies:
        out["facies"] = facies
    if raw.get("probability") is not None:
        out["probability"] = raw["probability"]
    elif props.get("probability") is not None:
        out["probability"] = props["probability"]
    if raw.get("region_id") is not None:
        out["region_id"] = raw["region_id"]
    elif props.get("region_id") is not None:
        out["region_id"] = props["region_id"]
    if props:
        # Keep non-style properties for re-export on save_draft.
        kept = {k: v for k, v in props.items() if k != "style"}
        if kept:
            out["properties"] = kept
    return out


def normalize_well(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a well record; malformed coordinates are flagged, never crash.

    A ``coordinates`` payload with fewer than 2 elements (audit #1162) used to
    raise IndexError; it now falls back to the scalar x/lng + y/lat keys, and
    when those are unusable too the feature keeps a placeholder position but is
    marked ``coordinate_status`` INVALID (same vocabulary as
    ``paleo_workbench.project.domain.CoordinateStatus``) instead of silently
    pretending to be a valid location.
    """
    x: float | None = None
    y: float | None = None
    coords = raw.get("coordinates")
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            x, y = float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            x = y = None
    if x is None or y is None:
        # Coordinates absent/short/non-numeric: fall back to SCALAR keys,
        # selected as whole CRS-consistent families (pipeline semantics,
        # audit #1150): (x, y) first, then (lng, lat), then (lon, lat). A
        # family is used only when BOTH keys are present and numeric — never
        # cross-paired: `{x, lat}` would mix a projected x with a geographic
        # latitude and silently pass as OK. An incomplete/unusable family
        # leaves x/y None and the feature falls through to INVALID below.
        for x_key, y_key in (("x", "y"), ("lng", "lat"), ("lon", "lat")):
            sx, sy = raw.get(x_key), raw.get(y_key)
            if sx is None or sy is None:
                continue
            try:
                x, y = float(sx), float(sy)
                break
            except (TypeError, ValueError):
                continue
    if (
        (x is None or y is None)
        and isinstance(coords, (list, tuple))
        and len(coords) == 1
    ):
        # No scalar pair: keep a numeric leading element as partial evidence.
        try:
            x = float(coords[0])
        except (TypeError, ValueError):
            x = None
    status = CoordinateStatus.OK if (x is not None and y is not None) else CoordinateStatus.INVALID
    if status == CoordinateStatus.INVALID:
        logger.warning(
            "well feature %r has unusable coordinates (missing/short/non-numeric); marked invalid",
            raw.get("name") or raw.get("id"),
        )
    return {
        "id": raw.get("id") or new_feature_id("well"),
        "kind": "well",
        "name": raw.get("name") or raw.get("well_name") or "",
        "coordinates": [x if x is not None else 0.0, y if y is not None else 0.0],
        "coordinate_status": status,
    }


def normalize_line(raw: dict[str, Any]) -> dict[str, Any]:
    coords = raw.get("coordinates") or []
    return {
        "id": raw.get("id") or new_feature_id("line"),
        "kind": "line",
        "name": raw.get("name") or "",
        "coordinates": [list(p) for p in coords],
    }


def normalize_label(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a label record; an anchor needs two numeric elements.

    A short anchor (audit #1162) used to raise IndexError; it now raises a
    descriptive ``ValueError`` that :func:`features_from_document` catches,
    logs and skips — malformed labels never abort document import.
    """
    if "anchor" in raw:
        anchor = raw["anchor"]
        if not isinstance(anchor, (list, tuple)) or len(anchor) < 2:
            raise ValueError(
                f"label anchor must have >= 2 coordinate elements, got {anchor!r}"
            )
        ax, ay = float(anchor[0]), float(anchor[1])
    else:
        ax = float(raw.get("x", 0.0))
        ay = float(raw.get("y", 0.0))
    return {
        "id": raw.get("id") or new_feature_id("label"),
        "kind": "label",
        "name": raw.get("text") or raw.get("name") or "",
        "coordinates": [ax, ay],
        "text": raw.get("text") or raw.get("name") or "",
    }
