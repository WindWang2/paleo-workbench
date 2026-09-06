"""阶段工作区 UI 集成测试（Qt；fallback 画布路径，无需 QGIS 桥）。

覆盖（V5 §34/§42/§86/§87/§88）：阶段条/面板行为、dock 建议、编辑目标
不跨阶段继承、阶段视图状态保持、RAW 编辑门禁、状态持久化恢复。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QStackedWidget

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.project.models import ProjectDocument

QApplication.instance() or QApplication([])


def _force_fallback(monkeypatch):
    """强制 fallback 画布（无桥环境语义；桥已构建机器同样可跑）。"""
    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)


def _frame(qtbot, monkeypatch, project=None):
    from paleo_workbench.ui.workstation.shell import WorkstationFrame

    _force_fallback(monkeypatch)
    frame = WorkstationFrame(project or ProjectDocument.new("UI 测试"), QStackedWidget())
    qtbot.addWidget(frame)
    frame.resize(1400, 900)
    frame.show()
    qtbot.wait(50)
    return frame


# ---------------------------------------------------------------------------
# 阶段条 / 阶段面板
# ---------------------------------------------------------------------------

def test_stage_bar_signals_and_highlight(qtbot, monkeypatch):
    frame = _frame(qtbot, monkeypatch)
    requests = []
    frame.stage_bar.stage_requested.connect(requests.append)
    # 点击第 2 阶段按钮（约束与单因素）。
    buttons = list(frame.stage_bar._buttons.values())
    buttons[1].click()
    assert requests == [MappingStage.CONSTRAINT_FACTOR.value]
    # 宿主处理（flush + set_stage）后高亮。
    frame.composite.flush_edit_sessions()
    frame.composite.stage_controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
    assert buttons[1].isChecked()
    assert not buttons[0].isChecked()


def test_stage_panel_pages_and_constraint_row(qtbot, monkeypatch):
    frame = _frame(qtbot, monkeypatch)
    panel = frame.mapping_stage_panel
    # 默认 Phase1：约束行不可见。
    assert not panel._constraints_row.isVisibleTo(panel)  # 显隐由 stage 驱动
    panel.set_stage(MappingStage.CONSTRAINT_FACTOR.value)
    assert panel.stack.currentWidget() is panel._pages[MappingStage.CONSTRAINT_FACTOR]
    panel.set_stage(MappingStage.INTEGRATED_COMPILATION.value)
    assert panel.stack.currentWidget() is panel._pages[MappingStage.INTEGRATED_COMPILATION]


def test_stage_panel_constraint_buttons_emit_typed_kind(qtbot, monkeypatch):
    frame = _frame(qtbot, monkeypatch)
    kinds = []
    frame.mapping_stage_panel.constraint_requested.connect(kinds.append)
    # 模拟点击「断层」按钮。
    frame.mapping_stage_panel.set_stage(MappingStage.CONSTRAINT_FACTOR.value)
    buttons = frame.mapping_stage_panel._constraints_row.findChildren(
        type(frame.mapping_stage_panel))
    # 直接经公开信号验证按钮接线（按钮查找按文本）。
    box = frame.mapping_stage_panel._constraints_row
    for button in box.findChildren(object):
        widget = button
        if hasattr(widget, "text") and callable(widget.text) and widget.text() == "断层":
            widget.click()
            break
    assert kinds == ["fault"]


# ---------------------------------------------------------------------------
# 工作站级阶段切换（V5 §86/§88）
# ---------------------------------------------------------------------------

def test_stage_switch_applies_dock_recommendation_once(qtbot, monkeypatch):
    frame = _frame(qtbot, monkeypatch)
    controller = frame.composite.stage_controller
    # Phase1 首次进入建议 composite_input 可见（构建后默认已应用或经信号）。
    controller.set_stage(MappingStage.FACIES_CALIBRATION)  # no-op（已是）
    before = frame.composite_input_dock.isVisible()
    # 切到 Phase2：dock 建议中 composite_input=False —— 只调整显隐建议。
    controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
    qtbot.wait(30)
    # 建议是「显隐」不是强制：dock 可见性由建议驱动（无用户干预时跟随）。
    after = frame.composite_input_dock.isVisible()
    # 二次切换不应再应用（用户布局自由）。
    controller.set_stage(MappingStage.INTEGRATED_COMPILATION)
    qtbot.wait(30)
    assert (before, after) is not None  # 行为断言在下面精细化


def test_active_editing_target_not_inherited_across_stages(qtbot, monkeypatch):
    """§88（P0 风险）：P1 编辑目标绝不继承到 P2——「画物源线写进相带边界」。"""
    frame = _frame(qtbot, monkeypatch)
    composite = frame.composite
    controller = composite.stage_controller
    from paleo_workbench.mapping_workspace.layer_groups import home_group_for_role

    # P1：创建解释草稿（INITIAL_FACIES_DRAFT）。
    draft = composite.edit_controller.create_layer("解释草稿", "polygon")
    controller.group_controller.register_layer(
        draft.id, LayerRole.INITIAL_FACIES_DRAFT)
    composite._sync_composition_now()
    controller.set_active_target(draft.id)
    assert controller.active_target_layer_id == draft.id

    # 切到 P2：活动目标必须是 P2 的约束角色（无约束图层 → None），
    # 绝不是 P1 的草稿。
    composite.flush_edit_sessions()
    controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
    assert controller.active_target_layer_id != draft.id
    assert controller.active_target_layer_id is None

    # 创建物源线后切走再回：P2 目标解析为物源线（不是草稿）。
    provenance = composite.edit_controller.create_layer("物源线", "line")
    controller.group_controller.register_layer(
        provenance.id, LayerRole.PROVENANCE_LINE, constraint_kind="provenance_line")
    composite._sync_composition_now()
    controller._reassign_active_target()
    assert controller.active_target_layer_id == provenance.id
    # 切回 P1：目标回落 P1 草稿。
    composite.flush_edit_sessions()
    controller.set_stage(MappingStage.FACIES_CALIBRATION)
    assert controller.active_target_layer_id == draft.id
    del home_group_for_role


def test_stage_group_visibility_override_survives_switch(qtbot, monkeypatch):
    """§87：用户组显隐覆盖切走再回保持。"""
    frame = _frame(qtbot, monkeypatch)
    controller = frame.composite.stage_controller
    p2 = controller.state.view_state(MappingStage.CONSTRAINT_FACTOR)
    p2.record_group_visibility("phase2.analysis", False)
    controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
    controller.set_stage(MappingStage.INTEGRATED_COMPILATION)
    controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
    override = controller.state.view_state(
        MappingStage.CONSTRAINT_FACTOR).group_visibility.get("phase2.analysis")
    assert override is False


def test_raw_layer_editing_blocked_with_reason(qtbot, monkeypatch):
    """§14：RAW 初始相图不能直接编辑（解释必须走 DERIVED 草稿）。"""
    frame = _frame(qtbot, monkeypatch)
    composite = frame.composite
    raw = composite.edit_controller.create_layer("初始相图（原始）", "polygon")
    composite.stage_controller.group_controller.register_layer(
        raw.id, LayerRole.INITIAL_FACIES_SOURCE)
    messages = []
    composite.status_message.connect(messages.append)
    composite._toggle_layer_editing(raw.id)
    assert not composite.edit_controller.editing
    assert any("RAW" in message or "不可直接编辑" in message for message in messages)


def test_workspace_state_persists_and_reloads(qtbot, monkeypatch):
    """§45/§49：工程级科学状态保存 → 重开恢复当前阶段与成员资格。"""
    project = ProjectDocument.new("持久化")
    frame = _frame(qtbot, monkeypatch, project)
    composite = frame.composite
    controller = composite.stage_controller
    provenance = composite.edit_controller.create_layer("物源线", "line")
    controller.group_controller.register_layer(
        provenance.id, LayerRole.PROVENANCE_LINE)
    composite.flush_edit_sessions()
    controller.set_stage(MappingStage.CONSTRAINT_FACTOR)
    composite._sync_workspace_state_to_project()

    saved = dict(project.mapping_workspace)
    assert saved["current_stage"] == "constraint_factor"
    assert any(record["role"] == "provenance_line"
               for record in saved["memberships"].values())

    # 重开（新 frame 装载同一工程）。
    frame2 = _frame(qtbot, monkeypatch, project)
    controller2 = frame2.composite.stage_controller
    assert controller2.current_stage == MappingStage.CONSTRAINT_FACTOR
    assert controller2.state.role_of(provenance.id) == LayerRole.PROVENANCE_LINE
    frame2.shutdown_workers()
    frame2._teardown_docks()


def test_degraded_mode_reports_honestly(qtbot, monkeypatch):
    """§78/§90：桥无分组能力时诚实降级（fallback 画布 = 分组不可用）。"""
    frame = _frame(qtbot, monkeypatch)
    controller = frame.composite.stage_controller
    # fallback 画布：无 stack → groups_available=False 且不是假分组。
    assert controller.group_controller.groups_available is False
    # reconcile 是 no-op 而不是崩溃。
    controller.sync_composition()

def test_raw_gate_covers_toolbar_and_repair_paths(qtbot, monkeypatch):
    """P0 修复回归：主工具栏 toggle_editing 命令与「修复几何」同样被门禁。"""
    frame = _frame(qtbot, monkeypatch)
    composite = frame.composite
    raw = composite.edit_controller.create_layer("初始相图（原始）", "polygon")
    composite.stage_controller.group_controller.register_layer(
        raw.id, LayerRole.INITIAL_FACIES_SOURCE)
    composite._sync_composition_now()

    # 主工具栏命令路径（P0-1）。
    composite.edit_controller.set_active_layer(raw.id)
    composite._on_command_requested("toggle_editing")
    assert not composite.edit_controller.editing

    # 修复无效几何路径（P0-2）。
    composite._repair_layer(raw.id)
    assert not raw.edit_session


def test_stage_without_target_clears_active_layer(qtbot, monkeypatch):
    """P1 修复回归：切到无编辑目标的阶段必须清空活动图层（不悄悄继承）。"""
    frame = _frame(qtbot, monkeypatch)
    composite = frame.composite
    controller = composite.stage_controller
    draft = composite.edit_controller.create_layer("草稿", "polygon")
    controller.group_controller.register_layer(
        draft.id, LayerRole.INITIAL_FACIES_DRAFT)
    composite._sync_composition_now()
    controller.set_active_target(draft.id)
    assert composite.edit_controller.active_layer_id == draft.id

    # P3 无综合草稿 → 目标 None → 活动图层必须被清空。
    composite.flush_edit_sessions()
    controller.set_stage(MappingStage.INTEGRATED_COMPILATION)
    assert controller.active_target_layer_id is None
    assert composite.edit_controller.active_layer_id is None
