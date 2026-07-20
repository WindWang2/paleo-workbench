from __future__ import annotations

from typing import Any

from paleo_workbench.viz.prediction_helpers import field_value  # noqa: F401  (re-export)


def active_map_document(
    map_documents: list | tuple | None,
    *,
    prefer_id: str | None = None,
):
    """Pick the active map document.

    Prefer ``prefer_id`` when that document is still in the list (preserves the
    user's layer-tree selection across project refresh). Otherwise fall back to
    the last document (most recently added / demo draft).
    """
    if not map_documents:
        return None
    docs = list(map_documents)
    if prefer_id:
        for doc in docs:
            doc_id = doc.get("id") if isinstance(doc, dict) else getattr(doc, "id", None)
            if doc_id == prefer_id:
                return doc
    return docs[-1]


def _close_ring(ring: list) -> list[list[float]]:
    pts = [[float(p[0]), float(p[1])] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    if pts and pts[0] != pts[-1]:
        pts.append(list(pts[0]))
    return pts


def _normalize_geojson_geometry(geometry: dict[str, Any]) -> dict[str, Any] | None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, (list, tuple)):
        rings = [_close_ring(list(ring)) for ring in coordinates if isinstance(ring, (list, tuple))]
        if not rings or any(len(ring) < 4 for ring in rings):
            return None
        return {"type": "Polygon", "coordinates": rings}
    if geometry_type == "MultiPolygon" and isinstance(coordinates, (list, tuple)):
        polygons: list[list[list[list[float]]]] = []
        for polygon in coordinates:
            if not isinstance(polygon, (list, tuple)):
                return None
            rings = [_close_ring(list(ring)) for ring in polygon if isinstance(ring, (list, tuple))]
            if not rings or any(len(ring) < 4 for ring in rings):
                return None
            polygons.append(rings)
        if not polygons:
            return None
        return {"type": "MultiPolygon", "coordinates": polygons}
    return None


def _facies_properties(raw: dict[str, Any]) -> dict[str, Any]:
    props = dict(raw.get("properties") or {})
    name = raw.get("name") or raw.get("facies") or raw.get("label") or ""
    props.setdefault("name", name)
    props.setdefault("facies", props.get("name") or name)
    return props


def facies_to_geojson(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a facies record (editor or GeoJSON) for PaleoMapCanvas."""
    if not isinstance(raw, dict):
        return None
    if raw.get("type") == "Feature" and isinstance(raw.get("geometry"), dict):
        props = _facies_properties(raw)
        return {
            "type": "Feature",
            "properties": props,
            "geometry": raw["geometry"],
            **({"id": raw["id"]} if raw.get("id") is not None else {}),
        }

    geometry = raw.get("geometry")
    if isinstance(geometry, dict):
        normalized_geometry = _normalize_geojson_geometry(geometry)
        if normalized_geometry is not None:
            return {
                "type": "Feature",
                "properties": _facies_properties(raw),
                "geometry": normalized_geometry,
                **({"id": raw["id"]} if raw.get("id") is not None else {}),
            }

    coords = raw.get("coordinates")
    if not coords:
        return None
    # GeoJSON Polygon: [[[x,y],...]] or editor ring: [[x,y],...]
    if (
        isinstance(coords[0], (list, tuple))
        and coords[0]
        and isinstance(coords[0][0], (list, tuple))
    ):
        ring = _close_ring(coords[0])
    else:
        ring = _close_ring(list(coords))
    if len(ring) < 4:
        return None
    return {
        "type": "Feature",
        "properties": _facies_properties(raw),
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        **({"id": raw["id"]} if raw.get("id") is not None else {}),
    }


def well_to_lnglat(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a well record to {name, lng, lat} for PaleoMapCanvas."""
    if not isinstance(raw, dict):
        return None
    if "coordinates" in raw and isinstance(raw["coordinates"], (list, tuple)):
        lng = float(raw["coordinates"][0])
        lat = float(raw["coordinates"][1])
    elif "lng" in raw and "lat" in raw:
        lng = float(raw["lng"])
        lat = float(raw["lat"])
    else:
        lng = float(raw.get("x", raw.get("lon", 0.0)))
        lat = float(raw.get("y", raw.get("lat", 0.0)))
    return {"name": str(raw.get("name") or raw.get("well_name") or ""), "lng": lng, "lat": lat}


def preview_payload_from_document(document) -> tuple[list[dict], list[dict], str]:
    """Build (facies_geojson, wells_lnglat, period_name) from a PaleoMapDocument."""
    if document is None:
        return [], [], ""
    facies_out: list[dict] = []
    for raw in field_value(document, "facies_polygons", []) or []:
        feat = facies_to_geojson(raw if isinstance(raw, dict) else {})
        if feat is not None:
            facies_out.append(feat)
    wells_out: list[dict] = []
    for raw in field_value(document, "well_overlays", []) or []:
        well = well_to_lnglat(raw if isinstance(raw, dict) else {})
        if well is not None:
            wells_out.append(well)
    period = str(field_value(document, "linked_target_horizon", "") or "")
    return facies_out, wells_out, period


def preview_payload_from_features(
    features: list[dict[str, Any]] | None,
    *,
    period_name: str = "",
) -> tuple[list[dict], list[dict], str]:
    """Build canvas payload from MapEditScene.export_features() records."""
    facies_out: list[dict] = []
    wells_out: list[dict] = []
    for f in features or []:
        if not isinstance(f, dict):
            continue
        kind = f.get("kind")
        if kind == "facies":
            feat = facies_to_geojson(f)
            if feat is not None:
                facies_out.append(feat)
        elif kind == "well":
            well = well_to_lnglat(f)
            if well is not None:
                wells_out.append(well)
    return facies_out, wells_out, period_name
