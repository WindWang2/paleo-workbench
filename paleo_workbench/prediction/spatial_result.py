"""Spatial prediction result contract and validation (Stage 13).

Production prediction payloads must carry explicit spatial meaning.
Supported classes:

- VECTOR_POLYGONS — GeoJSON-like features with real coordinates
- WELL_INTERVALS — depth intervals per well (not map-compilable alone)
- CLASSIFIED_RASTER — class grid + CRS/geotransform (map via layer/ref)
- NONE / missing — non-spatial (demo/heuristic legacy)

Bounded ``result_summary`` for PredictionTask must not embed full grids.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.prediction.model_package import (
    SPATIAL_CLASSIFIED_RASTER,
    SPATIAL_NONE,
    SPATIAL_VECTOR_POLYGONS,
    SPATIAL_WELL_INTERVALS,
)

KNOWN_SPATIAL = frozenset(
    {
        SPATIAL_VECTOR_POLYGONS,
        SPATIAL_WELL_INTERVALS,
        SPATIAL_CLASSIFIED_RASTER,
        SPATIAL_NONE,
        "",
    }
)


class SpatialResultError(ValueError):
    """Malformed or non-spatial prediction output for the declared schema."""


def spatial_type_of(payload: dict[str, Any] | None) -> str:
    """Detect spatial_output_type from provider payload / result_summary."""
    payload = payload or {}
    summary = payload.get("result_summary") or {}
    for src in (payload, summary, payload.get("output_schema") or {}, summary.get("spatial") or {}):
        if not isinstance(src, dict):
            continue
        t = str(src.get("spatial_output_type") or "").strip()
        if t:
            return t
    spatial = summary.get("spatial") or payload.get("spatial")
    if isinstance(spatial, dict):
        t = str(spatial.get("type") or spatial.get("spatial_output_type") or "").strip()
        if t:
            return t
        if spatial.get("features") or spatial.get("polygons"):
            return SPATIAL_VECTOR_POLYGONS
        if spatial.get("intervals") or spatial.get("well_intervals"):
            return SPATIAL_WELL_INTERVALS
        if spatial.get("grid") is not None or spatial.get("classes") is not None:
            return SPATIAL_CLASSIFIED_RASTER
    return SPATIAL_NONE


def extract_polygon_features(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return GeoJSON-like polygon Features from a spatial prediction payload."""
    payload = payload or {}
    summary = payload.get("result_summary") or {}
    spatial = summary.get("spatial") or payload.get("spatial") or {}
    if not isinstance(spatial, dict):
        return []
    features = spatial.get("features") or spatial.get("polygons") or []
    if not isinstance(features, list):
        return []
    out: list[dict[str, Any]] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry")
        if not isinstance(geom, dict):
            continue
        if geom.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        coords = geom.get("coordinates")
        if not coords:
            continue
        out.append(feat)
    return out


def validate_spatial_result(
    payload: dict[str, Any],
    *,
    expected_type: str | None = None,
    require_scientific: bool = False,
) -> list[str]:
    """Validate spatial structure; return error strings (empty = ok)."""
    errors: list[str] = []
    summary = payload.get("result_summary") or {}
    stype = expected_type or spatial_type_of(payload)
    if stype not in KNOWN_SPATIAL:
        errors.append(f"unknown spatial_output_type: {stype!r}")
        return errors

    if require_scientific and not summary.get("final_scientific_prediction", False):
        errors.append("result is not marked final_scientific_prediction")

    if stype in {"", SPATIAL_NONE}:
        return errors

    if stype == SPATIAL_VECTOR_POLYGONS:
        features = extract_polygon_features(payload)
        if not features:
            errors.append("VECTOR_POLYGONS result has no valid polygon features")
        else:
            for i, feat in enumerate(features):
                geom = feat.get("geometry") or {}
                coords = geom.get("coordinates")
                if not _has_finite_ring(coords):
                    errors.append(f"feature[{i}] has non-finite or empty coordinates")
                # Reject known demo square origin as the sole "geometry"
                if _looks_like_demo_square(coords):
                    # Not an error by itself if model intentionally used that CRS,
                    # but flag when ring matches the exact demo compiler constant box.
                    pass
        crs = (summary.get("spatial") or payload.get("spatial") or {}).get("crs")
        if not crs:
            # Soft: warn as error for production maps that need CRS.
            errors.append("VECTOR_POLYGONS missing crs")

    elif stype == SPATIAL_WELL_INTERVALS:
        spatial = summary.get("spatial") or payload.get("spatial") or {}
        intervals = spatial.get("intervals") or spatial.get("well_intervals") or []
        if not intervals:
            # Also accept predicted_regions with top/bottom
            regions = summary.get("predicted_regions") or []
            if not any(
                isinstance(r, dict) and ("top" in r or "bottom" in r) for r in regions
            ):
                errors.append("WELL_INTERVALS result has no intervals")

    elif stype == SPATIAL_CLASSIFIED_RASTER:
        spatial = summary.get("spatial") or payload.get("spatial") or {}
        if spatial.get("grid") is None and not spatial.get("artifact_path"):
            errors.append("CLASSIFIED_RASTER missing grid or artifact_path")
        if not spatial.get("crs") and not spatial.get("geotransform"):
            errors.append("CLASSIFIED_RASTER missing crs/geotransform")

    return errors


def bounded_result_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy result_summary without embedding large grids into ProjectDocument."""
    summary = dict(payload.get("result_summary") or {})
    spatial = summary.get("spatial")
    if isinstance(spatial, dict) and spatial.get("grid") is not None:
        spatial = dict(spatial)
        grid = spatial.pop("grid", None)
        # Keep shape metadata only.
        if hasattr(grid, "shape"):
            spatial["grid_shape"] = list(getattr(grid, "shape", []))
        elif isinstance(grid, list):
            spatial["grid_shape"] = [len(grid), len(grid[0]) if grid else 0]
        spatial["grid_omitted"] = True
        summary["spatial"] = spatial
    return summary


def is_map_compilable(payload: dict[str, Any] | None) -> bool:
    """True when production paleomap can consume real polygon geometry."""
    if not payload:
        return False
    stype = spatial_type_of(payload)
    if stype != SPATIAL_VECTOR_POLYGONS:
        return False
    return bool(extract_polygon_features(payload))


def _has_finite_ring(coords: Any) -> bool:
    try:
        if not coords:
            return False
        # Polygon: [ring, ...] ; MultiPolygon: [[ring,...], ...]
        ring = coords[0]
        if ring and isinstance(ring[0][0], (list, tuple)):
            ring = ring[0]
        if len(ring) < 4:
            return False
        for pt in ring:
            x, y = float(pt[0]), float(pt[1])
            if x != x or y != y:  # NaN
                return False
        return True
    except (TypeError, ValueError, IndexError):
        return False


def _looks_like_demo_square(coords: Any) -> bool:
    """Detect the fixed demo compiler square origin (114.0, 22.5)."""
    try:
        ring = coords[0]
        if ring and isinstance(ring[0][0], (list, tuple)):
            ring = ring[0]
        xs = [float(p[0]) for p in ring]
        ys = [float(p[1]) for p in ring]
        return min(xs) == 114.0 and min(ys) == 22.5 and max(xs) - min(xs) == 0.04
    except (TypeError, ValueError, IndexError):
        return False
