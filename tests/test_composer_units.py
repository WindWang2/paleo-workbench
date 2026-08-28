"""Cartographic unit-system tests (Issue #1025).

``VectorStyle`` quantities are logical pixels at 96 DPI; the composer SVG
viewBox is millimetres. Every renderer must convert through
``RenderContext.to_target`` so a 1 px stroke stays 0.2646 mm — not 1 mm — in
print layouts, and canvas/PDF/QGIS paint the same physical sizes.
"""

from __future__ import annotations

import re

import pytest

from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.renderer import MapComposerRenderer
from paleo_workbench.mapping.layers import MapDocument, VectorMapLayer
from paleo_workbench.mapping.renderers import RenderContext, RenderUnit

MM_PER_PX = 25.4 / 96.0


def _layer(stroke_width: float = 2.0, font_size: float = 10.0, marker: float = 6.0):
    return VectorMapLayer(
        name="unit-probe",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                "properties": {"name": "probe-line"},
            }
        ],
        style={
            "stroke": "#ff0000",
            "fill": "#00ff00",
            "stroke_width": stroke_width,
            "marker_size": marker,
            "labels": {
                "visible": True,
                "field": "name",
                "size": font_size,
                "color": "#000000",
            },
        },
    )


def _composition(layer) -> MapCompositionDocument:
    element = ComposerElement(
        id="main-map",
        element_type=ElementType.MAIN_MAP,
        x_mm=10,
        y_mm=10,
        width_mm=150,
        height_mm=120,
    )
    element.properties["layers"] = [layer]
    element.properties["extent"] = (0.0, 0.0, 1.0, 1.0)
    return MapCompositionDocument(
        id="comp",
        title="units",
        width_mm=297,
        height_mm=210,
        elements=[element],
    )


def _attr(svg: str, pattern: str) -> float:
    match = re.search(pattern, svg)
    assert match, f"pattern not found: {pattern}"
    return float(match.group(1))


# ---------------------------------------------------------------------------
# Conversion primitives
# ---------------------------------------------------------------------------


def test_render_unit_conversion_factors():
    ctx_px = RenderContext(extent=(0, 0, 1, 1), width=100, height=100)
    ctx_mm = RenderContext(
        extent=(0, 0, 1, 1), width=100, height=100, units=RenderUnit.MM
    )
    ctx_pt = RenderContext(
        extent=(0, 0, 1, 1), width=100, height=100, units=RenderUnit.PT
    )
    assert ctx_px.to_target(1.0) == 1.0
    assert ctx_mm.to_target(1.0) == pytest.approx(MM_PER_PX, abs=1e-9)
    assert ctx_pt.to_target(1.0) == pytest.approx(0.75, abs=1e-9)
    # Round trip sanity: 96 px is one inch in every unit.
    assert ctx_mm.to_target(96.0) == pytest.approx(25.4, abs=1e-6)
    assert ctx_pt.to_target(96.0) == pytest.approx(72.0, abs=1e-6)


def test_default_context_is_pixels_for_canvas_compatibility():
    ctx = RenderContext(extent=(0, 0, 1, 1), width=10, height=10)
    assert ctx.units is RenderUnit.PX


# ---------------------------------------------------------------------------
# Composer SVG physical sizes
# ---------------------------------------------------------------------------


def test_composer_svg_stroke_width_is_physical_mm():
    svg = MapComposerRenderer().render_to_svg(_composition(_layer(stroke_width=2.0)))
    stroke_mm = _attr(svg, r'stroke="#ff0000" stroke-width="([0-9.]+)"')
    assert stroke_mm == pytest.approx(2.0 * MM_PER_PX, abs=0.01), (
        f"2px stroke rendered as {stroke_mm}mm (raw px leak: 3.78× too thick)"
    )


def test_composer_svg_font_size_is_physical_mm():
    point_layer = VectorMapLayer(
        name="font-probe",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                "properties": {"name": "probe"},
            }
        ],
        style={
            "stroke": "#000000",
            "fill": "#0000ff",
            "labels": {
                "visible": True,
                "field": "name",
                "size": 10.0,
                "color": "#000000",
            },
        },
    )
    svg = MapComposerRenderer().render_to_svg(_composition(point_layer))
    font_mm = _attr(svg, r'font-size="([0-9.]+)"')
    assert font_mm == pytest.approx(10.0 * MM_PER_PX, abs=0.01), (
        f"10px font rendered as {font_mm}mm (mm viewBox would show 10mm ≈ 28pt text)"
    )


def test_composer_svg_marker_radius_is_physical_mm():
    point_layer = VectorMapLayer(
        name="pt",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                "properties": {},
            }
        ],
        style={
            "stroke": "#000000",
            "fill": "#0000ff",
            "marker_size": 6.0,
        },
    )
    svg = MapComposerRenderer().render_to_svg(_composition(point_layer))
    r_mm = _attr(svg, r'<circle[^>]*r="([0-9.]+)"')
    assert r_mm == pytest.approx((6.0 / 2.0) * MM_PER_PX, abs=0.01)


def test_composer_svg_dash_lengths_are_physical_mm():
    layer = _layer()
    layer.style["line_pattern"] = "fault"
    svg = MapComposerRenderer().render_to_svg(_composition(layer))
    dash = _attr(svg, r'stroke-dasharray="([0-9.]+),')
    values = [dash, _attr(svg, r'stroke-dasharray="[0-9.]+,([0-9.]+)"')]
    stroke_px = 2.0
    # FAULT pattern in Qt units is (6, 2) × pen width.
    assert values[0] == pytest.approx(6 * stroke_px * MM_PER_PX, abs=0.02)
    assert values[1] == pytest.approx(2 * stroke_px * MM_PER_PX, abs=0.02)


