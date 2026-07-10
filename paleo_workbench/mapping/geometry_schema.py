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
    return {
        "id": raw.get("id") or new_feature_id("facies"),
        "kind": "facies",
        "name": raw.get("name") or raw.get("facies") or raw.get("label") or "",
        "coordinates": ring,
        "style": dict(raw.get("style") or {}),
    }


def normalize_well(raw: dict[str, Any]) -> dict[str, Any]:
    if "coordinates" in raw and isinstance(raw["coordinates"], (list, tuple)):
        x, y = float(raw["coordinates"][0]), float(raw["coordinates"][1])
    else:
        x = float(raw.get("x", raw.get("lon", 0.0)))
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
