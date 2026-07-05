from geoviz_seismic import SeismicView
from geoviz_well_log import WellLogCanvas
from geoviz_well_log.cross_well_widget import CrossWellWidget

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel


def test_composite_visualization_panel_has_three_tabs(qtbot):
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "CompositeVisualizationPanel"
    assert panel.tabs.count() == 3
    assert isinstance(panel.well_canvas, WellLogCanvas)
    assert isinstance(panel.seismic_view, SeismicView)
    assert isinstance(panel.cross_well_widget, CrossWellWidget)


def test_composite_visualization_panel_loads_prediction(qtbot):
    project = ProjectDocument.new("Test")
    MockPredictionAdapter().run(project, [], seed=1)
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)

    panel.update_state(project.prediction_tasks)

    assert len(panel.well_canvas.tracks) > 0
    assert panel.seismic_view.is_ready()
    assert panel.cross_well_widget.canvas_count == 2
