# -*- coding: utf-8 -*-
"""V12 M1：编辑期联动开关的 UI 面（避免重叠 / 追踪 / 顶点范围）。

这三个能力（QgsSnappingConfig.avoidIntersections、QgsMapCanvasTracer、
顶点档位）实现早已在桥与服务层，但此前只有命令 handler、没有任何按钮——
"已实现但用户摸不到"。本用例钉住：登记面（工具组/动作/图标）、求值器的
勾选态与门禁、以及宿主命令面到控制器状态的闭环。
"""
from __future__ import annotations

import pytest

_TOGGLES = ("avoid_intersections", "tracing", "vertex_scope")


def test_toggles_are_registered_in_snapping_group():
    from paleo_workbench.mapping.action_registry import ACTION_SPECS
    from paleo_workbench.mapping.tool_availability import TOOL_GROUPS
    from paleo_workbench.mapping.tool_help import TOOL_HELP, TOOL_LABELS

    group = TOOL_GROUPS["snapping"]
    for tool_id in _TOGGLES:
        assert tool_id in group, f"{tool_id} 未登记进捕捉组"
        spec = ACTION_SPECS[tool_id]
        assert spec.group == "snapping"
        assert spec.icon, f"{tool_id} 缺图标名"
        assert tool_id in TOOL_LABELS and tool_id in TOOL_HELP


def test_toggle_icons_resolve_to_assets(qapp):
    from paleo_workbench.mapping.action_registry import ACTION_SPECS
    from paleo_workbench.ui.map_action_controller import _map_icon

    missing = [tool_id for tool_id in _TOGGLES
               if _map_icon(ACTION_SPECS[tool_id].icon).isNull()]
    assert not missing, f"图标资产缺失: {missing}"


def test_checked_state_follows_context_facts():
    from paleo_workbench.mapping.tool_availability import evaluate_tool
    from paleo_workbench.mapping.tool_context import ToolContext

    ctx = ToolContext(
        project_open=True, active_layer_id="L1", active_layer_kind="polygon",
        editing=True, native_canvas_available=True, snapping_available=True,
        avoid_intersections_enabled=True, tracing_enabled=False,
        vertex_all_layers=True,
    )
    assert evaluate_tool("avoid_intersections", ctx).checked is True
    assert evaluate_tool("tracing", ctx).checked is False
    assert evaluate_tool("vertex_scope", ctx).checked is True

    flipped = ToolContext(
        project_open=True, active_layer_id="L1", active_layer_kind="polygon",
        editing=True, native_canvas_available=True, snapping_available=True,
        avoid_intersections_enabled=False, tracing_enabled=True,
        vertex_all_layers=False,
    )
    assert evaluate_tool("avoid_intersections", flipped).checked is False
    assert evaluate_tool("tracing", flipped).checked is True
    assert evaluate_tool("vertex_scope", flipped).checked is False


def test_gates_report_why_disabled():
    """门禁必须给原因（不做无声禁用）。"""
    from paleo_workbench.mapping.tool_availability import evaluate_tool
    from paleo_workbench.mapping.tool_context import ToolContext

    fallback = ToolContext(
        project_open=True, active_layer_id="L1", active_layer_kind="polygon",
        editing=True, native_canvas_available=False,
    )
    assert evaluate_tool("tracing", fallback).enabled is False
    assert "原生画布" in evaluate_tool("tracing", fallback).disabled_reason

    no_session = ToolContext(
        project_open=True, active_layer_id="L1", active_layer_kind="polygon",
        editing=False, native_canvas_available=True,
    )
    verdict = evaluate_tool("vertex_scope", no_session)
    assert verdict.enabled is False
    assert verdict.disabled_reason


@pytest.mark.qgis
def test_host_command_toggles_controller_state(qtbot):
    """命令面闭环：点击 → 控制器权威翻转 → 上下文事实随动。"""
    pytest.importorskip("PySide6")
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    doc.resize(900, 600)
    doc.show()
    controller = doc.edit_controller
    # 门禁前提：开关都要有活动图层（vertex_scope 还要求编辑会话）——
    # 无目标时的拒绝由 test_gates_report_why_disabled 覆盖。
    layer = controller.create_layer("相带草稿", "polygon")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    doc._sync_composition_now()

    before = controller.tracing_enabled
    doc._on_command_requested("tracing")
    assert controller.tracing_enabled is not before

    before_avoid = controller.avoid_intersections_enabled
    doc._on_command_requested("avoid_intersections")
    assert controller.avoid_intersections_enabled is not before_avoid

    before_scope = controller.vertex_all_layers
    doc._on_command_requested("vertex_scope")
    assert controller.vertex_all_layers is not before_scope

    facts = controller.tool_context_inputs()
    assert facts["tracing_enabled"] is controller.tracing_enabled
    assert facts["avoid_intersections_enabled"] is controller.avoid_intersections_enabled
    assert facts["vertex_all_layers"] is controller.vertex_all_layers

    # 工具条实体：三个开关都建出了可勾选动作。
    for tool_id in _TOGGLES:
        action = doc.action_controller.actions[tool_id]
        assert action.isCheckable(), f"{tool_id} 不是可勾选动作"
