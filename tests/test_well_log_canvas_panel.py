from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel


def test_well_log_canvas_panel_empty_state(qtbot):
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "WellLogCanvasPanel"
    assert panel.empty_label.text() == "未选择预测任务"
    assert panel.canvas.tracks == []


def test_well_log_canvas_panel_loads_tracks(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(task)

    assert panel.empty_label.isHidden()
    assert panel.well_log_data.well_name == task.name
    assert len(panel.canvas.tracks) > 0
