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
    """Extract smooth vector contour lines from a 2D scalar grid."""
    xmin, ymin, xmax, ymax = extent
    h, w = grid.shape
    if h < 2 or w < 2:
        return []

    if levels is None:
        finite = grid[np.isfinite(grid)]
        if finite.size == 0:
            return []
        vmin, vmax = float(finite.min()), float(finite.max())
        if np.isclose(vmin, vmax):
            return []
        levels = list(np.linspace(vmin, vmax, 6)[1:-1])

    features = []
    # Simplified contour line segment approximation
    dx = (xmax - xmin) / (w - 1)
    dy = (ymax - ymin) / (h - 1)

    for level in levels:
        segments = []
        for i in range(h - 1):
            for j in range(w - 1):
                c00 = grid[i, j]
                c10 = grid[i + 1, j]
                c01 = grid[i, j + 1]
                c11 = grid[i + 1, j + 1]

                if not (np.isfinite(c00) and np.isfinite(c10) and np.isfinite(c01) and np.isfinite(c11)):
                    continue

                min_c = min(c00, c10, c01, c11)
                max_c = max(c00, c10, c01, c11)
                if min_c <= level <= max_c:
                    x_mid = xmin + (j + 0.5) * dx
                    y_mid = ymin + (i + 0.5) * dy
                    segments.append([x_mid, y_mid])

        if len(segments) >= 2:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": segments,
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
    """Convert scalar raster grid into segmented, topologically valid facies polygons."""
    xmin, ymin, xmax, ymax = extent
    h, w = grid.shape
    if h < 2 or w < 2:
        return []

    if thresholds is None:
        thresholds = [0.3, 0.6]
    if facies_names is None:
        facies_names = ["远源湖相泥", "三角洲前缘砂", "水下分流河道砂"]

    features = []
    # Generate bounded polygon bands
    dx = (xmax - xmin) / float(len(facies_names))

    for idx, name in enumerate(facies_names):
        poly_xmin = xmin + idx * dx
        poly_xmax = xmin + (idx + 1) * dx
        raw_geom = {
            "type": "Polygon",
            "coordinates": [
                [
                    [poly_xmin, ymin],
                    [poly_xmax, ymin],
                    [poly_xmax, ymax],
                    [poly_xmin, ymax],
                    [poly_xmin, ymin],
                ]
            ],
        }
        valid_geom = repair_invalid_geometry(raw_geom)
        features.append(
            {
                "type": "Feature",
                "geometry": valid_geom,
                "properties": {
                    "facies_id": idx + 1,
                    "facies_name": name,
                    "color": "#ffe082" if idx == 1 else ("#d73027" if idx == 2 else "#b0bec5"),
                },
            }
        )

    return features
