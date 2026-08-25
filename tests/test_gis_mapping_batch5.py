"""Unit tests for Batch 5: GIS & Cartography (Map Composer & Single-Factor Pipeline)."""

import numpy as np
import pytest

from paleo_workbench.mapping.composer import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
    composer_renderer,
)
from paleo_workbench.mapping.single_factor_pipeline import (
    extract_facies_polygons,
    extract_grid_contours,
)


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
    grid = np.array(
        [
            [0.1, 0.2, 0.3, 0.4],
            [0.2, 0.3, 0.5, 0.6],
            [0.3, 0.5, 0.7, 0.8],
            [0.4, 0.6, 0.8, 0.9],
        ],
        dtype=np.float64,
    )
    extent = (500000.0, 3400000.0, 520000.0, 3420000.0)

    contours = extract_grid_contours(grid, extent, levels=[0.3, 0.6])
    assert len(contours) > 0
    assert contours[0]["geometry"]["type"] == "LineString"

    facies = extract_facies_polygons(grid, extent)
    # #977 marching-squares + polygonization: on this diagonal ramp the same
    # facies band (三角洲前缘砂) forms TWO disconnected components at opposite
    # corners, so 4 polygons across 3 distinct facies. The old synthetic
    # striping collapsed them into 3 with distorted geometry.
    assert len(facies) == 4
    assert len({f["properties"]["facies_name"] for f in facies}) == 3
    assert facies[0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert "facies_name" in facies[0]["properties"]
