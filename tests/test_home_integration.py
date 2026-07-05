from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.ui.pages.home_page import HomePage


def test_app_shell_page_zero_is_home_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(0)
    assert isinstance(page, HomePage)


def test_home_page_has_workflow_data(qtbot):
    project = ProjectDocument.new("Test Project")
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(0)
    assert isinstance(page, HomePage)
    # With no compilation runs, all steps should be "待开始"
    for sw in page.workflow_progress.step_widgets:
        assert "待开始" in sw["status"].text()
