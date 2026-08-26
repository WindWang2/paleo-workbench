"""Contour extraction pipeline using Marching Squares for Geological Mapping."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from paleo_workbench.mapping.layers import ContourMapLayer
from paleo_workbench.mapping.map_styles import default_style_for
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def calculate_nice_contour_levels(
    vmin: float, vmax: float, target_count: int = 7
) -> list[float]:
    """Calculate pleasant, round contour levels within [vmin, vmax]."""
    if not math.isfinite(vmin) or not math.isfinite(vmax) or math.isclose(vmin, vmax):
        return []
    span = vmax - vmin
    raw_step = span / max(2, target_count)
    exp = math.floor(math.log10(raw_step))
    frac = raw_step / (10 ** exp)

    if frac < 1.5:
        step = 1.0 * (10 ** exp)
    elif frac < 3.5:
        step = 2.0 * (10 ** exp)
    elif frac < 7.5:
        step = 5.0 * (10 ** exp)
    else:
        step = 10.0 * (10 ** exp)

    start = math.ceil(vmin / step) * step
    levels = []
    curr = start
    while curr <= vmax:
        if curr >= vmin:
            levels.append(round(curr, 8))
        curr += step
    return levels


def calculate_quantile_contour_levels(
    grid_z: np.ndarray,
    quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
) -> list[float]:
    """Calculate quantile-based contour levels from valid grid values."""
    finite = grid_z[np.isfinite(grid_z)]
    if finite.size < 2:
        return []
    perc = [float(q) * 100.0 if q <= 1.0 else float(q) for q in quantiles]
    vals = np.nanpercentile(finite, perc)
    levels = sorted(set(round(float(v), 6) for v in vals))
    return levels


def calculate_polyline_length(coords: Sequence[Sequence[float]]) -> float:
    """Calculate total Euclidean length of a 2D polyline."""
    total = 0.0
    for i in range(len(coords) - 1):
        total += math.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1])
    return total


def douglas_peucker_2d(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """Simplify 2D polyline using Ramer-Douglas-Peucker algorithm with scalar 2D distance."""
    if len(points) <= 2 or tolerance <= 0.0:
        return points

    x0, y0 = points[0][0], points[0][1]
    x1, y1 = points[-1][0], points[-1][1]
    dx = x1 - x0
    dy = y1 - y0
    line_len = math.hypot(dx, dy)

    max_dist = -1.0
    index = -1

    for i in range(1, len(points) - 1):
        px, py = points[i][0], points[i][1]
        if line_len < 1e-12:
            d = math.hypot(px - x0, py - y0)
        else:
            d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / line_len
        if d > max_dist:
            max_dist = d
            index = i

    if max_dist > tolerance and index != -1:
        left = douglas_peucker_2d(points[: index + 1], tolerance)
        right = douglas_peucker_2d(points[index:], tolerance)
        return left[:-1] + right
    else:
        return [points[0], points[-1]]


def chaikin_smooth(points: list[list[float]], iterations: int = 1) -> list[list[float]]:
    """Smooth polyline using Chaikin's corner-cutting algorithm."""
    if len(points) < 3 or iterations <= 0:
        return points

    curr = points
    is_closed = math.isclose(curr[0][0], curr[-1][0], abs_tol=1e-5) and math.isclose(curr[0][1], curr[-1][1], abs_tol=1e-5)

    for _ in range(iterations):
        smoothed: list[list[float]] = []
        if is_closed:
            n = len(curr) - 1
            for i in range(n):
                p0 = curr[i]
                p1 = curr[(i + 1) % n]
                q = [0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]]
                r = [0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]]
                smoothed.extend([q, r])
            if smoothed:
                smoothed.append([smoothed[0][0], smoothed[0][1]])
        else:
            smoothed.append(curr[0])
            for i in range(len(curr) - 1):
                p0 = curr[i]
                p1 = curr[i + 1]
                q = [0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]]
                r = [0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]]
                smoothed.extend([q, r])
            smoothed.append(curr[-1])
        curr = smoothed
    return curr


