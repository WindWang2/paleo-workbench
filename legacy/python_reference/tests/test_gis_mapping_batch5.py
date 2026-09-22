"""Unit tests for Batch 5: GIS & Cartography (Map Composer & Single-Factor geoprocessing)."""

import numpy as np
import pytest

from paleo_workbench.mapping.composer import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
    composer_renderer,
)
from paleo_workbench.mapping.geological_pipeline.contouring import (
    generate_contour_layer,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    generate_facies_polygon_layer,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def test_map_composition_document_and_elements():
    doc = MapCompositionDocument(
        id="comp_01",
        title="川西须家河组古地理图",
        paper_size="A4",
        orientation="landscape",
        width_mm=297.0,
        height_mm=210.0,
    )

    doc.add_element(
        ComposerElement(
            id="elem_main_map",
            element_type=ElementType.MAIN_MAP,
            x_mm=10.0,
            y_mm=20.0,
            width_mm=220.0,
            height_mm=170.0,
        )
    )
    doc.add_element(
        ComposerElement(
            id="elem_title",
            element_type=ElementType.TITLE,
            x_mm=10.0,
            y_mm=5.0,
            width_mm=277.0,
            height_mm=12.0,
            properties={"text": "川西须家河组岩相古地理图"},
        )
    )
    doc.add_element(
        ComposerElement(
            id="elem_north_arrow",
            element_type=ElementType.NORTH_ARROW,
            x_mm=220.0,
            y_mm=25.0,
            width_mm=10.0,
            height_mm=15.0,
        )
    )
    doc.add_element(
        ComposerElement(
            id="elem_scale_bar",
            element_type=ElementType.SCALE_BAR,
            x_mm=20.0,
            y_mm=175.0,
            width_mm=50.0,
            height_mm=10.0,
            properties={"length_km": 50},
        )
    )
    doc.add_element(
        ComposerElement(
            id="elem_legend",
            element_type=ElementType.LEGEND,
            x_mm=235.0,
            y_mm=20.0,
            width_mm=50.0,
            height_mm=120.0,
        )
    )

    assert len(doc.elements) == 5
    d = doc.to_dict()
    assert d["title"] == "川西须家河组古地理图"
    assert len(d["elements"]) == 5

    # Render to SVG
    svg = composer_renderer.render_to_svg(doc)
    assert "<svg" in svg
    assert "</svg>" in svg
    assert "川西须家河组岩相古地理图" in svg
    assert "elem_north_arrow" in svg
    assert "elem_scale_bar" in svg
    assert "elem_legend" in svg


def test_single_factor_pipeline_contours_and_facies():
    """#1035: the degenerate single_factor_pipeline stubs (horizontal-line
    "contours", 1-pixel-box "polygons" behind ImportError fallbacks) were
    removed; the geological_pipeline marching-squares contouring and
    polygonization engines are the single scientific implementation."""
    grid = np.array(
        [
            [0.1, 0.2, 0.3, 0.4],
            [0.2, 0.3, 0.5, 0.6],
            [0.3, 0.5, 0.7, 0.8],
            [0.4, 0.6, 0.8, 0.9],
        ],
        dtype=np.float64,
    )
    extent = (500000.0, 3400000.0, 5200000.0 - 4680000.0 + 500000.0, 3420000.0)
    # keep the original extent values
    extent = (500000.0, 3400000.0, 520000.0, 3420000.0)
    grid_x = np.linspace(extent[0], extent[2], grid.shape[1])
    grid_y = np.linspace(extent[1], extent[3], grid.shape[0])
    result = FactorGridResult(
        grid_z=grid.astype(np.float32),
        grid_x=grid_x,
        grid_y=grid_y,
        factor_name="砂岩厚度",
        algorithm_id="kriging",
    )

    contour_layer = generate_contour_layer(result, levels=[0.3, 0.6])
    assert len(contour_layer.features) > 0
    lines: list[list[list[float]]] = []
    for feature in contour_layer.features:
        geom = feature["geometry"]
        if geom["type"] == "LineString":
            lines.append(geom["coordinates"])
        else:  # MultiLineString
            lines.extend(geom["coordinates"])
    assert lines, "contour layer must carry actual line geometry"
    for line in lines:
        # real marching-squares geometry has interpolated vertices and spans
        # actual distance — never one constant-Y horizontal segment per cell
        assert len(line) >= 2
        ys = [pt[1] for pt in line]
        assert max(ys) - min(ys) > 0.0 or len(line) > 2

    facies_layer = generate_facies_polygon_layer(result)
    facies = list(facies_layer.features)
    # #977 marching-squares + polygonization: on this diagonal ramp the same
    # facies band (三角洲前缘砂) forms TWO disconnected components at opposite
    # corners, so 4 polygons across 3 distinct facies. The old synthetic
    # striping collapsed them into 3 with distorted geometry.
    assert len(facies) == 4
    assert len({f["properties"]["facies_name"] for f in facies}) == 3
    assert facies[0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert "facies_name" in facies[0]["properties"]
