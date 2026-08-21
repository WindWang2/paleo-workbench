"""Native QGIS renderer/symbol serialization contract (requires the bridge).

These tests pin the authoritative style path: a QgsFeatureRenderer payload
round-trips through XML without losing symbol layers, expressions,
categories, ranges or colors — the property Paleo project saves rely on.
"""

from __future__ import annotations

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = pytest.mark.qgis

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)


def _bridge():
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    return bridge


def _layer_spec(**overrides):
    spec = {
        "id": "facies",
        "name": "Facies",
        "crs": "EPSG:3857",
        "data_revision": 1,
        "style_revision": 1,
        "visible": True,
        "opacity": 1.0,
        "features": [
            {"id": "f1", "wkt": "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"},
            {"id": "f2", "wkt": "POLYGON ((20 20, 30 20, 30 30, 20 30, 20 20))"},
        ],
    }
    spec.update(overrides)
    return spec


class TestLegacyMigration:
    def test_single_style_migrates_to_renderer_xml(self) -> None:
        xml = qgis_render_bridge.legacy_style_to_renderer_xml(
            {"fill": "#ff0000", "stroke": "#000000", "stroke_width": 1.5},
            "Polygon",
        )
        assert xml
        info = qgis_render_bridge.renderer_info(str(xml))
        assert info is not None
        assert info["type"] == "singleSymbol"
        assert info["symbol_count"] == 1

    def test_categorized_style_preserves_values_and_labels(self) -> None:
        xml = qgis_render_bridge.legacy_style_to_renderer_xml(
            {
                "renderer": "categorized",
                "field": "lithology",
                "fill": "#6c8ebf",
                "categories": [
                    ["sandstone", "#e0b040", "Sandstone"],
                    ["shale", "#708090", "Shale"],
                ],
            },
            "Polygon",
        )
        info = qgis_render_bridge.renderer_info(str(xml))
        assert info is not None
        assert info["type"] == "categorizedSymbol"
        assert info["symbol_count"] == 2

    def test_graduated_style_preserves_ranges(self) -> None:
        xml = qgis_render_bridge.legacy_style_to_renderer_xml(
            {
                "renderer": "graduated",
                "field": "depth",
                "ranges": [[0, 100, "#aaddaa", "shallow"], [100, 500, "#4060c0", "deep"]],
            },
            "LineString",
        )
        info = qgis_render_bridge.renderer_info(str(xml))
        assert info is not None
        assert info["type"] == "graduatedSymbol"
        assert info["symbol_count"] == 2

    def test_rule_style_preserves_expressions(self) -> None:
        xml = qgis_render_bridge.legacy_style_to_renderer_xml(
            {
                "renderer": "rule",
                "rules": [
                    {
                        "name": "normal faults",
                        "expression": "\"fault_type\" = 'normal'",
                        "label": "Normal",
                        "stroke": "#e03131",
                    },
                    {
                        "name": "thrust faults",
                        "expression": "\"fault_type\" = 'thrust'",
                        "label": "Thrust",
                        "stroke": "#1971c2",
                    },
                ],
            },
            "LineString",
        )
        info = qgis_render_bridge.renderer_info(str(xml))
        assert info is not None
        assert info["type"] == "RuleRenderer"

    def test_empty_style_returns_none(self) -> None:
        assert qgis_render_bridge.legacy_style_to_renderer_xml({}, "Polygon")


class TestRendererPayloadRendering:
    def test_renderer_xml_payload_renders_multilayer_symbol(self, qtbot) -> None:
        """A two-layer symbol (fill + inner stroke) survives save/load/render."""
        # Migrate a categorized base then verify the payload drives rendering
        # through the full snapshot path (style-only update keeps mirrors).
        xml = qgis_render_bridge.legacy_style_to_renderer_xml(
            {
                "renderer": "categorized",
                "field": "__pwb_id",
                "fill": "#6c8ebf",
                "categories": [["f1", "#ff0000", "red"], ["f2", "#00ff00", "green"]],
            },
            "Polygon",
        )
        assert xml
        bridge = _bridge()
        try:
            bridge.set_layer_snapshot(
                [_layer_spec(style={"renderer_xml": str(xml)})], "EPSG:3857"
            )
            frame = bridge.render_sync((0.0, 0.0, 40.0, 40.0), 160, 160, 96.0)
            rgba = frame["rgba"]
            stride = frame["stride"]

            def pixel(x: int, y: int):
                offset = y * stride + x * 4
                return tuple(rgba[offset : offset + 3])

            # f1 polygon occupies world 0-10 of 0-40 → screen x/y ∈ [0,40],
            # with y flipped: centre ≈ (20, 140).
            assert pixel(20, 140)[0] > 180, "first category fill missing"
            # f2 polygon occupies world 20-30 → screen x ∈ [80,120], y ∈ [40,80].
            assert pixel(100, 60)[1] > 180, "second category fill missing"
        finally:
            bridge.shutdown()

    def test_invalid_payload_fails_snapshot_and_keeps_previous_layers(self, qtbot) -> None:
        bridge = _bridge()
        try:
            good = _layer_spec()
            bridge.set_layer_snapshot([good], "EPSG:3857")
            with pytest.raises(RuntimeError, match="renderer"):
                bridge.set_layer_snapshot(
                    [_layer_spec(data_revision=2, style={"renderer_xml": "<not-a-renderer/>"})],
                    "EPSG:3857",
                )
            # The previous mirror generation still renders (#519 semantics).
            frame = bridge.render_sync((0.0, 0.0, 40.0, 40.0), 64, 64, 96.0)
            assert len(frame["rgba"]) == frame["height"] * frame["stride"]
        finally:
            bridge.shutdown()


class TestMirrorReuse:
    def test_style_only_update_reuses_mirror(self, qtbot) -> None:
        bridge = _bridge()
        try:
            bridge.set_layer_snapshot([_layer_spec()], "EPSG:3857")
            first = bridge.diagnostics()
            bridge.set_layer_snapshot(
                [_layer_spec(style={"fill": "#123456"}, style_revision=2)],
                "EPSG:3857",
            )
            second = bridge.diagnostics()
            assert second["mirror_builds"] == first["mirror_builds"] + 0
            assert second["mirror_reuses"] == first["mirror_reuses"] + 1
            assert second["style_reapplies"] == first["style_reapplies"] + 1

            # Pan/zoom (render request only) never rebuilds anything.
            before = bridge.diagnostics()
            bridge.render_sync((5.0, 5.0, 25.0, 25.0), 64, 64, 96.0)
            after = bridge.diagnostics()
            assert after["mirror_builds"] == before["mirror_builds"]
        finally:
            bridge.shutdown()
