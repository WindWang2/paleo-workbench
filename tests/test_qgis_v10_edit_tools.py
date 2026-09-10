# -*- coding: utf-8 -*-
"""V10 native vertex tool: insert (double-click on segment) / delete (Delete on
hover) / min-vertex guard / snap feedback (indicator + throttled callback)。

像素映射：extent 0-10 on 400px → 40px/unit；(x,y) → (40x, 400-40y)。
"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon",
                      "coordinates": [[(5.0, 5.0), (8.0, 5.0), (8.0, 8.0), (5.0, 8.0), (5.0, 5.0)]]},
         "properties": {"__pwb_fid": "f1", "name": "A"}},
    ],
}

_TRIANGLE_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon",
                      "coordinates": [[(5.0, 5.0), (8.0, 5.0), (6.5, 8.0), (5.0, 5.0)]]},
         "properties": {"__pwb_fid": "f1"}},
    ],
}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _setup(qtbot, stack, kind, fc=None, snapping=None):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer("doc-poly", "相带", "Polygon", "EPSG:4326",
                              json.dumps(fc or _FC), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    if snapping is not None:
        stack.set_snapping_config(canvas, json.dumps(snapping))
    events = []
    stack.set_edit_pick_callback(
        canvas, lambda action, payload: events.append((action, json.loads(payload))))
    stack.set_map_tool(canvas, kind)
    return w, events


def _pixel(x: float, y: float):
    from PySide6.QtCore import QPoint

    return QPoint(int(40 * x), int(400 - 40 * y))


# -- 双击段上插点 ---------------------------------------------------------------


def test_vertex_tool_double_click_inserts_on_segment(qtbot, stack):
    # snapping 关闭：走容差拾取 + 单几何段投影回退路径。
    w, events = _setup(qtbot, stack, "vertex")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseDClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(6.5, 5.0))
    qtbot.waitUntil(lambda: any(a == "vertex_inserted" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "vertex_inserted"][-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert payload["feature_id"] == "f1"
    # 段 (5,5)-(8,5) 的第二端点是外环顶点 1 → 插入位 [0,1]。
    assert payload["path"] == [0, 1]
    assert abs(payload["x"] - 6.5) < 0.1
    assert abs(payload["y"] - 5.0) < 0.1


def test_vertex_tool_insert_with_snapping_uses_locator_path(qtbot, stack):
    # snapping 开启：走 QgsPointLocator::Match(Edge) 路径（vertexIndex=段首 → +1）。
    w, events = _setup(qtbot, stack, "vertex", snapping={
        "enabled": True, "mode": "all_layers", "tolerance_px": 20.0,
        "types": ["vertex", "segment"],
    })
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseDClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(6.5, 5.0))
    qtbot.waitUntil(lambda: any(a == "vertex_inserted" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "vertex_inserted"][-1]
    assert payload["path"] == [0, 1]


def test_vertex_tool_double_click_on_vertex_no_insert(qtbot, stack):
    w, events = _setup(qtbot, stack, "vertex")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseDClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, _pixel(5.0, 5.0))
    QTest.qWait(80)
    assert not [p for a, p in events if a == "vertex_inserted"]


# -- Delete 删除 hover 顶点 -----------------------------------------------------


def test_vertex_tool_delete_key_removes_hover_vertex(qtbot, stack):
    w, events = _setup(qtbot, stack, "vertex")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseMove(w.viewport(), _pixel(5.0, 5.0))
    QTest.qWait(60)
    QTest.keyClick(w, Qt.Key_Delete)
    qtbot.waitUntil(lambda: any(a == "vertex_deleted" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "vertex_deleted"][-1]
    assert payload["feature_id"] == "f1"
    # 恰在重复点上：严格 < 取首顶点 [0,0]（与宿主寻址约定一致）。
    assert payload["path"] == [0, 0]


def test_vertex_tool_delete_rejected_below_min_vertices(qtbot, stack):
    # 三角形 ring（3 真实 + 闭合 = 4 坐标）：删除任一顶点剩 3 < 4 → 拒绝。
    w, events = _setup(qtbot, stack, "vertex", fc=_TRIANGLE_FC)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseMove(w.viewport(), _pixel(5.0, 5.0))
    QTest.qWait(60)
    QTest.keyClick(w, Qt.Key_Delete)
    QTest.qWait(120)
    assert not [p for a, p in events if a == "vertex_deleted"]


def test_vertex_tool_delete_without_hover_noop(qtbot, stack):
    w, events = _setup(qtbot, stack, "vertex")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(w, Qt.Key_Delete)
    QTest.qWait(80)
    assert not [p for a, p in events if a == "vertex_deleted"]


# -- snap feedback（指示 + 节流回调） ---------------------------------------------


def test_snap_feedback_emitted_with_match_info(qtbot, stack):
    w, events = _setup(qtbot, stack, "vertex", snapping={
        "enabled": True, "mode": "all_layers", "tolerance_px": 20.0,
        "types": ["vertex"],
    })
    from PySide6.QtTest import QTest

    QTest.mouseMove(w.viewport(), _pixel(5.2, 5.1))
    qtbot.waitUntil(
        lambda: any(a == "snap_feedback" and p.get("matched") for a, p in events),
        timeout=2000)
    payload = [p for a, p in events if a == "snap_feedback" and p.get("matched")][-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert payload["feature_id"] == "f1"
    assert payload["match_type"] == "vertex"
    assert abs(payload["x"] - 5.0) < 1e-6
    assert abs(payload["y"] - 5.0) < 1e-6
    assert payload["distance"] >= 0.0


def test_snap_feedback_throttled_when_signature_stable(qtbot, stack):
    w, events = _setup(qtbot, stack, "vertex", snapping={
        "enabled": True, "mode": "all_layers", "tolerance_px": 20.0,
        "types": ["vertex"],
    })
    from PySide6.QtTest import QTest

    QTest.mouseMove(w.viewport(), _pixel(5.2, 5.1))
    qtbot.waitUntil(
        lambda: any(a == "snap_feedback" and p.get("matched") for a, p in events),
        timeout=2000)
    before = len([1 for a, _ in events if a == "snap_feedback"])
    # 同命中下的亚像素移动（< 1 像素）：不得产生新的反馈回调。
    QTest.mouseMove(w.viewport(), _pixel(5.21, 5.1))
    QTest.mouseMove(w.viewport(), _pixel(5.22, 5.1))
    QTest.qWait(120)
    after = len([1 for a, _ in events if a == "snap_feedback"])
    assert after == before


def test_snap_feedback_unmatched_when_disabled(qtbot, stack):
    # snapping 关闭（默认）：locator 无命中 → matched:false（节流：只发一次）。
    w, events = _setup(qtbot, stack, "vertex")
    from PySide6.QtTest import QTest

    QTest.mouseMove(w.viewport(), _pixel(6.5, 6.5))
    qtbot.waitUntil(
        lambda: any(a == "snap_feedback" and p.get("matched") is False
                    for a, p in events),
        timeout=2000)
    unmatched = [p for a, p in events if a == "snap_feedback" and not p.get("matched")]
    assert unmatched and unmatched[-1] == {"matched": False}
