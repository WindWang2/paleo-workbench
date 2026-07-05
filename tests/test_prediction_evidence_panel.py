from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel


def test_prediction_evidence_panel_empty_state(qtbot):
    panel = PredictionEvidencePanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "PredictionEvidencePanel"
    assert panel.mock_value.text() == "—"
    assert panel.evidence_list.count() == 0
    assert panel.run_btn.text() == "运行测井预测"
    assert panel.send_btn.text() == "发送制备"


def test_prediction_evidence_panel_update_state(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)
    panel = PredictionEvidencePanel()
    qtbot.addWidget(panel)

    panel.update_state(task)

    assert panel.mock_value.text() == "Mock · 可替换"
    assert panel.evidence_list.count() == 3
    assert "sand_thickness" in panel.evidence_list.item(0).text()
