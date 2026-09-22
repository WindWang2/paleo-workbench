from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage


def test_app_shell_page_three_is_seismic_prediction_page(qtbot, monkeypatch):
    monkeypatch.setattr("paleo_workbench.viz.native_factor_map.require_native_scene", lambda: None)
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.seismic_page
    assert isinstance(page, SeismicPredictionPage)


def test_seismic_prediction_page_receives_project_prediction_tasks(qtbot, monkeypatch):
    monkeypatch.setattr("paleo_workbench.viz.native_factor_map.require_native_scene", lambda: None)
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.seismic_page

    assert page.context_toolbar.task_value.text() == task.name
    assert page.view_panel.volume_shape == (8, 10, 12)
    assert page.control_panel.shape_value.text() == "8 × 10 × 12"
