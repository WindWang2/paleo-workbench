"""Contour extraction pipeline using Marching Squares for Geological Mapping."""

from __future__ import annotations

import math
from typing import Any, Mapping

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


def generate_contour_layer(
    grid_result: FactorGridResult,
    levels: list[float] | None = None,
    interval: float | None = None,
    layer_id: str | None = None,
    name: str | None = None,
    style: dict[str, Any] | None = None,
) -> ContourMapLayer:
    """Extract smooth vector contour lines from FactorGridResult into a ContourMapLayer."""
    grid_z = grid_result.grid_z
    grid_x = grid_result.grid_x
    grid_y = grid_result.grid_y
    h, w = grid_z.shape
    xmin, ymin, xmax, ymax = grid_result.extent

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
        else:
            levels = calculate_nice_contour_levels(vmin, vmax, target_count=7)

    features: list[dict[str, Any]] = []

    try:
        from skimage.measure import find_contours

        # skimage find_contours expects finite 2D array
        filled_grid = np.nan_to_num(grid_z, nan=vmin)
        for level in levels:
            contours = find_contours(filled_grid, float(level))
            for c in contours:
                if len(c) < 2:
                    continue
                # c is (row, col) coordinates in grid index space
                coords = [
                    [
                        float(xmin + col * (xmax - xmin) / max(1, w - 1)),
                        float(ymin + row * (ymax - ymin) / max(1, h - 1)),
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
                            "factor": grid_result.factor_name,
                            "unit": grid_result.unit or "",
                        },
                    }
                )
    except ImportError:
        # Fallback bilinear grid cell interpolation
        dx = (xmax - xmin) / max(1, w - 1)
        dy = (ymax - ymin) / max(1, h - 1)
        for level in levels:
            for i in range(h - 1):
                for j in range(w - 1):
                    c00 = grid_z[i, j]
                    c10 = grid_z[i + 1, j]
                    c01 = grid_z[i, j + 1]
                    c11 = grid_z[i + 1, j + 1]
                    if not (np.isfinite(c00) and np.isfinite(c10) and np.isfinite(c01) and np.isfinite(c11)):
                        continue
                    min_c = min(c00, c10, c01, c11)
                    max_c = max(c00, c10, c01, c11)
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
                                    "coordinates": [[x0, (y0 + y1) / 2.0], [x1, (y0 + y1) / 2.0]],
                                },
                                "properties": {
                                    "level": float(level),
                                    "factor": grid_result.factor_name,
                                    "unit": grid_result.unit or "",
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
