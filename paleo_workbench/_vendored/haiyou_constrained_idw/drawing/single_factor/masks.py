"""Mask builders shared by all single-factor surface methods."""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np

PointTuple = Tuple[float, float]


def build_data_hull_mask(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    well_xy: np.ndarray,
    buffer_meters: float = 0.0,
) -> Optional[np.ndarray]:
    """Mark grid cells inside the well-point convex hull (+ optional buffer)."""
    if well_xy is None or well_xy.size == 0 or len(grid_x) < 2 or len(grid_y) < 2:
        return None

    points = np.asarray(well_xy, dtype=float).reshape(-1, 2)
    if points.shape[0] < 3:
        return None

    hull = _convex_hull(points)
    if len(hull) < 3:
        return None

    if buffer_meters > 0.0:
        hull = _offset_convex_hull(hull, float(buffer_meters))

    rows = len(grid_y)
    cols = len(grid_x)
    mask = np.zeros((rows, cols), dtype=bool)
    for row in range(rows):
        y = float(grid_y[row])
        for col in range(cols):
            x = float(grid_x[col])
            mask[row, col] = _point_in_polygon((x, y), hull)
    return mask


def apply_mask_to_grid(grid: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
    """Return a copy of ``grid`` with cells outside ``mask`` set to NaN."""
    if mask is None or grid.size == 0:
        return np.array(grid, dtype=float, copy=True)
    result = np.array(grid, dtype=float, copy=True)
    result[~np.asarray(mask, dtype=bool)] = np.nan
    return result


def _convex_hull(points: np.ndarray) -> Tuple[PointTuple, ...]:
    unique = sorted({(float(x), float(y)) for x, y in points})
    if len(unique) <= 1:
        return tuple(unique)
    if len(unique) == 2:
        return tuple(unique)

    def cross(o: PointTuple, a: PointTuple, b: PointTuple) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[PointTuple] = []
    for pt in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], pt) <= 0.0:
            lower.pop()
        lower.append(pt)

    upper: list[PointTuple] = []
    for pt in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], pt) <= 0.0:
            upper.pop()
        upper.append(pt)

    return tuple(lower[:-1] + upper[:-1])


def _offset_convex_hull(hull: Sequence[PointTuple], distance: float) -> Tuple[PointTuple, ...]:
    if distance <= 0.0 or len(hull) < 3:
        return tuple(hull)
    cx = sum(pt[0] for pt in hull) / len(hull)
    cy = sum(pt[1] for pt in hull) / len(hull)
    expanded: list[PointTuple] = []
    for x, y in hull:
        dx = x - cx
        dy = y - cy
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            expanded.append((x, y))
            continue
        scale = (length + distance) / length
        expanded.append((cx + dx * scale, cy + dy * scale))
    return tuple(expanded)


def _point_in_polygon(pt: PointTuple, ring: Sequence[PointTuple]) -> bool:
    if len(ring) < 3:
        return False
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            denom = yj - yi
            if abs(denom) > 1e-30:
                x_intersect = (xj - xi) * (y - yi) / denom + xi
                if x < x_intersect:
                    inside = not inside
        j = i
    return inside


def estimate_hull_buffer_meters(map_diagonal: float, ratio: float = 0.02) -> float:
    return max(float(map_diagonal) * max(0.0, float(ratio)), 0.0)


def resolve_data_hull_buffer_meters(
    requested_buffer: float,
    search_radius: float,
    map_diagonal: float,
    *,
    limit_to_well_coverage: bool,
) -> float:
    """Resolve convex-hull buffer used to suppress far-field extrapolation."""
    explicit = float(requested_buffer)
    if explicit > 0.0:
        return explicit
    if not limit_to_well_coverage:
        return 0.0
    radius = max(float(search_radius), 1.0)
    return min(max(radius * 0.15, estimate_hull_buffer_meters(map_diagonal, 0.02)), radius * 0.5)


def build_bfs_reach_mask(
    seed_mask: np.ndarray,
    domain_mask: np.ndarray,
    max_distance_cells: float,
) -> np.ndarray:
    """Limit BFS gap-fill to cells within ``max_distance_cells`` of IDW seeds."""
    domain = np.asarray(domain_mask, dtype=bool)
    seeds = np.asarray(seed_mask, dtype=bool) & domain
    if max_distance_cells <= 0.0 or not bool(np.any(seeds)):
        return seeds
    try:
        from scipy.ndimage import distance_transform_edt
    except ImportError:
        return seeds
    dist = distance_transform_edt(~seeds)
    return domain & (dist <= float(max_distance_cells))


