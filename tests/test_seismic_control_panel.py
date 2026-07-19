from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel


def test_seismic_control_panel_empty_state(qtbot):
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "SeismicControlPanel"
    assert panel.title_label.text() == "智能分析结果"
    assert panel.shape_value.text() == "—"
    assert panel.mode_combo.currentText() == "vd"
    assert panel.attribute_value.text() == "振幅"
    assert not hasattr(panel, "run_btn")
    assert panel.send_btn.text() == "发送编图"


def test_seismic_control_panel_update_state(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)

    panel.update_state(task, volume_shape=(8, 10, 12))

    assert panel.shape_value.text() == "8 × 10 × 12"
    assert panel.mock_value.text() == "Mock · 可替换"
    assert panel.status_value.text() == "complete"


def test_seismic_control_panel_reflects_selected_attribute(qtbot):
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)

    panel.set_attribute_label("包络")

    assert panel.attribute_value.text() == "包络"
