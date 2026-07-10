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
    facies, wells, lines, labels = [], [], [], []
    for f in features:
        kind = f.get("kind")
        if kind == "facies":
            facies.append({
                "id": f["id"],
                "name": f.get("name", ""),
                "coordinates": f.get("coordinates", []),
                "style": f.get("style") or {},
            })
        elif kind == "well":
            c = f.get("coordinates") or [0, 0]
            wells.append({"id": f["id"], "name": f.get("name", ""), "x": c[0], "y": c[1]})
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