def _stitch_segments(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    simplify_tol: float = 0.0,
    smooth_iterations: int = 0,
) -> list[list[list[float]]]:
    """Stitch unordered line segments into ordered continuous polylines."""
    if not segments:
        return []

    def pt_key(pt: tuple[float, float]) -> tuple[float, float]:
        return (round(pt[0], 6), round(pt[1], 6))

    adj: dict[tuple[float, float], list[tuple[tuple[float, float], tuple[float, float], int]]] = {}
    edges_used = [False] * len(segments)

    for edge_id, (pA, pB) in enumerate(segments):
        kA = pt_key(pA)
        kB = pt_key(pB)
        if kA == kB:
            continue
        adj.setdefault(kA, []).append((kB, pB, edge_id))
        adj.setdefault(kB, []).append((kA, pA, edge_id))

    polylines: list[list[list[float]]] = []

    # 1. Traverse starting from open endpoints (degree 1)
    for start_k, neighbors in list(adj.items()):
        unused_neighbors = [item for item in neighbors if not edges_used[item[2]]]
        if len(unused_neighbors) == 1:
            chain: list[list[float]] = []
            curr_k = start_k
            first_edge = unused_neighbors[0][2]
            p0, p1 = segments[first_edge]
            curr_pt = p0 if pt_key(p0) == start_k else p1
            chain.append([curr_pt[0], curr_pt[1]])

            while True:
                available = [item for item in adj.get(curr_k, []) if not edges_used[item[2]]]
                if not available:
                    break
                next_k, next_pt, edge_idx = available[0]
                edges_used[edge_idx] = True
                chain.append([next_pt[0], next_pt[1]])
                curr_k = next_k

            if len(chain) >= 2:
                polylines.append(chain)

    # 2. Traverse remaining loops (closed contours)
    for edge_id, (pA, pB) in enumerate(segments):
        if edges_used[edge_id]:
            continue
        kA = pt_key(pA)
        kB = pt_key(pB)
        if kA == kB:
            continue

        chain = [[pA[0], pA[1]], [pB[0], pB[1]]]
        edges_used[edge_id] = True
        curr_k = kB

        while True:
            available = [item for item in adj.get(curr_k, []) if not edges_used[item[2]]]
            if not available:
                break
            next_k, next_pt, e_idx = available[0]
            edges_used[e_idx] = True
            chain.append([next_pt[0], next_pt[1]])
            curr_k = next_k
            if curr_k == kA:
                break

        if len(chain) >= 2:
            polylines.append(chain)

    processed: list[list[list[float]]] = []
    for poly in polylines:
        if len(poly) < 2:
            continue
        if simplify_tol > 0.0:
            poly = douglas_peucker_2d(poly, simplify_tol)
        if smooth_iterations > 0 and len(poly) >= 3:
            poly = chaikin_smooth(poly, smooth_iterations)
        if len(poly) >= 2:
            processed.append(poly)

    return processed


def _marching_squares_pure_python(
    grid_z: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    level: float,
    *,
    simplify_tol: float = 0.0,
    smooth_iterations: int = 0,
) -> list[list[list[float]]]:
    """Pure-Python 16-case Marching Squares with linear edge interpolation and saddle disambiguation."""
    h, w = grid_z.shape
    if h < 2 or w < 2:
        return []

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []

    for i in range(h - 1):
        y0, y1 = float(grid_y[i]), float(grid_y[i + 1])
        for j in range(w - 1):
            x0, x1 = float(grid_x[j]), float(grid_x[j + 1])
            z00 = float(grid_z[i, j])
            z10 = float(grid_z[i, j + 1])
            z11 = float(grid_z[i + 1, j + 1])
            z01 = float(grid_z[i + 1, j])

            if not (math.isfinite(z00) and math.isfinite(z10) and math.isfinite(z11) and math.isfinite(z01)):
                continue

            min_z = min(z00, z10, z11, z01)
            max_z = max(z00, z10, z11, z01)
            if level < min_z or level > max_z:
                continue

            b0 = 1 if z00 >= level else 0
            b1 = 1 if z10 >= level else 0
            b2 = 1 if z11 >= level else 0
            b3 = 1 if z01 >= level else 0
            case_idx = b0 | (b1 << 1) | (b2 << 2) | (b3 << 3)

            if case_idx == 0 or case_idx == 15:
                continue

            # Edge 0 (bottom): z00 -> z10
            t0 = (level - z00) / (z10 - z00) if not math.isclose(z10, z00) else 0.5
            p0 = (x0 + t0 * (x1 - x0), y0)

            # Edge 1 (right): z10 -> z11
            t1 = (level - z10) / (z11 - z10) if not math.isclose(z11, z10) else 0.5
            p1 = (x1, y0 + t1 * (y1 - y0))

            # Edge 2 (top): z01 -> z11
            t2 = (level - z01) / (z11 - z01) if not math.isclose(z11, z01) else 0.5
            p2 = (x0 + t2 * (x1 - x0), y1)

            # Edge 3 (left): z00 -> z01
            t3 = (level - z00) / (z01 - z00) if not math.isclose(z01, z00) else 0.5
            p3 = (x0, y0 + t3 * (y1 - y0))

            v_center = (z00 + z10 + z11 + z01) / 4.0

            if case_idx in (1, 14):
                segments.append((p3, p0))
            elif case_idx in (2, 13):
                segments.append((p0, p1))
            elif case_idx in (3, 12):
                segments.append((p3, p1))
            elif case_idx in (4, 11):
                segments.append((p1, p2))
            elif case_idx == 5:
                if v_center >= level:
                    segments.append((p3, p2))
                    segments.append((p0, p1))
                else:
                    segments.append((p3, p0))
                    segments.append((p1, p2))
            elif case_idx in (6, 9):
                segments.append((p0, p2))
            elif case_idx in (7, 8):
                segments.append((p2, p3))
            elif case_idx == 10:
                if v_center >= level:
                    segments.append((p3, p0))
                    segments.append((p1, p2))
                else:
                    segments.append((p0, p1))
                    segments.append((p2, p3))

    if not segments:
        return []

    return _stitch_segments(segments, simplify_tol=simplify_tol, smooth_iterations=smooth_iterations)


