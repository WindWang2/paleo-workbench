# -*- coding: utf-8 -*-
"""M3 Task 4: 原生选择/identify 工具 + 选中高亮。"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

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


def test_identify_click_hits_without_current_layer(qtbot, stack):
    """识别不得依赖 canvas.currentLayer：未选活动层时点击要素仍须回报。"""
    canvas, w, events = _setup(qtbot, stack, "pan")
    stack.set_current_layer(canvas, "")
    events.clear()
    stack.set_map_tool(canvas, "identify")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(260, 140))
    qtbot.waitUntil(lambda: any(a == "identify" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "identify"][-1]
    assert payload["layer_doc_id"] == "doc-poly"
    assert payload["feature_id"] == "f1"


def test_identify_miss_emits_empty_payload(qtbot, stack):
    canvas, w, events = _setup(qtbot, stack, "identify")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    qtbot.waitUntil(lambda: any(a == "identify" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "identify"][-1]
    assert payload.get("feature_id") in ("", None)
    assert payload.get("layer_doc_id") in ("", None)


_BOTTOM_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon",
                      "coordinates": [[[1.0, 1.0], [7.0, 1.0], [7.0, 7.0], [1.0, 7.0], [1.0, 1.0]]]},
         "properties": {"__pwb_fid": "bottom-f1", "name": "底层大面"}},
    ],
}
_TOP_FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [4.0, 4.0]},
         "properties": {"__pwb_fid": "top-p1", "name": "顶层井点"}},
    ],
}


def test_identify_topmost_layer_wins_over_containing_polygon(qtbot, stack):
    """识别语义：点在顶层点要素上时不得命中包住它的底层大面。

    底层多边形与顶层井点 distance 同为 0——按层序最上者胜
    （生产场景：工区 boundary 盖住全部井位，先扫先得会把每次
    井点点击都识别成 boundary）。仅顶层命中区域外仍可识别底层。
    """
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer("doc-bottom", "工区面", "Polygon", "EPSG:4326",
                              json.dumps(_BOTTOM_FC), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.upsert_mirror_layer("doc-top", "井位", "Point", "EPSG:4326",
                              json.dumps(_TOP_FC), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_selection_callback(
        canvas, lambda action, payload: events.append((action, json.loads(payload))))
    stack.set_map_tool(canvas, "identify")

    # 井点 (4,4) 同时在底层大面内 → (162,238)：须命中顶层井点
    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(162, 238))
    qtbot.waitUntil(lambda: any(a == "identify" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "identify"][-1]
    assert payload["layer_doc_id"] == "doc-top"
    assert payload["feature_id"] == "top-p1"

    # 面内非井点 (2,2) → (80,240)：无顶层命中，仍识别底层大面
    events.clear()
    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(80, 240))
    qtbot.waitUntil(lambda: any(a == "identify" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "identify"][-1]
    assert payload["layer_doc_id"] == "doc-bottom"
    assert payload["feature_id"] == "bottom-f1"


_SAME_SPOT_BOTTOM = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [4.0, 4.0]},
         "properties": {"__pwb_fid": "same-bottom"}},
    ],
}
_SAME_SPOT_TOP = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [4.0, 4.0]},
         "properties": {"__pwb_fid": "same-top"}},
    ],
}


def test_identify_overlapping_point_layers(qtbot, stack):
    """同 rank（点）同距离（同坐标）：视觉最上层点要素胜出。

    后 upsert 的层在图例中位于其上（canvas 树首个子节点为顶层），
    识别应取画面上可见压住下层的那个点——方向由本测试锚定，
    若桥层序语义反转则此处翻转。
    """
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    canvas = stack.create_canvas()
    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    stack.upsert_mirror_layer("same-bottom", "下层点", "Point", "EPSG:4326",
                              json.dumps(_SAME_SPOT_BOTTOM), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.upsert_mirror_layer("same-top", "上层点", "Point", "EPSG:4326",
                              json.dumps(_SAME_SPOT_TOP), "", "", "", True, 1.0,
                              is_reference=False, is_editable=True)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_selection_callback(
        canvas, lambda action, payload: events.append((action, json.loads(payload))))
    stack.set_map_tool(canvas, "identify")

    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(162, 238))
    qtbot.waitUntil(lambda: any(a == "identify" for a, _ in events), timeout=2000)
    payload = [p for a, p in events if a == "identify"][-1]
    assert payload["layer_doc_id"] == "same-top"
    assert payload["feature_id"] == "same-top"


def test_highlight_features_roundtrip(qtbot, stack):
    canvas, w, events = _setup(qtbot, stack, "pan")
    assert stack.highlight_count(canvas) == 0
    stack.highlight_features(canvas, "doc-poly", json.dumps(["f1"]))
    assert stack.highlight_count(canvas) == 1
    stack.highlight_features(canvas, "doc-poly", json.dumps(["f1", "unknown"]))
    assert stack.highlight_count(canvas) == 1  # 未知 id 跳过
    stack.clear_highlights(canvas)
    assert stack.highlight_count(canvas) == 0
