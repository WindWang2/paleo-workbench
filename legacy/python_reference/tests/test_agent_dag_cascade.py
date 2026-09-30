"""Regression tests for DAG failure cascade (ISSUE-021).

An upstream task failure used to strand every downstream node in PENDING:
they could never run (dependencies never complete) while ``is_finished()``
kept returning False, so the swarm harness reported an eternally
incomplete run. Failed nodes must cascade SKIPPED to transitive dependents.
"""

from __future__ import annotations

from paleo_workbench.agent.harness import PaleoAIHarness
from paleo_workbench.agent.planner import (
    TaskGraph,
    TaskNode,
    TaskPlanner,
    TaskStatus,
)


def _chain_graph() -> TaskGraph:
    """a -> b -> c (plus an independent node d that must be untouched)."""
    graph = TaskGraph()
    graph.add_node(TaskNode(id="a", agent_name="missing_agent", action="x", description="a"))
    graph.add_node(
        TaskNode(id="b", agent_name="whatever", action="x", description="b",
                 dependencies=["a"])
    )
    graph.add_node(
        TaskNode(id="c", agent_name="whatever", action="x", description="c",
                 dependencies=["b"])
    )
    graph.add_node(TaskNode(id="d", agent_name="whatever", action="x", description="d"))
    return graph


def test_failed_node_cascades_skipped_to_transitive_dependents():
    graph = _chain_graph()
    graph.nodes["a"].status = TaskStatus.FAILED
    graph.nodes["a"].error = "boom"

    skipped = graph.cascade_skip("a", "skipped: upstream task 'a' failed")

    assert skipped == ["b", "c"]
    assert graph.nodes["b"].status is TaskStatus.SKIPPED
    assert graph.nodes["c"].status is TaskStatus.SKIPPED
    assert "a" in (graph.nodes["b"].error or "")
    # Independent node untouched.
    assert graph.nodes["d"].status is TaskStatus.PENDING
    # The failed chain reaches a terminal state once unrelated work settles
    # (the harness loop runs independent nodes normally).
    graph.nodes["d"].status = TaskStatus.COMPLETED
    assert graph.is_finished()


def test_diamond_dependency_cascade_skips_each_branch_once():
    graph = TaskGraph()
    graph.add_node(TaskNode(id="root", agent_name="m", action="x", description="r"))
    for name in ("left", "right"):
        graph.add_node(
            TaskNode(id=name, agent_name="m", action="x", description=name,
                     dependencies=["root"])
        )
    graph.add_node(
        TaskNode(id="join", agent_name="m", action="x", description="j",
                 dependencies=["left", "right"])
    )
    graph.nodes["root"].status = TaskStatus.FAILED
    graph.nodes["root"].error = "boom"

    skipped = graph.cascade_skip("root", "reason")

    assert sorted(skipped) == ["join", "left", "right"]
    assert graph.is_finished()


class _StubIntent:
    class primary_domain:
        value = "well"

    target_horizon = ""
    factor_type = ""
    parameters: dict = {}


class _StubParser:
    def parse(self, query, context):
        return _StubIntent()


class _StubPlanner(TaskPlanner):
    def __init__(self, graph: TaskGraph):
        self._graph = graph

    def create_plan(self, intent):  # noqa: ARG002 (stub)
        return self._graph


def test_harness_loop_reports_finished_after_upstream_failure():
    """End-to-end through the harness execution loop: a missing agent fails
    node 'a', and the harness must cascade SKIPPED so the run terminates in
    a terminal (finished) state instead of stranding PENDING dependents."""
    graph = _chain_graph()
    harness = PaleoAIHarness(parser=_StubParser(), planner=_StubPlanner(graph))

    result = harness.execute_query("test query")

    assert result.plan.nodes["a"].status is TaskStatus.FAILED
    assert result.plan.nodes["b"].status is TaskStatus.SKIPPED
    assert result.plan.nodes["c"].status is TaskStatus.SKIPPED
    assert result.plan.is_finished(), "DAG must reach a terminal state"
    assert not result.success, "a failed run must not report success"
    assert any("Skipped 2 downstream" in line for line in result.execution_logs), (
        result.execution_logs
    )
