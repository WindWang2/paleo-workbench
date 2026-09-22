"""M6 — component graph coverage and placeholder contracts.

New components (subtitle / well legend / profile placeholder): serialisable,
renderable, registry-covered, and honest when unbound (a placeholder never
invents content). The layout export policy demotes compositions carrying
components without native layout counterparts to the composer fallback.
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.renderer import composer_renderer
from paleo_workbench.mapping.composer.registry import all_specs, get_spec


def _composition_with(element: ComposerElement) -> MapCompositionDocument:
    doc = MapCompositionDocument(id="comp_m6", title="t")
    doc.add_element(
        ComposerElement("el_map", ElementType.MAIN_MAP, 8, 12, 180.0, 150.0)
    )
    doc.add_element(element)
    return doc


def test_new_component_types_have_registry_specs():
    types = {spec.element_type for spec in all_specs()}
    assert {
        ElementType.SUBTITLE,
        ElementType.WELL_LEGEND,
        ElementType.PROFILE,
    } <= types
    for etype in (ElementType.SUBTITLE, ElementType.WELL_LEGEND, ElementType.PROFILE):
        spec = get_spec(etype)
        assert spec.element_type is etype


def test_subtitle_roundtrip_and_render():
    el = ComposerElement(
        "el_sub", ElementType.SUBTITLE, 60.0, 8.0, 120.0, 6.0,
        properties={"text": "连井剖面综合图", "font_size": 4.0},
    )
    restored = ComposerElement.from_dict(el.to_dict())
    assert restored.element_type is ElementType.SUBTITLE
    assert restored.properties["text"] == "连井剖面综合图"
    svg = composer_renderer._render_element_svg(restored)
    assert "连井剖面综合图" in svg


def test_profile_unbound_renders_placeholder_only():
    el = ComposerElement(
        "el_prof", ElementType.PROFILE, 30.0, 168.0, 90.0, 30.0
    )
    svg = composer_renderer._render_element_svg(el)
    assert 'data-placeholder="true"' in svg
    assert "剖面（未绑定数据）" in svg
    # the placeholder group carries only frame + label, no content shapes
    group = svg.split("</g>")[0]
    assert "<path" not in group and "<polygon" not in group


def test_profile_bound_renders_content_frame():
    el = ComposerElement(
        "el_prof2", ElementType.PROFILE, 30.0, 168.0, 90.0, 30.0,
        properties={"section_ref": "section-77", "title": "连井剖面"},
    )
    svg = composer_renderer._render_element_svg(el)
    assert 'data-placeholder="true"' not in svg


def test_well_legend_unbound_is_placeholder_bound_is_legend():
    unbound = ComposerElement(
        "el_wl", ElementType.WELL_LEGEND, 210.0, 100.0, 70.0, 50.0
    )
    svg = composer_renderer._render_element_svg(unbound)
    assert 'data-placeholder="true"' in svg

    bound = ComposerElement(
        "el_wl2", ElementType.WELL_LEGEND, 210.0, 100.0, 70.0, 50.0,
        properties={
            "title": "测井图例",
            "items": ({"label": "GR", "color": "#00aa00"},),
        },
    )
    svg_bound = composer_renderer._render_element_svg(bound)
    assert 'data-placeholder="true"' not in svg_bound
    assert "GR" in svg_bound


def test_layout_export_falls_back_for_unmappable_profile(tmp_path):
    from paleo_workbench.mapping.layout_export import build_layout_spec

    composition = _composition_with(
        ComposerElement("el_prof", ElementType.PROFILE, 30.0, 168.0, 90.0, 30.0)
    )
    with pytest.raises(ValueError, match="profile"):
        build_layout_spec(
            composition, map_extent=(0.0, 0.0, 10.0, 9.0), crs="EPSG:4326"
        )


def test_layout_export_maps_subtitle_to_label():
    from paleo_workbench.mapping.layout_export import build_layout_spec

    composition = _composition_with(
        ComposerElement(
            "el_sub", ElementType.SUBTITLE, 60.0, 8.0, 120.0, 6.0,
            properties={"text": "T1 砂体分布"},
        )
    )
    spec = build_layout_spec(
        composition, map_extent=(0.0, 0.0, 10.0, 9.0), crs="EPSG:4326"
    )
    labels = [i for i in spec["items"] if i["type"] == "label"]
    assert any(i["text"] == "T1 砂体分布" for i in labels)
