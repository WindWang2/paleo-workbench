from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.project.models import ProjectDocument


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

    page.task_panel.update_state = lambda tasks, selected_index=None: calls["task"].append(
        (tasks, selected_index)
    )
    page.canvas_panel.update_state = lambda task, project=None: calls["canvas"].append(
        (task, project)
    )
    page.evidence_panel.update_state = lambda task, bound_las=False: calls["evidence"].append(
        (task, bound_las)
    )
    page.canvas_panel.has_bound_las = lambda: False

    tasks = [{"name": "old"}, {"name": "active"}]
    project = object()
    page.update_state(tasks, project=project)

    assert calls["task"] == [(tasks, None)]
    assert calls["canvas"] == [(tasks[-1], project)]
    assert calls["evidence"] == [(tasks[-1], False)]


def test_well_log_completion_from_replaced_project_is_ignored(qtbot, monkeypatch):
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    old_project = ProjectDocument.new("old")
    new_project = ProjectDocument.new("new")
    service = object()
    page.set_project(old_project)
    page._inference_service = service
    page._active_inference_context = (page._session_token, old_project, service)
    received = []
    monkeypatch.setattr(page, "_on_inference_completed", received.append)

    page.set_project(new_project)
    page._on_inference_completed_if_current({"stale": True})

    assert received == []


def test_complete_run_without_result_is_visible(qtbot, monkeypatch):
    """#635: complete + result=None must not be a silent no-op."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    page._project = ProjectDocument.new("p")
    seen: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: seen.append((args, kwargs)),
    )
    page._on_inference_completed(
        {
            "run": SimpleNamespace(
                status="complete",
                parameters={"error": "CatalogStore save failed"},
                output_version_ids=["ver:1"],
            ),
            "result": None,
        }
    )
    assert seen
    assert "CatalogStore save failed" in str(seen[0])
