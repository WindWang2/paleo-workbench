"""Workflow DAG engine package (Harness 2.0).

Static validated DAGs of professional actions, persisted resumable runs,
deterministic cache over catalog-verified outputs, and standard execution
receipts. Entry points:

- :class:`WorkflowEngine` — create / run / resume / rerun / cancel runs
- :class:`WorkflowSpec` / :class:`NodeSpec` — the static graph (data only)
- :class:`WorkflowRunStore` — atomic JSON checkpoints in project storage
- :func:`validate_workflow_spec` — the fail-closed static gate
"""
from __future__ import annotations

from paleo_workbench.workflow.dag.engine import (
    WorkflowEngine,
    WorkflowValidationError,
)
from paleo_workbench.workflow.dag.model import (
    NodeCondition,
    NodeRun,
    NodeSpec,
    NodeState,
    RetryPolicy,
    RunState,
    SlotSpec,
    WorkflowRun,
    WorkflowSpec,
)
from paleo_workbench.workflow.dag.receipt import ExecutionReceipt
from paleo_workbench.workflow.dag.store import WorkflowRunStore
from paleo_workbench.workflow.dag.validation import (
    BindingError,
    validate_workflow_spec,
)

__all__ = [
    "BindingError",
    "ExecutionReceipt",
    "NodeCondition",
    "NodeRun",
    "NodeSpec",
    "NodeState",
    "RetryPolicy",
    "RunState",
    "SlotSpec",
    "WorkflowEngine",
    "WorkflowRun",
    "WorkflowRunStore",
    "WorkflowSpec",
    "WorkflowValidationError",
    "validate_workflow_spec",
]
