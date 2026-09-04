# -*- coding: utf-8 -*-
"""M3 Task 1: 捕捉配置下推 C++ canvas snappingUtils 并生效。"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_GEOJSON_POINTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
         "properties": {"name": "P1"}}
    ],
}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _show_canvas(qtbot, canvas):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget

    w = wrapInstance(canvas, QWidget)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    return w


def _add_point_layer(stack, doc_id="doc-井位"):
    # 注意顺序：加图层会触发画布自动缩放到图层范围，extent 必须在 add 之后设置。
    stack.upsert_mirror_layer(doc_id, "井位", "Point", "EPSG:4326",
                              json.dumps(_GEOJSON_POINTS), "", "", "", True, 1.0)


def test_snap_to_map_matches_vertex_within_tolerance(qtbot, stack):
    canvas = stack.create_canvas()
    _show_canvas(qtbot, canvas)
    _add_point_layer(stack)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    stack.set_snapping_config(canvas, json.dumps({
        "enabled": True, "mode": "all_layers",
        "tolerance_px": 20.0, "types": ["vertex"],
    }))
    # 地图坐标接近顶点 (5,5)，容差内应命中并吸附到顶点
    result = stack.snap_to_map(canvas, 4.9, 5.1)
    assert result["matched"] is True
    assert abs(result["x"] - 5.0) < 1e-6
    assert abs(result["y"] - 5.0) < 1e-6
    assert result["vertex_index"] == 0
    assert result["layer_doc_id"] == "doc-井位"


def test_snap_disabled_returns_no_match(qtbot, stack):
    canvas = stack.create_canvas()
    _show_canvas(qtbot, canvas)
    _add_point_layer(stack)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    stack.set_snapping_config(canvas, json.dumps({"enabled": False}))
    result = stack.snap_to_map(canvas, 4.9, 5.1)
    assert result["matched"] is False


def test_snap_per_layer_override_excludes_layer(qtbot, stack):
    canvas = stack.create_canvas()
    _show_canvas(qtbot, canvas)
    _add_point_layer(stack)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    stack.set_snapping_config(canvas, json.dumps({
        "enabled": True, "mode": "all_layers",
        "tolerance_px": 20.0, "types": ["vertex"],
        "layers": {"doc-井位": {"enabled": False, "types": ["vertex"], "tolerance_px": 20.0}},
    }))
    result = stack.snap_to_map(canvas, 4.9, 5.1)
    assert result["matched"] is False
