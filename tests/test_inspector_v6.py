"""V6 §6/§7：typed Inspector（curve kind / 上下文 seam）+ 组新鲜度聚合。

* 检查器新增 ``curve`` kind（D-P0-1：引擎拾取信号此前无生产消费者）：
  字段缺失显示「—」，绝不编造值；
* ``set_context_seam``：宿主注入图层域状态（角色/成熟度/可编辑/新鲜度），
  检查器不直接触碰 mapping 权威；
* ``LayerGroupController.apply_freshness`` + 真实 ``group_summary`` 聚合
  （此前硬编码 0/0）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFormLayout

from paleo_workbench.mapping_workspace.dependencies import (
    ArtifactFreshness,
    FreshnessStatus,
    MappingStage,
    StaleSummary,
)
from paleo_workbench.mapping_workspace.layer_group_controller import (
    LayerGroupController,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord, MappingWorkspaceState
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.inspector import WorkstationInspector


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


# --- curve kind ---------------------------------------------------------------


def test_inspector_curve_kind_honest_fields(qtbot):
    inspector = WorkstationInspector(project=None)
    qtbot.addWidget(inspector)
    inspector.show_payload({"kind": "curve", "object": {"mnemonic": "GR"}})
    assert "曲线" in inspector.header.text()
    labels = [
        inspector.properties_form.itemAt(i, QFormLayout.ItemRole.LabelRole).widget().text()
        for i in range(inspector.properties_form.rowCount())
    ]
    assert "曲线名" in labels
    assert "单位" in labels


def test_inspector_curve_kind_missing_values_not_invented(qtbot):
    inspector = WorkstationInspector(project=None)
    qtbot.addWidget(inspector)
    inspector.show_payload({"kind": "curve", "object": {"mnemonic": "GR"}})
    values = [
        inspector.properties_form.itemAt(i, QFormLayout.ItemRole.FieldRole).widget().text()
        for i in range(inspector.properties_form.rowCount())
    ]
    # 缺失单位/值/井名 → 「—」，不编造
    assert "—" in values


# --- 图层上下文 seam -----------------------------------------------------------


def test_inspector_layer_context_seam_rows(qtbot):
    inspector = WorkstationInspector(project=None)
    qtbot.addWidget(inspector)
    inspector.set_context_seam(
        lambda payload: {
            "角色": "物源线（约束）",
            "成熟度": "◈ 派生",
            "可编辑": "✎ 可编辑",
            "新鲜度": "↻ 已过期",
        }
    )
    inspector.show_payload({"kind": "layer", "layer_type": "矢量图层", "object": None})
    labels = [
        inspector.properties_form.itemAt(i, QFormLayout.ItemRole.LabelRole).widget().text()
        for i in range(inspector.properties_form.rowCount())
    ]
    for expected in ("角色", "成熟度", "可编辑", "新鲜度"):
        assert expected in labels, expected


def test_inspector_layer_without_seam_keeps_basic_rows(qtbot):
    inspector = WorkstationInspector(project=None)
    qtbot.addWidget(inspector)
    inspector.show_payload({"kind": "layer", "layer_type": "矢量图层", "object": None})
    labels = [
        inspector.properties_form.itemAt(i, QFormLayout.ItemRole.LabelRole).widget().text()
        for i in range(inspector.properties_form.rowCount())
    ]
    assert "类型" in labels
    assert "角色" not in labels  # 无 seam 不显示域行（不编造）


# --- 组新鲜度聚合 ---------------------------------------------------------------


def _group_controller() -> tuple[LayerGroupController, MappingWorkspaceState]:
    state = MappingWorkspaceState()
    controller = LayerGroupController(state)
    return controller, state


def test_group_summary_aggregates_real_staleness():
    controller, state = _group_controller()
    state.memberships = {}
    # L1 = factor 任务 T1 的图层；L2 = 无成员资格图层。
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord as LayerMembership

    state.memberships["L1"] = LayerMembershipRecord(layer_id="L1",
        role=LayerRole.FACTOR_GRID, factor_task_id="T1"
    )
    controller._group_orders["phase2.factors"] = ["L1", "L2"]
    controller.apply_freshness(
        StaleSummary(
            artifacts=(
                ArtifactFreshness(
                    "factor:T1", "factor", MappingStage.CONSTRAINT_FACTOR,
                    FreshnessStatus.STALE, "输入版本更新",
                ),
            )
        )
    )
    summary = controller.group_summary("phase2.factors")
    assert summary["layers"] == 2
    assert summary["stale"] == 1
    assert summary["errors"] == 0


def test_group_summary_counts_missing_input_as_error():
    controller, state = _group_controller()
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord as LayerMembership

    state.memberships["L1"] = LayerMembershipRecord(layer_id="L1",
        role=LayerRole.FACTOR_GRID, factor_task_id="T1"
    )
    controller._group_orders["phase2.factors"] = ["L1"]
    controller.apply_freshness(
        StaleSummary(
            artifacts=(
                ArtifactFreshness(
                    "factor:T1", "factor", MappingStage.CONSTRAINT_FACTOR,
                    FreshnessStatus.MISSING_INPUT, "输入缺失",
                ),
            )
        )
    )
    summary = controller.group_summary("phase2.factors")
    assert summary["stale"] == 1
    assert summary["errors"] == 1


def test_group_summary_without_freshness_stays_zero():
    controller, _state = _group_controller()
    controller._group_orders["phase2.factors"] = ["L1"]
    summary = controller.group_summary("phase2.factors")
    assert summary == {"layers": 1, "stale": 0, "errors": 0}


def test_layer_freshness_resolves_phase1_draft_by_layer_id():
    controller, state = _group_controller()
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord as LayerMembership

    state.memberships["D1"] = LayerMembershipRecord(layer_id="D1",
        role=LayerRole.INITIAL_FACIES_DRAFT, source_version_id="v1"
    )
    controller.apply_freshness(
        StaleSummary(
            artifacts=(
                ArtifactFreshness(
                    "phase1_draft:D1", "phase1_draft",
                    MappingStage.FACIES_CALIBRATION,
                    FreshnessStatus.CURRENT,
                ),
            )
        )
    )
    artifact = controller.layer_freshness("D1")
    assert artifact is not None and artifact.status == FreshnessStatus.CURRENT
    assert controller.layer_freshness("unknown-layer") is None
