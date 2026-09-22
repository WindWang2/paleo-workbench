"""Facies SVG pattern renderer XML: generator + native-bridge mirror wiring."""

from __future__ import annotations

import json
from xml.dom import minidom

import pytest

from paleo_workbench.mapping.facies_patterns import FACIES_PATTERN_DIR
from paleo_workbench.mapping.facies_renderer_xml import (
    categorized_fill_renderer_xml,
)
from paleo_workbench.mapping.geological_symbols import symbol_by_id
from paleo_workbench.mapping.qgis_mirror import (
    mirror_snapshot_to_stack,
    reset_publish_ledger,
)


def _facies_v2_inputs():
    fallback = symbol_by_id("facies_v2").legacy_fallback
    style = fallback.to_dict()
    return (
        style["field"],
        [tuple(entry) for entry in style["categories"]],
        dict(style["fill_patterns"]),
    )


def _svg_fill_layers(dom):
    return [
        layer for layer in dom.getElementsByTagName("layer")
        if layer.getAttribute("class") == "SVGFill"
    ]


def test_facies_v2_xml_is_wellformed_with_expected_svgfill_count():
    field, categories, fill_patterns = _facies_v2_inputs()
    assert len(categories) == 9
    xml = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns=fill_patterns)
    dom = minidom.parseString(xml)
    symbols = dom.getElementsByTagName("symbol")
    assert len(symbols) == 9
    svg_layers = _svg_fill_layers(dom)
    assert len(svg_layers) == len(fill_patterns) == 7
    for layer in svg_layers:
        options = {
            node.getAttribute("name"): node.getAttribute("value")
            for node in layer.getElementsByTagName("Option")
            if node.hasAttribute("name")
        }
        assert options["width"] == "4"
        assert options["pattern_width_unit"] == "MM"
        svg_file = options["svgFile"]
        assert svg_file.startswith(str(FACIES_PATTERN_DIR))
        import os

        assert os.path.isfile(svg_file)


def test_unmapped_classes_keep_simple_fill_only():
    field, categories, _ = _facies_v2_inputs()
    xml = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns={})
    dom = minidom.parseString(xml)
    assert not _svg_fill_layers(dom)
    assert len(dom.getElementsByTagName("symbol")) == 9
    simple = [
        layer for layer in dom.getElementsByTagName("layer")
        if layer.getAttribute("class") == "SimpleFill"
    ]
    assert len(simple) == 9


def test_missing_svg_file_falls_back_to_simple_fill(tmp_path):
    field, categories, fill_patterns = _facies_v2_inputs()
    xml = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns=fill_patterns,
        pattern_dir=tmp_path)
    dom = minidom.parseString(xml)
    assert not _svg_fill_layers(dom)
    assert len(dom.getElementsByTagName("symbol")) == 9


def test_category_values_labels_and_base_colors_survive():
    field, categories, fill_patterns = _facies_v2_inputs()
    xml = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns=fill_patterns)
    dom = minidom.parseString(xml)
    seen = {
        node.getAttribute("value"): node.getAttribute("label")
        for node in dom.getElementsByTagName("category")
    }
    assert seen == {value: label for value, _fill, label in categories}
    fills = [
        node.getAttribute("value")
        for node in dom.getElementsByTagName("Option")
        if node.getAttribute("name") == "color"
    ]
    for _value, fill, _label in categories:
        assert fill in fills


@pytest.mark.qgis
def test_same_input_produces_byte_identical_xml():
    """Deterministic ids: identical inputs must yield identical bytes.

    The mirror publish ledger compares renderer XML verbatim — random ids
    would defeat its no-op path and force a full republish every time.
    """
    field, categories, fill_patterns = _facies_v2_inputs()
    first = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns=fill_patterns)
    second = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns=fill_patterns)
    assert first == second


def test_different_fill_patterns_produce_different_xml():
    field, categories, fill_patterns = _facies_v2_inputs()
    full = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns=fill_patterns)
    bare = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns={})
    assert full != bare


def test_generated_xml_round_trips_through_native_bridge():
    qgis_render_bridge = pytest.importorskip(
        "qgis_render_bridge",
        reason="optional qgis_render_bridge is not built",
    )
    field, categories, fill_patterns = _facies_v2_inputs()
    xml = categorized_fill_renderer_xml(
        field=field, categories=categories, fill_patterns=fill_patterns)
    info = qgis_render_bridge.renderer_info(xml)
    assert info is not None
    assert info["type"] == "categorizedSymbol"
    assert info["symbol_count"] == 9


class _FakeStack:
    def __init__(self):
        self.calls: list[dict] = []

    def set_destination_crs(self, canvas, crs):
        pass

    def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            **kwargs):
        """upsert_mirror_layer(...) -> str"""
        self.calls.append({
            "doc_id": doc_id, "geom": geom, "geojson": json.loads(geojson),
            "renderer_xml": renderer_xml, "legacy_style": legacy_style,
        })
        return f"qgis-{doc_id}"

    def remove_mirror_layers_except(self, seen):
        pass

    def set_mirror_layer_order(self, order):
        pass

    def refresh_canvas(self, canvas):
        pass


