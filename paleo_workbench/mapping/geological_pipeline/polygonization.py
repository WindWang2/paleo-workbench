"""Raster classification and polygonization into geological facies/zone GIS layers."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from paleo_workbench.mapping.layers import PolygonMapLayer
from paleo_workbench.mapping.geological_pipeline.geometry_units import (
    area_unit_label,
    is_geographic_crs,
    ring_area_with_unit,
)
from paleo_workbench.mapping.topology import repair_invalid_geometry
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def calculate_shoelace_area(ring: Sequence[Sequence[float]]) -> float:
    """Calculate planar area of a coordinate ring using the Shoelace formula."""
    n = len(ring)
    if n < 3:
        return 0.0
    area2 = 0.0
    for i in range(n - 1):
        area2 += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return 0.5 * abs(area2)


def calculate_signed_area(ring: Sequence[Sequence[float]]) -> float:
    """Calculate signed planar area (positive for CCW, negative for CW)."""
    n = len(ring)
    if n < 3:
        return 0.0
    area2 = 0.0
    for i in range(n - 1):
        area2 += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return 0.5 * area2


def _ring_centroid(ring: Sequence[Sequence[float]]) -> tuple[float, float]:
    """Area centroid of a ring (shoelace); falls back to the first vertex for
    degenerate rings so containment testing always has a deterministic point."""
    n = len(ring)
    if n == 0:
        return (0.0, 0.0)
    area2 = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n - 1):
        cross = ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
        area2 += cross
        cx += (ring[i][0] + ring[i + 1][0]) * cross
        cy += (ring[i][1] + ring[i + 1][1]) * cross
    if math.isclose(area2, 0.0, abs_tol=1e-12):
        return (float(ring[0][0]), float(ring[0][1]))
    return (cx / (3.0 * area2), cy / (3.0 * area2))


def _point_in_ring(x: float, y: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray casting point in polygon test (shared kernel, v7 §4)."""
    from paleo_workbench.mapping.geometry_planar import point_in_ring_scalar

    return point_in_ring_scalar(x, y, ring)


def simplify_collinear_ring(ring: list[list[float]]) -> list[list[float]]:
    """Remove redundant collinear vertices along straight horizontal/vertical grid steps."""
    if len(ring) <= 4:
        return ring
    pts = ring[:-1]
    n = len(pts)
    keep: list[list[float]] = []
    for i in range(n):
        p_prev = pts[(i - 1) % n]
        p_curr = pts[i]
        p_next = pts[(i + 1) % n]
        dx1, dy1 = p_curr[0] - p_prev[0], p_curr[1] - p_prev[1]
        dx2, dy2 = p_next[0] - p_curr[0], p_next[1] - p_curr[1]
        is_collinear = (
            (math.isclose(dy1, 0.0, abs_tol=1e-9) and math.isclose(dy2, 0.0, abs_tol=1e-9) and dx1 * dx2 > 0)
            or (math.isclose(dx1, 0.0, abs_tol=1e-9) and math.isclose(dx2, 0.0, abs_tol=1e-9) and dy1 * dy2 > 0)
        )
        if not is_collinear:
            keep.append(p_curr)

    if len(keep) >= 3:
        keep.append([keep[0][0], keep[0][1]])
        return keep
    return ring


def _compute_geometry_area(geom: dict[str, Any]) -> float:
    """Compute total planar area for Polygon or MultiPolygon."""
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])
    if gtype == "Polygon":
        if not coords:
            return 0.0
        ext_area = calculate_shoelace_area(coords[0])
        holes_area = sum(calculate_shoelace_area(h) for h in coords[1:])
        return max(0.0, ext_area - holes_area)
    elif gtype == "MultiPolygon":
        total = 0.0
        for poly_coords in coords:
            if not poly_coords:
                continue
            ext = calculate_shoelace_area(poly_coords[0])
            holes = sum(calculate_shoelace_area(h) for h in poly_coords[1:])
            total += max(0.0, ext - holes)
        return total
    return 0.0


