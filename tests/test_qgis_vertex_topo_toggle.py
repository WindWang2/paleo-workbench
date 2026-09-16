# -*- coding: utf-8 -*-
"""顶点拖拽服从工程拓扑开关（用户现场：开关关了仍一起拖）。

两相邻正方形共用 x=5 的边（同一层）：拓扑开 → 拖共位顶点两要素同动
（edit_gesture=vertex_move_multi）；拓扑关 → 只动按中的那一个要素
（vertex_move）。QGIS 语义：开关管的是"共位邻居是否联动"。
"""
import contextlib
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon",
                      "coordinates": [[(2.0, 2.0), (5.0, 2.0), (5.0, 5.0), (2.0, 5.0), (2.0, 2.0)]]},
         "properties": {"__pwb_fid": "fA"}},
        {"type": "Feature",
         "geometry": {"type": "Polygon",
                      "coordinates": [[(5.0, 2.0), (8.0, 2.0), (8.0, 5.0), (5.0, 5.0), (5.0, 2.0)]]},
         "properties": {"__pwb_fid": "fB"}},
    ],
}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


@contextlib.contextmanager
def _setup(qtbot, stack):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer("doc-adj", "相邻相带", "Polygon", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    assert stack.start_mirror_layer_editing("doc-adj") == ""
    stack.set_current_layer(canvas, "doc-adj")
    events = []
    stack.set_edit_pick_callback(
        canvas, lambda action, payload: events.append((action, json.loads(payload))))
    stack.set_map_tool(canvas, "vertex")
    try:
        yield w, canvas, events
    finally:
        stack.set_map_tool(canvas, "pan")
        if stack.mirror_layer_editing("doc-adj"):
            stack.roll_back_mirror_layer("doc-adj")
        # 单例拓扑开关是进程级状态：恢复默认关，不污染后续用例。
        stack.set_snapping_config(canvas, json.dumps({
            "enabled": True, "mode": "all_layers", "tolerance_px": 12.0,
            "types": ["vertex", "segment"], "topological_editing": False,
        }))


def _push_topo(stack, canvas, on: bool) -> None:
    stack.set_snapping_config(canvas, json.dumps({
        "enabled": True,
        "mode": "all_layers",
        "tolerance_px": 12.0,
        "types": ["vertex", "segment"],
        "topological_editing": on,
    }))


def _drag_shared_vertex(qtbot, w):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    # 共位顶点 (5,5) → (200,200)；拖到 (6,6) → (240,160)
    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    QTest.mouseMove(w.viewport(), QPoint(240, 160))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(240, 160))


def _gestures(events):
    return [(a, p) for a, p in events
            if a == "edit_gesture" and p.get("gesture", "").startswith("vertex_move")]


def test_vertex_drag_topo_off_moves_single_feature(qtbot, stack):
    """用户现场：先开后关 → 关后拖共位顶点只动一个要素。"""
    with _setup(qtbot, stack) as (w, canvas, events):
        _push_topo(stack, canvas, True)
        _push_topo(stack, canvas, False)
        _drag_shared_vertex(qtbot, w)
        qtbot.waitUntil(lambda: bool(_gestures(events)), timeout=3000)
        action, payload = _gestures(events)[-1]
        assert payload["gesture"] == "vertex_move", payload
        assert len(payload["features"]) == 1, payload


def test_vertex_drag_topo_on_moves_both_features(qtbot, stack):
    """对照：开 → 共位顶点两要素同动。"""
    with _setup(qtbot, stack) as (w, canvas, events):
        _push_topo(stack, canvas, True)
        _drag_shared_vertex(qtbot, w)
        qtbot.waitUntil(lambda: bool(_gestures(events)), timeout=3000)
        print("ALL:", [(a, p) for a, p in events])
        action, payload = _gestures(events)[-1]
        assert payload["gesture"] == "vertex_move_multi", payload
        assert sorted(payload["features"]) == ["fA", "fB"], payload
