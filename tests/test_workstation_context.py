# -*- coding: utf-8 -*-
"""B11/B12/B4 workstation context integration.

- B11: explorer selections publish into the shared SelectionContext via
  ViewCoordinationController (no second selection bus).
- B12/#1186: agent plans carry minimal permissions (never blanket WRITE),
  GUI undo restores the pre-action state instead of a fabricated default.
- B4: the inspector style page routes layer styling to the real layer
  properties editor instead of a fake in-panel palette.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace, _plan_risks

from tests.test_workstation_shell import _project as _shell_project


def _project(tmp_path: Path) -> ProjectDocument:
    project = _shell_project(tmp_path)
    return project


def test_explorer_selection_publishes_to_shared_context(qtbot, tmp_path):
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    assert ws._coordination is shell.view_coordination

    payload = {"kind": "well", "well_name": "A12", "id": "A12"}
    ws._publish_explorer_selection(payload)
    snapshot = shell.view_coordination.selection_context.snapshot()
    assert snapshot.active_well_id == "A12"
    assert (
        snapshot.source_widget_id
        == type(shell.view_coordination).SOURCE_WORKSTATION
    )

    ws._publish_explorer_selection({"kind": "layer", "layer_id": "lyr-1"})
    snapshot = shell.view_coordination.selection_context.snapshot()
    assert snapshot.active_layer_id == "lyr-1"


def test_explorer_garbage_payload_is_not_published(qtbot, tmp_path):
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    before = shell.view_coordination.selection_context.snapshot()
    ws = shell.workstation
    ws._publish_explorer_selection(None)
    ws._publish_explorer_selection({"kind": "well", "well_name": ""})
    after = shell.view_coordination.selection_context.snapshot()
    assert after.timestamp == before.timestamp


# ---------------------------------------------------------------------------
# B12 / #1186 — agent permissions and undo
# ---------------------------------------------------------------------------


def test_agent_plans_never_request_write():
    for command in (
        "显示所有井的平面位置",
        "打开井 A12",
        "打开井 A12，把 GR 曲线放到第一道",
        "生成井震联合剖面",
        "当前上下文是什么",
    ):
        plan = AgentWorkspace._plan(command)
        risks = _plan_risks(plan)
        assert "write" not in risks, command
        assert risks <= {"read", "compute"}, command


def test_agent_planner_does_not_invent_default_well(qtbot):
    panel = AgentWorkspace()
    qtbot.addWidget(panel)
    plan = panel._plan("打开井")
    assert plan.action_id == "well.open"
    assert not str(plan.parameters.get("well") or "").strip()
    # 执行期解析：绑定了活动井就带上，没绑定就留空（参数校验会诚实拒绝）。
    panel.set_active_well("W23")
    plan.parameters.setdefault("well", "")
    resolved = panel._well_from_parameters(plan.parameters)
    assert resolved == "W23"
    panel2 = AgentWorkspace()
    qtbot.addWidget(panel2)
    assert panel2._well_from_parameters({"well": ""}) == ""


def test_agent_context_label_reflects_real_state(qtbot, tmp_path):
    panel = AgentWorkspace(project=_project(tmp_path))
    qtbot.addWidget(panel)
    text = panel.context_label.text()
    assert "Pearl River Mouth" in text
    assert "D63" in text  # stratigraphy.target_horizon, real project value
    assert "井震联合" not in text  # old fabricated label is gone
    panel.set_active_well("A12")
    assert "井 A12" in panel.context_label.text()


def test_shell_undo_restores_previous_well(qtbot, tmp_path):
    from unittest.mock import patch

    from paleo_workbench.ui.app_shell import AppShell

    project = _project(tmp_path)
    project.wells.append(
        WellEntity(name="W23", surface_x=3.0, surface_y=4.0, project_x=3.0, project_y=4.0)
    )
    project.resources.append(
        ResourceItem(name="W23.Las", path="wells/W23.Las", type="well_log", format="las")
    )
    shell = AppShell(project=project)
    qtbot.addWidget(shell)
    ws = shell.workstation

    with patch.object(ws.linked_workspace, "open_well") as open_well:
        ws.show_well("A12")
        assert ws._current_well_name == "A12"
        ws._open_well_from_agent("W23")
        assert open_well.call_args_list[-1].args == ("W23",)
        # 撤销 Agent 动作：恢复动作前的井 A12，而不是编造默认井名。
        ws._undo_agent_gui({})
        assert open_well.call_args_list[-1].args == ("A12",)
        assert ws._agent_undo_stack == []
        # 撤销历史为空时诚实提示，不伪造成功。
        ws._undo_agent_gui({})
        assert open_well.call_args_list[-1].args == ("A12",)


# ---------------------------------------------------------------------------
# B4 — style page routes to the real editor
# ---------------------------------------------------------------------------


def test_inspector_style_page_routes_layer_to_real_editor(qtbot, tmp_path):
    from paleo_workbench.ui.workstation.inspector import WorkstationInspector

    inspector = WorkstationInspector(_project(tmp_path))
    qtbot.addWidget(inspector)

    inspector.show_payload({"kind": "layer", "layer_id": "lyr-9", "name": "砂岩等值线"})
    assert inspector.style_edit_button.isVisibleTo(inspector.style_page)
    assert "砂岩等值线" in inspector.style_summary.text()

    received = []
    inspector.edit_style_requested.connect(received.append)
    inspector.style_edit_button.click()
    assert received == ["lyr-9"]


def test_inspector_style_page_honest_for_non_layers(qtbot, tmp_path):
    from paleo_workbench.ui.workstation.inspector import WorkstationInspector

    inspector = WorkstationInspector(_project(tmp_path))
    qtbot.addWidget(inspector)
    inspector.show_payload({"kind": "well", "well_name": "A12", "object": None})
    assert not inspector.style_edit_button.isVisibleTo(inspector.style_page)
    assert "没有可编辑的地图样式" in inspector.style_summary.text()
    inspector.show_empty()
    assert not inspector.style_edit_button.isVisibleTo(inspector.style_page)


def test_shell_routes_style_edit_request_to_composite(qtbot, tmp_path):
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    opened = []
    with patch_composite(ws, opened):
        ws.inspector.edit_style_requested.emit("lyr-3")
    assert opened == [("lyr-3", "symbology")]


def patch_composite(ws, opened):
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        original = ws.composite.open_layer_properties
        ws.composite.open_layer_properties = (
            lambda layer_id, *, focus="": opened.append((layer_id, focus))
        )
        try:
            yield
        finally:
            ws.composite.open_layer_properties = original

    return _ctx()
