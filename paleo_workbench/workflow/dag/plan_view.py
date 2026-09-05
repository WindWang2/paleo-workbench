"""UI-independent workflow plan model (H11).

Task Center / Agent panel consume THIS model — never the engine internals,
never widgets. One :class:`WorkflowPlanView` renders a WorkflowRun (live or
finished) as an ordered checklist:

    ✓ 输入检查            succeeded
    ● 插值 61%           running + progress
    ○ 等值线             pending
    ↷ 质检（条件未满足）   skipped
    ✗ 导出               failed

The view never touches Qt; the panel decides how to paint it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.workflow.dag.model import (
    NodeState,
    RunState,
    WorkflowRun,
    WorkflowSpec,
)

_SYMBOLS = {
    NodeState.PENDING: "○",
    NodeState.RUNNING: "●",
    NodeState.SUCCEEDED: "✓",
    NodeState.FAILED: "✗",
    NodeState.CANCELLED: "⊗",
    NodeState.SKIPPED: "↷",
    NodeState.UNAVAILABLE: "⊘",
}

_STATE_LABELS = {
    RunState.RUNNING: "运行中",
    RunState.COMPLETED: "已完成",
    RunState.FAILED: "失败",
    RunState.CANCELLED: "已取消",
    RunState.INTERRUPTED: "已中断（可恢复）",
}


@dataclass(slots=True)
class PlanItem:
    """One checklist row (pure data)."""

    node_id: str
    label: str
    state: NodeState
    detail: str = ""
    from_cache: bool = False
    receipt_status: str | None = None
    error: str | None = None

    def symbol(self) -> str:
        return _SYMBOLS.get(self.state, "○")

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "state": self.state.value,
            "detail": self.detail,
            "from_cache": self.from_cache,
            "receipt_status": self.receipt_status,
            "error": self.error,
            "symbol": self.symbol(),
        }


@dataclass(slots=True)
class WorkflowPlanView:
    """Checklist model of one workflow (plan-ahead or live/finished run)."""

    workflow_id: str
    name: str
    state: str = RunState.RUNNING.value
    progress: float = 0.0
    items: list[PlanItem] = field(default_factory=list)

    # ------------------------------------------------------------ build --
    @classmethod
    def from_spec(cls, spec: WorkflowSpec) -> "WorkflowPlanView":
        """Plan-ahead view: every node pending, in topological order."""
        view = cls(
            workflow_id=spec.workflow_id, name=spec.name, state=RunState.RUNNING.value
        )
        view.items = [
            PlanItem(node_id=n.node_id, label=n.description or n.node_id, state=NodeState.PENDING)
            for n in spec.nodes
        ]
        return view

    @classmethod
    def from_run(cls, run: WorkflowRun) -> "WorkflowPlanView":
        view = cls(workflow_id=run.workflow.workflow_id, name=run.workflow.name)
        view.update_from_run(run)
        return view

    @classmethod
    def from_summary(cls, summary: dict[str, Any], *, spec: WorkflowSpec | None = None) -> "WorkflowPlanView":
        """Rebuild from a persisted run summary (e.g. a workflow.run action
        result) — the panel never needs the engine for this."""
        view = cls(
            workflow_id=str(summary.get("workflow_id", "")),
            name=str(summary.get("name", "")),
            state=str(summary.get("state", RunState.RUNNING.value)),
            progress=float(summary.get("progress", 0.0) or 0.0),
        )
        nodes = summary.get("nodes") or {}
        if spec is not None:
            ordered = [n for n in spec.nodes if n.node_id in nodes]
        else:
            ordered = list(nodes)
        for node in ordered:
            node_id = node.node_id if spec is not None else node
            info = nodes.get(node_id) or {}
            state = NodeState(info.get("state", "pending"))
            detail = info.get("skip_reason") or info.get("error") or ""
            receipt_status = info.get("receipt_status")
            item = PlanItem(
                node_id=node_id,
                label=node.description
                if spec is not None
                else str(info.get("label") or node_id),
                state=state,
                detail=str(detail),
                from_cache=bool(info.get("from_cache", False)),
                receipt_status=receipt_status,
                error=info.get("error"),
            )
            view.items.append(item)
        return view

    def update_from_run(self, run: WorkflowRun) -> None:
        self.state = run.state.value
        total = len(run.node_runs)
        done = sum(
            1
            for nr in run.node_runs.values()
            if nr.state
            in (
                NodeState.SUCCEEDED,
                NodeState.FAILED,
                NodeState.CANCELLED,
                NodeState.SKIPPED,
                NodeState.UNAVAILABLE,
            )
        )
        self.progress = round(done / total, 3) if total else 0.0
        by_id = {n.node_id: n for n in run.workflow.nodes}
        self.items = [
            PlanItem(
                node_id=nr.node_id,
                label=by_id[nr.node_id].description or nr.node_id,
                state=nr.state,
                detail=nr.skip_reason or nr.error or "",
                from_cache=nr.from_cache,
                receipt_status=(nr.receipt or {}).get("status"),
                error=nr.error,
            )
            for nr in run.node_runs.values()
        ]
        # Preserve topological order of the spec.
        order = {n.node_id: i for i, n in enumerate(run.workflow.nodes)}
        self.items.sort(key=lambda item: order.get(item.node_id, 10**9))

    # ----------------------------------------------------------- output --
    def current_node(self) -> str | None:
        for item in self.items:
            if item.state is NodeState.RUNNING:
                return item.label
        return None

    def state_label(self) -> str:
        return _STATE_LABELS.get(RunState(self.state), self.state)

    def checklist(self) -> list[dict[str, Any]]:
        """Rows for a checklist renderer (pure data, UI decides styling)."""
        rows = [item.to_dict() for item in self.items]
        current = self.current_node()
        for row in rows:
            if row["state"] == "running":
                row["detail"] = row["detail"] or f"{int(self.progress * 100)}%"
        if current:
            for row in rows:
                if row["label"] == current:
                    row["current"] = True
        return rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "state": self.state,
            "state_label": self.state_label(),
            "progress": self.progress,
            "current_node": self.current_node(),
            "items": self.checklist(),
        }
