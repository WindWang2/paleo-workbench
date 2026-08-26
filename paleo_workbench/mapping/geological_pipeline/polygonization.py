"""Raster classification and polygonization into geological facies/zone GIS layers."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from paleo_workbench.mapping.layers import PolygonMapLayer
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


def _point_in_ring(x: float, y: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray casting point in polygon test."""
    inside = False
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1):
            inside = not inside
    return inside


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
) -> list[dict[str, Any]]:
    """Trace cell boundaries of target_class and form valid GeoJSON Polygon / MultiPolygon geometries."""
    h, w = class_grid.shape
    xmin, ymin, xmax, ymax = extent
    dx = (xmax - xmin) / float(max(1, w))
    dy = (ymax - ymin) / float(max(1, h))

    mask = (class_grid == target_class) & np.isfinite(grid_z)
    if not np.any(mask):
        return []

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
        return []

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
        return []

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

    # Sort exterior rings ascending so innermost containing island matches first
    exterior_rings.sort(key=lambda ring: calculate_shoelace_area(ring))

    poly_groups: list[dict[str, Any]] = []
    for ext in exterior_rings:
        poly_groups.append({"exterior": ext, "holes": []})

    for hole in holes:
        test_pt = hole[0]
        matched = False
        for pg in poly_groups:
            if _point_in_ring(test_pt[0], test_pt[1], pg["exterior"]):
                pg["holes"].append(hole)
                matched = True
                break
        if not matched and poly_groups:
            poly_groups[0]["holes"].append(hole)

    geoms: list[dict[str, Any]] = []
    for pg in poly_groups:
        coords = [pg["exterior"]] + pg["holes"]
        geom = {"type": "Polygon", "coordinates": coords}
        repaired = repair_invalid_geometry(geom)
        geoms.append(repaired)

    return geoms


def generate_facies_polygon_layer(
    grid_result: FactorGridResult,
    thresholds: list[float] | None = None,
    facies_names: list[str] | None = None,
    colors: list[str] | None = None,
    layer_id: str | None = None,
    name: str | None = None,
) -> PolygonMapLayer:
    """Classify scalar grid and polygonize into topologically valid Facies / Zone Polygon layer."""
    grid_z = grid_result.grid_z
    h, w = grid_z.shape
    xmin, ymin, xmax, ymax = grid_result.extent

    finite = grid_z[np.isfinite(grid_z)]
    if finite.size == 0 or h < 1 or w < 1:
        return PolygonMapLayer(
            id=layer_id or f"facies_{grid_result.factor_name}",
            name=name or f"{grid_result.factor_name} 相带多边形",
            extent=grid_result.extent,
            crs=grid_result.crs or "EPSG:4326",
            features=(),
        )

    vmin, vmax = float(finite.min()), float(finite.max())

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

    for c_idx in range(len(facies_names)):
        c_mask = (class_grid == c_idx) & np.isfinite(grid_z)
        if not np.any(c_mask):
            continue

        facies_name = facies_names[c_idx]
        color = colors[c_idx % len(colors)]
        mean_val = float(np.mean(grid_z[c_mask]))

        geoms = _polygonize_raster_boundaries(
            class_grid, grid_z, grid_result.extent, target_class=c_idx
        )

        for geom in geoms:
            geom_area = _compute_geometry_area(geom)
            area_pct = (geom_area / total_grid_area) * 100.0

            features.append(
                {
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "facies_id": c_idx + 1,
                        "facies_name": facies_name,
                        "facies": facies_name,
                        "color": color,
                        "area": round(geom_area, 4),
                        "area_percent": round(area_pct, 4),
                        "mean_value": round(mean_val, 4),
                    },
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
        crs=grid_result.crs or "EPSG:4326",
        features=tuple(features),
        categories=[{"name": fn, "color": col} for fn, col in zip(facies_names, colors)],
        style=style,
    )
