from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.workflow.factors import create_mock_factor_map


def test_app_shell_page_six_is_preparation_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(6)
    assert isinstance(page, PreparationPage)


def test_preparation_page_has_factor_tasks(qtbot):
    project = ProjectDocument.new("Test")
    create_mock_factor_map(project, target_horizon="T1", factor_type="sand", seed=1)
    create_mock_factor_map(project, target_horizon="T1", factor_type="shale", seed=2)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(6)
    assert isinstance(page, PreparationPage)
    summary_text = page.task_panel.summary_label.text()
    assert "2 / 2" in summary_text
