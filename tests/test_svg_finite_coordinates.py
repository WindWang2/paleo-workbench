"""Regression tests for SVG finite-coordinate guarantees (ISSUE-019).

Vector geometries coming out of interpolation/edge pipelines can carry NaN
or Inf vertices; the SVG layer renderers used to format them verbatim,
emitting ``nan``/``inf`` into points attributes (invalid SVG, silent
render failure in strict viewers). The composer scale bar also floor-
divided its half-way label, printing "0" for every sub-2 km bar.
"""

from __future__ import annotations

import math

from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.renderer import MapComposerRenderer
from paleo_workbench.mapping.layers import VectorMapLayer
from paleo_workbench.mapping.renderers import (
    RenderContext,
    SingleSymbolRenderer,
)

NAN = float("nan")
INF = float("inf")


def _ctx() -> RenderContext:
    return RenderContext(extent=(0.0, 0.0, 100.0, 100.0), width=200.0, height=200.0)


def test_polygon_with_nan_vertices_does_not_emit_nan_svg():
    layer = VectorMapLayer(id="v1", name="poly", crs="EPSG:4326")
    layer.set_features(
        (
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0.0, 0.0], [NAN, 10.0], [20.0, INF], [30.0, 30.0]]],
                },
            },
        )
    )
    svg = SingleSymbolRenderer().render_svg(layer, _ctx())
    assert "nan" not in svg.lower()
    assert "inf" not in svg.lower()
    # The finite vertices still render.
    assert "<polygon" in svg


def test_linestring_with_all_nan_vertices_renders_no_element():
    layer = VectorMapLayer(id="v2", name="line", crs="EPSG:4326")
    layer.set_features(
        (
            {
                "geometry": {"type": "LineString", "coordinates": [[NAN, NAN], [INF, 1.0]]},
            },
        )
    )
    svg = SingleSymbolRenderer().render_svg(layer, _ctx())
    assert "<polyline" not in svg


def test_point_feature_with_nan_coords_is_skipped():
    layer = VectorMapLayer(id="v3", name="pt", crs="EPSG:4326")
    layer.set_features(
        (
            {"geometry": {"type": "Point", "coordinates": [NAN, 5.0]}},
            {"geometry": {"type": "Point", "coordinates": [10.0, 10.0]}},
        )
    )
    svg = SingleSymbolRenderer().render_svg(layer, _ctx())
    assert "nan" not in svg.lower()
    assert "<circle" in svg  # the finite point still renders


def test_scale_bar_halfway_label_is_not_floored_to_zero():
    doc = MapCompositionDocument(id="d1", title="t")
    doc.elements = [
        ComposerElement(
            id="bar",
            element_type=ElementType.SCALE_BAR,
            x_mm=10.0,
            y_mm=10.0,
            width_mm=40.0,
            height_mm=6.0,
            properties={"length_km": 1},
        )
    ]
    renderer = MapComposerRenderer()
    svg = renderer.render_to_svg(doc)
    assert ">0.5<" in svg, "1 km bar must label its half point as 0.5, not 0"
    assert ">1 km<" in svg
    assert math.isfinite(1)  # sanity: module imported


def test_scale_bar_survives_non_numeric_length():
    doc = MapCompositionDocument(id="d1", title="t")
    doc.elements = [
        ComposerElement(
            id="bar2",
            element_type=ElementType.SCALE_BAR,
            x_mm=10.0,
            y_mm=10.0,
            width_mm=40.0,
            height_mm=6.0,
            properties={"length_km": "fifty"},
        )
    ]
    renderer = MapComposerRenderer()
    svg = renderer.render_to_svg(doc)
    assert ">25<" in svg  # falls back to 50 km default, half = 25
    assert ">50 km<" in svg
