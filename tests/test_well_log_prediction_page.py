from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage


def test_well_log_prediction_page_assembles_three_widgets(qtbot):
    page = WellLogPredictionPage()
    qtbot.addWidget(page)

    assert page.objectName() == "WellLogPredictionPage"
    assert isinstance(page.task_panel, PredictionTaskPanel)
    assert isinstance(page.canvas_panel, WellLogCanvasPanel)
    assert isinstance(page.evidence_panel, PredictionEvidencePanel)


def test_well_log_prediction_page_update_delegates(qtbot):
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    calls = {"task": [], "canvas": [], "evidence": []}

    page.task_panel.update_state = lambda tasks: calls["task"].append(tasks)
    page.canvas_panel.update_state = lambda task, project=None: calls["canvas"].append(
        (task, project)
    )
    page.evidence_panel.update_state = lambda task: calls["evidence"].append(task)

    tasks = [{"name": "old"}, {"name": "active"}]
    project = object()
    page.update_state(tasks, project=project)

    assert calls["task"] == [tasks]
    assert calls["canvas"] == [(tasks[-1], project)]
    assert calls["evidence"] == [tasks[-1]]
