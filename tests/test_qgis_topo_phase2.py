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


def _box_select_then_translate(qtbot, stack, modifier):
    """空处拖框选中两点 → 拖其中一点 → 两点平移同一向量。"""
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

        QTest.mousePress(view.viewport(), Qt.LeftButton, modifier,
                         _pixel(1.5, 1.5))
        QTest.mouseMove(view.viewport(), _pixel(6.5, 2.5))
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, modifier,
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


def test_box_select_translates_distinct_vertices(qtbot, stack):
    """§4 框选多节点：空处拖框选中两点，再拖其中一点，两点平移同一向量。"""
    from PySide6.QtCore import Qt

    _box_select_then_translate(qtbot, stack, Qt.NoModifier)


def test_shift_box_select_translates_distinct_vertices(qtbot, stack):
    """§4 规格写法：Shift+拖框同样进入框选（修饰键不拦截该手势）。"""
    from PySide6.QtCore import Qt

    _box_select_then_translate(qtbot, stack, Qt.ShiftModifier)


def test_tracing_inserts_vertices_at_intersections(qtbot, stack):
    """§4 追踪交点插点：追踪沿边 + 与其他边相交处插入交点顶点。

    追踪开着时 QgsTracer 取 setAddPointsOnIntersectionsEnabled——沿水平
    引导线 (2,5)→(8,5) 追踪，与竖直引导线 (5,2)→(5,8) 的交点 (5,5) 必须
    成为环上顶点，否则新面与该边仍是两点相切（后续拓扑检查看不到共享点）。
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    addr = stack.create_canvas()
    view = wrapInstance(addr, QGraphicsView)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.show()
    guides = _collection(
        _line("h", [[2.0, 5.0], [8.0, 5.0]]),
        _line("v", [[5.0, 2.0], [5.0, 8.0]]),
    )
    try:
        stack.upsert_mirror_layer(
            "guide-x", "引导线", "LineString", "EPSG:4326", guides,
            "", "", "", True, 1.0, is_reference=False, is_editable=True,
            data_revision=1)
        stack.upsert_mirror_layer(
            "draft-x", "草稿", "Polygon", "EPSG:4326", _collection(),
            "", "", "", True, 1.0, is_reference=False, is_editable=True,
            data_revision=1)
        stack.set_canvas_extent(addr, 0.0, 0.0, 10.0, 10.0)
        assert stack.start_mirror_layer_editing("draft-x") == ""
        stack.set_current_layer(addr, "draft-x")
        captured = []
        stack.set_digitize_callback(
            addr, lambda status, geom: captured.append((status, geom)))
        stack.set_tracing_enabled(addr, True)
        stack.set_snapping_config(addr, json.dumps({
            "enabled": True, "mode": "all_layers", "tolerance_px": 20.0,
            "types": ["vertex", "segment"],
        }))
        stack.set_map_tool(addr, "addPolygon")

        def _pixel(x, y):
            return QPoint(int(40 * x), int(400 - 40 * y))

        for x, y in [(2.0, 5.0), (8.0, 5.0), (8.0, 2.0), (2.0, 2.0)]:
            QTest.mouseMove(view.viewport(), _pixel(x, y))
            QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                             _pixel(x, y))
        QTest.mouseClick(view.viewport(), Qt.RightButton, Qt.NoModifier,
                         _pixel(2.0, 2.0))
        qtbot.waitUntil(
            lambda: any(s == "completed" for s, _ in captured), timeout=3000)
        ring = json.loads(
            [g for s, g in captured if s == "completed"][-1]
        )["coordinates"][0]
        assert any(abs(float(px) - 5.0) <= 0.05 and abs(float(py) - 5.0) <= 0.05
                   for px, py in ring), f"交点未插入环（ring={ring}）"
    finally:
        stack.set_tracing_enabled(addr, False)
        stack.set_map_tool(addr, "pan")
        for doc in ("draft-x", "guide-x"):
            if stack.mirror_layer_editing(doc):
                stack.roll_back_mirror_layer(doc)


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
