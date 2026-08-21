"""Rule-based renderer contract (P0): attribute-driven geological symbology.

Requires the native bridge; exercises the full snapshot path with rule
expressions over feature attributes (lithology/fault_type style predicates).
"""

from __future__ import annotations

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = pytest.mark.qgis

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)


def _rule_layer():
    return {
        "id": "faults",
        "name": "Faults",
        "crs": "EPSG:3857",
        "data_revision": 1,
        "style_revision": 1,
        "visible": True,
        "opacity": 1.0,
        "features": [
            {
                "id": "normal-1",
                "wkt": "LINESTRING (0 5, 10 5)",
                "attributes": {"fault_type": "normal"},
            },
            {
                "id": "thrust-1",
                "wkt": "LINESTRING (0 15, 10 15)",
                "attributes": {"fault_type": "thrust"},
            },
        ],
        "style": {
            "renderer": "rule",
            "rules": [
                {
                    "name": "normal",
                    "expression": "\"fault_type\" = 'normal'",
                    "stroke": "#e03131",
                    "stroke_width": 2.0,
                },
                {
                    "name": "thrust",
                    "expression": "\"fault_type\" = 'thrust'",
                    "stroke": "#1971c2",
                    "stroke_width": 2.0,
                },
            ],
        },
    }


def _pixel(frame: dict, x: int, y: int) -> tuple[int, ...]:
    stride = frame["stride"]
    offset = y * stride + x * 4
    rgba = frame["rgba"]
    return tuple(rgba[offset : offset + 3])


def _render(bridge, extent=(0.0, 0.0, 20.0, 20.0), width=160, height=160):
    bridge.set_layer_snapshot([_rule_layer()], "EPSG:3857")
    return bridge.render_sync(extent, width, height, 96.0)


def test_rule_renderer_routes_by_expression(qtbot) -> None:
    """Each rule paints only its matching features with its own symbol."""
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    try:
        frame = _render(bridge)
        # Normal fault line at world y=5 → screen y ≈ 120: red channel dominates.
        red_pixel = _pixel(frame, 80, 120)
        assert red_pixel[0] > 150 and red_pixel[0] > red_pixel[2], (
            f"normal-fault rule did not paint red: {red_pixel}"
        )
        # Thrust fault line at world y=15 → screen y ≈ 40: blue channel dominates.
        blue_pixel = _pixel(frame, 80, 40)
        assert blue_pixel[2] > 150 and blue_pixel[2] > blue_pixel[0], (
            f"thrust-fault rule did not paint blue: {blue_pixel}"
        )
    finally:
        bridge.shutdown()


def test_rule_renderer_payload_roundtrip_preserves_rules(qtbot) -> None:
    """Migration → render → serialize keeps the rule tree intact."""
    xml = qgis_render_bridge.legacy_style_to_renderer_xml(
        _rule_layer()["style"], "LineString"
    )
    info = qgis_render_bridge.renderer_info(str(xml))
    assert info["type"] == "RuleRenderer"
    # A rule renderer exposes one symbol per rule to the selector.
    assert info["symbol_count"] == 2


def test_rule_with_unmatched_feature_renders_nothing_for_it(qtbot) -> None:
    layer = _rule_layer()
    layer["features"] = [
        {
            "id": "other",
            "wkt": "LINESTRING (5 8, 15 8)",
            "attributes": {"fault_type": "strike_slip"},
        }
    ]
    bridge = qgis_render_bridge.QgisRenderBridge()
    bridge.initialize()
    try:
        bridge.set_layer_snapshot([layer], "EPSG:3857")
        frame = bridge.render_sync((0.0, 0.0, 20.0, 20.0), 160, 160, 96.0)
        # World y=8 → screen y≈96: no rule matches, so the line stays unpainted.
        assert all(channel < 60 for channel in _pixel(frame, 80, 96))
    finally:
        bridge.shutdown()
