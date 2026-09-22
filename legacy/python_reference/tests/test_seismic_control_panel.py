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
    # Mock adapter output is honestly labeled Demo (synthetic source),
    # matching PredictionEvidencePanel's labeling (I3 parity).
    assert panel.mock_value.text() == "Demo · Mock · 可替换"
    assert panel.status_value.text() == "complete"


def test_seismic_control_panel_reflects_selected_attribute(qtbot):
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)

    panel.set_attribute_label("包络")

    assert panel.attribute_value.text() == "包络"


def test_seismic_control_panel_heuristic_label_not_real(qtbot):
    """Heuristic output (is_mock=False, final_scientific_prediction=False)
    must display as 启发式, never 真实 (review finding I3)."""
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)
    # The Mock adapter is is_mock=True; force heuristic semantics.
    task.result_summary = {
        "is_mock": False,
        "final_scientific_prediction": False,
        "probabilities_uncalibrated": True,
        "is_replaceable": True,
    }
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, volume_shape=(8, 10, 12))
    assert "真实" not in panel.mock_value.text()
    assert "启发式" in panel.mock_value.text()


def test_seismic_control_panel_scientific_label(qtbot):
    """A genuine scientific prediction (final_scientific_prediction=True,
    not mock) displays as 科学预测."""
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)
    task.result_summary = {
        "is_mock": False,
        "final_scientific_prediction": True,
        "is_replaceable": False,
    }
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, volume_shape=(8, 10, 12))
    assert "科学预测" in panel.mock_value.text()


def test_seismic_control_panel_demo_source_labeled(qtbot):
    """Synthetic/demo source output must carry the Demo marker even when
    is_mock is absent (parity with PredictionEvidencePanel)."""
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)
    task.result_summary = {
        "is_mock": False,
        "final_scientific_prediction": True,
        "source": "synthetic/demo",
    }
    panel = SeismicControlPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, volume_shape=(8, 10, 12))
    assert "Demo" in panel.mock_value.text()
