# -*- coding: utf-8 -*-
"""M3 Task 2: 原生采点/线/面工具 digitizingCompleted 几何回调。"""
import json

import pytest

pytest.importorskip("PySide6")


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _show_canvas(qtbot, canvas):
    # QgsMapCanvas 是 QGraphicsView：鼠标事件必须发给 viewport()，
    # 否则事件落在 scroll-area 框体上不会被 canvas 处理。
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    return w


def _click(w, button, pos):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt

    QTest.mouseClick(w.viewport(), button, Qt.NoModifier, pos)


def test_add_point_tool_emits_completed_geometry(qtbot, stack):
    canvas = stack.create_canvas()
    w = _show_canvas(qtbot, canvas)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_digitize_callback(canvas, lambda status, geom: events.append((status, geom)))
    stack.set_map_tool(canvas, "addPoint")
    from PySide6.QtCore import Qt

    _click(w, Qt.LeftButton, w.viewport().rect().center())
    qtbot.waitUntil(lambda: len(events) >= 1, timeout=2000)
    status, geom = events[-1]
    assert status == "completed"
    g = json.loads(geom)
    assert g["type"] == "Point"
    assert abs(g["coordinates"][0] - 5.0) < 0.2
    assert abs(g["coordinates"][1] - 5.0) < 0.2


def test_add_line_tool_right_click_finishes(qtbot, stack):
    canvas = stack.create_canvas()
    w = _show_canvas(qtbot, canvas)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_digitize_callback(canvas, lambda status, geom: events.append((status, geom)))
    stack.set_map_tool(canvas, "addLine")
    from PySide6.QtCore import Qt, QPoint

    _click(w, Qt.LeftButton, QPoint(100, 100))
    _click(w, Qt.LeftButton, QPoint(300, 300))
    _click(w, Qt.RightButton, QPoint(300, 300))
    qtbot.waitUntil(lambda: any(s == "completed" for s, _ in events), timeout=2000)
    g = json.loads([g for s, g in events if s == "completed"][-1])
    assert g["type"] in ("LineString", "MultiLineString")
    coords = g["coordinates"]
    if g["type"] == "MultiLineString":
        coords = coords[0]
    assert len(coords) == 2
    assert abs(coords[0][0] - 2.5) < 0.2  # 100/400 * 10
    assert abs(coords[1][0] - 7.5) < 0.2


def test_escape_cancels_digitizing(qtbot, stack):
    canvas = stack.create_canvas()
    w = _show_canvas(qtbot, canvas)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_digitize_callback(canvas, lambda status, geom: events.append((status, geom)))
    stack.set_map_tool(canvas, "addLine")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint

    _click(w, Qt.LeftButton, QPoint(100, 100))
    QTest.keyClick(w, Qt.Key_Escape)
    qtbot.waitUntil(lambda: any(s == "canceled" for s, _ in events), timeout=2000)
    assert not [g for s, g in events if s == "completed"]


def test_unknown_tool_kind_falls_back_or_raises(stack):
    canvas = stack.create_canvas()
    with pytest.raises(Exception):
        stack.set_map_tool(canvas, "no_such_tool")
