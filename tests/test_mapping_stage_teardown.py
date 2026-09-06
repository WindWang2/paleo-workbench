"""阶段工作区生命周期/teardown 回归（V5 §89/§61）。

30 次小规模循环：构建 → 切阶段 → 建图层/编辑 → flush → teardown。
fallback 画布路径（不依赖桥；工程切换语义同生产）。检查：
无 destroyed-C++ 对象回溯、无 stale callback 崩溃、状态无跨工程泄漏。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.project.models import ProjectDocument

QApplication.instance() or QApplication([])

CYCLES = 30


def _composite(qtbot, monkeypatch, project):
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    return doc


def test_teardown_cycles_without_stale_callbacks(qtbot, monkeypatch):
    """30 × (open → 切三阶段 → 编辑 → flush → close)：无生命周期崩溃。"""
    for cycle in range(CYCLES):
        project = ProjectDocument.new(f"循环 {cycle}")
        doc = _composite(qtbot, monkeypatch, project)
        controller = doc.stage_controller

        # 三阶段往返。
        controller.set_stage(MappingStage.CONSTRAINT_FACTOR, apply_docks=False)
        layer = doc.edit_controller.create_layer(f"物源线{cycle}", "line")
        controller.group_controller.register_layer(
            layer.id, LayerRole.PROVENANCE_LINE, constraint_kind="provenance_line")
        doc._sync_composition_now()
        controller.set_stage(MappingStage.INTEGRATED_COMPILATION, apply_docks=False)
        controller.set_stage(MappingStage.FACIES_CALIBRATION, apply_docks=False)

        # 编辑 + flush（不静默丢弃）。
        doc.edit_controller.set_active_layer(layer.id)
        doc.edit_controller.start_editing()
        doc.flush_edit_sessions()

        # 关闭：teardown 后不得再收到任何树/阶段回调引发的 C++ 访问。
        doc.shutdown()
        QApplication.processEvents()
    assert True


def test_project_switch_does_not_leak_state(qtbot, monkeypatch):
    """§61：工程切换后旧工程的成员资格/阶段不得泄漏进新工程。"""
    project_a = ProjectDocument.new("工程A")
    doc = _composite(qtbot, monkeypatch, project_a)
    layer = doc.edit_controller.create_layer("A物源线", "line")
    doc.stage_controller.group_controller.register_layer(
        layer.id, LayerRole.PROVENANCE_LINE)
    doc.stage_controller.set_stage(MappingStage.INTEGRATED_COMPILATION)
    doc.flush_edit_sessions()

    project_b = ProjectDocument.new("工程B")
    doc.set_project(project_b)
    controller = doc.stage_controller
    # 新工程：无 A 的成员资格；阶段回落默认（新 state）。
    assert not controller.state.memberships
    assert controller.state.role_of(layer.id) == LayerRole.LEGACY_UNCLASSIFIED
    # 再切回 A（重新装载）：成员资格从 A 的持久化状态恢复。
    doc.set_project(project_a)
    assert controller.state.role_of(layer.id) == LayerRole.PROVENANCE_LINE
    assert controller.current_stage == MappingStage.INTEGRATED_COMPILATION