def test_px_context_emits_unconverted_values():
    """The canvas path (units=px) keeps byte-stable px semantics."""
    from paleo_workbench.mapping.renderers import DEFAULT_RENDERER_REGISTRY

    layer = _layer(stroke_width=2.0)
    ctx = RenderContext(extent=(0, 0, 1, 1), width=100, height=100)
    svg = DEFAULT_RENDERER_REGISTRY.resolve(layer).render_svg(layer, ctx)
    stroke = _attr(svg, r'stroke="#ff0000" stroke-width="([0-9.]+)"')
    assert stroke == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------------------
# Screen ↔ print physical parity
# ---------------------------------------------------------------------------


def test_screen_and_composer_agree_physically():
    """Same style on canvas (px) and composer (mm) → same physical size."""
    from paleo_workbench.mapping.renderers import DEFAULT_RENDERER_REGISTRY

    layer = VectorMapLayer(
        name="parity-probe",
        features=[
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                "properties": {"name": "probe"},
            }
        ],
        style={
            "stroke": "#ff0000",
            "fill": "#00ff00",
            "stroke_width": 2.0,
            "labels": {
                "visible": True,
                "field": "name",
                "size": 10.0,
                "color": "#000000",
            },
        },
    )
    px_svg = DEFAULT_RENDERER_REGISTRY.resolve(layer).render_svg(
        layer, RenderContext(extent=(0, 0, 1, 1), width=150, height=120)
    )
    mm_svg = MapComposerRenderer().render_to_svg(_composition(layer))
    px_stroke = _attr(px_svg, r'stroke="#ff0000" stroke-width="([0-9.]+)"')
    mm_stroke = _attr(mm_svg, r'stroke="#ff0000" stroke-width="([0-9.]+)"')
    # 1 px = 0.2646 mm: the two numbers describe the same physical stroke.
    assert mm_stroke == pytest.approx(px_stroke * MM_PER_PX, abs=0.02)
    px_font = _attr(px_svg, r'font-size="([0-9.]+)"')
    mm_font = _attr(mm_svg, r'font-size="([0-9.]+)"')
    assert mm_font == pytest.approx(px_font * MM_PER_PX, abs=0.02)


def test_high_dpi_px_context_scales_physical_sizes():
    """A 192 DPI px context doubles device sizes (export parity)."""
    from paleo_workbench.mapping.renderers import DEFAULT_RENDERER_REGISTRY

    layer = _layer(stroke_width=2.0)
    lo = DEFAULT_RENDERER_REGISTRY.resolve(layer).render_svg(
        layer, RenderContext(extent=(0, 0, 1, 1), width=150, height=120, dpi=96)
    )
    hi = DEFAULT_RENDERER_REGISTRY.resolve(layer).render_svg(
        layer, RenderContext(extent=(0, 0, 1, 1), width=300, height=240, dpi=192)
    )
    # Stroke width is dpi-independent in logical px (Qt pen behaviour);
    # coordinates scale with the viewport. Both must render identical
    # stroke-width because the pen is defined in logical px.
    assert _attr(lo, r'stroke-width="([0-9.]+)"') == _attr(
        hi, r'stroke-width="([0-9.]+)"'
    )


# ---------------------------------------------------------------------------
# QGIS wire parity
# ---------------------------------------------------------------------------


def test_qgis_wire_converts_label_px_to_points():
    from paleo_workbench.mapping.map_render_backend import _flatten_qgis_style

    flat = _flatten_qgis_style(
        {
            "labels": {
                "size": 12.0,
                "halo_width": 2.0,
                "halo_color": "#ffff00",
            }
        }
    )
    labels = flat["labels"]
    # QgsTextFormat.setSize uses points; 12 px @96dpi == 9 pt.
    assert labels["size"] == pytest.approx(9.0)
    # QgsTextBufferSettings.setSize defaults to MILLIMETRES; 2 px == 0.529 mm.
    assert labels["buffer"] == pytest.approx(2.0 * MM_PER_PX)
    assert labels["buffer_color"] == "#ffff00"


def test_well_symbol_inner_dot_stays_proportional_in_mm():
    """Review F1 regression: the well symbol's centre-dot floors (0.5/0.8 px)
    must convert with the ring radius, or the ring+dot symbol degenerates to
    a solid disc in the mm composer (dot >= ring at small marker sizes)."""
    from paleo_workbench.mapping.renderers import DEFAULT_RENDERER_REGISTRY

    for marker_px in (6.0, 7.0):
        layer = VectorMapLayer(
            name="well",
            features=[
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                    "properties": {},
                }
            ],
            style={
                "stroke": "#000000",
                "fill": "#ffffff",
                "marker_size": marker_px,
                "marker": "well",
            },
        )
        svg = DEFAULT_RENDERER_REGISTRY.resolve(layer).render_svg(
            layer,
            RenderContext(
                extent=(0, 0, 1, 1), width=150, height=120, units=RenderUnit.MM
            ),
        )
        radii = [float(m) for m in re.findall(r'<circle[^>]*r="([0-9.]+)"', svg)]
        assert len(radii) >= 2, "well symbol must draw ring + inner dot"
        ring, dot = max(radii), min(radii)
        assert dot < 0.86 * ring, (
            f"marker_size={marker_px}: dot {dot:.3f}mm vs ring {ring:.3f}mm "
            f"— symbol collapsed to a solid disc"
        )
