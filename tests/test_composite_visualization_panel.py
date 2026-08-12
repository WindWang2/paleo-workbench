from geoviz import (
    CrossWellCanvas,
    PaleoMapCanvas,
    SeismicView,
    WellLogCanvas,
    WellTieCanvas,
)
from PySide6.QtWidgets import QFrame

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel


def test_composite_visualization_panel_has_engine_aligned_tabs(qtbot):
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "CompositeVisualizationPanel"
    # Seven tabs: six package canvases + GeoVizEngine prepare/render host.
    assert panel.tabs.count() == 7
    assert panel.tabs.tabText(0) == "测井"
    assert panel.tabs.tabText(1) == "多井对比剖面"
    assert panel.tabs.tabText(2) == "地震"
    assert panel.tabs.tabText(3) == "连井"
    assert panel.tabs.tabText(4) == "古地理"
    assert panel.tabs.tabText(5) == "井震标定"
    assert panel.tabs.tabText(6) == "引擎预览"
    # Same primary public canvas types as geo-viz-engine domain pages.
    assert isinstance(panel.well_canvas, WellLogCanvas)
    assert isinstance(panel.seismic_view, SeismicView)
    assert isinstance(panel.cross_well_canvas, CrossWellCanvas)
    assert panel.cross_well_widget is panel.cross_well_canvas.widget
    assert isinstance(panel.map_canvas, PaleoMapCanvas)
    assert isinstance(panel.well_tie_canvas, WellTieCanvas)


def test_composite_visualization_panel_loads_prediction(qtbot):
    project = ProjectDocument.new("Test")
    MockPredictionAdapter().run(project, [], seed=1)
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)

    panel.update_state(project.prediction_tasks)

    if panel.well_host._engine_view is None:
        assert len(panel.well_canvas.tracks) > 0
    else:
        assert panel.well_host._engine_load["curve_count"] > 0
    assert panel.seismic_view.is_ready()
    assert panel.cross_well_widget.canvas_count == 2
    assert panel.well_tie_canvas._depths is not None
    assert panel.well_tie_canvas._synthetic is not None


def test_composite_well_host_prefers_retained_engine_when_available(qtbot, monkeypatch):
    import paleo_workbench.viz.hosts.well_log_host as host_module

    class FakeNativeView(QFrame):
        def submit_multi_track(self, payload):
            return {
                "curve_count": len(payload["curves"]),
                "track_count": len(payload["tracks"]),
            }

    monkeypatch.setattr(
        host_module.engine_adapter,
        "try_import_welllog",
        lambda: (object(), FakeNativeView, object()),
    )
    project = ProjectDocument.new("Test")
    MockPredictionAdapter().run(project, [], seed=1)
    panel = CompositeVisualizationPanel()
    qtbot.addWidget(panel)

    panel.update_state(project.prediction_tasks)

    host = panel.well_host
    assert host._engine_view is not None
    assert host.view_stack.currentWidget() is host.engine_host
    assert host._engine_load["curve_count"] >= 1
    # No parallel legacy scene is maintained while the native surface is live.
    assert host.canvas.tracks == []
