from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.ui.pages.visualization_trace_panel import VisualizationTracePanel


def test_visualization_trace_panel_empty_state(qtbot):
    panel = VisualizationTracePanel()
    qtbot.addWidget(panel)

    panel.update_state([], [])

    assert panel.objectName() == "VisualizationTracePanel"
    assert panel.task_value.text() == "未选择预测任务"
    assert panel.map_value.text() == "未选择古地理图"
    assert panel.refresh_btn.text() == "刷新视图"
    assert "PNG" in panel.export_btn.text()
    assert hasattr(panel, "export_svg_btn")
    assert hasattr(panel, "export_pdf_btn")


def test_visualization_trace_panel_update_state(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)
    doc = PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2")
    panel = VisualizationTracePanel()
    qtbot.addWidget(panel)

    panel.update_state([task], [doc])

    assert panel.task_value.text() == task.name
    assert panel.map_value.text() == "ZJ2 Map"
