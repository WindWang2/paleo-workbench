"""Issue #847 — workflow state honesty batch.

Covers:
1. ``_evidence_step_status`` must report ``failed`` for factor_map/prediction
   steps whose tasks all failed (previously returned ``running``).
2. ``WorkflowOrchestrator`` must refuse to advance without evidence-backed
   validity (previously walked an empty project straight to 已完成).
3. Freshness overlay exceptions must be logged, not silently swallowed.
"""

from __future__ import annotations

import logging

from paleo_workbench.project.models import FactorMapTask, PredictionTask, ProjectDocument
from paleo_workbench.workflow.orchestrator import WorkflowOrchestrator
from paleo_workbench.workflow.service import (
    home_workflow_steps,
    infer_workflow_step_status,
)


def _factor_task(status: str) -> FactorMapTask:
    return FactorMapTask(
        name="sand",
        target_horizon="H1",
        factor_type="sand",
        method="IDW",
        status=status,
    )


def _prediction_task(status: str) -> PredictionTask:
    return PredictionTask(name="p1", status=status)


# --------------------------------------------------------------------- 1. failed


def test_factor_map_all_failed_reports_failed():
    project = ProjectDocument.new(name="Demo")
    project.factor_map_tasks.append(_factor_task("failed"))
    project.factor_map_tasks.append(_factor_task("failed"))

    assert infer_workflow_step_status(project, "factor_map") == "failed"


def test_factor_map_mixed_complete_failed_reports_failed():
    """Any failed task must surface as failed, not be hidden behind complete."""
    project = ProjectDocument.new(name="Demo")
    project.factor_map_tasks.append(_factor_task("complete"))
    project.factor_map_tasks.append(_factor_task("failed"))

    assert infer_workflow_step_status(project, "factor_map") == "failed"


def test_prediction_all_failed_reports_failed():
    project = ProjectDocument.new(name="Demo")
    project.prediction_tasks.append(_prediction_task("failed"))

    assert infer_workflow_step_status(project, "prediction") == "failed"


def test_factor_map_running_when_no_completion_no_failure():
    """The pre-existing semantics stay intact for the running/pending cases."""
    project = ProjectDocument.new(name="Demo")
    project.factor_map_tasks.append(_factor_task("running"))
    assert infer_workflow_step_status(project, "factor_map") == "running"

    project.prediction_tasks.append(_prediction_task("complete"))
    assert infer_workflow_step_status(project, "prediction") == "complete"


def test_home_steps_surface_failed_factor_map():
    project = ProjectDocument.new(name="Demo")
    run_steps = home_workflow_steps(project)
    project.factor_map_tasks.append(_factor_task("failed"))
    by_type = {s.step_type: s.status for s in home_workflow_steps(project)}
    assert all(s.status == "pending" for s in run_steps)  # unchanged baseline
    assert by_type["factor_map"] == "failed"


# ------------------------------------------------------------------- 2. orchestrator


def test_orchestrator_refuses_advance_without_evidence():
    """An empty project must not walk the workflow strip to 已完成."""
    project = ProjectDocument.new(name="Demo")
    orchestrator = WorkflowOrchestrator(project=project)

    result = orchestrator.next_step()
    assert result.success is False
    assert orchestrator.current_step_index == 0


def test_orchestrator_refuses_advance_when_current_step_invalid():
    """Advancing past data_check with no factor output must be refused."""
    project = ProjectDocument.new(name="Demo")
    from paleo_workbench.project.models import ResourceItem

    project.resources.append(
        ResourceItem(name="A1.las", path="a.las", type="well_log", format="las")
    )
    orchestrator = WorkflowOrchestrator(project=project)

    first = orchestrator.next_step()
    assert first.success is True  # data_check is complete → advance to factor_map
    assert orchestrator.get_step_context().step_id == "factor_map"

    result = orchestrator.next_step()
    assert result.success is False  # factor_map is pending → no evidence to advance
    assert orchestrator.current_step_index == 1


def test_orchestrator_advances_when_step_evidence_complete():
    project = ProjectDocument.new(name="Demo")
    from paleo_workbench.project.models import ResourceItem

    project.resources.append(
        ResourceItem(name="A1.las", path="a.las", type="well_log", format="las")
    )
    project.factor_map_tasks.append(_factor_task("complete"))
    orchestrator = WorkflowOrchestrator(project=project)

    assert orchestrator.next_step().success is True  # data_check ok
    assert orchestrator.next_step().success is True  # factor_map complete ok


# ------------------------------------------------------------------- 3. freshness logging


def test_freshness_overlay_exception_is_logged(caplog):
    project = ProjectDocument.new(name="Demo")
    project.factor_map_tasks.append(_factor_task("complete"))

    class BoomFreshness:
        def step_freshness(self, step_type):
            raise RuntimeError("catalog backend exploded")

    with caplog.at_level(logging.WARNING, logger="paleo_workbench.workflow"):
        status = infer_workflow_step_status(
            project, "factor_map", freshness_service=BoomFreshness()
        )

    assert status == "complete"  # degrades safely
    assert any(
        "freshness overlay failed" in rec.message
        and "catalog backend exploded" in (rec.exc_text or "")
        for rec in caplog.records
    ), [r.message for r in caplog.records]


def test_home_steps_freshness_service_failure_is_logged(caplog, monkeypatch):
    project = ProjectDocument.new(name="Demo")

    def boom_for_project(*args, **kwargs):
        raise RuntimeError("freshness module broken")

    monkeypatch.setattr(
        "paleo_workbench.workflow.freshness.FreshnessService.for_project",
        boom_for_project,
        raising=False,
    )
    with caplog.at_level(logging.WARNING, logger="paleo_workbench.workflow"):
        steps = home_workflow_steps(project)

    by_type = {s.step_type: s.status for s in steps}
    assert by_type["factor_map"] == "pending"  # evidence-only fallback intact
    assert any("freshness service unavailable" in r.message for r in caplog.records)