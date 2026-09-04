from __future__ import annotations

import logging
from typing import Any

from paleo_workbench.project.domain import CoordinateStatus
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.mapping.geometry_schema import (
    normalize_facies,
    normalize_well,
    normalize_line,
    normalize_label,
)

logger = logging.getLogger(__name__)


def features_from_document(doc: PaleoMapDocument | None) -> list[dict[str, Any]]:
    if doc is None:
        return []
    out: list[dict[str, Any]] = []
    for raw in doc.facies_polygons or []:
        try:
            out.append(normalize_facies(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            logger.warning("Skipping malformed %s feature during document import", "facies", exc_info=True)
            continue
    for raw in doc.well_overlays or []:
        try:
            out.append(normalize_well(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            logger.warning("Skipping malformed %s feature during document import", "well", exc_info=True)
            continue
    for raw in getattr(doc, "line_features", None) or []:
        try:
            out.append(normalize_line(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            logger.warning("Skipping malformed %s feature during document import", "line", exc_info=True)
            continue
    for raw in getattr(doc, "label_features", None) or []:
        try:
            out.append(normalize_label(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            logger.warning("Skipping malformed %s feature during document import", "label", exc_info=True)
            continue
    return out


def apply_features_to_document(doc: PaleoMapDocument, features: list[dict[str, Any]]) -> None:
    """Write editor features back into the document, preserving payload fields.

    Facies keep prediction/compiler attributes (``properties``, ``facies``,
    ``probability``, ``region_id``). Wells keep dual ``x``/``y`` and ``lng``/``lat``;
    wells with missing/unusable coordinates carry a ``coordinate_status`` marker
    (``paleo_workbench.project.domain.CoordinateStatus``) instead of silently
    posing as valid locations. Labels with malformed coordinates are skipped
    with a logged diagnostic.
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
            # Audit #1162: a coordinates payload with fewer than 2 elements
            # used to silently land at (x, 0.0). Keep the partial position
            # but flag it via coordinate_status so downstream consumers can
            # filter unusable wells instead of trusting the fabricated y.
            c = f.get("coordinates")
            x = y = 0.0
            if isinstance(c, (list, tuple)) and len(c) >= 2:
                status = CoordinateStatus.OK
                try:
                    x, y = float(c[0]), float(c[1])
                except (TypeError, ValueError):
                    status = CoordinateStatus.INVALID
                    logger.warning(
                        "well feature %r has non-numeric coordinates; marked invalid",
                        f.get("id"),
                    )
            else:
                status = (
                    CoordinateStatus.INVALID
                    if isinstance(c, (list, tuple)) and len(c) == 1
                    else CoordinateStatus.MISSING
                )
                if isinstance(c, (list, tuple)) and len(c) == 1:
                    try:
                        x = float(c[0])
                    except (TypeError, ValueError):
                        pass
                logger.warning(
                    "well feature %r has %s coordinates; marked %s",
                    f.get("id"),
                    "unusable" if status == CoordinateStatus.INVALID else "no",
                    status,
                )
            # Never silently upgrade a feature already flagged upstream.
            prior = str(f.get("coordinate_status") or "")
            if prior and prior != CoordinateStatus.OK:
                status = prior
            well_record: dict[str, Any] = {
                "id": f["id"],
                "name": f.get("name", ""),
                "x": x,
                "y": y,
                "lng": f.get("lng", x),
                "lat": f.get("lat", y),
            }
            if status != CoordinateStatus.OK:
                well_record["coordinate_status"] = status
            wells.append(well_record)
        elif kind == "line":
            lines.append({
                "id": f["id"],
                "name": f.get("name", ""),
                "coordinates": f.get("coordinates", []),
            })
        elif kind == "label":
            # Audit #1162: single-element coordinates used to IndexError here.
            # Skip malformed labels with a diagnostic instead of crashing.
            c = f.get("coordinates")
            if not isinstance(c, (list, tuple)) or len(c) < 2:
                logger.warning(
                    "skipping label feature %r: coordinates must have >= 2 elements, got %r",
                    f.get("id"),
                    c,
                )
                continue
            try:
                anchor = [float(c[0]), float(c[1])]
            except (TypeError, ValueError):
                logger.warning(
                    "skipping label feature %r: non-numeric coordinates %r",
                    f.get("id"),
                    c,
                )
                continue
            labels.append({
                "id": f["id"],
                "text": f.get("text") or f.get("name", ""),
                "anchor": anchor,
            })
    doc.facies_polygons = facies
    doc.well_overlays = wells
    doc.line_features = lines
    doc.label_features = labels
