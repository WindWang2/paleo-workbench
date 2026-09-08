"""评审轮 P0/P1 修复的回归测试（R1/R2/R3 findings）。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Review", region="HZ")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture()
def document(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    return doc


def _add_layer(document, kind, role, name="层", **extra):
    layer = document.edit_controller.create_layer(name, kind)
    document.stage_controller.state.set_membership(LayerMembershipRecord(
        layer_id=str(layer.id), role=role, **extra))
    document.edit_controller.set_active_layer(str(layer.id))
    document._sync_action_state()
    return layer


# R1#2 (P1): 阶段切换刷新统一可用性
def test_stage_switch_refreshes_evaluator_availability(qtbot, tmp_path):
    from PySide6.QtWidgets import QStackedWidget

    from paleo_workbench.ui.workstation.shell import WorkstationFrame

    frame = WorkstationFrame(_project(tmp_path), QStackedWidget())
    qtbot.addWidget(frame)
    composite = frame.composite
    actions = composite.action_controller.actions
    # phase1：factor 组不显示。
    frame.composite.stage_controller.set_stage("facies_calibration")
    composite._sync_action_state()
    assert not actions["factor_workbench"].isVisible()
    assert not actions["map_export"].isVisible()
    # → phase2：经 shell 的阶段处理器（含 _sync_action_state）后组可见。
    frame.composite.stage_controller.set_stage("constraint_factor")
    assert actions["factor_workbench"].isVisible()
    assert actions["factor_overlay"].isVisible()
    # → phase3：layout_export 可见。
    frame.composite.stage_controller.set_stage("integrated_compilation")
    assert actions["map_export"].isVisible()
    assert actions["map_product_assemble"].isVisible()


def test_cancelling_render_priority():
    """RUNNING + cancel_requested → 「取消中」（渲染优先级回归，确定性）。"""
    from paleo_workbench.runtime.task_scheduler import TaskHandle, TaskState
    from paleo_workbench.ui.workstation.task_center import _TaskRowDelegate

    from paleo_workbench.runtime.task_scheduler import TaskSpec

    spec = TaskSpec(title="t", callable=lambda ctx: None)
    running = TaskHandle(task_id="t1", spec=spec, state=TaskState.RUNNING,
                         cancel_requested=True)
    assert _TaskRowDelegate._state_text(running) == "取消中"
    plain_running = TaskHandle(task_id="t2", spec=spec, state=TaskState.RUNNING)
    assert "运行中" in _TaskRowDelegate._state_text(plain_running)
    done = TaskHandle(task_id="t3", spec=spec, state=TaskState.DONE,
                      cancel_requested=True)
    assert _TaskRowDelegate._state_text(done) == "完成"


# R1#4 (P1): 验证器崩溃 → error issue（不再假通过）
def test_run_qa_validator_crash_becomes_issue(document, monkeypatch):
    layer = _add_layer(document, "polygon", LayerRole.INTEGRATED_FACIES)
    document.stage_controller.set_stage("integrated_compilation")

    class _CrashingTopology:
        def validate(self, layers):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        type(document.edit_controller), "topology",
        property(lambda self: _CrashingTopology()),
        raising=False,
    )
    messages = []
    document.status_message.connect(messages.append)
    from paleo_workbench.ui.workstation.stage_actions import (
        StageActionDispatcher,
    )

    dispatcher = StageActionDispatcher(document)
    dispatcher.run_qa()
    joined = " | ".join(messages)
    reports = document._project.quality_reports
    assert reports, "QA 报告必须生成"
    last = reports[-1]
    assert last.status == "issues"
    assert any(i["kind"] == "error" for i in last.issues)
    assert "QA 发现" in joined


# R3#1 (P1): 新鲜度变化 → 树装饰即时刷新
def test_stale_summary_refreshes_tree_decorations(document, qtbot):
    from paleo_workbench.mapping_workspace.dependencies import (
        ArtifactFreshness,
        FreshnessStatus,
        StaleSummary,
    )
    from paleo_workbench.mapping_workspace.stages import MappingStage

    layer = _add_layer(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    document._sync_composition_now()
    from PySide6.QtCore import Qt

    tree = document.layer_manager.tree

    def _row_text():
        for row in range(tree.topLevelItemCount()):
            if str(tree.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole)) == str(layer.id):
                return tree.topLevelItem(row).text(1)
        return ""

    assert _row_text() == ""
    summary = StaleSummary(
        artifacts=(ArtifactFreshness(
            f"phase1_draft:{layer.id}", "phase1_draft",
            MappingStage.FACIES_CALIBRATION, FreshnessStatus.STALE, "输入已更新"
        ),),
    )
    document.stage_controller.group_controller.apply_freshness(summary)
    document.stage_controller.stale_summary_changed.emit(summary)
    assert "已过期" in _row_text(), _row_text()


# R1#8 (P2): attribute_table 对 RAW 只读可用
def test_attribute_table_available_on_raw_layer(document):
    layer = _add_layer(document, "polygon", LayerRole.INITIAL_FACIES_SOURCE)
    actions = document.action_controller.actions
    assert not actions["toggle_editing"].isEnabled()
    assert actions["attribute_table"].isEnabled(), \
        "属性表是只读查看——RAW 层不得禁用（QGIS 语义）"


# R1#9 (P2): 未知几何类型 fail-closed
def test_unknown_kind_capture_fails_closed(document):
    layer = _add_layer(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    document._on_command_requested("toggle_editing")
    from paleo_workbench.ui.workstation.tool_surface import (
        ToolContext,
        evaluate_tool,
    )

    # V8 canonical：扁平图层事实（kind 未知 = ""），不再嵌套呈现快照。
    ctx = ToolContext(
        project_open=True,
        mapping_stage="constraint_factor",
        active_layer_id=str(layer.id),
        active_layer_kind="",
        edit_gate_open=True,
        vector_writable=True,
        editing=True,
    )
    for tool in ("add_point", "add_line", "add_polygon"):
        avail = evaluate_tool(tool, ctx)
        assert not avail.enabled
        assert "未知" in avail.reason, f"{tool}: {avail.reason}"


# R1#1 (P0): style_manager 调用契约（后端签名匹配）
def test_style_manager_call_signature(document, monkeypatch):
    calls = {}

    def _fake_open(parent, *, style_db_path):
        calls["parent_ok"] = parent is document
        calls["path"] = style_db_path
        return True

    import paleo_workbench.ui.map_symbology_bridge as bridge

    monkeypatch.setattr(bridge, "open_style_manager", _fake_open)
    document._open_style_manager()
    assert calls.get("parent_ok") is True
    assert calls.get("path", "").endswith("styles.db")


# R1#7 (P2): 缺失图层装饰
def test_missing_layer_gets_missing_decoration(document, qtbot):
    layer = _add_layer(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    document._sync_composition_now()
    # 直接从编辑权威删除（树上残留行）。
    document.edit_controller._layers.pop(str(layer.id))
    document._push_layer_decorations()
    state = document.layer_manager._decorations.get(str(layer.id))
    assert state is not None and state.missing is True
