# -*- coding: utf-8 -*-
"""M3 Task 5: 键盘路径归一——原生工具占有 Esc 时取消语义留在画布侧。

- 桥级：采点进行中 native_tool_busy 为 True；postEvent Esc 后 digitize 回调
  收到 canceled 且 busy 归 False（工具保持激活）。
- controller 级：cancel_active_tool 按 native_tool_busy 分流——busy 时派发
  画布而不碰 Python 工具栈；非 busy 走旧 key_press("escape") 路径。
"""
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


@pytest.fixture()
def stack(qapp):
    from qgis_render_bridge.mapstack import QgisMapStack

    s = QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


def _show_canvas(qtbot, canvas):
    # QgsMapCanvas 是 QGraphicsView：鼠标事件必须发给 viewport()。
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QGraphicsView

    w = wrapInstance(canvas, QGraphicsView)
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    return w


def test_native_tool_busy_and_posted_escape_dispatch(qtbot, stack):
    canvas = stack.create_canvas()
    w = _show_canvas(qtbot, canvas)
    stack.set_canvas_extent(canvas, 0.0, 0.0, 10.0, 10.0)
    events = []
    stack.set_digitize_callback(canvas, lambda status, geom: events.append((status, geom)))
    stack.set_map_tool(canvas, "addLine")
    assert stack.native_tool_busy(canvas) is False

    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    QTest.mouseClick(w.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(100, 100))
    qtbot.waitUntil(lambda: stack.native_tool_busy(canvas), timeout=2000)

    # shim.cancel_native_tool 的派发路径：postEvent 直发画布
    QApplication.postEvent(
        w, QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    qtbot.waitUntil(lambda: any(s == "canceled" for s, _ in events), timeout=2000)
    assert not [g for s, g in events if s == "completed"]
    qtbot.waitUntil(lambda: not stack.native_tool_busy(canvas), timeout=2000)


class _FakeCanvas:
    def __init__(self, busy: bool):
        self._busy = busy
        self.cancel_calls = 0

    def native_tool_busy(self) -> bool:
        return self._busy

    def cancel_native_tool(self) -> None:
        self.cancel_calls += 1


def _project(tmp_path: Path):
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    return project


def test_cancel_active_tool_routes_to_native_when_busy(qtbot, tmp_path):
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller

    pressed = []
    original = controller.tools.key_press
    controller.tools.key_press = lambda key: pressed.append(key)  # noqa: E731
    try:
        canvas = _FakeCanvas(busy=True)
        controller._canvas = canvas
        controller.cancel_active_tool()
        assert canvas.cancel_calls == 1
        assert pressed == []  # busy 时不碰 Python 工具栈
    finally:
        controller.tools.key_press = original
        # orderly 关闭：宿主契约是显式 shutdown 回收镜像图层（qtbot 拆树
        # 不保证 destroyed 链时序），否则共享 QgsProject 泄漏到后续用例。
        document.shutdown()


def test_cancel_active_tool_falls_back_when_not_busy(qtbot, tmp_path):
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller

    pressed = []
    original = controller.tools.key_press
    controller.tools.key_press = lambda key: pressed.append(key)  # noqa: E731
    try:
        canvas = _FakeCanvas(busy=False)
        controller._canvas = canvas
        controller.cancel_active_tool()
        assert canvas.cancel_calls == 0
        assert pressed == ["escape"]
    finally:
        controller.tools.key_press = original
        document.shutdown()