def _polygonize_raster_boundaries(
    class_grid: np.ndarray,
    grid_z: np.ndarray,
    extent: tuple[float, float, float, float],
    target_class: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Trace cell boundaries of target_class and form valid GeoJSON Polygon / MultiPolygon geometries.

    Hole assignment is deterministic: each hole ring is matched, by its area
    centroid, to the *smallest* exterior containing it (exteriors are iterated
    smallest-area first). An unmatched hole is promoted to an exterior island
    and counted — it is never silently stapled onto an unrelated polygon.
    """
    qc: dict[str, int] = {"holes_promoted_to_exterior": 0}
    h, w = class_grid.shape
    xmin, ymin, xmax, ymax = extent
    dx = (xmax - xmin) / float(max(1, w))
    dy = (ymax - ymin) / float(max(1, h))

    mask = (class_grid == target_class) & np.isfinite(grid_z)
    if not np.any(mask):
        return [], qc

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []

    for i in range(h):
        y0 = ymin + i * dy
        y1 = ymin + (i + 1) * dy
        for j in range(w):
            if not mask[i, j]:
                continue
            x0 = xmin + j * dx
            x1 = xmin + (j + 1) * dx

            if i == 0 or not mask[i - 1, j]:
                segments.append(((x0, y0), (x1, y0)))
            if j == w - 1 or not mask[i, j + 1]:
                segments.append(((x1, y0), (x1, y1)))
            if i == h - 1 or not mask[i + 1, j]:
                segments.append(((x1, y1), (x0, y1)))
            if j == 0 or not mask[i, j - 1]:
                segments.append(((x0, y1), (x0, y0)))

    if not segments:
        return [], qc

    def pt_key(pt: tuple[float, float]) -> tuple[float, float]:
        return (round(pt[0], 6), round(pt[1], 6))

    adj: dict[tuple[float, float], list[tuple[tuple[float, float], int]]] = {}
    edges_used = [False] * len(segments)

    for edge_id, (pA, pB) in enumerate(segments):
        kA = pt_key(pA)
        kB = pt_key(pB)
        if kA == kB:
            continue
        adj.setdefault(kA, []).append((pB, edge_id))

    loops: list[list[list[float]]] = []

    for edge_id, (pA, pB) in enumerate(segments):
        if edges_used[edge_id]:
            continue
        kA = pt_key(pA)
        chain = [[pA[0], pA[1]], [pB[0], pB[1]]]
        edges_used[edge_id] = True
        curr_k = pt_key(pB)

        while True:
            available = [item for item in adj.get(curr_k, []) if not edges_used[item[1]]]
            if not available:
                break
            next_pt, e_idx = available[0]
            edges_used[e_idx] = True
            chain.append([next_pt[0], next_pt[1]])
            curr_k = pt_key(next_pt)
            if curr_k == kA:
                break

        if len(chain) >= 4 and math.isclose(chain[0][0], chain[-1][0], abs_tol=1e-5) and math.isclose(chain[0][1], chain[-1][1], abs_tol=1e-5):
            simplified = simplify_collinear_ring(chain)
            if len(simplified) >= 4:
                loops.append(simplified)

    if not loops:
        return [], qc

    exterior_rings: list[list[list[float]]] = []
    holes: list[list[list[float]]] = []

    for loop in loops:
        signed_a = calculate_signed_area(loop)
        if math.isclose(signed_a, 0.0, abs_tol=1e-12):
            continue
        if signed_a > 0:
            exterior_rings.append(loop)
        else:
            holes.append(loop)

    if not exterior_rings:
        for h_loop in holes:
            exterior_rings.append(list(reversed(h_loop)))
        holes = []

    # Sort exterior rings ascending so ties resolve to the innermost
    # (smallest) containing exterior — deterministic nesting assignment.
    exterior_rings.sort(key=lambda ring: calculate_shoelace_area(ring))

    poly_groups: list[dict[str, Any]] = []
    for ext in exterior_rings:
        poly_groups.append({"exterior": ext, "holes": []})

    for hole in holes:
        # Majority vote over hole-ring vertices: a hole belongs to the
        # smallest exterior containing most of its vertices. Vertex tests
        # (not centroid) are required here — for concentric rings the hole
        # ring's centroid falls INSIDE the inner island, which would attach
        # the hole to the wrong polygon.
        best_idx = -1
        best_votes = 0
        for g_idx, pg in enumerate(poly_groups):
            votes = sum(
                1
                for pt in hole[:-1]
                if _point_in_ring(pt[0], pt[1], pg["exterior"])
            )
            if votes > best_votes:
                best_votes = votes
                best_idx = g_idx
        if best_idx >= 0 and best_votes > 0:
            poly_groups[best_idx]["holes"].append(hole)
        else:
            # No exterior contains this ring: promote it to an island instead
            # of attaching it to an unrelated polygon.
            promoted = list(reversed(hole))
            exterior_rings.append(promoted)
            poly_groups.append({"exterior": promoted, "holes": []})
            qc["holes_promoted_to_exterior"] += 1

    geoms: list[dict[str, Any]] = []
    for pg in poly_groups:
        coords = [pg["exterior"]] + pg["holes"]
        geom = {"type": "Polygon", "coordinates": coords}
        repaired = repair_invalid_geometry(geom)
        geoms.append(repaired)

    return geoms, qc


def _mapping_to_lists(obj: Any) -> Any:
    """Recursively convert shapely ``mapping`` output (tuples) to plain lists
    so the geometry round-trips through JSON and list-based consumers."""
    if isinstance(obj, (list, tuple)):
        return [_mapping_to_lists(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _mapping_to_lists(value) for key, value in obj.items()}
    return obj


def _clip_polygon_to_ring(
    geom: dict[str, Any], clip_ring: Sequence[Sequence[float]]
) -> dict[str, Any] | None:
    """Intersect a GeoJSON polygon with a user domain ring (shared kernel,
    v7 §4)."""
    from paleo_workbench.mapping.geometry_operations import clip_polygon_to_ring

    return clip_polygon_to_ring(geom, clip_ring)


def _filter_small_polygons(
    geoms: list[dict[str, Any]], min_area: float
) -> tuple[list[dict[str, Any]], int]:
    """Drop polygons whose net area is below *min_area*; return kept + dropped count.

    The caller records the count in layer QC — a scientific result is only
    removed by an explicit, visible threshold.
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for geom in geoms:
        if _compute_geometry_area(geom) < min_area:
            dropped += 1
        else:
            kept.append(geom)
    return kept, dropped


def generate_facies_polygon_layer(
    grid_result: FactorGridResult,
    thresholds: list[float] | None = None,
    facies_names: list[str] | None = None,
    colors: list[str] | None = None,
    layer_id: str | None = None,
    name: str | None = None,
    min_area: float | None = None,
    clip_ring: Sequence[Sequence[float]] | None = None,
) -> PolygonMapLayer:
    """Classify scalar grid and polygonize into topologically valid Facies / Zone Polygon layer.

    *min_area* removes polygons below an explicit area threshold (the drop
    count is reported in layer metadata ``polygon_qc`` — nothing is removed
    silently). *clip_ring* restricts output polygons to a user domain; the
    grid-level equivalent is ``InterpolationOptions.boundary`` (D6), and both
    must describe the same domain for consistent maps.
    """
    grid_z = grid_result.grid_z
    h, w = grid_z.shape
    xmin, ymin, xmax, ymax = grid_result.extent

    finite = grid_z[np.isfinite(grid_z)]
    if finite.size == 0 or h < 1 or w < 1:
        return PolygonMapLayer(
            id=layer_id or f"facies_{grid_result.factor_name}",
            name=name or f"{grid_result.factor_name} 相带多边形",
            extent=grid_result.extent,
            crs=grid_result.crs or "",
            features=(),
            metadata={"polygon_qc": {
                "small_polygon_threshold": min_area,
                "small_polygons_dropped": 0,
                "clipped_to_domain": 0,
                "empty_after_clip": 0,
                "holes_promoted_to_exterior": 0,
            }},
        )

    vmin, vmax = float(finite.min()), float(finite.max())

    thresholds_is_explicit = thresholds is not None
    if thresholds is None:
        if math.isclose(vmin, vmax):
            thresholds = [vmin]
        else:
            thresholds = [vmin + (vmax - vmin) * 0.333, vmin + (vmax - vmin) * 0.666]
    else:
        thresholds = sorted(set(float(t) for t in thresholds))

    if facies_names is None:
        if len(thresholds) == 2:
            facies_names = ["低值相带", "中值相带", "高值相带"]
        elif len(thresholds) == 1 and math.isclose(vmin, vmax):
            facies_names = ["均一相带"]
        else:
            facies_names = [f"相带 {i+1}" for i in range(len(thresholds) + 1)]

    if colors is None:
        default_palette = ["#b0bec5", "#ffe082", "#d73027", "#81c784", "#4fc3f7", "#ba68c8"]
        colors = [default_palette[i % len(default_palette)] for i in range(len(facies_names))]

    # Classify grid cells: 0, 1, ..., len(facies_names)-1
    class_grid = np.zeros((h, w), dtype=np.int16)
    for idx, th in enumerate(thresholds):
        class_grid[grid_z >= th] = min(idx + 1, len(facies_names) - 1)

    features: list[dict[str, Any]] = []
    total_grid_area = max(1e-12, (xmax - xmin) * (ymax - ymin))
    polygon_qc: dict[str, Any] = {
        "small_polygon_threshold": min_area,
        "small_polygons_dropped": 0,
        "clipped_to_domain": 0,
        "empty_after_clip": 0,
        # V6 §15: the classification thresholds ARE part of the product —
        # data-derived defaults (⅓/⅔ span) were previously invisible to QC,
        # breaking reproducibility of the default path. The nodata extent is
        # reported too (holes are honest, but their size must be visible).
        "thresholds": [float(t) for t in thresholds],
        "thresholds_source": "explicit" if thresholds_is_explicit else "data_derived_default",
        "nodata_cells": int((~np.isfinite(grid_z)).sum()),
        "total_cells": int(grid_z.size),
        "area_unit": area_unit_label(grid_result.crs),
    }
    area_warnings: list[str] = []
    if is_geographic_crs(grid_result.crs):
        area_warnings.append(
            "geographic CRS: per-feature areas are local-scale approximations"
        )
    if not str(grid_result.crs or "").strip():
        area_warnings.append("CRS undeclared: area unit unknown (not metres)")
    if area_warnings:
        polygon_qc["area_warnings"] = area_warnings

    for c_idx in range(len(facies_names)):
        c_mask = (class_grid == c_idx) & np.isfinite(grid_z)
        if not np.any(c_mask):
            continue

        facies_name = facies_names[c_idx]
        color = colors[c_idx % len(colors)]
        mean_val = float(np.mean(grid_z[c_mask]))

        geoms, hole_qc = _polygonize_raster_boundaries(
            class_grid, grid_z, grid_result.extent, target_class=c_idx
        )
        polygon_qc["holes_promoted_to_exterior"] = (
            polygon_qc.get("holes_promoted_to_exterior", 0)
            + hole_qc["holes_promoted_to_exterior"]
        )
        if clip_ring is not None:
            clipped_geoms: list[dict[str, Any]] = []
            for geom in geoms:
                clipped = _clip_polygon_to_ring(geom, clip_ring)
                if clipped is None:
                    polygon_qc["empty_after_clip"] += 1
                else:
                    clipped_geoms.append(clipped)
                    polygon_qc["clipped_to_domain"] += 1
            geoms = clipped_geoms
        if min_area is not None and min_area > 0:
            geoms, dropped = _filter_small_polygons(geoms, float(min_area))
            polygon_qc["small_polygons_dropped"] += dropped

        for geom in geoms:
            # V6 §15 (P0-10): ``area`` stays in the CRS's own axis units
            # (conservation checks compare like with like), but it can no
            # longer be MISTAKEN for m²: every feature carries ``area_unit``,
            # and under a geographic CRS an explicitly-labelled local-scale
            # ``area_approx_m2`` is provided alongside (square degrees are
            # never presented as if physically meaningful).
            raw_area = _compute_geometry_area(geom)
            geom_area, area_unit, area_warning = ring_area_with_unit(
                geom["coordinates"][0], grid_result.crs
            )
            if area_warning and area_warning not in polygon_qc.get("area_warnings", []):
                polygon_qc.setdefault("area_warnings", []).append(area_warning)
            area_pct = (raw_area / total_grid_area) * 100.0

            properties: dict[str, Any] = {
                "facies_id": c_idx + 1,
                "facies_name": facies_name,
                "facies": facies_name,
                "color": color,
                "area": round(raw_area, 4),
                "area_unit": area_unit_label(grid_result.crs),
                "area_percent": round(area_pct, 4),
                "mean_value": round(mean_val, 4),
            }
            if is_geographic_crs(grid_result.crs):
                properties["area_approx_m2"] = round(geom_area, 4)

            features.append(
                {
                    "type": "Feature",
                    "geometry": geom,
                    "properties": properties,
                }
            )

    categories = [
        (facies_names[i], colors[i % len(colors)], facies_names[i])
        for i in range(len(facies_names))
    ]

    style = {
        "renderer": "categorized",
        "field": "facies_name",
        "fill": colors[0] if colors else "#b0bec5",
        "stroke": "#26364d",
        "stroke_width": 1.0,
        "categories": [list(c) for c in categories],
    }

    return PolygonMapLayer(
        id=layer_id or f"facies_{grid_result.factor_name}",
        name=name or f"{grid_result.factor_name} 相带",
        extent=grid_result.extent,
        crs=grid_result.crs or "",
        features=tuple(features),
        categories=[{"name": fn, "color": col} for fn, col in zip(facies_names, colors)],
        style=style,
        metadata={"polygon_qc": polygon_qc},
    )
