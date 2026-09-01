from pathlib import Path

from PySide6.QtWidgets import QStackedWidget

from paleo_workbench.harness.actions.well import _well_resource_path
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui import navigation
from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(WellEntity(name="A12", surface_x=1.0, surface_y=2.0))
    project.resources.extend(
        [
            ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las"),
            ResourceItem(name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"),
            ResourceItem(name="meta.json", path=".preview_cache/meta.json", type="tabular", format="json"),
        ]
    )
    project.stratigraphy.target_horizon = "D63"
    return project


def test_app_shell_starts_in_native_workstation(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)

    assert shell.workstation.objectName() == "WorkstationFrame"
    assert shell.ribbon.height() == 0
    assert shell.workstation.document_stack.currentWidget() is shell.workstation.linked_workspace
    assert shell.workstation.document_tabs.count() == 4
    assert isinstance(shell.page_stack, QStackedWidget)
    assert shell.page_stack.count() == 5
    assert shell.workstation.linked_workspace._views_created is False


def test_legacy_workflows_are_documents_not_a_second_shell(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)

    shell.navigate_to(navigation.PAGE_INDEX_MAPPING, "review")
    assert shell.page_stack.currentIndex() == navigation.PAGE_INDEX_MAPPING
    assert shell.workstation.document_stack.currentWidget() is shell.page_stack
    assert shell.workstation.document_tabs.tabText(shell.workstation.TAB_LEGACY) == "成图审核"

    shell.workstation.activate_joint()
    assert shell.workstation.document_stack.currentWidget() is shell.workstation.linked_workspace

    shell.workstation.document_tabs.setCurrentIndex(shell.workstation.TAB_MAP)
    assert shell.workstation.linked_workspace._maximized_pane is shell.workstation.linked_workspace.map_pane

    shell.workstation.document_tabs.setCurrentIndex(shell.workstation.TAB_WELL)
    assert shell.workstation.linked_workspace._maximized_pane is shell.workstation.linked_workspace.well_pane


def test_explorer_separates_data_from_storage_cache(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    explorer = shell.workstation.explorer
    explorer.set_mode("data")

    labels = []
    root = explorer.model.invisibleRootItem()
    pending = [root.child(row) for row in range(root.rowCount())]
    while pending:
        item = pending.pop()
        labels.append(item.text())
        pending.extend(item.child(row) for row in range(item.rowCount()))

    assert "A12.Las" in labels
    assert "D63.dat" in labels
    assert "meta.json" not in labels
    assert "存储缓存默认隐藏" in explorer.footer_label.text()


def test_agent_plans_map_scientific_commands_to_typed_actions():
    show = AgentWorkspace._plan("显示所有井的平面位置")
    assert show.action_id == "well.list"
    assert show.gui_action == "show_wells"

    log = AgentWorkspace._plan("打开井 A12，把 GR 曲线放到第一道")
    assert log.action_id == "well.open"
    assert log.parameters == {"well": "A12"}
    assert log.followup_action == ("well.create_display", {"well": "A12", "curves": ["GR"]})

    joint = AgentWorkspace._plan("生成井震联合剖面")
    assert joint.action_id == "workflow.status"
    assert joint.gui_action == "focus_joint"


def test_agent_resolves_project_relative_well_resources(tmp_path):
    project = _project(tmp_path)
    context = ActionContext(
        project=project,
        project_path=str(tmp_path / "demo.paleo.json"),
    )

    assert _well_resource_path(context, project.wells[0]) == str(
        (tmp_path / "wells" / "A12.Las").resolve()
    )
