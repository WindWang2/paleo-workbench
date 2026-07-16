from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

FeatureKind = Literal["facies", "well", "line", "label"]


def new_feature_id(prefix: str = "feat") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def normalize_facies(raw: dict[str, Any]) -> dict[str, Any]:
    """Return {id, kind, name, coordinates: list[list[float,float]], style}."""
    coords = raw.get("coordinates") or raw.get("geometry", {}).get("coordinates") or []
    # Accept ring as [[x,y], ...] or GeoJSON Polygon first ring
    if coords and isinstance(coords[0], (list, tuple)) and isinstance(coords[0][0], (list, tuple)):
        ring = list(coords[0])
    else:
        ring = [list(p) for p in coords]
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
        "coordinates": ring,
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
    if "coordinates" in raw and isinstance(raw["coordinates"], (list, tuple)):
        x, y = float(raw["coordinates"][0]), float(raw["coordinates"][1])
    else:
        # Accept x/lon/lng and y/lat (preview helpers and demo drafts use lng/lat).
        x = float(raw.get("x", raw.get("lng", raw.get("lon", 0.0))))
        y = float(raw.get("y", raw.get("lat", 0.0)))
    return {
        "id": raw.get("id") or new_feature_id("well"),
        "kind": "well",
        "name": raw.get("name") or raw.get("well_name") or "",
        "coordinates": [x, y],
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
    if "anchor" in raw:
        ax, ay = float(raw["anchor"][0]), float(raw["anchor"][1])
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
