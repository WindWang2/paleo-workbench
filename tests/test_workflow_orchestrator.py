"""Unit tests for WorkflowOrchestrator deep module (Candidate 4)."""

from __future__ import annotations

import pytest
from paleo_workbench.project.models import ProjectDocument, ProjectMeta, ResourceItem
from paleo_workbench.workflow.orchestrator import WorkflowOrchestrator, WorkflowStepContext, StepTransitionResult


def test_workflow_orchestrator_initial_context():
    project = ProjectDocument(meta=ProjectMeta(name="Test"))
    orchestrator = WorkflowOrchestrator(project=project)

    ctx = orchestrator.get_step_context()
    assert isinstance(ctx, WorkflowStepContext)
    assert ctx.step_id == "data_check"
    assert ctx.index == 0
    assert ctx.total_steps == 6
    assert ctx.step_name == "数据校验"


def test_workflow_orchestrator_prerequisite_blocking():
    project = ProjectDocument(meta=ProjectMeta(name="Test"))
    orchestrator = WorkflowOrchestrator(project=project)
    orchestrator.current_step_index = 1  # factor_map step

    res = orchestrator.next_step()
    assert isinstance(res, StepTransitionResult)
    assert res.success is False
    assert "数据资产清单不能为空" in res.message


def test_workflow_orchestrator_successful_advancement():
    project = ProjectDocument(meta=ProjectMeta(name="Test"))
    project.resources.append(ResourceItem(name="Well-01", type="well_log", format="las", path="/tmp/well.las"))
    orchestrator = WorkflowOrchestrator(project=project)

    res = orchestrator.next_step()
    assert res.success is True
    assert orchestrator.current_step_index == 1
    assert orchestrator.get_step_context().step_id == "factor_map"
