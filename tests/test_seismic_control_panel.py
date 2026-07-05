from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel


def test_seismic_control_panel_empty_state(qtbot):
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "SeismicControlPanel"
    assert panel.shape_value.text() == "—"
    assert panel.mode_value.text() == "vd"
    assert panel.run_btn.text() == "运行地震预测"
    assert panel.send_btn.text() == "发送编图"


def test_seismic_control_panel_update_state(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)

    panel.update_state(task, volume_shape=(8, 10, 12))

    assert panel.shape_value.text() == "8 × 10 × 12"
    assert panel.mock_value.text() == "Mock · 可替换"
