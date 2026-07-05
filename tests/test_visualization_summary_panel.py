from paleo_workbench.project.models import PaleoMapDocument, ResourceItem
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.visualization_summary_panel import VisualizationSummaryPanel


def test_visualization_summary_panel_counts(qtbot):
    project = ProjectDocument.new("Test")
    project.resources.append(ResourceItem(name="A.las", path="A.las", type="well_log", format="las"))
    project.paleomap_documents.append(PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2"))
    MockPredictionAdapter().run(project, [], seed=1)
    panel = VisualizationSummaryPanel()
    qtbot.addWidget(panel)

    panel.update_state(project.resources, project.prediction_tasks, project.paleomap_documents)

    assert panel.objectName() == "VisualizationSummaryPanel"
    assert panel.prediction_count_value.text() == "1 个"
    assert panel.map_count_value.text() == "1 幅"
    assert panel.resource_count_value.text() == "1 项"
