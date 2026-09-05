"""Workflow DAG engine tests (H2/H3): static validation, execution order,
conditional skip, retry, cancel propagation, crash resume, partial rerun,
deterministic cache identity gates and the project-switch guard."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from paleo_workbench.harness import (
    ActionRegistry,
    ActionRisk,
    ActionSpec,
)
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.workflow.dag import (
    NodeRun,
    NodeSpec,
    NodeState,
    RunState,
    SlotSpec,
    WorkflowEngine,
    WorkflowSpec,
    WorkflowValidationError,
    validate_workflow_spec,
)
from paleo_workbench.workflow.dag.model import RetryPolicy
from paleo_workbench.workflow.dag.store import WorkflowRunStore

sys.path.insert(0, str(Path(__file__).parent / "fakes"))
from inmemory_catalog import InMemoryCatalog  # noqa: E402


class Recorder:
    """Counts handler executions per node id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def handler(self, name, *, output=None, raises=None):
        def _handler(ctx, params):
            self.calls.append((name, dict(params)))
            if raises is not None:
                raise raises
            return output if output is not None else {"node": name, "version_ids": [f"ver-{name}"]}
        return _handler

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.calls if n == name)


def build_registry(rec: Recorder, *, cacheable: bool = False) -> ActionRegistry:
    reg = ActionRegistry()
    for name in ("a.compute", "b.compute", "c.compute", "d.compute"):
        reg.register(
            ActionSpec(
                action_id=name,
                description=f"{name} test action",
                handler=rec.handler(name),
                risk=ActionRisk.COMPUTE,
                deterministic=True,
                cacheable=cacheable,
                output_refs=("DataVersionRef",) if cacheable else (),
            )
        )
    return reg


def make_engine(reg: ActionRegistry, store_root: str | None = None, catalog=None) -> WorkflowEngine:
    store = WorkflowRunStore(store_root or tempfile.mkdtemp())
    return WorkflowEngine(registry=reg, store=store, catalog=catalog)


def linear_spec(**node_kwargs) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="test.linear",
        name="linear",
        nodes=(
            NodeSpec(node_id="a", action_id="a.compute"),
            NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
            NodeSpec(node_id="c", action_id="c.compute", depends_on=("b",)),
        ),
        **node_kwargs,
    )


# ------------------------------------------------------------ static gates --

