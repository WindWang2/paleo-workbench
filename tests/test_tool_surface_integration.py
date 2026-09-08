"""V7 工具面集成测试：CompositeDocument/QAction 侧的矩阵与原因呈现。

单元矩阵在 ``test_tool_surface.py``（纯 Python）；此处验证工作站实际
QAction 表面（tooltip/statusTip 原因、组可见性、RAW/冻结/几何门禁）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.command_registry import command_registry
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture()
def document(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    return doc


def _create_layer(document, kind="polygon"):
    layer = document.edit_controller.create_layer("测试图层", kind)
    document._sync_action_state()
    return layer


def _assign_role(document, layer_id, role: LayerRole, **extra):
    state = document.stage_controller.state
    state.set_membership(LayerMembershipRecord(
        layer_id=str(layer_id), role=role, **extra
    ))
    document.edit_controller.set_active_layer(str(layer_id))
    document._sync_action_state()


# ---------------------------------------------------------------------------
# 工具条 IA（goal §6）：组齐全 + 此前不可达的动作进入表面
# ---------------------------------------------------------------------------


def test_toolbar_carries_all_professional_groups(document):
    # refresh/select_all 等此前在 composite 表面不可达（audit C5）——现在
    # 全部挂载在 MapToolbar 上（associatedWidgets 含工具条即挂载）。
    for action_id in (
        "pan", "refresh", "select_all", "invert_selection", "clear_selection",
        "identify", "toggle_editing", "add_polygon", "split", "snapping",
        "layer_new", "layer_properties", "attribute_table", "layer_zoom",
        "layer_export", "symbology", "style_manager", "factor_workbench",
        "factor_overlay", "qa_run", "map_product_assemble", "map_export",
    ):
        objects = document.action_controller.actions[action_id].associatedObjects()
        assert objects, f"{action_id} 应挂载到工具条"


def test_new_surface_action_dispatch_has_backend(document, monkeypatch):
    """layer_new 分派到真实后端（新建图层对话框入口），非死按钮。

    对话框本身是模态的——以桩替换验证分派连线路由（模态 UI 另有
    visual QA 覆盖）。
    """
    calls = []
    monkeypatch.setattr(
        document, "_create_vector_layer", lambda: calls.append(1)
    )
    document._on_command_requested("layer_new")
    assert calls == [1]


# ---------------------------------------------------------------------------
# 禁用原因呈现（goal §5：tooltip/statusTip 同源）
# ---------------------------------------------------------------------------


def test_disabled_action_carries_reason_in_status_tip(document):
    layer = _create_layer(document, "polygon")
    _assign_role(document, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    # 未开始编辑：save_edits 禁用，原因可见于 statusTip/tooltip。
    action = document.action_controller.actions["save_edits"]
    assert not action.isEnabled()
    assert "编辑" in action.statusTip()
    assert "编辑" in action.toolTip()


def test_raw_layer_block_reason_flows_to_actions(document):
    layer = _create_layer(document, "polygon")
    _assign_role(document, layer.id, LayerRole.INITIAL_FACIES_SOURCE)
    action = document.action_controller.actions["toggle_editing"]
    assert not action.isEnabled()
    assert "RAW" in action.statusTip()


def test_frozen_maturity_blocks_editing(document):
    layer = _create_layer(document, "polygon")
    _assign_role(document, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    state = document.stage_controller.state
    state.set_maturity(f"phase1_draft:{layer.id}", "frozen")
    document._sync_action_state()
    action = document.action_controller.actions["toggle_editing"]
    assert not action.isEnabled()
    assert "冻结" in action.statusTip()


def test_factor_grid_role_disables_vector_capture_but_keeps_view_tools(document):
    layer = _create_layer(document, "polygon")
    _assign_role(document, layer.id, LayerRole.FACTOR_GRID, factor_task_id="f1")
    actions = document.action_controller.actions
    assert not actions["toggle_editing"].isEnabled()
    assert "RAW" in actions["toggle_editing"].statusTip()
    for tool in ("add_polygon", "add_line", "move_feature", "vertex"):
        assert not actions[tool].isEnabled(), tool
    for tool in ("layer_properties", "symbology", "layer_export", "qa_run"):
        assert actions[tool].isEnabled(), tool


def test_phase2_line_role_add_line_primary_add_polygon_disabled(document):
    document.stage_controller.set_stage("phase2")
    layer = _create_layer(document, "line")
    _assign_role(document, layer.id, LayerRole.PROVENANCE_LINE)
    actions = document.action_controller.actions
    assert actions["toggle_editing"].isEnabled()
    # 会话开启后：add_line 主捕获可用；add_polygon 被几何门禁禁用。
    document._on_command_requested("toggle_editing")
    assert actions["add_line"].isEnabled()
    assert not actions["add_polygon"].isEnabled()
    assert "线" in actions["add_polygon"].statusTip() or \
        "面" in actions["add_polygon"].statusTip()


def test_phase1_hides_add_line_via_evaluator(document):
    # 新工程默认 phase1。
    document.stage_controller.set_stage("phase1")
    layer = _create_layer(document, "polygon")
    _assign_role(document, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    actions = document.action_controller.actions
    assert actions["add_line"].isVisible() is False
    assert actions["add_polygon"].isVisible() is True


def test_style_manager_disabled_without_bridge(document):
    # 本环境桥未构建（与 main 一致）——QGIS 原因必须可见。先建活动图层：
    # 无图层时 symbology 组整组隐藏（V8 M1），后端判词要在组显示后才是
    # 工具自己的禁用原因。
    actions = document.action_controller.actions
    if document.uses_native_stack:
        pytest.skip("桥已构建（本测试针对无桥环境）")
    layer = _create_layer(document, "polygon")
    _assign_role(document, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    assert not actions["style_manager"].isEnabled()
    assert "QGIS" in actions["style_manager"].statusTip()
    # 符号系统/图层属性走 fallback 对话框——不因缺桥禁用。
    assert actions["symbology"].isEnabled()
    assert actions["layer_properties"].isEnabled()


# ---------------------------------------------------------------------------
# 能力三态 / 上下文快照
# ---------------------------------------------------------------------------


def test_capability_snapshot_three_states(document):
    snap = document._capability_snapshot()
    assert snap.mode in {"native", "degraded", "unavailable"}
    if not document.uses_native_stack:
        assert snap.mode == "unavailable"
        assert snap.reason


def test_tool_context_reflects_active_layer(document):
    layer = _create_layer(document, "line")
    _assign_role(document, layer.id, LayerRole.PALEO_SHORELINE)
    ctx = document.tool_context()
    # V8 canonical：扁平图层事实 + mapping_stage（无嵌套 .layer/.stage）。
    assert ctx.active_layer_kind == "line"
    assert ctx.layer_role == LayerRole.PALEO_SHORELINE.value
    assert ctx.edit_gate_open is True
    assert ctx.mapping_stage == "facies_calibration"
    # 呈现快照仍可经文档取（状态条/inspector 消费）。
    snapshot = document.active_layer_capability()
    assert snapshot.kind == "line"
    assert snapshot.editable is True


# ---------------------------------------------------------------------------
# palette：阶段命令 applicability 与工具条同源（goal §3/§5）
# ---------------------------------------------------------------------------


def test_stage_palette_commands_carry_applicability(qtbot, tmp_path):
    from PySide6.QtWidgets import QStackedWidget

    from paleo_workbench.ui.workstation.shell import WorkstationFrame

    frame = WorkstationFrame(_project(tmp_path), QStackedWidget())
    qtbot.addWidget(frame)
    try:
        spec = command_registry.get("stage:constraint_factor:open_factor_workbench")
        assert spec is not None
        assert spec.applicability is not None

        class _Ctx:
            project_open = True
            mapping_stage = "constraint_factor"
            active_layer_id = "x"
            active_layer_editable = True
            editing_active = False
            qgis_bridge_available = False
            write_granted = False

        # 阶段匹配 + 工程开 → 可用（无因）。
        assert command_registry.evaluate(
            "stage:constraint_factor:open_factor_workbench", _Ctx()
        ).enabled

        class _CtxNoProject:
            project_open = False

        avail = command_registry.evaluate(
            "stage:constraint_factor:open_factor_workbench", _CtxNoProject()
        )
        assert not avail.enabled
        assert avail.reason
    finally:
        command_registry.clear(keep_core=False)


# -- V8 M6：单一受门禁执行路径（tool_requested / command_requested 双入口） --


def test_tool_requested_path_regates_with_fresh_context(document, monkeypatch):
    """checkable 工具动作的 tool_requested 路径同样被 re-gate 拦截。

    构造过期窗口：动作在上一次刷新时可用（编辑会话中），随后会话结束
    但尚未重刷——直接触发 _on_tool_requested 必须被新鲜求值拒绝并回报
    原因，而不是透传给 activate_tool。
    """
    layer = _create_layer(document, "polygon")
    _assign_role(document, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    document.edit_controller.start_editing()
    document._sync_action_state()
    assert document.tool_availability()["add_polygon"].enabled

    # 过期窗口：会话结束后不调用 _sync_action_state。
    document.edit_controller.rollback_edits()

    calls = []
    monkeypatch.setattr(
        document.edit_controller, "activate_tool",
        lambda tool_id: calls.append(tool_id))
    messages = []
    document.status_message.connect(messages.append)

    document._on_tool_requested("add_polygon")
    assert calls == [], "stale-window tool request must not reach activate_tool"
    assert any("不可用" in m for m in messages), messages
    # 拒绝后 checked 已被回同步（QAction 的翻转不得残留）。
    assert not document.action_controller.actions["add_polygon"].isChecked()


def test_command_requested_path_regates_disabled_command(document, monkeypatch):
    """命令路径 re-gate：结构性前提不满足时 save_edits 被拒并带原因。"""
    calls = []
    monkeypatch.setattr(
        document, "_save_edits_with_feedback",
        lambda: calls.append("save"))
    messages = []
    document.status_message.connect(messages.append)

    document._on_command_requested("save_edits")
    assert calls == []
    # 最根本的 blocker 优先（无活动图层先于会话状态）。
    assert any("不可用" in m for m in messages), messages
