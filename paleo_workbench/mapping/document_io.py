from __future__ import annotations

from typing import Any

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.mapping.geometry_schema import (
    normalize_facies,
    normalize_well,
    normalize_line,
    normalize_label,
)


def features_from_document(doc: PaleoMapDocument | None) -> list[dict[str, Any]]:
    if doc is None:
        return []
    out: list[dict[str, Any]] = []
    for raw in doc.facies_polygons or []:
        try:
            out.append(normalize_facies(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            continue
    for raw in doc.well_overlays or []:
        try:
            out.append(normalize_well(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            continue
    for raw in getattr(doc, "line_features", None) or []:
        try:
            out.append(normalize_line(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            continue
    for raw in getattr(doc, "label_features", None) or []:
        try:
            out.append(normalize_label(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            continue
    return out


def apply_features_to_document(doc: PaleoMapDocument, features: list[dict[str, Any]]) -> None:
    """Write editor features back into the document, preserving payload fields.

    Facies keep prediction/compiler attributes (``properties``, ``facies``,
    ``probability``, ``region_id``). Wells keep dual ``x``/``y`` and ``lng``/``lat``.
    """
    facies, wells, lines, labels = [], [], [], []
    for f in features:
        kind = f.get("kind")
        if kind == "facies":
            normalized = normalize_facies(f)
            record: dict[str, Any] = {
                "id": f["id"],
                "name": f.get("name", ""),
                "coordinates": normalized.get("coordinates", []),
                "geometry_type": normalized["geometry_type"],
                "geometry": normalized["geometry"],
                "style": f.get("style") or {},
            }
            if f.get("facies") is not None:
                record["facies"] = f["facies"]
            elif f.get("name"):
                record["facies"] = f["name"]
            if f.get("probability") is not None:
                record["probability"] = f["probability"]
            if f.get("region_id") is not None:
                record["region_id"] = f["region_id"]
            props = f.get("properties")
            if isinstance(props, dict) and props:
                record["properties"] = dict(props)
            facies.append(record)
        elif kind == "well":
            c = f.get("coordinates") or [0, 0]
            x = float(c[0]) if len(c) >= 1 else 0.0
            y = float(c[1]) if len(c) >= 2 else 0.0
            wells.append({
                "id": f["id"],
                "name": f.get("name", ""),
                "x": x,
                "y": y,
                "lng": f.get("lng", x),
                "lat": f.get("lat", y),
            })
        elif kind == "line":
            lines.append({
                "id": f["id"],
                "name": f.get("name", ""),
                "coordinates": f.get("coordinates", []),
            })
        elif kind == "label":
            c = f.get("coordinates") or [0, 0]
            labels.append({
                "id": f["id"],
                "text": f.get("text") or f.get("name", ""),
                "anchor": [c[0], c[1]],
            })
    doc.facies_polygons = facies
    doc.well_overlays = wells
    doc.line_features = lines
    doc.label_features = labels
