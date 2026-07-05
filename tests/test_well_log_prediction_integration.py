from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage


def test_app_shell_page_two_is_well_log_prediction_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(2)
    assert isinstance(page, WellLogPredictionPage)


def test_well_log_prediction_page_receives_project_prediction_tasks(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(2)

    assert page.task_panel.name_value.text() == task.name
    assert page.canvas_panel.well_log_data.well_name == task.name
    assert page.evidence_panel.evidence_list.count() == 3
