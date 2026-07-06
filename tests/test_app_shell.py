from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui import tokens
from paleo_workbench.project.models import ExportArtifact, ResourceItem


def test_app_shell_assembles_all_zones(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.menu_bar is not None
    assert shell.header_toolbar is not None
    assert shell.icon_rail is not None
    assert shell.sidebar is not None
    assert shell.page_stack is not None
    assert shell.status_bar is not None


def test_app_shell_has_nine_pages(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.count() == 9


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


def test_app_shell_data_sidebar_receives_resource_counts(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.icon_rail.nav_buttons[1].click()
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

    texts = "\n".join(
        label.text() for label in shell.sidebar.findChildren(type(shell.sidebar.context_label))
    )
    assert "资源 1" in texts
    assert "成果 1" in texts
    assert "PDF 翻页阅读" in texts


def test_app_shell_set_project_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.set_project_name("HZ26 Demo")
    assert "HZ26 Demo" in shell.status_bar.status_label.text()


def test_app_shell_object_name(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.objectName() == "AppShell"
