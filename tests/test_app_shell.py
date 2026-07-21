from paleo_workbench.ui.app_shell import AppShell, PAGE_INDEX_DATA
from paleo_workbench.ui import tokens
from paleo_workbench.project.models import (
    ExportArtifact,
    PaleoMapDocument,
    ProjectDocument,
    ResourceItem,
)


def test_app_shell_assembles_all_zones(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.menu_bar is not None
    assert not hasattr(shell, "header_toolbar")
    assert shell.menu_bar.search_box.objectName() == "SearchBox"
    assert shell.icon_rail is not None
    assert shell.sidebar is not None
    assert shell.page_stack is not None
    assert shell.status_bar is not None


def test_app_shell_has_ten_pages(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.count() == 10


def test_app_shell_default_page_is_zero(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.currentIndex() == 0


def test_app_shell_icon_rail_switches_page(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.icon_rail.nav_buttons[4].click()
    assert shell.page_stack.currentIndex() == 4
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[4]


def test_app_shell_hides_sidebar_on_data_page_and_restores_on_navigation(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.icon_rail.nav_buttons[1].click()
    assert shell.page_stack.currentIndex() == PAGE_INDEX_DATA
    assert shell.sidebar.isHidden()

    shell.icon_rail.nav_buttons[4].click()
    assert shell.page_stack.currentIndex() == 4
    assert shell.sidebar.isHidden()
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[4]


def test_app_shell_data_sidebar_receives_resource_counts(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        )
    ]
    artifacts = [
        ExportArtifact(
            linked_id="map_1",
            format="PDF",
            output_path="/tmp/map.pdf",
        )
    ]

    shell.update_data_page({}, resources, artifacts)

    texts = "\n".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[0]
    assert "项目总览" in texts
    assert "资源 1" not in texts
    assert "阅读器: empty" not in texts


def test_app_shell_switching_to_data_renders_cached_context(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        )
    ]
    artifacts = [
        ExportArtifact(
            linked_id="map_1",
            format="PDF",
            output_path="/tmp/map.pdf",
        )
    ]

    shell.update_data_page({}, resources, artifacts)
    shell.icon_rail.nav_buttons[1].click()

    texts = "\n".join(label.text() for label in shell.sidebar._content_labels)
    assert "资源 1" in texts
    assert "成果 1" in texts
    assert "异常 0" in texts
    assert "阅读器: empty" in texts


def test_app_shell_set_project_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.set_project_name("HZ26 Demo")
    assert "HZ26 Demo" in shell.status_bar.status_label.text()


def test_app_shell_mapping_sidebar_shows_map_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    docs = [
        PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2"),
    ]
    shell.update_mapping_page(docs)
    shell.icon_rail.nav_buttons[8].click()

    texts = "\n".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == "编图"
    assert "图件: ZJ2 Map" in texts
    assert "层位: ZJ2" in texts
    assert "状态: 已保存" in texts


def test_app_shell_object_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.objectName() == "AppShell"


def test_app_shell_syncs_data_page_context_to_sidebar(tmp_path, qtbot):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    shell = AppShell(project=project)
    qtbot.addWidget(shell)
    page = shell.page_stack.widget(1)

    page._set_selected_asset(resource)
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == "text", timeout=3000)

    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[0]
    assert "项目总览" in " ".join(label.text() for label in shell.sidebar._content_labels)

    shell.icon_rail.nav_buttons[1].click()

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[1]
    assert "当前选择: notes.txt" in text
    assert "阅读器: text" in text


def test_app_shell_initializes_sidebar_on_home_context(tmp_path, qtbot):
    path = tmp_path / "resource-1.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    project.resources.append(
        ResourceItem(
            name="resource-1.txt",
            path=str(path),
            type="document",
            format="txt",
        )
    )

    shell = AppShell(project=project)
    qtbot.addWidget(shell)

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[0]
    assert "项目总览" in text
    assert "资源 1" not in text


def test_app_shell_update_data_page_preserves_sidebar_selection(tmp_path, qtbot):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    shell = AppShell(project=project)
    qtbot.addWidget(shell)
    page = shell.page_stack.widget(1)

    page._set_selected_asset(resource)
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == "text", timeout=3000)
    shell.update_data_page({}, project.resources, project.export_artifacts)
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[0]

    shell.icon_rail.nav_buttons[1].click()

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert "资源 1" in text
    assert "当前选择: notes.txt" in text
    assert "格式: document / txt" in text
    assert "阅读器: text" in text


def test_app_shell_retains_data_sidebar_context_when_navigating_back(tmp_path, qtbot):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    shell = AppShell(project=project)
    qtbot.addWidget(shell)
    page = shell.page_stack.widget(1)

    page._set_selected_asset(resource)
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == "text", timeout=3000)
    shell.icon_rail.nav_buttons[4].click()
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[4]
    shell.icon_rail.nav_buttons[1].click()

    text = " ".join(label.text() for label in shell.sidebar._content_labels)
    assert shell.sidebar.context_label.text() == "数据"
    assert "资源 1" in text
    assert "当前选择: notes.txt" in text
    assert "阅读器: text" in text
    assert "当前选择: 未选择" not in text
    assert "阅读器: empty" not in text


def test_app_shell_has_workflow_stepper(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert hasattr(shell, "workflow_stepper")
    assert shell.workflow_stepper is not None
    assert shell.workflow_stepper.objectName() == "WorkflowStepper"


def test_app_shell_stepper_switches_stage_and_recalls_subpage(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    # Initial stage is 3 (HomePage = index 0)
    assert shell.workflow_stepper.active_stage_index == 3
    assert shell.page_stack.currentIndex() == 0

    # Click Stepper Stage 0 (Data & Prep) -> should switch to PAGE_INDEX_DATA (1)
    shell.workflow_stepper.stage_buttons[0].click()
    assert shell.page_stack.currentIndex() == 1
    assert shell.workflow_stepper.active_stage_index == 0

    # Click Stepper Stage 2 (Mapping) -> should switch to PAGE_INDEX_MAPPING (8)
    shell.workflow_stepper.stage_buttons[2].click()
    assert shell.page_stack.currentIndex() == 8
    assert shell.workflow_stepper.active_stage_index == 2

    # Switch subpage within Stage 2 to PAGE_INDEX_VISUALIZATION (6)
    shell._switch_page(6)
    assert shell.page_stack.currentIndex() == 6

    # Switch back to Stage 0, then back to Stage 2 -> should recall PAGE_INDEX_VISUALIZATION (6)
    shell.workflow_stepper.stage_buttons[0].click()
    assert shell.page_stack.currentIndex() == 1

    shell.workflow_stepper.stage_buttons[2].click()
    assert shell.page_stack.currentIndex() == 6

