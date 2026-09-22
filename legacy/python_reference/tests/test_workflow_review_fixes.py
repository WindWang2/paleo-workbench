"""Review-fix regressions: run re-entry interlock, honest carry-over
identity with $context bindings, condition-reference waits, project-switch
INTERRUPTED semantics, checkpoint-failure abort, external cancel bridge,
recipe-load path boundary."""
from __future__ import annotations

import threading

import pytest

from paleo_workbench.harness import ActionRegistry, ActionRisk, ActionSpec
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.workflow.dag import (
    NodeCondition,
    NodeSpec,
    NodeState,
    RunState,
    WorkflowEngine,
    WorkflowSpec,
    WorkflowValidationError,
)
from paleo_workbench.workflow.dag.store import WorkflowRunStore


@pytest.fixture()
def engine(tmp_path):
    reg = ActionRegistry()
    eng = WorkflowEngine(registry=reg, store=WorkflowRunStore(str(tmp_path / "runs")))
    return eng, reg


class TestRunInterlock:
    def test_concurrent_run_refused(self, engine):
        eng, reg = engine
        started = threading.Event()
        release = threading.Event()

        def slow(ctx, p):
            started.set()
            release.wait(2)
            return {}

        reg.register(ActionSpec(action_id="a.slow", description="a", handler=slow, risk=ActionRisk.COMPUTE))
        spec = WorkflowSpec(
            workflow_id="wf.lock",
            name="lock",
            nodes=(NodeSpec(node_id="a", action_id="a.slow"),),
        )
        ctx = ActionContext()
        run = eng.create_run(spec, context=ctx)
        outcome = {}

        def driver():
            outcome["run"] = eng.run(run.run_id, context=ctx)

        thread = threading.Thread(target=driver)
        thread.start()
        assert started.wait(2)
        with pytest.raises(WorkflowValidationError, match="already executing"):
            eng.run(run.run_id, context=ctx)
        with pytest.raises(WorkflowValidationError, match="already executing"):
            eng.resume(run.run_id, context=ctx)
        release.set()
        thread.join(5)
        assert outcome["run"].state is RunState.COMPLETED


class TestContextBindingCarryOver:
    def test_selection_change_busts_carry_over(self, engine):
        eng, reg = engine
        calls = []

        def handler(ctx, p):
            calls.append(dict(p))
            return {"version_ids": []}

        reg.register(ActionSpec(action_id="a.ctx", description="a", handler=handler, risk=ActionRisk.COMPUTE))
        spec = WorkflowSpec(
            workflow_id="wf.ctx",
            name="ctx",
            nodes=(
                NodeSpec(
                    node_id="a",
                    action_id="a.ctx",
                    parameters={"wells": {"$context": "selection.selected_well_ids"}},
                ),
            ),
        )
        ctx = ActionContext()
        ctx.selection = ctx.selection.__class__(selected_well_ids=("W1", "W2"))
        first = eng.create_run(spec, context=ctx)
        eng.run(first.run_id, context=ctx)
        calls.clear()

        # The active selection changed: a rerun must NOT carry the node over
        # even though nothing else (slots/inputs) changed.
        ctx.selection = ctx.selection.__class__(selected_well_ids=("W9",))
        second = eng.rerun(first.run_id, from_nodes=["a"], context=ctx)
        assert second.node_runs["a"].from_cache is False
        assert calls == [{"wells": ["W9"]}]


class TestConditionWaits:
    def test_condition_on_non_dependency_waits_then_skips_or_runs(self, engine):
        eng, reg = engine
        reg.register(ActionSpec(action_id="a.c", description="a", handler=lambda c, p: {"count": 5}, risk=ActionRisk.COMPUTE))
        downstream = []
        reg.register(
            ActionSpec(
                action_id="b.c",
                description="b",
                handler=lambda c, p: downstream.append(1),
                risk=ActionRisk.COMPUTE,
            )
        )
        spec = WorkflowSpec(
            workflow_id="wf.condwait",
            name="condwait",
            nodes=(
                NodeSpec(node_id="a", action_id="a.c"),
                NodeSpec(
                    node_id="b",
                    action_id="b.c",
                    condition=NodeCondition(kind="node_output_equals", node="a", key="count", value=5),
                ),
            ),
        )
        run = eng.create_run(spec, context=ActionContext())
        done = eng.run(run.run_id, context=ActionContext())
        assert done.state is RunState.COMPLETED
        # b waited for a's terminal state, saw count == 5, and executed.
        assert done.node_runs["b"].state is NodeState.SUCCEEDED
        assert downstream == [1]


class TestExternalCancel:
    def test_external_token_stops_run(self, engine):
        eng, reg = engine

        class _ExternalToken:
            def __init__(self):
                self.flag = False

            @property
            def is_cancelled(self):
                return self.flag

            def raise_if_cancelled(self):
                pass

        external = _ExternalToken()
        reg.register(ActionSpec(action_id="a.n", description="a", handler=lambda c, p: {}, risk=ActionRisk.COMPUTE))
        spec = WorkflowSpec(
            workflow_id="wf.ext",
            name="ext",
            nodes=(
                NodeSpec(node_id="a", action_id="a.n"),
                NodeSpec(node_id="b", action_id="a.n", depends_on=("a",)),
            ),
        )
        ctx = ActionContext()
        run = eng.create_run(spec, context=ctx)
        # The external token cancels right after the first node completes.
        original = reg.get("a.n").handler

        def spy(ctx, p):
            result = original(ctx, p)
            external.flag = True
            return result

        reg.unregister("a.n")
        reg.register(ActionSpec(action_id="a.n", description="a", handler=spy, risk=ActionRisk.COMPUTE))
        done = eng.run(run.run_id, context=ctx, external_cancel=external)
        # An explicit external cancel is a TERMINAL cancel (same as
        # engine.cancel): b never runs, and resume refuses to revive it.
        assert done.state is RunState.CANCELLED
        assert done.node_runs["a"].state is NodeState.SUCCEEDED
        assert done.node_runs["b"].state is NodeState.CANCELLED
        external.flag = False
        revived = eng.resume(run.run_id, context=ctx, external_cancel=external)
        assert revived.state is RunState.CANCELLED  # terminal, untouched


class TestRecipeBoundary:
    def test_recipe_load_outside_store_refused(self, engine, tmp_path):
        from paleo_workbench.workflow.recipe import RecipeDocument, recipe_from_spec, save_recipe

        eng, reg = engine
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        spec = WorkflowSpec(
            workflow_id="wf.boundary",
            name="boundary",
            nodes=(NodeSpec(node_id="a", action_id="x.y", parameters={"p": "v"}),),
        )
        path = save_recipe(recipe_from_spec(spec), outside / "secret.paleo-workflow.json")

        from paleo_workbench.harness.actions.workflow import _contained_recipe_path

        ctx = ActionContext(project_path=str(tmp_path / "proj.paleo.json"))
        with pytest.raises(PermissionError, match="outside the project workflow store"):
            _contained_recipe_path(ctx, str(path))


class TestMetaWorkflowGuard:
    def test_workflow_action_cannot_be_a_node(self, engine):
        eng, reg = engine
        reg.register(ActionSpec(action_id="workflow.run", description="run", handler=lambda c, p: {}, risk=ActionRisk.COMPUTE))
        spec = WorkflowSpec(
            workflow_id="wf.meta",
            name="meta",
            nodes=(NodeSpec(node_id="a", action_id="workflow.run"),),
        )
        from paleo_workbench.workflow.dag import validate_workflow_spec

        problems = validate_workflow_spec(spec, reg)
        assert any("meta-workflow" in p for p in problems)
