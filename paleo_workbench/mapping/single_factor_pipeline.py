"""Single-Factor Pipeline: Converts scalar grids to vector contours and paleofacies polygons."""

from __future__ import annotations

import math
from typing import Any
import numpy as np

from paleo_workbench.mapping.topology import repair_invalid_geometry


def extract_grid_contours(
    grid: np.ndarray,
    extent: tuple[float, float, float, float],
    levels: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Extract smooth vector contour lines from a 2D scalar grid using Marching Squares."""
    xmin, ymin, xmax, ymax = extent
    h, w = grid.shape
    if h < 2 or w < 2:
        return []

    finite = grid[np.isfinite(grid)]
    if finite.size == 0:
        return []
    vmin, vmax = float(finite.min()), float(finite.max())
    if np.isclose(vmin, vmax):
        return []

    if levels is None:
        levels = list(np.linspace(vmin, vmax, 6)[1:-1])

    features = []
    
    # Try skimage find_contours (robust Marching Squares)
    try:
        from skimage.measure import find_contours
        for level in levels:
            contours = find_contours(grid, float(level))
            for c in contours:
                if len(c) < 2:
                    continue
                # c is (row, col) coordinates
                coords = [
                    [
                        float(xmin + col * (xmax - xmin) / (w - 1)),
                        float(ymin + row * (ymax - ymin) / (h - 1)),
                    ]
                    for row, col in c
                ]
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": coords,
                        },
                        "properties": {
                            "level": float(level),
                            "kind": "contour",
                        },
                    }
                )
    except ImportError:
        # Fallback cell-by-cell line segment collector
        dx = (xmax - xmin) / (w - 1)
        dy = (ymax - ymin) / (h - 1)
        for level in levels:
            for i in range(h - 1):
                for j in range(w - 1):
                    c00 = grid[i, j]
                    c10 = grid[i + 1, j]
                    c01 = grid[i, j + 1]
                    c11 = grid[i + 1, j + 1]
                    if not (np.isfinite(c00) and np.isfinite(c10) and np.isfinite(c01) and np.isfinite(c11)):
                        continue
                    min_c, max_c = min(c00, c10, c01, c11), max(c00, c10, c01, c11)
                    if min_c <= level <= max_c:
                        x0 = xmin + j * dx
                        x1 = xmin + (j + 1) * dx
                        y0 = ymin + i * dy
                        y1 = ymin + (i + 1) * dy
                        features.append(
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "LineString",
                                    "coordinates": [[x0, (y0 + y1) / 2], [x1, (y0 + y1) / 2]],
                                },
                                "properties": {
                                    "level": float(level),
                                    "kind": "contour",
                                },
                            }
                        )

    return features


def extract_facies_polygons(
    grid: np.ndarray,
    extent: tuple[float, float, float, float],
    thresholds: list[float] | None = None,
    facies_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Convert scalar raster grid into segmented, topologically valid facies polygons based on raster thresholds."""
    xmin, ymin, xmax, ymax = extent
    h, w = grid.shape
    if h < 2 or w < 2:
        return []

    if thresholds is None:
        finite = grid[np.isfinite(grid)]
        if finite.size > 0:
            vmin, vmax = float(finite.min()), float(finite.max())
            thresholds = [vmin + (vmax - vmin) * 0.33, vmin + (vmax - vmin) * 0.66]
        else:
            thresholds = [0.3, 0.6]

    if facies_names is None:
        facies_names = ["远源湖相泥", "三角洲前缘砂", "水下分流河道砂"]

    # Classify raster cells into facies classes: 0, 1, ..., len(facies_names)-1
    class_grid = np.zeros((h, w), dtype=np.int16)
    for idx, th in enumerate(thresholds):
        class_grid[grid >= th] = min(idx + 1, len(facies_names) - 1)

    features = []

    # Palette
    default_colors = ["#b0bec5", "#ffe082", "#d73027", "#81c784", "#4fc3f7", "#ba68c8"]

    try:
        import rasterio.features
        import rasterio.transform

        # rasterio coordinates origin is top-left (xmin, ymax) with positive dx, negative dy
        transform = rasterio.transform.from_bounds(xmin, ymin, xmax, ymax, w, h)
        shapes = rasterio.features.shapes(np.flipud(class_grid), transform=transform)

        for geom, class_val in shapes:
            c_idx = int(class_val)
            if c_idx < 0 or c_idx >= len(facies_names):
                continue
            name = facies_names[c_idx]
            color = default_colors[c_idx % len(default_colors)]
            valid_geom = repair_invalid_geometry(geom)
            if not valid_geom or valid_geom.get("type") is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": valid_geom,
                    "properties": {
                        "facies_id": c_idx + 1,
                        "facies_name": name,
                        "color": color,
                    },
                }
            )
    except ImportError:
        # Fallback grid cell box collector
        dx = (xmax - xmin) / float(w)
        dy = (ymax - ymin) / float(h)
        for i in range(h):
            for j in range(w):
                c_idx = int(class_grid[i, j])
                name = facies_names[c_idx]
                color = default_colors[c_idx % len(default_colors)]
                x0, x1 = xmin + j * dx, xmin + (j + 1) * dx
                y0, y1 = ymin + i * dy, ymin + (i + 1) * dy
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
                        },
                        "properties": {
                            "facies_id": c_idx + 1,
                            "facies_name": name,
                            "color": color,
                        },
                    }
                )

    return features
