"""拓扑编辑二阶段：线悬挂点检查 + 线层原生会话（真桥）。"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


def _line(feature_id, coords):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"__pwb_fid": feature_id},
    }


def _collection(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _canvas(qtbot, stack):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    addr = stack.create_canvas()
    view = wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.show()
    return addr, view


def _cleanup(stack, addr, *docs):
    stack.set_map_tool(addr, "pan")
    for doc in docs:
        if stack.mirror_layer_editing(doc):
            stack.roll_back_mirror_layer(doc)


def _upsert_line(stack, doc_id, features):
    stack.upsert_mirror_layer(
        doc_id, doc_id, "LineString", "EPSG:4326", _collection(*features),
        "", "", "", True, 1.0, is_reference=False, is_editable=True,
        data_revision=1)


def _run(stack, addr, layer_ids, rules=None):
    config = {
        "layer_ids": list(layer_ids),
        "rules": rules or ["dangle", "is_valid"],
        "precision": 8,
    }
    raw = stack.run_geometry_checks(addr, json.dumps(config))
    payload = json.loads(raw) if isinstance(raw, str) else raw
    assert "errors" in payload, payload
    return payload


def test_open_line_reports_dangle(qtbot, stack):
    addr, _view = _canvas(qtbot, stack)
    try:
        _upsert_line(stack, "fault", [
            _line("a", [[0.0, 0.0], [1.0, 0.0]]),
        ])
        stack.set_canvas_extent(addr, -1.0, -1.0, 2.0, 2.0)
        payload = _run(stack, addr, ["fault"])
        dangles = [e for e in payload["errors"] if e.get("rule") == "dangle"]
        assert dangles, payload["errors"]
        assert dangles[0].get("fixable") is False
        assert dangles[0].get("feature_id") in {"a", "1", 1, "a"}
    finally:
        _cleanup(stack, addr, "fault")


def test_connected_line_network_has_no_dangle(qtbot, stack):
    """三条线围成闭合网：每个端点都落在另一条线上 → 无悬挂。"""
    addr, _view = _canvas(qtbot, stack)
    try:
        _upsert_line(stack, "shore", [
            _line("a", [[0.0, 0.0], [1.0, 0.0]]),
            _line("b", [[1.0, 0.0], [1.0, 1.0]]),
            _line("c", [[1.0, 1.0], [0.0, 0.0]]),
        ])
        stack.set_canvas_extent(addr, -1.0, -1.0, 2.0, 2.0)
        payload = _run(stack, addr, ["shore"])
        dangles = [e for e in payload["errors"] if e.get("rule") == "dangle"]
        assert not dangles, dangles
    finally:
        _cleanup(stack, addr, "shore")


def test_box_select_translates_distinct_vertices(qtbot, stack):
    """§4 框选多节点：空处拖框选中两点，再拖其中一点，两点平移同一向量。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    addr = stack.create_canvas()
    view = wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.show()
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[
                [2.0, 2.0], [6.0, 2.0], [6.0, 6.0], [2.0, 6.0], [2.0, 2.0]]]},
            "properties": {"__pwb_fid": "sq"},
        }],
    }
    try:
        stack.upsert_mirror_layer(
            "doc-box", "框选", "Polygon", "EPSG:4326", json.dumps(fc),
            "", "", "", True, 1.0, is_reference=False, is_editable=True,
            data_revision=1)
        stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
        assert stack.start_mirror_layer_editing("doc-box") == ""
        stack.set_current_layer(addr, "doc-box")
        events = []
        stack.set_edit_pick_callback(
            addr, lambda action, payload: events.append(
                (action, json.loads(payload))))
        stack.set_map_tool(addr, "vertex")

        def _pixel(x, y):
            from PySide6.QtCore import QPoint
            return QPoint(int(40 * x), int(400 - 40 * y))

        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                         _pixel(1.5, 1.5))
        QTest.mouseMove(view.viewport(), _pixel(6.5, 2.5))
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                           _pixel(6.5, 2.5))
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                         _pixel(2.0, 2.0))
        QTest.mouseMove(view.viewport(), _pixel(3.0, 3.0))
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                           _pixel(3.0, 3.0))
        qtbot.waitUntil(
            lambda: any(a == "edit_gesture" for a, _ in events), timeout=2000)
        payload = json.loads(stack.mirror_features_json("doc-box", 0))
        ring = payload["features"][0]["geometry"]["coordinates"][0]
        pts = {(round(x, 1), round(y, 1)) for x, y in ring}
        assert (3.0, 3.0) in pts
        assert (7.0, 3.0) in pts
        # 闭合环必须仍闭合：首尾同点，且顶点数不变（平移不是重建环）。
        assert len(ring) == 5, ring
        assert ring[0] == ring[-1], ring
        assert (round(ring[0][0], 1), round(ring[0][1], 1)) == (3.0, 3.0)
    finally:
        stack.set_map_tool(addr, "pan")
        if stack.mirror_layer_editing("doc-box"):
            stack.roll_back_mirror_layer("doc-box")


def test_line_layer_starts_native_editing(qtbot, stack):
    addr, _view = _canvas(qtbot, stack)
    try:
        _upsert_line(stack, "fault", [
            _line("a", [[0.0, 0.0], [1.0, 0.0]]),
        ])
        assert stack.start_mirror_layer_editing("fault") == ""
        assert stack.mirror_layer_editing("fault") is True
    finally:
        _cleanup(stack, addr, "fault")
