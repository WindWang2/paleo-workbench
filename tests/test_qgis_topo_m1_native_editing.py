# -*- coding: utf-8 -*-
"""拓扑编辑迁移 M1：原生编辑 MVP——真桥面（规格 §8 → §2/§4）。

场景 5（层内拓扑）与原生会话生命周期在真实 QGIS 桥上验收；宿主侧
（场景 1/3/4、全或无保存、手势管理器）在 tests/test_topo_m1_native_editing.py。

像素映射：extent 0-10 on 400px → 40px/unit；(x, y) → (40x, 400-40y)。
"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

# 两面共享节点 (6, 6)：A 的右上角 == B 的左下角（1e-8 精确重合）。
_SHARED_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             (4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]]},
         "properties": {"__pwb_fid": "fa"}},
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


def _setup(qtbot, stack, fc=None):
    """镜像层 + 原生会话 + 当前层 + 顶点工具；返回 (viewport, events, deltas)。"""
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer("doc-draft", "相带草稿", "Polygon", "EPSG:4326",
                              json.dumps(fc or _SHARED_FC), "", "", "",
                              True, 1.0,
                              is_reference=False, is_editable=True,
                              data_revision=1)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    assert stack.start_mirror_layer_editing("doc-draft") == ""
    stack.set_current_layer(canvas, "doc-draft")
    events = []
    stack.set_edit_pick_callback(
        canvas, lambda action, payload: events.append(
            (action, json.loads(payload))))
    deltas = []
    stack.set_committed_callback(
        canvas, lambda doc, payload: deltas.append(json.loads(payload)))
    stack.set_map_tool(canvas, "vertex")
    return w, events, deltas


def _pixel(x: float, y: float):
    from PySide6.QtCore import QPoint

    return QPoint(int(40 * x), int(400 - 40 * y))


def _readback(stack):
    payload = json.loads(stack.mirror_features_json("doc-draft", 0))
    assert payload["exists"]
    return payload["features"]


def _ring_of(readback_features, host_id):
    # M1 读回注入 id = fid 表解析的宿主 feature_id
    for feature in readback_features:
        if str(feature.get("id")) == host_id:
            return feature["geometry"]["coordinates"][0]
    raise AssertionError(f"feature {host_id} not in readback")


def _has_vertex(ring, x, y, tol=0.05):
    return any(
        abs(float(px) - x) <= tol and abs(float(py) - y) <= tol
        for px, py in ring)


def test_scenario5_shared_node_drag_moves_both_one_macro_undo(qtbot, stack):
    """场景 5：拖动共享节点 → 两面同步移动；一次 undo 整体回退，无缝隙。"""
    w, events, _deltas = _setup(qtbot, stack)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    # 拖动共享节点 (6,6) → (7,7)
    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                     _pixel(6.0, 6.0))
    QTest.mouseMove(w.viewport(), _pixel(7.0, 7.0))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                       _pixel(7.0, 7.0))
    qtbot.waitUntil(
        lambda: any(a == "edit_gesture" for a, _ in events), timeout=2000)

    gesture = [p for a, p in events if a == "edit_gesture"][-1]
    assert gesture["gesture"] in ("vertex_move", "vertex_move_multi")
    assert gesture["undo_text"] in ("Moved vertex", "Moved vertices")
    assert sorted(gesture["features"]) == ["fa", "fb"], "共享节点联合移动"

    ring_a = _ring_of(_readback(stack), "fa")
    ring_b = _ring_of(_readback(stack), "fb")
    assert _has_vertex(ring_a, 7.0, 7.0) and _has_vertex(ring_b, 7.0, 7.0)
    # 无缝隙：共享节点移动后仍精确重合（6,6 不再出现于任何一面）
    assert not _has_vertex(ring_a, 6.0, 6.0)
    assert not _has_vertex(ring_b, 6.0, 6.0)

    # 一次 undo（层内一宏）整体回退
    assert stack.undo_mirror_edit("doc-draft") == ""
    ring_a = _ring_of(_readback(stack), "fa")
    ring_b = _ring_of(_readback(stack), "fb")
    assert _has_vertex(ring_a, 6.0, 6.0) and _has_vertex(ring_b, 6.0, 6.0)
    assert not _has_vertex(ring_a, 7.0, 7.0)
    assert not _has_vertex(ring_b, 7.0, 7.0)


def test_scenario5_commit_emits_geometry_delta_for_both(qtbot, stack):
    """提交后 committed 增量含两要素几何变化（宿主回写通道输入）。"""
    w, events, deltas = _setup(qtbot, stack)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                     _pixel(6.0, 6.0))
    QTest.mouseMove(w.viewport(), _pixel(7.0, 7.0))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                       _pixel(7.0, 7.0))
    qtbot.waitUntil(
        lambda: any(a == "edit_gesture" for a, _ in events), timeout=2000)

    assert stack.commit_mirror_layer("doc-draft") == ""
    assert len(deltas) == 1
    delta = deltas[0]
    changed = sorted(
        entry["feature_id"] for entry in delta["geometry_changes"])
    assert changed == ["fa", "fb"]
    assert delta["doc_id"] == "doc-draft"
    assert stack.mirror_layer_editing("doc-draft") is False


def test_rollback_restores_session_baseline(qtbot, stack):
    """快照基线回滚：编辑后 rollBack → 镜像复位到会话开启时状态。"""
    w, events, _deltas = _setup(qtbot, stack)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                     _pixel(6.0, 6.0))
    QTest.mouseMove(w.viewport(), _pixel(7.0, 7.0))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                       _pixel(7.0, 7.0))
    qtbot.waitUntil(
        lambda: any(a == "edit_gesture" for a, _ in events), timeout=2000)

    assert stack.roll_back_mirror_layer("doc-draft") == ""
    assert stack.mirror_layer_editing("doc-draft") is False
    assert _has_vertex(_ring_of(_readback(stack), "fa"), 6.0, 6.0)
    assert not _has_vertex(_ring_of(_readback(stack), "fb"), 7.0, 7.0)


def test_v1_mode_when_no_session_keeps_callback_behavior(qtbot, stack):
    """无原生会话 → 工具保持 v1 回调模式（M1 之前的行为不变）。"""
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer("doc-poly", "层", "Polygon", "EPSG:4326",
                              json.dumps(_SHARED_FC), "", "", "",
                              True, 1.0, is_reference=False,
                              is_editable=True)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_edit_pick_callback(
        canvas, lambda action, payload: events.append(
            (action, json.loads(payload))))
    stack.set_map_tool(canvas, "vertex")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                     _pixel(6.0, 6.0))
    QTest.mouseMove(w.viewport(), _pixel(7.0, 7.0))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier,
                       _pixel(7.0, 7.0))
    qtbot.waitUntil(
        lambda: any(a == "vertex_moved" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "vertex_moved"][-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert payload["feature_id"] in ("fa", "fb")  # v1：单要素回调


def test_add_feature_macro_and_committed_pairing(qtbot, stack):
    """编辑会话中数字化：add_mirror_feature 一宏可撤；commit 增量按宿主
    id 配对（fid 表按 provider 现值重建）。"""
    w, _events, deltas = _setup(qtbot, stack)
    feature = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[
            (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)]]},
        "properties": {"__pwb_fid": "fnew"},
    }
    assert stack.add_mirror_feature("doc-draft", json.dumps(feature)) == ""
    assert len(_readback(stack)) == 3
    assert stack.undo_mirror_edit("doc-draft") == ""
    assert len(_readback(stack)) == 2
    assert stack.redo_mirror_edit("doc-draft") == ""
    assert stack.commit_mirror_layer("doc-draft") == ""
    assert len(deltas) == 1
    added = deltas[0]["added"]
    assert len(added) == 1
    assert added[0]["properties"]["__pwb_fid"] == "fnew"