def resolve_bfs_reach_cells(
    search_radius: float,
    grid_step: float,
    grid_resolution: int,
    *,
    limit_to_well_coverage: bool,
    data_hull_active: bool,
) -> float:
    """How far BFS may propagate from IDW-interpolated cells (in grid cells)."""
    del search_radius, data_hull_active
    if limit_to_well_coverage:
        # Only bridge tiny raster holes for contour closure; never flood void pockets.
        return min(4.0, max(2.0, float(grid_resolution) * 0.02))
    return float(max(int(grid_resolution) * 4, 9999))


def resolve_contour_support_dilation_cells(grid_resolution: int, *, limit_to_well_coverage: bool) -> float:
    """Allow a thin halo around IDW cells for smooth contour extraction."""
    if limit_to_well_coverage:
        return min(3.0, max(2.0, float(grid_resolution) * 0.015))
    return min(6.0, max(3.0, float(grid_resolution) * 0.03))


def build_contour_support_mask(
    seed_mask: np.ndarray,
    domain_mask: np.ndarray,
    *,
    dilation_cells: float,
) -> np.ndarray:
    """Cells eligible for contouring: IDW support plus a tiny local halo."""
    return build_bfs_reach_mask(seed_mask, domain_mask, dilation_cells)


def build_contour_component_mask(
    seed_mask: np.ndarray,
    domain_mask: np.ndarray,
    dilation_cells: float,
) -> np.ndarray:
    """Dilate each IDW-connected component separately (no cross-void bridging)."""
    domain = np.asarray(domain_mask, dtype=bool)
    seeds = np.asarray(seed_mask, dtype=bool) & domain
    if dilation_cells <= 0.0 or not bool(np.any(seeds)):
        return seeds
    try:
        from scipy.ndimage import label
    except ImportError:
        return build_bfs_reach_mask(seeds, domain, dilation_cells)

    labeled, count = label(seeds)
    if count <= 0:
        return seeds
    result = np.zeros_like(seeds)
    for comp_id in range(1, int(count) + 1):
        component = labeled == comp_id
        result |= build_bfs_reach_mask(component, domain, dilation_cells)
    return result


def resolve_contour_component_dilation_cells(
    grid_resolution: int,
    *,
    limit_to_well_coverage: bool,
) -> float:
    """Dilation used only for contour-surface continuity inside IDW components.

    Kept moderate so extraction stays near wells (cleaner nested isolines) and
    does not flood empty map limbs with open scrap contours.
    """
    if limit_to_well_coverage:
        return min(24.0, max(12.0, float(grid_resolution) * 0.09))
    # Even when the display trend extends to the boundary, contour extraction
    # still uses this component halo around IDW seeds only.
    return min(30.0, max(14.0, float(grid_resolution) * 0.1))


def resolve_contour_hole_fill_max_cells(
    grid_resolution: int,
    dilation_cells: float,
) -> int:
    """Maximum raster hole size (cells) eligible for contour-surface gap fill."""
    span = max(6.0, float(dilation_cells) * 2.5)
    cap = max(128, int(float(grid_resolution) * float(grid_resolution) * 0.03))
    return int(min(span * span, cap))


def build_contour_hole_fill_mask(
    component_mask: np.ndarray,
    grid: np.ndarray,
    max_hole_cells: int,
) -> np.ndarray:
    """Return only *small* NaN holes inside the contour component mask.

    Large interior void pockets (e.g. perimeter wells enclosing a no-data zone)
    are excluded so contour extraction can close micro-gaps near wells without
    flooding empty regions.
    """
    domain = np.asarray(component_mask, dtype=bool)
    finite = np.isfinite(np.asarray(grid, dtype=float))
    holes = domain & ~finite
    if not bool(holes.any()) or int(max_hole_cells) <= 0:
        return np.zeros_like(domain, dtype=bool)

    try:
        from scipy.ndimage import label
    except ImportError:
        return holes

    labeled, count = label(holes)
    if count <= 0:
        return np.zeros_like(domain, dtype=bool)

    small_holes = np.zeros_like(holes)
    limit = int(max_hole_cells)
    for comp_id in range(1, int(count) + 1):
        component = labeled == comp_id
        if int(component.sum()) <= limit:
            small_holes |= component
    return small_holes