from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.visualization_page import VisualizationPage


def test_app_shell_page_five_is_visualization_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(6)
    assert isinstance(page, VisualizationPage)


def test_visualization_page_receives_project_slices(qtbot):
    project = ProjectDocument.new("Test")
    project.resources.append(ResourceItem(name="A.las", path="A.las", type="well_log", format="las"))
    task = MockPredictionAdapter().run(project, [], seed=1)
    project.paleomap_documents.append(PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2"))

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(6)

    assert page.summary_panel.prediction_count_value.text() == "1 个"
    assert page.trace_panel.task_value.text() == task.name
    assert page.composite_panel.cross_well_widget.canvas_count == 2
