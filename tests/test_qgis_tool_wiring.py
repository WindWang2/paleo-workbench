# -*- coding: utf-8 -*-
"""M3 真机回归：shim 把宿主工具激活映射到原生 QgsMapTool kind。

覆盖审查缺口 T1：activate_tool → tools.set_active_tool → 桥 set_map_tool
的整条链路（tool-id→kind 映射表打错字会静默回落 pan，桥级测试全绿而
真机无法编辑——2026-09-04 真机回归即此因：attach_canvas 直传工具栈，
shim 只认带 .tools 属性的控制器，包装从未安装）。
"""
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis


def _project(tmp_path: Path):
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    return project


def test_shim_maps_tool_ids_to_native_kinds(qtbot, tmp_path, monkeypatch):
    from qgis_render_bridge.mapstack import QgisMapStack
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    calls = []
    original = QgisMapStack.set_map_tool

    def spy(self, addr, kind):
        calls.append((int(addr), kind))
        return original(self, addr, kind)

    monkeypatch.setattr(QgisMapStack, "set_map_tool", spy)

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    document.show()
    canvas_addr = int(document.canvas.canvas_address)

    controller = document.edit_controller
    point = controller.create_layer("井点", "point")
    line = controller.create_layer("断层", "line")
    poly = controller.create_layer("相带", "polygon")
    controller.start_editing()

    def kinds():
        return [kind for addr, kind in calls if addr == canvas_addr]

    cases = [
        (point.id, "add_point", "addPoint"),
        (line.id, "add_line", "addLine"),
        (poly.id, "add_polygon", "addPolygon"),
        (point.id, "vertex", "vertex"),
        (point.id, "move_feature", "move"),
        (point.id, "select", "select"),
        (point.id, "select_rectangle", "select"),
        (point.id, "pan", "pan"),
    ]
    for layer_id, action_id, expected in cases:
        controller.set_active_layer(layer_id)
        controller.start_editing()  # 编辑会话按图层开启（QGIS 语义）
        before = len(kinds())
        controller.activate_tool(action_id)
        new = kinds()[before:]
        assert new and new[-1] == expected, (
            f"{action_id} 应映射原生 kind {expected}，实际 {new or '（未调用 set_map_tool）'}"
        )


def test_cad_dock_stays_hidden(qtbot, qapp):
    """隐藏高级数字化 dock（M3 Task 1 真机回归）：QDockWidget 非浮动子控件
    会随父画布 show 被 Qt 递归显示；构造后必须显式 hide，且激活采点工具
    不得自行弹出（CAD 会话未开启）。"""
    from shiboken6 import wrapInstance
    from PySide6.QtWidgets import QWidget
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    stack.initialize()
    try:
        canvas = stack.create_canvas()
        w = wrapInstance(canvas, QWidget)
        qtbot.addWidget(w)
        w.resize(400, 400)
        w.show()
        dock = next(
            (c for c in w.children()
             if c.metaObject().className() == "QgsAdvancedDigitizingDockWidget"),
            None,
        )
        assert dock is not None, "cadDock 未创建"
        assert dock.isHidden()
        stack.set_map_tool(canvas, "addPoint")
        qtbot.wait(100)
        assert dock.isHidden(), "激活采点工具后 dock 不应显示（CAD 会话未开启）"
    finally:
        stack.shutdown()
