# -*- coding: utf-8 -*-
"""M3 Task 3: 桥内顶点编辑/要素移动工具——拾取 + rubber band 预览 + 回调。"""
import json

import pytest

pytest.importorskip("PySide6")

# 正方形环：顶点序 (5,5)(8,5)(8,8)(5,8)，闭合回 (5,5)
_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon",
                      "coordinates": [[(5.0, 5.0), (8.0, 5.0), (8.0, 8.0), (5.0, 8.0), (5.0, 5.0)]]},
         "properties": {"__pwb_fid": "f1", "name": "A"}},
    ],
}


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _setup(qtbot, stack, kind):
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer("doc-poly", "相带", "Polygon", "EPSG:4326",
                              json.dumps(_FC), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    # 加图层后画布自动缩放到图层范围，extent 必须在 add 之后设置
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_edit_pick_callback(
        canvas, lambda action, payload: events.append((action, json.loads(payload))))
    stack.set_map_tool(canvas, kind)
    return w, events


def test_vertex_tool_drag_emits_vertex_moved(qtbot, stack):
    w, events = _setup(qtbot, stack, "vertex")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    # 顶点 (5,5) → 像素 (200,200)；拖到 (6,6) → (240,160)
    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    QTest.mouseMove(w.viewport(), QPoint(240, 160))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(240, 160))
    qtbot.waitUntil(lambda: any(a == "vertex_moved" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "vertex_moved"][-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert payload["feature_id"] == "f1"
    assert payload["path"] == [0, 0]  # 外环第 0 顶点
    assert abs(payload["x"] - 6.0) < 0.2
    assert abs(payload["y"] - 6.0) < 0.2


def test_move_tool_drag_emits_feature_moved(qtbot, stack):
    w, events = _setup(qtbot, stack, "move")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    # 面内 (6.5,6.5) → (260,140)；向右拖 40px ≈ +1.0 地图单位
    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(260, 140))
    QTest.mouseMove(w.viewport(), QPoint(300, 140))
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(300, 140))
    qtbot.waitUntil(lambda: any(a == "feature_moved" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "feature_moved"][-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert payload["feature_id"] == "f1"
    assert abs(payload["dx"] - 1.0) < 0.2
    assert abs(payload["dy"] - 0.0) < 0.2


def test_vertex_tool_pick_miss(qtbot, stack):
    w, events = _setup(qtbot, stack, "vertex")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    # 空白处 (1,9) → (40,40)
    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    qtbot.waitUntil(lambda: any(a == "pick_miss" for a, _ in events), timeout=2000)
    assert not [p for a, p in events if a in ("vertex_moved", "feature_moved")]


def test_vertex_tool_escape_cancels_drag(qtbot, stack):
    w, events = _setup(qtbot, stack, "vertex")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    QTest.mousePress(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    QTest.mouseMove(w.viewport(), QPoint(240, 160))
    QTest.keyClick(w, Qt.Key_Escape)
    QTest.mouseRelease(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(240, 160))
    # 充分处理后仍无 vertex_moved
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    QTest.qWait(50)
    assert not [p for a, p in events if a == "vertex_moved"]
