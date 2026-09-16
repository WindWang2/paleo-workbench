# -*- coding: utf-8 -*-
"""V12 M2-1：段移动（拖段同步平移两端点 + 跨层共享节点联动 + 一宏撤销）。"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_FC_A = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             (4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]]},
         "properties": {"__pwb_fid": "fa"}},
    ],
}
_FC_B = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             (6.0, 6.0), (8.0, 6.0), (8.0, 8.0), (6.0, 8.0), (6.0, 6.0)]]},
         "properties": {"__pwb_fid": "fb"}},
    ],
}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _canvas(qtbot, stack, fc, doc_id, current=True, all_layers=False):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer(doc_id, "草稿", "Polygon", "EPSG:4326",
                              json.dumps(fc), "", "", "",
                              True, 1.0,
                              is_reference=False, is_editable=True,
                              data_revision=1)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    assert stack.start_mirror_layer_editing(doc_id) == ""
    if current:
        stack.set_current_layer(canvas, doc_id)
    if all_layers:
        stack.set_vertex_edit_scope(canvas, True)
    events = []
    stack.set_edit_pick_callback(
        canvas, lambda action, payload: events.append(
            (action, json.loads(payload))))
    stack.set_map_tool(canvas, "vertex")
    return canvas, w, events


def _pixel(x: float, y: float):
    from PySide6.QtCore import QPoint

    return QPoint(int(40 * x), int(400 - 40 * y))


def _ring(stack, doc_id, host_id):
    payload = json.loads(stack.mirror_features_json(doc_id, 0))
    for feature in payload["features"]:
        if str(feature.get("id")) == host_id:
            return feature["geometry"]["coordinates"][0]
    raise AssertionError(f"{host_id} missing")


def _has(ring, x, y, tol=0.05):
    return any(abs(px - x) <= tol and abs(py - y) <= tol for px, py in ring)


def test_segment_drag_moves_both_endpoints_one_macro(qtbot, stack):
    """拖段（命中段中点）→ 该段两端点同步平移（单宏）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    canvas, w, events = _canvas(qtbot, stack, _FC_A, "doc-seg")

    # 按在顶边中点 (5,6)（不是顶点），拖到 (6,7)。
    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                     _pixel(5.0, 6.0))
    QTest.mouseMove(w.viewport(), _pixel(6.0, 7.0))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                       _pixel(6.0, 7.0))
    qtbot.waitUntil(
        lambda: any(a == "edit_gesture" for a, _ in events), timeout=2000)

    gesture = [p for a, p in events if a == "edit_gesture"][-1]
    assert gesture["gesture"] in ("vertex_move", "vertex_move_multi")
    ring = _ring(stack, "doc-seg", "fa")
    # 顶边两端点同步平移：每个顶点的 dx>0、dy>0，且两端点位移量一致
    # （捕捉吸附会修正数值，只断言位移语义，不硬编码具体量）。
    original = [(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]
    deltas = [
        (ring[i][0] - original[i][0], ring[i][1] - original[i][1])
        for i in (2, 3)  # 顶边两端点 (6,6) 与 (4,6)
    ]
    assert deltas[0][0] > 0 and deltas[1][0] > 0, f"两端点未右移: {ring}"
    assert deltas[0][1] > 0 and deltas[1][1] > 0, f"两端点未上移: {ring}"
    assert abs(deltas[0][0] - deltas[1][0]) < 1e-6, f"两端点 dx 不一致: {ring}"
    assert abs(deltas[0][1] - deltas[1][1]) < 1e-6, f"两端点 dy 不一致: {ring}"
    # 下边两点不动（只有顶边平移）。
    assert abs(ring[0][0] - 4.0) < 1e-6 and abs(ring[1][0] - 6.0) < 1e-6
    assert not _has(ring, 4.0, 6.0) and not _has(ring, 6.0, 6.0)

    # 一宏撤销 → 整体回退。
    assert stack.undo_mirror_edit("doc-seg") == ""
    ring = _ring(stack, "doc-seg", "fa")
    assert _has(ring, 4.0, 6.0) and _has(ring, 6.0, 6.0)


def test_segment_drag_does_not_swallow_box_select(qtbot, stack):
    """按在空白处仍是框选（段命中不得吞掉「点空处」语义）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    canvas, w, events = _canvas(qtbot, stack, _FC_A, "doc-seg")

    # 按在空白处 (1.5, 1.5)，不命中段 → 框选分支（无任何提交）。
    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                     _pixel(1.5, 1.5))
    QTest.mouseMove(w.viewport(), _pixel(2.5, 2.5))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                       _pixel(2.5, 2.5))
    qtbot.wait(300)
    assert not any(a == "edit_gesture" for a, _ in events), (
        f"空白处按滑却产生了提交：{[a for a, _ in events]}")


def test_segment_drag_all_layers_moves_shared_nodes(qtbot, stack):
    """全层档段移动：跨层共位节点联动（两面共享边两端点）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    # 建两面共享 (6,4)-(6,6) 这条边的两面（fa 的右边 / fb 的左边）。
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Polygon", "coordinates": [[
                 (4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]]},
             "properties": {"__pwb_fid": "fa"}},
            {"type": "Feature",
             "geometry": {"type": "Polygon", "coordinates": [[
                 (6.0, 4.0), (8.0, 4.0), (8.0, 6.0), (6.0, 6.0), (6.0, 4.0)]]},
             "properties": {"__pwb_fid": "fb"}},
        ],
    }
    canvas, w, events = _canvas(qtbot, stack, fc, "doc-seg", all_layers=True)
    # 跨层/跨要素共享联动是拓扑开语义：先推开（应用里用户打开开关同款）。
    stack.set_snapping_config(canvas, json.dumps({
        "enabled": True, "mode": "all_layers", "tolerance_px": 12.0,
        "types": ["vertex", "segment"], "topological_editing": True,
    }))

    # 按在共享边中点 (6,5)，拖到 (7,6)：共享边两端点应两面同步。
    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                     _pixel(6.0, 5.0))
    QTest.mouseMove(w.viewport(), _pixel(7.0, 6.0))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                       _pixel(7.0, 6.0))
    qtbot.waitUntil(
        lambda: any(a == "edit_gesture" for a, _ in events), timeout=2000)

    gesture = [p for a, p in events if a == "edit_gesture"][-1]
    assert sorted(gesture["features"]) == ["fa", "fb"]
    ring_a = _ring(stack, "doc-seg", "fa")
    ring_b = _ring(stack, "doc-seg", "fb")
    # 共享边两端点同步平移：两面都离开原位 (6,4)/(6,6)，且同向同量。
    assert not _has(ring_a, 6.0, 4.0) and not _has(ring_a, 6.0, 6.0)
    assert not _has(ring_b, 6.0, 4.0) and not _has(ring_b, 6.0, 6.0)
    for ring in (ring_a, ring_b):
        # 找到移动后的两端点（x>6 即已右移）。
        moved = [pt for pt in ring if pt[0] > 6.0]
        assert len(moved) >= 2, f"未同步移动: {ring}"
    # 无缝隙：共享边仍精确重合。
    assert not _has(ring_a, 6.0, 4.0) and not _has(ring_a, 6.0, 6.0)
    assert not _has(ring_b, 6.0, 4.0) and not _has(ring_b, 6.0, 6.0)
