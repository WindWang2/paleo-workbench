# -*- coding: utf-8 -*-
"""M3 Task 4: 原生选择/identify 工具 + 选中高亮。"""
import json

import pytest

pytest.importorskip("PySide6")

_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon",
                      "coordinates": [[[5.0, 5.0], [8.0, 5.0], [8.0, 8.0], [5.0, 8.0], [5.0, 5.0]]]},
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
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    stack.set_current_layer(canvas, "doc-poly")
    events = []
    stack.set_selection_callback(
        canvas, lambda action, payload: events.append((action, json.loads(payload))))
    stack.set_map_tool(canvas, kind)
    return canvas, w, events


def _drag(w, start, end):
    """显式 buttons 状态的拖动（QTest.mouseMove 不带 buttons，
    QgsMapToolSelectionHandler 的框选分支要求 buttons()==LeftButton）。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    vp = w.viewport()

    def ev(etype, pos, button, buttons):
        return QMouseEvent(etype, QPointF(pos),
                           QPointF(vp.mapToGlobal(pos)),
                           button, buttons, Qt.NoModifier)

    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonPress, start,
                                  Qt.LeftButton, Qt.LeftButton))
    # 首个 move 事件的橡皮筋矩形恒为退化点（handler 的 mSelectionActive
    # 初始分支），真实拖动的第二个 move 才展开成 start→end 矩形
    mid = type(start)((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseMove, mid,
                                  Qt.NoButton, Qt.LeftButton))
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseMove, end,
                                  Qt.NoButton, Qt.LeftButton))
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonRelease, end,
                                  Qt.LeftButton, Qt.NoButton))


def test_select_drag_rectangle_selects_feature(qtbot, stack):
    canvas, w, events = _setup(qtbot, stack, "select")
    from PySide6.QtCore import QPoint

    _drag(w, QPoint(150, 50), QPoint(350, 250))
    qtbot.waitUntil(lambda: any(a == "selection" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "selection"][-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert "f1" in payload["feature_ids"]
    assert payload["modifiers"] == []


def test_select_click_miss_clears(qtbot, stack):
    canvas, w, events = _setup(qtbot, stack, "select")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    # 空白处 (1,9) → (40,40)
    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    qtbot.waitUntil(lambda: any(a == "selection" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "selection"][-1]
    assert payload["feature_ids"] == []


def test_identify_click_reports_feature(qtbot, stack):
    canvas, w, events = _setup(qtbot, stack, "identify")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    # 面内 (6.5,6.5) → (260,140)
    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(260, 140))
    qtbot.waitUntil(lambda: any(a == "identify" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "identify"][-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert payload["feature_id"] == "f1"


def test_highlight_features_roundtrip(qtbot, stack):
    canvas, w, events = _setup(qtbot, stack, "pan")
    assert stack.highlight_count(canvas) == 0
    stack.highlight_features(canvas, "doc-poly", json.dumps(["f1"]))
    assert stack.highlight_count(canvas) == 1
    stack.highlight_features(canvas, "doc-poly", json.dumps(["f1", "unknown"]))
    assert stack.highlight_count(canvas) == 1  # 未知 id 跳过
    stack.clear_highlights(canvas)
    assert stack.highlight_count(canvas) == 0