def _polygon_layer(style):
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

    return MapLayerSnapshot(
        id="facies-1", name="相", layer_type="vector",
        extent=(0, 0, 10, 10), crs="EPSG:32650",
        data_revision=1, style_revision=1,
        features=({
            "type": "Feature",
            "geometry": {"type": "Polygon",
                         "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "properties": {"facies_name": "delta"},
        },),
        style=style, visible=True, opacity=1.0,
        renderer_payload=None,
    )


class _Snap:
    def __init__(self, layers, project_crs="EPSG:32650"):
        self.layers = tuple(layers)
        self.project_crs = project_crs


@pytest.fixture(autouse=True)
def _clean_ledger():
    reset_publish_ledger()
    yield
    reset_publish_ledger()


def test_mirror_publishes_renderer_xml_for_patterned_style():
    stack = _FakeStack()
    _, _, failures = mirror_snapshot_to_stack(
        stack, 0x1, _Snap([_polygon_layer(
            symbol_by_id("facies_v2").legacy_fallback.to_dict())]))
    assert failures == []
    assert len(stack.calls) == 1
    call = stack.calls[0]
    assert call["legacy_style"] is None
    assert call["renderer_xml"]
    dom = minidom.parseString(call["renderer_xml"])
    assert (dom.documentElement.getAttribute("type")
            == "categorizedSymbol")
    assert len(_svg_fill_layers(dom)) == 7


def test_mirror_leaves_unpatterned_style_untouched():
    stack = _FakeStack()
    style = {"renderer": "categorized", "field": "facies_name",
             "categories": [["delta", "#d9a066", "三角洲"]]}
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_polygon_layer(style)]))
    assert len(stack.calls) == 1
    assert stack.calls[0]["renderer_xml"] == ""
    assert stack.calls[0]["legacy_style"] == style


def test_mirror_respects_qgis_style_passthrough():
    stack = _FakeStack()
    style = dict(symbol_by_id("facies_v2").legacy_fallback.to_dict())
    style["qgis_style"] = {"renderer_xml": "<renderer-v2/>",
                           "labeling_xml": ""}
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_polygon_layer(style)]))
    assert len(stack.calls) == 1
    assert stack.calls[0]["renderer_xml"] == "<renderer-v2/>"
    assert stack.calls[0]["legacy_style"] is None


def test_mirror_skips_pattern_xml_for_non_polygon():
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

    stack = _FakeStack()
    style = symbol_by_id("facies_v2").legacy_fallback.to_dict()
    layer = MapLayerSnapshot(
        id="pts", name="点", layer_type="vector",
        extent=(0, 0, 10, 10), crs="EPSG:32650",
        data_revision=1, style_revision=1,
        features=({"type": "Feature",
                   "geometry": {"type": "Point", "coordinates": [1, 2]},
                   "properties": {"facies_name": "delta"}},),
        style=style, visible=True, opacity=1.0, renderer_payload=None,
    )
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    assert len(stack.calls) == 1
    assert stack.calls[0]["renderer_xml"] == ""
    assert stack.calls[0]["legacy_style"] == style


def test_empty_label_falls_back_to_value():
    field, categories, fill_patterns = _facies_v2_inputs()
    dict_shape = {value: fill for value, fill, _label in categories}
    from paleo_workbench.mapping.map_styles import VectorStyle

    parsed = VectorStyle.from_dict({
        "renderer": "categorized", "field": field,
        "categories": dict_shape, "fill_patterns": fill_patterns,
    })
    assert all(label == "" for _v, _f, label in parsed.categories)
    xml = categorized_fill_renderer_xml(
        field=parsed.field, categories=parsed.categories,
        fill_patterns=fill_patterns)
    dom = minidom.parseString(xml)
    seen = {
        node.getAttribute("value"): node.getAttribute("label")
        for node in dom.getElementsByTagName("category")
    }
    assert seen == {value: value for value, _fill, _label in categories}


def test_mirror_falls_back_to_legacy_when_generation_fails(monkeypatch):
    import paleo_workbench.mapping.facies_renderer_xml as gen

    def _boom(**kwargs):
        raise RuntimeError("no svg today")

    monkeypatch.setattr(gen, "categorized_fill_renderer_xml", _boom)
    stack = _FakeStack()
    style = symbol_by_id("facies_v2").legacy_fallback.to_dict()
    diags: list = []
    _, _, failures = mirror_snapshot_to_stack(
        stack, 0x1, _Snap([_polygon_layer(style)]), diags=diags)
    assert failures == []
    assert len(stack.calls) == 1
    assert stack.calls[0]["renderer_xml"] == ""
    assert stack.calls[0]["legacy_style"] == style
    assert any("facies pattern renderer skipped" in message
               for _, message in diags)
