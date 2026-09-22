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
    assert panel.run_btn.text() == "运行线上测井预测"
    assert panel.send_btn.text() == "发送制备"
    assert panel.export_btn.text() == "导出单井剖面"


def test_prediction_evidence_panel_update_state(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)
    panel = PredictionEvidencePanel()
    qtbot.addWidget(panel)

    panel.update_state(task)

    # Honest labeling: the mock adapter's output is demo + mock — never 真实.
    assert panel.mock_value.text() == "Demo · Mock · 可替换"
    assert panel.source_value.text() == "合成演示数据"
    assert panel.evidence_list.count() == 3
    assert "sand_thickness" in panel.evidence_list.item(0).text()


def test_prediction_evidence_panel_labels_heuristic(qtbot):
    from paleo_workbench.project.models import PredictionTask

    task = PredictionTask(
        name="启发式",
        adapter_kind="local",
        result_summary={
            "predicted_regions": [],
            "is_mock": False,
            "is_replaceable": True,
            "final_scientific_prediction": False,
            "model_type": "heuristic",
            "probabilities_uncalibrated": True,
        },
        evidence_contribution=[],
    )
    panel = PredictionEvidencePanel()
    qtbot.addWidget(panel)
    panel.update_state(task)
    # Heuristic (not scientific, not mock) is labeled 启发式, never 真实.
    assert panel.mock_value.text() == "启发式 · 可替换"
