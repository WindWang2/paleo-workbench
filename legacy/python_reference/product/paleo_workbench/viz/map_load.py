from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paleo_workbench.viz.mapping_helpers import (
    facies_to_geojson,
    preview_payload_from_document,
    well_to_lnglat,
)


def load_map_payload_from_document(doc: Any) -> tuple[list, list, str]:
    """Reuse mapping_helpers.preview_payload_from_document."""
    return preview_payload_from_document(doc)


def load_map_payload_from_geojson_path(path: str | Path) -> tuple[list, list, str]:
    """Load a GeoJSON 相图 file into (facies_features, wells, period).

    Accepts a FeatureCollection, a single Feature, or a bare geometry.
    Polygon/MultiPolygon features become facies polygons; Point features
    become well overlays (name taken from properties when present).
    """
    facies, wells, doc_name = _parse_geojson_document(path)
    return facies, wells, doc_name


def _parse_geojson_document(path: str | Path) -> tuple[list[dict], list[dict], str]:
    """Parse one GeoJSON file into (facies_features, wells, doc_name)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("GeoJSON 根节点必须是对象")

    raw_features: list[Any]
    is_collection = data.get("type") == "FeatureCollection"
    if is_collection:
        raw_features = list(data.get("features") or [])
    elif data.get("type") == "Feature":
        raw_features = [data]
    else:
        raw_features = [data]  # bare geometry dict

    facies: list[dict] = []
    wells: list[dict] = []
    for raw in raw_features:
        if not isinstance(raw, dict):
            continue
        props = raw.get("properties") if raw.get("type") == "Feature" else {}
        props = dict(props or {}) if isinstance(props, dict) else {}
        geometry = raw.get("geometry") if raw.get("type") == "Feature" else raw
        geometry_type = str((geometry or {}).get("type") or "")
        if geometry_type in {"Polygon", "MultiPolygon"}:
            feat = facies_to_geojson(
                {"type": "Feature", "properties": props, "geometry": geometry}
            )
            if feat is not None:
                facies.append(feat)
        elif geometry_type == "Point":
            coords = (geometry or {}).get("coordinates") or []
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                well = well_to_lnglat(
                    {
                        "name": props.get("name") or props.get("well_name") or "",
                        "lng": coords[0],
                        "lat": coords[1],
                    }
                )
                if well is not None:
                    wells.append(well)

    doc_name = str(data.get("name") or "") if is_collection else ""
    return facies, wells, doc_name


# Hierarchy role (resource layer role) → geo-viz-engine feature level name.
_ROLE_TO_LEVEL = {
    "facies": "facies",
    "subfacies": "sub_facies",
    "microfacies": "micro_facies",
}


def load_facies_group_payload(
    entries: list[tuple[str, str | None]],
    *,
    clicked_path: str = "",
) -> tuple[list[dict], list[dict], str]:
    """Load and merge a 相/亚相/微相 GeoJSON sibling group.

    *entries* are ``(path, role)`` pairs ordered coarse → fine (role may be
    ``None`` for layers whose level cannot be recognized). Facies features of
    role-carrying layers are annotated with the engine's ``level`` metadata
    (respecting any explicit ``level`` already in the data) and a synthesized
    ``id`` when missing, so the merged set drives the hierarchical
    ``PaleoMapCanvas.load_hierarchy`` path. Wells are deduplicated across
    layers; the clicked layer's document name becomes the period label.
    """
    all_facies: list[dict] = []
    wells_by_key: dict[tuple, dict] = {}
    period = ""
    for path, role in entries:
        facies, wells, doc_name = _parse_geojson_document(path)
        level = _ROLE_TO_LEVEL.get(role or "")
        stem = Path(path).stem
        for index, feat in enumerate(facies):
            if level:
                props = dict(feat.get("properties") or {})
                props.setdefault("level", level)
                props.setdefault("id", f"{level}-{stem}-{index}")
                feat = {**feat, "properties": props}
            all_facies.append(feat)
        for well in wells:
            key = (
                well.get("name", ""),
                round(float(well.get("lng", 0.0)), 6),
                round(float(well.get("lat", 0.0)), 6),
            )
            wells_by_key.setdefault(key, well)
        if clicked_path and str(Path(path)) == str(Path(clicked_path)):
            period = doc_name
    return all_facies, list(wells_by_key.values()), period
