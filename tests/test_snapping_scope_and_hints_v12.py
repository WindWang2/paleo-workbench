# -*- coding: utf-8 -*-
"""V12 M1/M2 增量：捕捉范围选择器（M1-1）、激活预检（M1-8）、零位移提示（M2-4）。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


# ---------------------------------------------------------------------------
# M1-1 捕捉范围（所有图层 / 仅当前图层）
# ---------------------------------------------------------------------------

def test_snapping_dialog_scope_writes_authority(qapp):
    """对话框范围选择 → SnappingService.current_layer_only 权威。"""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.ui.workstation.composite_panels import SnappingSettingsDialog

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    dialog = SnappingSettingsDialog(controller)
    assert dialog._scope_combo is not None

    dialog._scope_combo.setCurrentIndex(1)  # 仅当前图层
    dialog.accept()
    assert controller.snapping.current_layer_only is True

    dialog2 = SnappingSettingsDialog(controller)
    assert dialog2._scope_combo.currentIndex() == 1, "重开对话框应回显当前权威"
    dialog2._scope_combo.setCurrentIndex(0)
    dialog2.accept()
    assert controller.snapping.current_layer_only is False


def test_set_snapping_scope_updates_model(qapp):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    controller.set_snapping_scope(True)
    assert controller.snapping.current_layer_only is True
    controller.set_snapping_scope(False)
    assert controller.snapping.current_layer_only is False


# ---------------------------------------------------------------------------
# M1-8 激活预检（无编辑目标 → 不绑定节点/移动工具）
# ---------------------------------------------------------------------------

@pytest.mark.qgis
def test_vertex_activation_refused_without_canvas_target(qtbot, monkeypatch):
    """原生会话在开但画布当前层不就位 → 不切换节点工具（R6）。"""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带草稿", "polygon")
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "Polygon", "coordinates": [[
                          (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0),
                          (0.0, 0.0)]]},
                      attributes={}),
    ])
    doc._sync_composition_now()
    controller.set_active_layer(layer.id)
    controller.start_editing()
    assert controller.native_editing.is_open(layer.id)

    # 画布侧"目标未就位"（模拟推送仍失败的残余状态）。
    monkeypatch.setattr(controller, "current_canvas_layer_id", lambda: "")
    controller.activate_tool("vertex")
    active = controller.tools.active_tool
    active_id = getattr(active, "tool_id", "") if active is not None else ""
    assert active_id != "vertex", (
        "预检失效：无编辑目标却绑定了节点工具（哑态复归）")


@pytest.mark.qgis
def test_vertex_activation_binds_when_target_ready(qtbot):
    """目标就位（M0-2b 推送链）→ 正常绑定节点工具。"""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带草稿", "polygon")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    controller.activate_tool("vertex")
    assert controller.tools.active_tool.tool_id == "vertex"


# ---------------------------------------------------------------------------
# M2-4 零位移点击提示（真桥端到端）
# ---------------------------------------------------------------------------

@pytest.mark.qgis
def test_zero_displacement_click_emits_hint(qtbot):
    """单击命中节点（非拖动）→ 状态提示"单击不移动节点"。"""
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest

    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    doc.resize(900, 600)
    doc.show()
    controller = doc.edit_controller
    layer = controller.create_layer("相带草稿", "polygon")
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "Polygon", "coordinates": [[
                          (4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0),
                          (4.0, 4.0)]]},
                      attributes={}),
    ])
    doc._sync_composition_now()
    controller.set_active_layer(layer.id)
    controller.start_editing()
    doc.canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.wait(150)
    controller.activate_tool("vertex")

    viewport = doc.canvas._canvas_viewport()
    xmin, ymin, xmax, ymax = doc.canvas.view_extent
    width, height = viewport.width(), viewport.height()

    def pixel(x: float, y: float):
        return QPoint(int(round((x - xmin) / (xmax - xmin) * width)),
                      int(round((ymax - y) / (ymax - ymin) * height)))

    hints: list[str] = []
    doc.canvas.status_hint.connect(hints.append)
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, pixel(4.0, 4.0))
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, pixel(4.0, 4.0))
    qtbot.wait(200)
    assert any("单击不移动节点" in hint for hint in hints), (
        f"零位移点击无提示：{hints}")
