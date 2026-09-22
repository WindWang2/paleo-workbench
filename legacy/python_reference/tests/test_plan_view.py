"""H11: the UI-independent plan model and its agent-panel consumption."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from paleo_workbench.workflow.dag.model import (
    NodeRun,
    NodeSpec,
    NodeState,
    RunState,
    WorkflowRun,
    WorkflowSpec,
)
from paleo_workbench.workflow.dag.plan_view import WorkflowPlanView


def _spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="wf.plan",
        name="单因素图",
        nodes=(
            NodeSpec(node_id="a", action_id="x.y", description="输入检查"),
            NodeSpec(node_id="b", action_id="x.y", depends_on=("a",), description="插值"),
            NodeSpec(node_id="c", action_id="x.y", depends_on=("b",), description="编图"),
        ),
    )


def _run_mixed_states() -> WorkflowRun:
    run = WorkflowRun.create(_spec(), {})
    run.state = RunState.RUNNING
    run.node_runs["a"] = NodeRun(
        node_id="a", state=NodeState.SUCCEEDED, receipt={"status": "success"}
    )
    run.node_runs["b"] = NodeRun(node_id="b", state=NodeState.RUNNING)
    run.node_runs["c"] = NodeRun(node_id="c", state=NodeState.PENDING)
    return run


class TestPlanView:
    def test_plan_ahead_all_pending(self):
        view = WorkflowPlanView.from_spec(_spec())
        rows = view.checklist()
        assert [r["symbol"] for r in rows] == ["○", "○", "○"]
        assert [r["label"] for r in rows] == ["输入检查", "插值", "编图"]

    def test_mixed_states_symbols_and_progress(self):
        view = WorkflowPlanView.from_run(_run_mixed_states())
        rows = view.checklist()
        assert rows[0]["symbol"] == "✓"
        assert rows[1]["symbol"] == "●"
        assert rows[2]["symbol"] == "○"
        assert view.progress == 0.333  # rounded for stable display
        assert view.current_node() == "插值"

    def test_skipped_and_cache_rows(self):
        run = WorkflowRun.create(_spec(), {})
        run.state = RunState.COMPLETED
        run.node_runs["a"] = NodeRun(node_id="a", state=NodeState.SUCCEEDED)
        run.node_runs["b"] = NodeRun(node_id="b", state=NodeState.SKIPPED, skip_reason="条件未满足")
        run.node_runs["c"] = NodeRun(node_id="c", state=NodeState.SUCCEEDED, from_cache=True)
        rows = WorkflowPlanView.from_run(run).checklist()
        assert rows[1]["symbol"] == "↷"
        assert "条件未满足" in rows[1]["detail"]
        assert rows[2]["from_cache"] is True

    def test_from_summary_needs_no_engine(self):
        summary = {
            "run_id": "r1",
            "workflow_id": "wf.plan",
            "name": "单因素图",
            "state": "failed",
            "progress": 1.0,
            "nodes": {
                "a": {"state": "succeeded", "receipt_status": "success"},
                "b": {"state": "failed", "error": "插值发散"},
                "c": {"state": "skipped", "skip_reason": "upstream b failed"},
            },
        }
        view = WorkflowPlanView.from_summary(summary, spec=_spec())
        rows = view.checklist()
        assert rows[1]["symbol"] == "✗"
        assert "插值发散" in rows[1]["detail"]
        assert view.state_label() == "失败"

    def test_to_dict_round_trip_safe(self):
        data = WorkflowPlanView.from_run(_run_mixed_states()).to_dict()
        assert data["current_node"] == "插值"
        assert len(data["items"]) == 3


@pytest.fixture()
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class TestPanelWiring:
    def test_panel_renders_checklist_and_progress(self, qapp):
        pytest.importorskip("PySide6")
        sys.path.insert(0, str(Path(__file__).parent))
        from paleo_workbench.ui.workstation.agent_panel import AgentWorkspace

        panel = AgentWorkspace(project=None)
        try:
            # Progress signal path updates the label (queued through bridge).
            panel._on_progress_changed(0.66, "单因素图 · 插值")
            assert "66%" in panel.progress_label.text()
            assert panel.progress_label.isVisibleTo(panel)

            # Completion renders the checklist from the run summary.
            from types import SimpleNamespace

            # Shape mirrors the real workflow.run action output (_run_summary):
            # nodes keyed by node_id with state/receipt facts.
            outputs = {
                "run_id": "r-test",
                "workflow_id": "wf.plan",
                "name": "单因素图",
                "state": "running",
                "progress": 0.333,
                "nodes": {
                    "a": {"label": "输入检查", "state": "succeeded", "receipt_status": "success"},
                    "b": {"label": "插值", "state": "running"},
                    "c": {"label": "编图", "state": "pending"},
                },
            }
            result = SimpleNamespace(
                action_id="workflow.run",
                outputs=outputs,
                ok=True,
                error=None,
            )
            plan = SimpleNamespace(gui_action=None, action_id="workflow.run", parameters={})
            payload = {"plan": plan, "receipt_id": "x", "results": [result]}
            panel._on_completed(payload)
            text = panel.history.toPlainText()
            assert "✓ 输入检查" in text
            assert "● 插值" in text
            assert "○ 编图" in text
            # The progress line resets after completion.
            assert not panel.progress_label.isVisibleTo(panel)
        finally:
            panel.deleteLater()
