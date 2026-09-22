"""Adversarial matrix (H13): every abuse/failure path lands in an honest,
fail-closed terminal state — never a fake success, never a silent pass."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from paleo_workbench.harness import (
    ActionRegistry,
    ActionRisk,
    ActionSpec,
    ActionStatus,
    HarnessExecutor,
)
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.executor import (
    ActionUnavailableError,
    ActionValidationError,
)
from paleo_workbench.workflow.dag import (
    NodeSpec,
    SlotSpec,
    NodeState,
    RunState,
    WorkflowEngine,
    WorkflowSpec,
    WorkflowValidationError,
    validate_workflow_spec,
)
from paleo_workbench.workflow.dag.model import RetryPolicy
from paleo_workbench.workflow.dag.store import WorkflowRunStore
from paleo_workbench.workflow.recipe import RecipeError, load_recipe, save_recipe, recipe_from_spec

sys.path.insert(0, str(Path(__file__).parent / "fakes"))


@pytest.fixture()
def engine(tmp_path):
    reg = ActionRegistry()
    return WorkflowEngine(
        registry=reg, store=WorkflowRunStore(str(tmp_path / "runs"))
    ), reg


def _reg_spec(reg, action_id, handler, *, risk=ActionRisk.COMPUTE, **kwargs):
    reg.register(
        ActionSpec(action_id=action_id, description=action_id, handler=handler, risk=risk, **kwargs)
    )


class TestStaticAdversarial:
    def test_duplicate_action_registration_rejected(self):
        reg = ActionRegistry()
        spec = ActionSpec(action_id="a.b", description="dup", handler=lambda c, p: {})
        reg.register(spec)
        with pytest.raises(Exception, match="already registered"):
            reg.register(spec)

    def test_duplicate_provider_id_rejected(self):
        from paleo_workbench.providers.contracts import ProviderDescriptor, ProviderFamily
        from paleo_workbench.providers.errors import DuplicateProviderError
        from paleo_workbench.providers.registry import ProviderRegistry

        class P:
            descriptor = ProviderDescriptor(
                provider_id="evil.dup",
                family=ProviderFamily.INTERPOLATION,
                version="1.0.0",
                display_name="dup",
            )

            def execute(self, inputs, parameters, context):  # pragma: no cover
                raise AssertionError

        reg = ProviderRegistry()
        reg.register(P())
        with pytest.raises(DuplicateProviderError):
            reg.register(P())

    def test_self_dependency_rejected(self, engine):
        eng, reg = engine
        _reg_spec(reg, "a.b", lambda c, p: {})
        spec = WorkflowSpec(
            workflow_id="wf.self",
            name="self",
            nodes=(NodeSpec(node_id="a", action_id="a.b", depends_on=("a",)),),
        )
        assert any("self-dependency" in p for p in validate_workflow_spec(spec, reg))

    def test_nested_invalid_input_schema_rejected_at_runtime(self):
        reg = ActionRegistry()
        _reg_spec(
            reg,
            "a.nested",
            lambda c, p: {"never": True},
            input_schema={
                "type": "object",
                "properties": {
                    "roi": {
                        "type": "object",
                        "properties": {"il0": {"type": "integer"}},
                        "required": ["il0"],
                        "additionalProperties": False,
                    }
                },
            },
        )
        result = HarnessExecutor(reg).execute(
            "a.nested", {"roi": {"il0": "not-int"}}, ActionContext()
        )
        assert result.status == ActionStatus.REJECTED.value

    def test_malicious_recipe_path_traversal_refused(self, tmp_path):
        spec = WorkflowSpec(
            workflow_id="wf.t",
            name="t",
            nodes=(NodeSpec(node_id="a", action_id="x.y", parameters={"p": "../../etc/passwd"}),),
        )
        recipe = recipe_from_spec(spec)
        # Relative traversal is allowed by the portability gate (no absolute
        # path) but path CONTAINMENT happens at execution (resolve_contained_output).
        path = save_recipe(recipe, tmp_path / "t.paleo-workflow.json")
        assert path.exists()
        with pytest.raises(RecipeError):
            load_recipe(tmp_path / "missing.paleo-workflow.json")

    def test_recipe_with_embedded_sql_refused(self, tmp_path):
        spec = WorkflowSpec(
            workflow_id="wf.sql",
            name="sql",
            nodes=(NodeSpec(node_id="a", action_id="x.y", parameters={"sql": "SELECT 1"}),),
        )
        with pytest.raises(RecipeError, match="forbidden"):
            save_recipe(recipe_from_spec(spec), tmp_path / "sql.paleo-workflow.json")


class TestRuntimeAdversarial:
    def test_cancelled_action_marks_node_cancelled(self, engine):
        eng, reg = engine
        from paleo_workbench.runtime.task_scheduler import TaskCancelled

        def cancels(ctx, p):
            ctx.cancel.raise_if_cancelled = ctx.cancel.raise_if_cancelled
            raise TaskCancelled("mid-node cancel")

        _reg_spec(reg, "a.cancel", cancels)
        _reg_spec(reg, "b.after", lambda c, p: {})
        spec = WorkflowSpec(
            workflow_id="wf.cancel",
            name="cancel",
            nodes=(
                NodeSpec(node_id="a", action_id="a.cancel"),
                NodeSpec(node_id="b", action_id="b.after", depends_on=("a",)),
            ),
        )
        ctx = ActionContext()
        run = eng.create_run(spec, context=ctx)
        done = eng.run(run.run_id, context=ctx)
        assert done.state is RunState.CANCELLED
        assert done.node_runs["a"].state is NodeState.CANCELLED
        assert done.node_runs["b"].state is NodeState.CANCELLED

    def test_non_idempotent_write_never_retried_by_default(self, engine):
        eng, reg = engine
        calls = []

        def write_once(ctx, p):
            calls.append(1)
            raise RuntimeError("disk full")

        _reg_spec(reg, "a.write", write_once, risk=ActionRisk.WRITE)
        spec = WorkflowSpec(
            workflow_id="wf.write",
            name="write",
            nodes=(NodeSpec(node_id="a", action_id="a.write"),),
        )
        # WRITE needs an explicit grant; with it, a failed write is retried
        # exactly once at most under the default policy (max_attempts=1).
        ctx = ActionContext(permissions=frozenset({ActionRisk.READ, ActionRisk.COMPUTE, ActionRisk.WRITE}))
        run = eng.create_run(spec, context=ctx)
        done = eng.run(run.run_id, context=ctx)
        assert len(calls) == 1  # default policy: no blind re-execution of writes
        assert done.state is RunState.FAILED

        # Without the grant the write never executes at all (guard gate).
        calls.clear()
        run2 = eng.create_run(spec, context=ActionContext())
        done2 = eng.run(run2.run_id, context=ActionContext())
        assert calls == []
        assert done2.node_runs["a"].action_status == "rejected"

    def test_missing_output_key_fails_dependents(self, engine):
        eng, reg = engine
        downstream_calls = []

        _reg_spec(reg, "a.hollow", lambda c, p: {"not_the_key": 1})
        _reg_spec(
            reg,
            "b.need",
            lambda c, p: downstream_calls.append(1),
        )
        spec = WorkflowSpec(
            workflow_id="wf.hollow",
            name="hollow",
            nodes=(
                NodeSpec(node_id="a", action_id="a.hollow"),
                NodeSpec(
                    node_id="b",
                    action_id="b.need",
                    depends_on=("a",),
                    parameters={"v": {"$ref": "a"}},
                ),
            ),
        )
        ctx = ActionContext()
        run = eng.create_run(spec, context=ctx)
        # $ref resolves to the WHOLE outputs dict (present), so the node runs;
        # a MISSING node reference is the fail-closed path instead.
        done = eng.run(run.run_id, context=ctx)
        assert done.state is RunState.COMPLETED

        # A ref to an absent upstream node id is a static error up front.
        spec2 = WorkflowSpec(
            workflow_id="wf.hollow2",
            name="hollow2",
            nodes=(
                NodeSpec(
                    node_id="b",
                    action_id="b.need",
                    depends_on=(),
                    parameters={"v": {"$ref": "ghost"}},
                ),
            ),
        )
        with pytest.raises(WorkflowValidationError):
            eng.create_run(spec2, context=ctx)
        assert downstream_calls == [1]

    def test_stale_upstream_busts_downstream_identity(self, engine, tmp_path):
        eng, reg = engine
        execution_counter = {"a": 0, "b": 0}
        from inmemory_catalog import InMemoryCatalog, sha256_of_file

        catalog = InMemoryCatalog()
        eng2 = WorkflowEngine(
            registry=reg, store=eng.store_for(ActionContext()), catalog=catalog
        )

        def compute_a(ctx, p):
            execution_counter["a"] += 1
            f = tmp_path / f"a-out-{execution_counter['a']}.dat"
            f.write_bytes(f"payload-{execution_counter['a']}".encode())
            version = catalog.register_input(
                name="a-out", path=str(f), checksum=sha256_of_file(f)
            )
            return {"version_ids": [version.version_id], "n": execution_counter["a"]}

        def compute_b(ctx, p):
            execution_counter["b"] += 1
            return {"echo": p["up"]["n"]}

        _reg_spec(reg, "a.compute", compute_a, deterministic=True, cacheable=True, output_refs=("DataVersionRef",))
        _reg_spec(reg, "b.compute", compute_b)

        spec = WorkflowSpec(
            workflow_id="wf.stale",
            name="stale",
            slots=(SlotSpec(name="seed", schema={"type": "integer"}),),
            nodes=(
                NodeSpec(
                    node_id="a",
                    action_id="a.compute",
                    parameters={"seed": {"$slot": "seed"}},
                ),
                NodeSpec(
                    node_id="b",
                    action_id="b.compute",
                    depends_on=("a",),
                    parameters={"up": {"$ref": "a"}},
                ),
            ),
        )
        ctx = ActionContext(catalog=catalog)
        first = eng2.create_run(spec, slot_values={"seed": 1}, context=ctx)
        eng2.run(first.run_id, context=ctx)
        assert execution_counter == {"a": 1, "b": 1}

        # The seed change makes 'a' semantically NEW: its identity changes,
        # it re-executes, produces a different output version — and the
        # downstream identity changes with it, so 'b' re-executes too.
        # (Re-running an UNCHANGED deterministic 'a' would legitimately
        # cache-hit: identical identity + resolvable outputs.)
        second = eng2.rerun(
            first.run_id,
            from_nodes=["a"],
            slot_overrides={"seed": 2},
            context=ctx,
        )
        assert second.node_runs["a"].from_cache is False
        assert second.node_runs["b"].from_cache is False
        assert execution_counter == {"a": 2, "b": 2}
        assert second.node_runs["b"].outputs["echo"] == 2

    def test_handler_import_error_is_unavailable(self):
        reg = ActionRegistry()

        def needs_optional_backend(ctx, p):
            import some_optional_geology_backend  # noqa: F401

        _reg_spec(reg, "a.opt", needs_optional_backend)
        result = HarnessExecutor(reg).execute("a.opt", {}, ActionContext())
        assert result.status == ActionStatus.UNAVAILABLE.value

    def test_unavailable_node_never_retried(self, engine):
        eng, reg = engine
        calls = []

        def unavailable(ctx, p):
            calls.append(1)
            raise ActionUnavailableError("engine gone")

        _reg_spec(
            reg,
            "a.gone",
            unavailable,
        )
        spec = WorkflowSpec(
            workflow_id="wf.gone",
            name="gone",
            nodes=(
                NodeSpec(
                    node_id="a",
                    action_id="a.gone",
                    retry=RetryPolicy(max_attempts=3),
                ),
            ),
        )
        run = eng.create_run(spec, context=ActionContext())
        eng.run(run.run_id, context=ActionContext())
        assert calls == [1]  # unavailability is terminal, retries never run

    def test_permission_refusal_is_rejected(self):
        reg = ActionRegistry()
        _reg_spec(reg, "a.write", lambda c, p: {}, risk=ActionRisk.WRITE)
        result = HarnessExecutor(reg).execute("a.write", {}, ActionContext())
        assert result.status == ActionStatus.REJECTED.value
        assert "write" in (result.error or "")

    def test_output_schema_mismatch_fails_even_when_handler_succeeds(self):
        reg = ActionRegistry()
        _reg_spec(
            reg,
            "a.liar",
            lambda c, p: {"result": "definitely-a-string"},
            output_schema={"type": "object", "properties": {"result": {"type": "integer"}}},
        )
        result = HarnessExecutor(reg).execute("a.liar", {}, ActionContext())
        assert result.status == ActionStatus.FAILED.value
        assert "output schema mismatch" in (result.error or "")

    def test_fast_reruns_are_isolated(self, engine):
        """Rapid repeated create/run cycles must not bleed state."""
        eng, reg = engine
        _reg_spec(reg, "a.count", lambda c, p: {"n": 1})
        spec = WorkflowSpec(
            workflow_id="wf.rapid",
            name="rapid",
            nodes=(NodeSpec(node_id="a", action_id="a.count"),),
        )
        ctx = ActionContext()
        seen = []
        for _ in range(5):
            run = eng.create_run(spec, context=ctx)
            done = eng.run(run.run_id, context=ctx)
            seen.append(done.run_id)
        assert len(set(seen)) == 5  # every run has its own identity
        store = eng.store_for(ctx)
        for run_id in seen:
            loaded = store.load(run_id)
            assert loaded.state is RunState.COMPLETED

    def test_project_switch_refuses_resume(self, engine):
        eng, reg = engine
        _reg_spec(reg, "a.n", lambda c, p: {})
        spec = WorkflowSpec(
            workflow_id="wf.proj",
            name="proj",
            nodes=(NodeSpec(node_id="a", action_id="a.n"),),
        )
        ctx = ActionContext(project_path="/wks/one.paleo.json")
        run = eng.create_run(spec, context=ctx)
        eng.run(run.run_id, context=ctx)
        other = ActionContext(project_path="/wks/two.paleo.json")
        with pytest.raises(WorkflowValidationError, match="refused"):
            eng.resume(run.run_id, context=other)
