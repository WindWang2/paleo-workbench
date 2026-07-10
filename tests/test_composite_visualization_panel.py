from geoviz_cross_well import CrossWellCanvas
from geoviz_paleo_map import PaleoMapCanvas
from geoviz_seismic import SeismicView
from geoviz_well_log import WellLogCanvas

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel


def test_composite_visualization_panel_has_four_tabs(qtbot):
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "CompositeVisualizationPanel"
    assert panel.tabs.count() == 4
    assert panel.tabs.tabText(0) == "测井"
    assert panel.tabs.tabText(1) == "地震"
    assert panel.tabs.tabText(2) == "连井"
    assert panel.tabs.tabText(3) == "古地理"
    # Same primary public canvas types as geo-viz-engine domain pages.
    assert isinstance(panel.well_canvas, WellLogCanvas)
    assert isinstance(panel.seismic_view, SeismicView)
    assert isinstance(panel.cross_well_canvas, CrossWellCanvas)
    assert panel.cross_well_widget is panel.cross_well_canvas.widget
    assert isinstance(panel.map_canvas, PaleoMapCanvas)


def test_composite_visualization_panel_loads_prediction(qtbot):
    project = ProjectDocument.new("Test")
    MockPredictionAdapter().run(project, [], seed=1)
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)

    panel.update_state(project.prediction_tasks)

    assert len(panel.well_canvas.tracks) > 0
    assert panel.seismic_view.is_ready()
    assert panel.cross_well_widget.canvas_count == 2
