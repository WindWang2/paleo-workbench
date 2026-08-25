"""Raster classification and polygonization into geological facies/zone GIS layers."""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
from shapely.geometry import mapping, shape
from shapely.validation import make_valid

from paleo_workbench.mapping.layers import PolygonMapLayer
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


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
    if finite.size == 0:
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

    if facies_names is None:
        if len(thresholds) == 2:
            facies_names = ["低值相带", "中值相带", "高值相带"]
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

    try:
        import rasterio.features
        import rasterio.transform

        transform = rasterio.transform.from_bounds(xmin, ymin, xmax, ymax, w, h)
        shapes = rasterio.features.shapes(np.flipud(class_grid), transform=transform)

        for geom, class_val in shapes:
            c_idx = int(class_val)
            if c_idx < 0 or c_idx >= len(facies_names):
                continue
            facies_name = facies_names[c_idx]
            color = colors[c_idx % len(colors)]

            # Clean and validate geometry via shapely
            try:
                sh_geom = shape(geom)
                if not sh_geom.is_valid:
                    sh_geom = make_valid(sh_geom)
                if sh_geom.is_empty:
                    continue
                valid_geojson = mapping(sh_geom)
            except Exception:
                valid_geojson = geom

            features.append(
                {
                    "type": "Feature",
                    "geometry": valid_geojson,
                    "properties": {
                        "facies_id": c_idx + 1,
                        "facies_name": facies_name,
                        "facies": facies_name,
                        "color": color,
                    },
                }
            )

    except ImportError:
        # Fallback grid cell rectangles
        dx = (xmax - xmin) / float(w)
        dy = (ymax - ymin) / float(h)
        for i in range(h):
            for j in range(w):
                c_idx = int(class_grid[i, j])
                facies_name = facies_names[c_idx]
                color = colors[c_idx % len(colors)]
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
                            "facies_name": facies_name,
                            "facies": facies_name,
                            "color": color,
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
        "fill": colors[0],
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
