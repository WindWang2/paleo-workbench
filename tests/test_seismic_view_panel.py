from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel


def test_seismic_view_panel_empty_state(qtbot):
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "SeismicViewPanel"
    assert panel.empty_label.text() == "未选择预测任务"
    assert panel.volume_shape is None


def test_seismic_view_panel_loads_demo_volume(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)

    panel.update_state(task)

    assert panel.empty_label.isHidden()
    assert panel.volume_shape == (8, 10, 12)
    assert panel.view.is_ready()