class TestStaticValidation:
    def _reg(self) -> ActionRegistry:
        reg = ActionRegistry()
        for name in ("a.compute", "b.compute"):
            reg.register(
                ActionSpec(action_id=name, description=name, handler=lambda c, p: {}, risk=ActionRisk.READ)
            )
        return reg

    def test_cycle_rejected(self):
        spec = WorkflowSpec(
            workflow_id="t.cycle",
            name="cycle",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute", depends_on=("b",)),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
            ),
        )
        problems = validate_workflow_spec(spec, self._reg())
        assert any("cycle" in p for p in problems)

    def test_missing_dependency_rejected(self):
        spec = WorkflowSpec(
            workflow_id="t.missing",
            name="missing",
            nodes=(NodeSpec(node_id="a", action_id="a.compute", depends_on=("ghost",)),),
        )
        assert any("does not exist" in p for p in validate_workflow_spec(spec, self._reg()))

    def test_duplicate_node_rejected(self):
        spec = WorkflowSpec(
            workflow_id="t.dup",
            name="dup",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(node_id="a", action_id="b.compute"),
            ),
        )
        assert any("duplicate node id" in p for p in validate_workflow_spec(spec, self._reg()))

    def test_unknown_action_rejected(self):
        spec = WorkflowSpec(
            workflow_id="t.unknown",
            name="unknown",
            nodes=(NodeSpec(node_id="a", action_id="ghost.action"),),
        )
        assert any("unknown action" in p for p in validate_workflow_spec(spec, self._reg()))

    def test_ref_requires_explicit_dependency(self):
        spec = WorkflowSpec(
            workflow_id="t.refdep",
            name="refdep",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(
                    node_id="b",
                    action_id="b.compute",
                    parameters={"up": {"$ref": "a"}},
                ),
            ),
        )
        assert any("depends_on" in p for p in validate_workflow_spec(spec, self._reg()))

    def test_unknown_slot_binding_rejected(self):
        spec = WorkflowSpec(
            workflow_id="t.slot",
            name="slot",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute", parameters={"s": {"$slot": "nope"}}),
            ),
        )
        assert any("$slot" in p for p in validate_workflow_spec(spec, self._reg()))

    def test_nonwhitelisted_context_binding_rejected(self):
        spec = WorkflowSpec(
            workflow_id="t.ctx",
            name="ctx",
            nodes=(
                NodeSpec(
                    node_id="a",
                    action_id="a.compute",
                    parameters={"x": {"$context": "project.meta.secret"}},
                ),
            ),
        )
        assert any("whitelisted" in p for p in validate_workflow_spec(spec, self._reg()))

    def test_engine_create_run_enforces_validation(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        bad = WorkflowSpec(
            workflow_id="t.bad",
            name="bad",
            nodes=(NodeSpec(node_id="a", action_id="ghost.action"),),
        )
        with pytest.raises(WorkflowValidationError):
            engine.create_run(bad, context=ActionContext())

    def test_missing_required_slot_rejected(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        spec = WorkflowSpec(
            workflow_id="t.req",
            name="req",
            slots=(SlotSpec(name="factor", schema={"type": "string"}),),
            nodes=(NodeSpec(node_id="a", action_id="a.compute"),),
        )
        with pytest.raises(WorkflowValidationError):
            engine.create_run(spec, slot_values={}, context=ActionContext())


# ----------------------------------------------------------------- running --

class TestRun:
    def test_linear_run_order_and_receipts(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        ctx = ActionContext()
        run = engine.create_run(linear_spec(), context=ctx)
        done = engine.run(run.run_id, context=ctx)
        assert done.state is RunState.COMPLETED
        assert [n for n, _ in rec.calls] == ["a.compute", "b.compute", "c.compute"]
        for nr in done.node_runs.values():
            assert nr.state is NodeState.SUCCEEDED
            assert nr.receipt is not None
            assert nr.receipt["status"] in ("success", "degraded")
            assert nr.receipt["action_id"]
            assert nr.receipt["environment"]

    def test_diamond_dependencies(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        spec = WorkflowSpec(
            workflow_id="t.diamond",
            name="diamond",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
                NodeSpec(node_id="c", action_id="c.compute", depends_on=("a",)),
                NodeSpec(node_id="d", action_id="d.compute", depends_on=("b", "c")),
            ),
        )
        ctx = ActionContext()
        run = engine.create_run(spec, context=ctx)
        done = engine.run(run.run_id, context=ctx)
        assert done.state is RunState.COMPLETED
        order = [n for n, _ in rec.calls]
        assert order.index("a.compute") < order.index("b.compute")
        assert order.index("a.compute") < order.index("c.compute")
        assert order.index("d.compute") > order.index("b.compute")
        assert order.index("d.compute") > order.index("c.compute")

    def test_slot_and_ref_bindings_resolve(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        spec = WorkflowSpec(
            workflow_id="t.bind",
            name="bind",
            slots=(
                SlotSpec(name="factor", schema={"type": "string"}),
                SlotSpec(name="grid_n", schema={"type": "integer", "minimum": 4}, default=16),
            ),
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(
                    node_id="b",
                    action_id="b.compute",
                    depends_on=("a",),
                    parameters={
                        "factor": {"$slot": "factor"},
                        "grid_n": {"$slot": "grid_n"},
                        "up": {"$ref": "a"},
                    },
                ),
            ),
        )
        ctx = ActionContext()
        run = engine.create_run(spec, slot_values={"factor": "GR"}, context=ctx)
        done = engine.run(run.run_id, context=ctx)
        assert done.state is RunState.COMPLETED
        b_params = dict(rec.calls[-1][1])
        assert b_params["factor"] == "GR"
        assert b_params["grid_n"] == 16  # default applied
        assert b_params["up"]["version_ids"] == ["ver-a.compute"]

    def test_condition_false_skips_node(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        spec = WorkflowSpec(
            workflow_id="t.cond",
            name="cond",
            nodes=(
                NodeSpec(
                    node_id="a",
                    action_id="a.compute",
                    parameters={"mode": "fast"},
                ),
                NodeSpec(
                    node_id="b",
                    action_id="b.compute",
                    depends_on=("a",),
                    condition=_cond_node_output_equals("a", "mode", "full"),
                ),
            ),
        )
        ctx = ActionContext()
        run = engine.create_run(spec, context=ctx)
        done = engine.run(run.run_id, context=ctx)
        assert done.state is RunState.COMPLETED
        assert done.node_runs["b"].state is NodeState.SKIPPED
        assert rec.count("b.compute") == 0

    def test_unavailable_action_marks_unavailable_and_skips_dependents(self):
        from paleo_workbench.harness.executor import ActionUnavailableError

        rec = Recorder()
        reg = ActionRegistry()
        reg.register(
            ActionSpec(
                action_id="a.compute",
                description="a",
                handler=rec.handler("a.compute"),
                risk=ActionRisk.COMPUTE,
            )
        )
        reg.register(
            ActionSpec(
                action_id="b.compute",
                description="b",
                handler=lambda c, p: (_ for _ in ()).throw(ActionUnavailableError("engine missing")),
                risk=ActionRisk.COMPUTE,
            )
        )
        reg.register(
            ActionSpec(
                action_id="c.compute",
                description="c",
                handler=rec.handler("c.compute"),
                risk=ActionRisk.COMPUTE,
            )
        )
        engine = make_engine(reg)
        spec = WorkflowSpec(
            workflow_id="t.unavail",
            name="unavail",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
                NodeSpec(node_id="c", action_id="c.compute", depends_on=("b",)),
            ),
        )
        ctx = ActionContext()
        run = engine.create_run(spec, context=ctx)
        done = engine.run(run.run_id, context=ctx)
        assert done.state is RunState.FAILED
        assert done.node_runs["b"].state is NodeState.UNAVAILABLE
        assert done.node_runs["c"].state is NodeState.SKIPPED

    def test_retry_then_success(self):
        rec = Recorder()
        reg = ActionRegistry()
        attempts = {"n": 0}

        def flaky(ctx, params):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("transient")
            return {"ok": True}

        reg.register(ActionSpec(action_id="a.compute", description="a", handler=flaky, risk=ActionRisk.COMPUTE))
        engine = make_engine(reg)
        spec = WorkflowSpec(
            workflow_id="t.retry",
            name="retry",
            nodes=(
                NodeSpec(
                    node_id="a",
                    action_id="a.compute",
                    retry=RetryPolicy(max_attempts=3, backoff_seconds=0.0),
                ),
            ),
        )
        run = engine.create_run(spec, context=ActionContext())
        done = engine.run(run.run_id, context=ActionContext())
        assert done.state is RunState.COMPLETED
        assert done.node_runs["a"].attempt == 3

    def test_retry_exhausted_fails(self):
        reg = ActionRegistry()

        def always(ctx, params):
            raise RuntimeError("permanent")

        reg.register(ActionSpec(action_id="a.compute", description="a", handler=always, risk=ActionRisk.COMPUTE))
        engine = make_engine(reg)
        spec = WorkflowSpec(
            workflow_id="t.retryx",
            name="retryx",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute", retry=RetryPolicy(max_attempts=2)),
            ),
        )
        run = engine.create_run(spec, context=ActionContext())
        done = engine.run(run.run_id, context=ActionContext())
        assert done.state is RunState.FAILED
        assert done.node_runs["a"].attempt == 2
        assert done.node_runs["a"].error

    def test_parallel_branches_with_max_concurrency(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        spec = WorkflowSpec(
            workflow_id="t.par",
            name="par",
            max_concurrency=2,
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
                NodeSpec(node_id="c", action_id="c.compute", depends_on=("a",)),
                NodeSpec(node_id="d", action_id="d.compute", depends_on=("b", "c")),
            ),
        )
        run = engine.create_run(spec, context=ActionContext())
        done = engine.run(run.run_id, context=ActionContext())
        assert done.state is RunState.COMPLETED
        assert len(rec.calls) == 4


def _cond_node_output_equals(node: str, key: str, value) -> "NodeCondition":
    from paleo_workbench.workflow.dag.model import NodeCondition

    return NodeCondition(kind="node_output_equals", node=node, key=key, value=value)


# ------------------------------------------------------------------ cancel --

class TestCancel:
    def test_cancel_between_nodes_propagates(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        ctx = ActionContext()

        def slow(ctx, params):
            import time

            time.sleep(0.3)
            return {"done": True}

        reg = engine._registry
        reg.unregister("b.compute")
        reg.register(ActionSpec(action_id="b.compute", description="b", handler=slow, risk=ActionRisk.COMPUTE))

        spec = WorkflowSpec(
            workflow_id="t.cancel",
            name="cancel",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
                NodeSpec(node_id="c", action_id="c.compute", depends_on=("b",)),
            ),
        )
        run = engine.create_run(spec, context=ctx)
        import threading

        def cancel_soon():
            import time

            time.sleep(0.1)
            engine.cancel(run.run_id)

        thread = threading.Thread(target=cancel_soon)
        thread.start()
        done = engine.run(run.run_id, context=ctx)
        thread.join()
        assert done.state is RunState.CANCELLED
        assert done.node_runs["a"].state is NodeState.SUCCEEDED
        assert done.node_runs["c"].state is NodeState.CANCELLED
        assert rec.count("c.compute") == 0

    def test_scheduler_bridge_cancellation(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        ctx = ActionContext()
        reg = engine._registry

        def slow(ctx, params):
            import time

            for _ in range(50):
                ctx.cancel.raise_if_cancelled()
                time.sleep(0.02)
            return {"done": True}

        reg.unregister("a.compute")
        reg.register(ActionSpec(action_id="a.compute", description="a", handler=slow, risk=ActionRisk.COMPUTE))

        spec = WorkflowSpec(
            workflow_id="t.sched",
            name="sched",
            nodes=(NodeSpec(node_id="a", action_id="a.compute"),),
        )
        run = engine.create_run(spec, context=ctx)
        handle = engine.submit_to_scheduler(run.run_id, context=ctx)
        try:
            import time

            time.sleep(0.15)
            from paleo_workbench.runtime.task_scheduler import (
                get_scheduler,
                reset_global_scheduler,
            )

            get_scheduler().cancel(handle.task_id)
            terminal = {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
            deadline = time.time() + 10
            while time.time() < deadline:
                state = engine.store_for(ctx).load(run.run_id).state
                if state in terminal:
                    break
                time.sleep(0.05)
            persisted = engine.store_for(ctx).load(run.run_id)
            assert persisted.state is RunState.CANCELLED
            assert persisted.node_runs["a"].state is NodeState.CANCELLED
        finally:
            from paleo_workbench.runtime.task_scheduler import reset_global_scheduler

            reset_global_scheduler()


# --------------------------------------------------------- resume / rerun --

class TestResumeAndRerun:
    def test_crash_resume_reexecutes_only_interrupted_node(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        ctx = ActionContext()
        run = engine.create_run(linear_spec(), context=ctx)
        done = engine.run(run.run_id, context=ctx)
        assert done.state is RunState.COMPLETED
        rec.calls.clear()

        # Simulate a crash mid-run: flip a completed run's tail back to a
        # running checkpoint on disk, exactly as a crash would leave it.
        store = engine.store_for(ctx)
        crashed = store.load(run.run_id)
        crashed.state = RunState.RUNNING
        crashed.node_runs["c"].state = NodeState.RUNNING
        store.save(crashed)

        resumed = engine.resume(run.run_id, context=ctx)
        assert resumed.state is RunState.COMPLETED
        # a and b kept their receipts; only c re-executed.
        assert rec.count("a.compute") == 0
        assert rec.count("b.compute") == 0
        assert rec.count("c.compute") == 1

    def test_resume_refuses_other_project(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        ctx = ActionContext(project_path="/wks/one.paleo.json")
        run = engine.create_run(linear_spec(), context=ctx)
        engine.run(run.run_id, context=ctx)
        other = ActionContext(project_path="/wks/two.paleo.json")
        with pytest.raises(WorkflowValidationError, match="refused"):
            engine.resume(run.run_id, context=other)

    def test_rerun_from_node_carries_independent_head(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        ctx = ActionContext()
        run = engine.create_run(linear_spec(), context=ctx)
        engine.run(run.run_id, context=ctx)
        rec.calls.clear()

        rerun = engine.rerun(run.run_id, from_nodes=["b"], context=ctx)
        assert rerun.state is RunState.COMPLETED
        assert rerun.run_id != run.run_id
        assert rerun.node_runs["a"].from_cache is True
        assert rec.count("a.compute") == 0
        assert rec.count("b.compute") == 1
        assert rec.count("c.compute") == 1

    def test_rerun_with_slot_override_reexecutes_affected(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        spec = WorkflowSpec(
            workflow_id="t.rerun2",
            name="rerun2",
            slots=(SlotSpec(name="factor", schema={"type": "string"}),),
            nodes=(
                NodeSpec(
                    node_id="a",
                    action_id="a.compute",
                    parameters={"factor": {"$slot": "factor"}},
                ),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
            ),
        )
        ctx = ActionContext()
        run = engine.create_run(spec, slot_values={"factor": "GR"}, context=ctx)
        engine.run(run.run_id, context=ctx)
        rec.calls.clear()

        rerun = engine.rerun(
            run.run_id, from_nodes=["a"], slot_overrides={"factor": "RT"}, context=ctx
        )
        assert rerun.state is RunState.COMPLETED
        assert rerun.node_runs["a"].from_cache is False
        assert dict(rec.calls[0][1])["factor"] == "RT"


# ------------------------------------------------------------------- cache --

class TestCache:
    def _cacheable_setup(self, tmp_path: Path):
        rec = Recorder()
        catalog = InMemoryCatalog()
        reg = ActionRegistry()
        for name in ("a.compute", "b.compute"):
            reg.register(
                ActionSpec(
                    action_id=name,
                    description=name,
                    handler=rec.handler(name, output={"version_ids": [f"store-ver-{name}"]}),
                    risk=ActionRisk.COMPUTE,
                    deterministic=True,
                    cacheable=True,
                    output_refs=("DataVersionRef",),
                )
            )
        return rec, catalog, reg, tmp_path

    @staticmethod
    def _register_real_file(catalog: InMemoryCatalog, tmp_path: Path, name: str) -> str:
        """Register a REAL file so catalog.verify_integrity can verify it."""
        f = tmp_path / f"{name}.dat"
        f.write_bytes(b"deterministic-workflow-output")
        from inmemory_catalog import sha256_of_file

        version = catalog.register_input(
            name=name, path=str(f), checksum=sha256_of_file(f)
        )
        return version.version_id

    def test_cache_hit_requires_catalog_resolvable_outputs(self, tmp_path):
        rec, catalog, reg, tmp_path = self._cacheable_setup(tmp_path)
        engine = make_engine(reg, catalog=catalog)
        ctx = ActionContext()
        spec = WorkflowSpec(
            workflow_id="t.cache1",
            name="cache1",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
            ),
        )
        run = engine.create_run(spec, context=ctx)
        engine.run(run.run_id, context=ctx)
        rec.calls.clear()

        # Handlers here emit invented version ids — they never resolve in
        # the catalog, so a cache hit is refused and the node re-executes.
        run2 = engine.rerun(run.run_id, from_nodes=["a"], context=ctx)
        assert run2.node_runs["a"].from_cache is False
        assert rec.count("a.compute") == 1

    def test_cache_reuses_registered_outputs(self, tmp_path):
        rec, catalog, reg, tmp_path = self._cacheable_setup(tmp_path)
        executions: list = []

        def real_output(ctx, params):
            executions.append(1)
            version_id = self._register_real_file(catalog, tmp_path, "same-content")
            # Deterministic action: same content identity each run.
            return {"version_ids": [version_id]}

        reg.unregister("a.compute")
        reg.register(
            ActionSpec(
                action_id="a.compute",
                description="a",
                handler=real_output,
                risk=ActionRisk.COMPUTE,
                deterministic=True,
                cacheable=True,
                output_refs=("DataVersionRef",),
            )
        )
        engine = make_engine(reg, catalog=catalog)
        ctx = ActionContext()
        spec = WorkflowSpec(
            workflow_id="t.cache2",
            name="cache2",
            nodes=(NodeSpec(node_id="a", action_id="a.compute"),),
        )
        run = engine.create_run(spec, context=ctx)
        first = engine.run(run.run_id, context=ctx)
        assert first.node_runs["a"].from_cache is False
        assert len(executions) == 1

        second = engine.rerun(run.run_id, from_nodes=["a"], context=ctx)
        assert second.node_runs["a"].from_cache is True
        assert len(executions) == 1  # re-execution did not happen
        assert second.node_runs["a"].output_version_ids == (
            first.node_runs["a"].output_version_ids
        )

    def test_deleted_output_never_reuses(self, tmp_path):
        rec, catalog, reg, tmp_path = self._cacheable_setup(tmp_path)

        def real_output(ctx, params):
            version_id = self._register_real_file(catalog, tmp_path, "doomed")
            return {"version_ids": [version_id]}

        reg.unregister("a.compute")
        reg.register(
            ActionSpec(
                action_id="a.compute",
                description="a",
                handler=real_output,
                risk=ActionRisk.COMPUTE,
                deterministic=True,
                cacheable=True,
                output_refs=("DataVersionRef",),
            )
        )
        engine = make_engine(reg, catalog=catalog)
        ctx = ActionContext()
        spec = WorkflowSpec(
            workflow_id="t.cache3",
            name="cache3",
            nodes=(NodeSpec(node_id="a", action_id="a.compute"),),
        )
        run = engine.create_run(spec, context=ctx)
        engine.run(run.run_id, context=ctx)

        # Corrupt the cache truth: the backing file disappears.
        version_id = engine.store_for(ctx).load(run.run_id).node_runs["a"].output_version_ids[0]
        ref = catalog.resolve_version(version_id)
        Path(ref.path).unlink()

        executions: list = []

        def counting(ctx, params):
            executions.append(1)
            version_id = self._register_real_file(catalog, tmp_path, "rebuilt")
            return {"version_ids": [version_id]}

        reg.unregister("a.compute")
        reg.register(
            ActionSpec(
                action_id="a.compute",
                description="a",
                handler=counting,
                risk=ActionRisk.COMPUTE,
                deterministic=True,
                cacheable=True,
                output_refs=("DataVersionRef",),
            )
        )
        engine2 = WorkflowEngine(
            registry=reg, store=engine.store_for(ctx), catalog=catalog
        )
        second = engine2.rerun(run.run_id, from_nodes=["a"], context=ctx)
        assert second.node_runs["a"].from_cache is False
        assert executions == [1]  # deleted output → honest re-execution

    def test_param_change_busts_cache(self, tmp_path):
        rec, catalog, reg, tmp_path = self._cacheable_setup(tmp_path)
        seen: list = []

        def param_output(ctx, params):
            seen.append(dict(params))
            version_id = self._register_real_file(catalog, tmp_path, f"out-{len(seen)}")
            return {"version_ids": [version_id]}

        reg.unregister("a.compute")
        reg.register(
            ActionSpec(
                action_id="a.compute",
                description="a",
                handler=param_output,
                risk=ActionRisk.COMPUTE,
                deterministic=True,
                cacheable=True,
                output_refs=("DataVersionRef",),
            )
        )
        engine = make_engine(reg, catalog=catalog)
        ctx = ActionContext()
        spec = WorkflowSpec(
            workflow_id="t.cache4",
            name="cache4",
            slots=(SlotSpec(name="p", schema={"type": "string"}),),
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute", parameters={"p": {"$slot": "p"}}),
            ),
        )
        run = engine.create_run(spec, slot_values={"p": "one"}, context=ctx)
        engine.run(run.run_id, context=ctx)
        rerun = engine.rerun(
            run.run_id, from_nodes=["a"], slot_overrides={"p": "two"}, context=ctx
        )
        assert rerun.node_runs["a"].from_cache is False
        assert seen[-1] == {"p": "two"}


# ------------------------------------------------------------ misc guards --

class TestGuards:
    def test_project_switch_probe_stops_run(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))

        import time

        def slow(ctx, params):
            time.sleep(0.2)
            return {"done": True}

        reg = engine._registry
        reg.unregister("a.compute")
        reg.register(ActionSpec(action_id="a.compute", description="a", handler=slow, risk=ActionRisk.COMPUTE))

        spec = WorkflowSpec(
            workflow_id="t.switch",
            name="switch",
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute"),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
            ),
        )
        project = object()  # identity sentinel
        ctx = ActionContext(project=project)
        run = engine.create_run(spec, context=ctx)

        import threading

        def switch_soon():
            time.sleep(0.05)
            ctx.project = object()  # host switched the live project

        thread = threading.Thread(target=switch_soon)
        thread.start()
        done = engine.run(
            run.run_id, context=ctx, project_probe=lambda: ctx.project
        )
        thread.join()
        # Fail-closed: nothing executed against the switched project, but
        # the run stays RESUMABLE (INTERRUPTED), not terminally cancelled.
        assert done.state is RunState.INTERRUPTED
        assert done.node_runs["b"].state is NodeState.PENDING
        assert rec.count("b.compute") == 0

        # Restoring the same project identity lets the run finish.
        ctx.project = project
        resumed = engine.resume(run.run_id, context=ctx, project_probe=lambda: ctx.project)
        assert resumed.state is RunState.COMPLETED
        assert rec.count("b.compute") == 1

    def test_corrupted_checkpoint_refuses_to_execute(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        ctx = ActionContext()
        run = engine.create_run(linear_spec(), context=ctx)
        engine.run(run.run_id, context=ctx)
        store = engine.store_for(ctx)
        path = store.root / f"run-{run.run_id}.json"
        path.write_text("{corrupted", encoding="utf-8")
        with pytest.raises(ValueError, match="corrupted"):
            engine.resume(run.run_id, context=ctx)

    def test_binding_failure_fails_node_and_skips_dependents(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        spec = WorkflowSpec(
            workflow_id="t.bindfail",
            name="bindfail",
            slots=(SlotSpec(name="opt", schema={"type": "string"}, required=False),),
            nodes=(
                NodeSpec(node_id="a", action_id="a.compute", parameters={"v": {"$slot": "opt"}}),
                NodeSpec(node_id="b", action_id="b.compute", depends_on=("a",)),
            ),
        )
        ctx = ActionContext()
        run = engine.create_run(spec, slot_values={}, context=ctx)
        done = engine.run(run.run_id, context=ctx)
        assert done.state is RunState.FAILED
        assert done.node_runs["a"].state is NodeState.FAILED
        assert done.node_runs["b"].state is NodeState.SKIPPED
        assert rec.count("b.compute") == 0

    def test_persisted_state_round_trip(self):
        rec = Recorder()
        engine = make_engine(build_registry(rec))
        ctx = ActionContext()
        run = engine.create_run(linear_spec(), context=ctx)
        engine.run(run.run_id, context=ctx)
        store = engine.store_for(ctx)
        loaded = store.load(run.run_id)
        assert loaded.workflow.workflow_id == "test.linear"
        assert loaded.node_runs["a"].state is NodeState.SUCCEEDED
        assert json.loads((store.root / f"run-{run.run_id}.json").read_text())["run_id"]