def generate_contour_layer(
    grid_result: FactorGridResult,
    levels: list[float] | None = None,
    interval: float | None = None,
    leveling_mode: str = "nice",
    simplify_tolerance: float = 0.0,
    smooth_iterations: int = 0,
    layer_id: str | None = None,
    name: str | None = None,
    style: dict[str, Any] | None = None,
) -> ContourMapLayer:
    """Extract smooth vector contour lines from FactorGridResult into a ContourMapLayer."""
    grid_z = grid_result.grid_z
    grid_x = grid_result.grid_x
    grid_y = grid_result.grid_y
    h, w = grid_z.shape

    finite = grid_z[np.isfinite(grid_z)]
    if finite.size < 2:
        return ContourMapLayer(
            id=layer_id or f"contour_{grid_result.factor_name}",
            name=name or f"{grid_result.factor_name} 等值线",
            extent=grid_result.extent,
            crs=grid_result.crs or "EPSG:4326",
            features=(),
            levels=[],
        )

    vmin, vmax = float(finite.min()), float(finite.max())

    if levels is None:
        if interval is not None and interval > 0:
            start = math.ceil(vmin / interval) * interval
            levels = []
            curr = start
            while curr <= vmax:
                levels.append(round(curr, 6))
                curr += interval
        elif leveling_mode == "quantile":
            levels = calculate_quantile_contour_levels(grid_z)
        else:
            levels = calculate_nice_contour_levels(vmin, vmax, target_count=7)

    features: list[dict[str, Any]] = []
    unit_str = grid_result.unit or ""

    for idx, level in enumerate(levels):
        flevel = float(level)
        polylines = _marching_squares_pure_python(
            grid_z, grid_x, grid_y, flevel,
            simplify_tol=simplify_tolerance,
            smooth_iterations=smooth_iterations,
        )

        is_index = False
        if interval is not None and interval > 0:
            is_index = math.isclose(flevel % (5.0 * interval), 0.0, abs_tol=1e-5) or math.isclose(flevel % (5.0 * interval), 5.0 * interval, abs_tol=1e-5)
        else:
            is_index = (idx % 5 == 0)

        label_text = f"{flevel:g} {unit_str}".strip() if unit_str else f"{flevel:g}"

        for poly in polylines:
            if len(poly) < 2:
                continue
            poly_len = calculate_polyline_length(poly)
            is_closed = math.isclose(poly[0][0], poly[-1][0], abs_tol=1e-5) and math.isclose(poly[0][1], poly[-1][1], abs_tol=1e-5)

            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": poly,
                    },
                    "properties": {
                        "level": flevel,
                        "label_text": label_text,
                        "is_index_contour": is_index,
                        "length": poly_len,
                        "is_closed": is_closed,
                        "factor": grid_result.factor_name,
                        "unit": unit_str,
                    },
                }
            )

    layer_style = dict(style) if style is not None else default_style_for("contour").to_dict()

    return ContourMapLayer(
        id=layer_id or f"contour_{grid_result.factor_name}",
        name=name or f"{grid_result.factor_name} 等值线",
        extent=grid_result.extent,
        crs=grid_result.crs or "EPSG:4326",
        features=tuple(features),
        levels=levels,
        contour_interval=interval,
        style=layer_style,
    )

