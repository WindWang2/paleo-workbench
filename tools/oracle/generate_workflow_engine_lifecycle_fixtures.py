#!/usr/bin/env python3
"""Oracle fixture generator for the CONV-32 store-driven workflow lifecycle
engine (C++ RunEngine, libs/workflow_engine run_engine.hpp/.cpp).

Freezes the REAL paleo_workbench.workflow.dag.engine WorkflowEngine behavior
(create/run/resume/rerun/cancel, crash mapping, conditions, retry, project
guard, checkpoint failure, cache reuse) so the C++ port replays the exact
same lifecycles. Regenerate with:

    python3 tools/oracle/generate_workflow_engine_lifecycle_fixtures.py

Determinism contract (the C++ test injects the same seams):
  * uuid.uuid4 + time.time are patched globally — run ids come from a fixed
    per-case pool, every timestamp from one ticking clock (1000.0, +0.5 per
    call) shared by model/store/receipt/engine, so the frozen timestamps
    also pin the exact save/clock call ORDER.
  * engine._RunCancelToken.wait is patched to RECORD the backoff durations
    without sleeping (the C++ BackoffWaiter seam records the same list).
  * receipt.environment_identity is patched to a fixed triple (the C++
    EnvironmentProvider seam injects the same values).
  * registry/executor are SimpleNamespace fakes (validated spec slice only);
    ActionSpec mirrors the C++ ActionInfo (empty resource_profile, null
    category — receipt fields the C++ seam does not carry).
  * the WorkflowRunStore is REAL, one fresh tmpdir per case; threads,
    the scheduler and parallel drive are never frozen (sequential only).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time as _time
import types
import uuid as _uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(REPO_ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({REPO_ROOT}) — oracle must import the real tree"
)

from paleo_workbench.harness.executor import ActionResult  # noqa: E402
from paleo_workbench.workflow.dag import engine as engine_mod  # noqa: E402
from paleo_workbench.workflow.dag import receipt as receipt_mod  # noqa: E402
from paleo_workbench.workflow.dag.engine import (  # noqa: E402
    CheckpointFailed,
    WorkflowEngine,
    WorkflowValidationError,
)
from paleo_workbench.workflow.dag.model import (  # noqa: E402
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
from paleo_workbench.workflow.dag.store import WorkflowRunStore  # noqa: E402

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_engine"
    / "workflow_engine_tests"
    / "fixtures"
    / "workflow_engine_lifecycle_oracle.json"
)

TICK_START = 1000.0
TICK_STEP = 0.5
FROZEN_ENV = {"python": "3.11.8", "platform": "Linux-oracle", "workbench": "oracle-1.0"}


# ----------------------------------------------------------- determinism --

class _Tick:
    value = TICK_START

    @classmethod
    def time(cls) -> float:
        now = cls.value
        cls.value += TICK_STEP
        return now


_time.time = _Tick.time  # model._now / engine / store.save / build_receipt

_ID_POOL: list[str] = []


class _FakeUuid:
    def __init__(self, run_id: str) -> None:
        self.hex = run_id * 2  # uuid4().hex[:16] == run_id


_uuid.uuid4 = lambda: _FakeUuid(_ID_POOL.pop(0) if _ID_POOL else "ffff000000000000")

WAITS: list[float] = []


def _record_wait(self, seconds: float) -> bool:  # noqa: ANN001
    WAITS.append(seconds)
    return False  # not cancelled — deterministic, no sleep


engine_mod._RunCancelToken.wait = _record_wait
receipt_mod.environment_identity = lambda: dict(FROZEN_ENV)


def rid(n: int) -> str:
    return f"r{n:015d}"  # exactly 16 chars, like uuid4().hex[:16]


def reset_determinism(ids: list) -> None:
    _Tick.value = TICK_START
    _ID_POOL.clear()
    _ID_POOL.extend(rid(i) if isinstance(i, int) else i for i in ids)
    WAITS.clear()


# --------------------------------------------------------------- fakes --

class FakeContext:
    """ActionContext slice the engine consumes (always passed, never None,
    so no uuid4 is drawn for a default session id)."""

    def __init__(self, workspace_id=None, project_path=None, project=None, **attrs):
        self.workspace_id = workspace_id
        self.project_path = project_path
        self.project = project
        self.extras = {}
        self.map_documents = {}
        self.catalog = None
        self.current_map_id = None    # _merge_session_pointers target
        self.active_well_id = None
        for key, value in attrs.items():
            setattr(self, key, value)

    def derived(self, **overrides):  # per-node context; shared is fine here
        return self


# _RunView(run, None) / run(context=None) would construct a real
# ActionContext whose session_id draws a uuid4 — one hidden id-pool
# consumer per _ready_batch call. The fake context has no such draw.
engine_mod.ActionContext = FakeContext


def make_action(action_id, version="1.0", cacheable=False, input_schema=None,
                description=None):
    return types.SimpleNamespace(
        action_id=action_id,
        version=version,
        cacheable=cacheable,
        input_schema=input_schema,
        description=description if description is not None else f"{action_id} action",
        resource_profile={},       # C++ ActionInfo carries no resource profile
        category=None,             # C++ ActionInfo carries no category
        risk=types.SimpleNamespace(value="compute"),
    )


class FakeRegistry:
    def __init__(self, actions: dict):
        self._actions = actions

    def get(self, action_id: str):
        return self._actions[action_id]  # KeyError is a LookupError


class ScriptedExecutor:
    """HarnessExecutor fake: records every execute(); scripted results are
    consumed per action in order, and a persistent fallback handler covers
    re-executions once a queue runs dry (default = plain success)."""

    def __init__(self):
        self.calls: list[dict] = []
        self._script: dict[str, list] = {}
        self._fallback: dict[str, object] = {}

    def script(self, action_id: str, results: list) -> None:
        self._script[action_id] = list(results)

    def fallback(self, action_id: str, handler) -> None:
        self._fallback[action_id] = handler

    def execute(self, action_id, parameters, context):
        self.calls.append({"action": action_id, "params": parameters})
        queue = self._script.get(action_id)
        item = queue.pop(0) if queue else None
        if item is None:
            item = self._fallback.get(action_id)
            if item is None:
                return ActionResult(action_id=action_id)
        if callable(item):
            return item(action_id, parameters, context)
        return item


def make_engine(actions: dict, executor: ScriptedExecutor, tmpdir: str):
    store = WorkflowRunStore(Path(tmpdir))
    engine = WorkflowEngine(
        registry=FakeRegistry(actions), executor=executor, store=store
    )
    return engine, store


# ------------------------------------------------------------ projection --

def proj_node(nr: NodeRun) -> dict:
    return {
        "state": nr.state.value,
        "attempt": nr.attempt,
        "action_status": nr.action_status,
        "from_cache": nr.from_cache,
        "parameters": nr.parameters,
        "input_version_ids": list(nr.input_version_ids),
        "cache_identity": nr.cache_identity,
        "output_version_ids": list(nr.output_version_ids),
        "outputs": nr.outputs,
        "receipt": nr.receipt,
        "skip_reason": nr.skip_reason,
        "error": nr.error,
        "started_at": nr.started_at,
        "finished_at": nr.finished_at,
    }


def proj_run(run: WorkflowRun) -> dict:
    return {
        "run_id": run.run_id,
        "state": run.state.value,
        "parent_run_id": run.parent_run_id,
        "project_name": run.project_name,
        "project_path": run.project_path,
        "spec_hash": run.spec_hash,
        "slot_values": run.slot_values,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "node_runs": {nr.node_id: proj_node(nr) for nr in run.node_runs.values()},
    }


# ------------------------------------------------------------- results --

def ok_result(action_id, outputs, elapsed_ms=12.5, status="success",
              warnings=None):
    return ActionResult(action_id=action_id, status=status, outputs=outputs,
                        warnings=list(warnings or []), elapsed_ms=elapsed_ms)


def a_outputs(params):
    return {"factor": params["factor"], "version_ids": ["v-a-1"]}


# ----------------------------------------------------------------- specs --

def chain_spec(wid="wf.chain") -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=wid,
        name="Chain",
        nodes=(
            NodeSpec(node_id="a", action_id="t.compute",
                     parameters={"factor": {"$slot": "factor"}}),
            NodeSpec(node_id="b", action_id="t.compute",
                     parameters={"up": {"$ref": "a", "key": "factor"}},
                     depends_on=("a",)),
        ),
        slots=(SlotSpec(name="factor", schema={"type": "string"}),),
    )


CHAIN_ACTIONS = {"t.compute": make_action("t.compute")}
B_OUTPUTS = {"report": "done", "version_ids": ["v-b-1"]}


def _compute_handler(aid, params, ctx):
    if "factor" in params:  # node a shape
        return ok_result(aid, a_outputs(params))
    return ok_result(aid, B_OUTPUTS, elapsed_ms=7.25)  # node b shape


def chain_executor() -> ScriptedExecutor:
    ex = ScriptedExecutor()
    ex.fallback("t.compute", _compute_handler)
    return ex


ALL_TMPDIRS: list[str] = []


def fresh_case() -> str:
    tmp = tempfile.mkdtemp(prefix="pwb-wf-life-")
    ALL_TMPDIRS.append(tmp)
    return tmp


# ----------------------------------------------------------------- cases --

def case_run_complete_chain() -> dict:
    tmp = fresh_case()
    reset_determinism([101, 102])
    ex = chain_executor()
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one",
                      project="proj-identity-1")
    run = engine.create_run(chain_spec(), slot_values={"factor": "porosity"},
                            context=ctx)
    run_id = run.run_id
    final = engine.run(run_id, context=ctx)
    persisted = store.load(run_id)
    assert proj_run(final) == proj_run(persisted), "returned run must be persisted"
    return {"run": proj_run(final), "calls": ex.calls}


def case_static_validation() -> dict:
    tmp = fresh_case()
    reset_determinism([201])
    ex = ScriptedExecutor()
    engine, _ = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    bad = WorkflowSpec(
        workflow_id="wf.bad",
        name="Bad",
        nodes=(NodeSpec(node_id="a", action_id="ghost.op"),),
    )
    try:
        engine.create_run(bad, slot_values={})
        raise AssertionError("unknown action must fail validation")
    except WorkflowValidationError as exc:
        error = {"type": type(exc).__name__, "message": str(exc),
                 "problems": list(exc.problems)}
    return {"error": error, "calls": ex.calls}


def case_slot_schema() -> dict:
    tmp = fresh_case()
    reset_determinism([301])
    ex = ScriptedExecutor()
    engine, _ = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    try:
        engine.create_run(chain_spec(), slot_values={}, context=None)
        raise AssertionError("missing required slot must fail")
    except WorkflowValidationError as exc:
        error = {"type": type(exc).__name__, "message": str(exc),
                 "problems": list(exc.problems)}
    return {"error": error}


def case_crash_resume() -> dict:
    tmp = fresh_case()
    reset_determinism([401, 402])
    ex = chain_executor()  # a already SUCCEEDED in the crashed checkpoint
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(chain_spec(), slot_values={"factor": "porosity"},
                            context=ctx)
    run_id = run.run_id
    # Fabricate the crashed checkpoint: a finished, b torn mid-RUNNING.
    crashed = store.load(run_id)
    crashed.state = RunState.RUNNING
    a = crashed.node_runs["a"]
    a.state = NodeState.SUCCEEDED
    a.attempt = 1
    a.action_status = "success"
    a.parameters = {"factor": "porosity"}
    a.outputs = {"factor": "porosity", "version_ids": ["v-a-1"]}
    a.output_version_ids = ("v-a-1",)
    a.started_at = _time.time()
    a.finished_at = _time.time()
    b = crashed.node_runs["b"]
    b.state = NodeState.RUNNING
    b.attempt = 1
    b.started_at = _time.time()
    store.save(crashed)
    resumed = engine.resume(run_id, context=ctx)
    return {"run": proj_run(resumed), "calls": ex.calls}


def case_failure_no_revival() -> dict:
    tmp = fresh_case()
    reset_determinism([501, 502])
    actions = {"t.compute": make_action("t.compute"), "t.fail": make_action("t.fail")}
    ex = ScriptedExecutor()
    ex.fallback("t.compute", _compute_handler)
    ex.script("t.fail", [
        ActionResult(action_id="t.fail", status="failed", error="engine exploded",
                     elapsed_ms=3.0),
    ])
    spec = WorkflowSpec(
        workflow_id="wf.fail",
        name="Fail",
        nodes=(
            NodeSpec(node_id="a", action_id="t.compute",
                     parameters={"factor": {"$slot": "factor"}}),
            NodeSpec(node_id="b", action_id="t.fail", depends_on=("a",)),
            NodeSpec(node_id="c", action_id="t.compute",
                     parameters={"mode": "report"}, depends_on=("b",)),
        ),
        slots=(SlotSpec(name="factor", schema={"type": "string"}),),
    )
    engine, store = make_engine(actions, ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={"factor": "porosity"}, context=ctx)
    failed = engine.run(run.run_id, context=ctx)
    assert failed.state.value == "failed"
    before = proj_run(store.load(run.run_id))
    revived = engine.resume(run.run_id, context=ctx)
    after = proj_run(store.load(run.run_id))
    assert revived.state.value == "failed"
    assert {k: v for k, v in after["node_runs"].items()} == {
        k: v for k, v in before["node_runs"].items()
    }, "resume must not revive failed nodes"
    return {"after_failure": before, "after_resume": after, "calls": ex.calls}


def case_rerun_carry_all() -> dict:
    tmp = fresh_case()
    reset_determinism([601, 602])
    ex = chain_executor()
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    first = engine.create_run(chain_spec(), slot_values={"factor": "porosity"},
                              context=ctx)
    engine.run(first.run_id, context=ctx)
    calls_before = len(ex.calls)
    rerun = engine.rerun(first.run_id, context=ctx)
    assert len(ex.calls) == calls_before, "carry-over rerun must not execute"
    return {"run": proj_run(rerun), "calls": ex.calls[calls_before:],
            "first_run_id": first.run_id}


def case_rerun_slot_override() -> dict:
    tmp = fresh_case()
    reset_determinism([701, 702])
    ex = chain_executor()
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    first = engine.create_run(chain_spec(), slot_values={"factor": "porosity"},
                              context=ctx)
    engine.run(first.run_id, context=ctx)
    calls_before = len(ex.calls)
    rerun = engine.rerun(first.run_id, slot_overrides={"factor": "silt"},
                         context=ctx)
    assert len(ex.calls) == calls_before + 2, "changed identity re-executes"
    return {"run": proj_run(rerun), "calls": ex.calls[calls_before:]}


def case_rerun_from_b() -> dict:
    tmp = fresh_case()
    reset_determinism([801, 802])
    ex = chain_executor()
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    first = engine.create_run(chain_spec(), slot_values={"factor": "porosity"},
                              context=ctx)
    engine.run(first.run_id, context=ctx)
    calls_before = len(ex.calls)
    rerun = engine.rerun(first.run_id, from_nodes=["b"], context=ctx)
    assert len(ex.calls) == calls_before + 1
    return {"run": proj_run(rerun), "calls": ex.calls[calls_before:]}


def _condition_case(value) -> dict:
    tmp = fresh_case()
    ex = ScriptedExecutor()
    counter = {"n": 0}

    def handler(aid, params, ctx):
        counter["n"] += 1
        if counter["n"] == 1:  # a always drives first (c waits on it)
            return ok_result(aid, {"flag": 42, "version_ids": ["v-a-9"]})
        return ok_result(aid, {"ran": True}, elapsed_ms=2.0)

    ex.fallback("t.compute", handler)
    spec = WorkflowSpec(
        workflow_id="wf.cond",
        name="Cond",
        nodes=(
            # c listed FIRST: proves the condition waits for a to become
            # terminal instead of being judged on missing outputs.
            NodeSpec(node_id="c", action_id="t.compute",
                     condition=NodeCondition(kind="node_output_equals",
                                             node="a", key="flag", value=value)),
            NodeSpec(node_id="a", action_id="t.compute"),
        ),
    )
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={}, context=ctx)
    final = engine.run(run.run_id, context=ctx)
    return proj_run(final)


def case_conditions() -> dict:
    reset_determinism([901, 902])
    false_branch = _condition_case(7)   # 42 != 7 -> "condition false"
    reset_determinism([911, 912])
    true_branch = _condition_case(42)   # waits for a, then executes
    return {"condition_false": false_branch, "condition_true": true_branch}


def case_retry_resource_shed() -> dict:
    tmp = fresh_case()
    reset_determinism([1001])
    ex = ScriptedExecutor()
    ex.script("t.compute", [
        ActionResult(action_id="t.compute", status="rejected",
                     error="ResourceExhausted: cpu: busy", elapsed_ms=1.0),
        ActionResult(action_id="t.compute", status="rejected",
                     error="ResourceExhausted: cpu: busy", elapsed_ms=1.0),
        ActionResult(action_id="t.compute", status="rejected",
                     error="ResourceExhausted: cpu: busy", elapsed_ms=1.0),
    ])
    spec = WorkflowSpec(
        workflow_id="wf.retry",
        name="Retry",
        nodes=(NodeSpec(node_id="r", action_id="t.compute",
                        retry=RetryPolicy(max_attempts=3, backoff_seconds=0.05)),),
    )
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={}, context=ctx)
    final = engine.run(run.run_id, context=ctx)
    return {"run": proj_run(final), "calls": ex.calls, "waits": list(WAITS)}


def case_plain_rejection() -> dict:
    tmp = fresh_case()
    reset_determinism([1101])
    ex = ScriptedExecutor()
    ex.script("t.compute", [
        ActionResult(action_id="t.compute", status="rejected",
                     error="invalid context: session expired", elapsed_ms=1.0),
        ActionResult(action_id="t.compute", status="rejected",
                     error="invalid context: session expired", elapsed_ms=1.0),
    ])
    spec = WorkflowSpec(
        workflow_id="wf.reject",
        name="Reject",
        nodes=(NodeSpec(node_id="r", action_id="t.compute",
                        retry=RetryPolicy(max_attempts=3)),),
    )
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={}, context=ctx)
    final = engine.run(run.run_id, context=ctx)
    node = final.node_runs["r"]
    assert node.attempt == 1, "plain rejections never retry"
    return {"run": proj_run(final), "calls": ex.calls, "waits": list(WAITS)}


def case_unavailable() -> dict:
    tmp = fresh_case()
    reset_determinism([1201])
    actions = {"t.compute": make_action("t.compute"),
               "t.unavail": make_action("t.unavail")}
    ex = ScriptedExecutor()
    ex.fallback("t.compute", _compute_handler)
    ex.script("t.unavail", [
        ActionResult(action_id="t.unavail", status="unavailable",
                     error="backend not installed", elapsed_ms=1.0),
    ])
    spec = WorkflowSpec(
        workflow_id="wf.unavail",
        name="Unavail",
        nodes=(
            NodeSpec(node_id="a", action_id="t.compute",
                     parameters={"factor": {"$slot": "factor"}}),
            NodeSpec(node_id="b", action_id="t.unavail", depends_on=("a",)),
            NodeSpec(node_id="c", action_id="t.compute", depends_on=("b",)),
        ),
        slots=(SlotSpec(name="factor", schema={"type": "string"}),),
    )
    engine, store = make_engine(actions, ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={"factor": "porosity"}, context=ctx)
    final = engine.run(run.run_id, context=ctx)
    assert final.node_runs["c"].skip_reason == "upstream b unavailable"
    return {"run": proj_run(final), "calls": ex.calls}


def case_cancel_mid_run() -> dict:
    tmp = fresh_case()
    reset_determinism([1301])
    actions = {"t.compute": make_action("t.compute"),
               "t.stop": make_action("t.stop")}
    ex = ScriptedExecutor()
    ex.fallback("t.compute", _compute_handler)
    ex.script("t.stop", [
        ActionResult(action_id="t.stop", status="cancelled",
                     error="user pressed stop", elapsed_ms=5.0),
    ])
    spec = WorkflowSpec(
        workflow_id="wf.cancel",
        name="Cancel",
        nodes=(
            NodeSpec(node_id="a", action_id="t.compute",
                     parameters={"factor": {"$slot": "factor"}}),
            NodeSpec(node_id="b", action_id="t.stop", depends_on=("a",)),
            NodeSpec(node_id="c", action_id="t.compute", depends_on=("b",)),
        ),
        slots=(SlotSpec(name="factor", schema={"type": "string"}),),
    )
    engine, store = make_engine(actions, ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={"factor": "porosity"}, context=ctx)
    cancelled = engine.run(run.run_id, context=ctx)
    first = proj_run(cancelled)
    assert first["state"] == "cancelled"
    second = engine.run(run.run_id, context=ctx)  # early return, no save
    second_proj = proj_run(second)
    assert second_proj == first, "second run() returns the run untouched"
    return {"first": first, "second": second_proj, "calls": ex.calls}


def case_cancel_no_active() -> dict:
    tmp = fresh_case()
    reset_determinism([1401])
    ex = ScriptedExecutor()
    ex.script("t.compute", [lambda aid, params, ctx: ok_result(aid, {"ok": True})])
    spec = WorkflowSpec(
        workflow_id="wf.solo",
        name="Solo",
        nodes=(NodeSpec(node_id="solo", action_id="t.compute"),),
    )
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={}, context=ctx)
    engine.run(run.run_id, context=ctx)
    return {"cancel_unknown": engine.cancel("no-such-run"),
            "cancel_finished": engine.cancel(run.run_id)}


def case_checkpoint_failure() -> dict:
    tmp = fresh_case()
    reset_determinism([1501, 1502])
    ex = chain_executor()
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(chain_spec(), slot_values={"factor": "porosity"},
                            context=ctx)
    run_id = run.run_id
    root = Path(tmp)

    def seal_run(runned) -> None:
        os.chmod(root, 0o500)  # next checkpoint write must fail

    raised = None
    try:
        engine.run(run_id, context=ctx, on_update=seal_run)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    finally:
        os.chmod(root, 0o700)
    assert raised == "CheckpointFailed", raised
    persisted = proj_run(store.load(run_id))
    assert persisted["node_runs"]["a"]["state"] == "succeeded"
    assert persisted["node_runs"]["b"]["state"] == "pending"
    resumed = engine.resume(run_id, context=ctx)
    assert resumed.state.value == "completed"
    return {"exception": raised, "after_failure": persisted,
            "after_resume": proj_run(resumed), "calls": ex.calls}


def case_project_guard() -> dict:
    tmp = fresh_case()
    reset_determinism([1601, 1602])
    ex = ScriptedExecutor()  # no node ever executes under the guard
    spec = WorkflowSpec(
        workflow_id="wf.guard",
        name="Guard",
        nodes=(NodeSpec(node_id="a", action_id="t.compute"),
               NodeSpec(node_id="b", action_id="t.compute", depends_on=("a",))),
    )
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    one = FakeContext(workspace_id="ws-1", project_path="/proj/one",
                      project="proj-live")
    two = FakeContext(workspace_id="ws-1", project_path="/proj/two",
                      project="proj-live")
    run = engine.create_run(spec, slot_values={}, context=one)

    mismatch_error = None
    try:
        engine.run(run.run_id, context=two)
    except WorkflowValidationError as exc:
        mismatch_error = {"type": type(exc).__name__, "message": str(exc),
                          "problems": list(exc.problems)}

    rerun_error = None
    try:
        engine.rerun(run.run_id, context=two)
    except WorkflowValidationError as exc:
        rerun_error = {"type": type(exc).__name__, "message": str(exc),
                       "problems": list(exc.problems)}

    switched = engine.run(run.run_id, context=one,
                          project_probe=lambda: "other-project")
    probe_raised = engine.run(run.run_id, context=one,
                              project_probe=_boom_probe)
    return {"run_mismatch": mismatch_error, "rerun_mismatch": rerun_error,
            "probe_switch": proj_run(switched),
            "probe_raise": proj_run(probe_raised)}


def _boom_probe():
    raise RuntimeError("probe blew up")


def case_degraded() -> dict:
    tmp = fresh_case()
    reset_determinism([1701])
    ex = ScriptedExecutor()
    ex.script("t.compute", [
        lambda aid, params, ctx: ok_result(
            aid, {"grid": "ok", "version_ids": ["v-d-1"]}, status="degraded",
            warnings=["low coverage", "sparse wells"]),
    ])
    spec = WorkflowSpec(
        workflow_id="wf.degraded",
        name="Degraded",
        nodes=(NodeSpec(node_id="d", action_id="t.compute"),),
    )
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={}, context=ctx)
    final = engine.run(run.run_id, context=ctx)
    assert final.state.value == "completed"
    assert final.node_runs["d"].action_status == "degraded"
    return {"run": proj_run(final), "calls": ex.calls}


def case_context_unavailable() -> dict:
    tmp = fresh_case()
    reset_determinism([1801])
    ex = ScriptedExecutor()
    spec = WorkflowSpec(
        workflow_id="wf.ctx",
        name="Ctx",
        nodes=(
            NodeSpec(node_id="n", action_id="t.compute",
                     parameters={"well": {"$context": "active_well_id"}}),
            NodeSpec(node_id="d", action_id="t.compute", depends_on=("n",)),
        ),
    )
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    # no active_well_id attribute on the session -> binding fails
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(spec, slot_values={}, context=ctx)
    final = engine.run(run.run_id, context=ctx)
    assert final.state.value == "failed"
    return {"run": proj_run(final), "calls": ex.calls}


def case_double_run_guard() -> dict:
    tmp = fresh_case()
    reset_determinism([1901, 1902])
    ex = chain_executor()
    engine, store = make_engine(dict(CHAIN_ACTIONS), ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    run = engine.create_run(chain_spec(), slot_values={"factor": "porosity"},
                            context=ctx)
    nested = {}

    def on_update(runned) -> None:
        try:
            engine.run(run.run_id, context=ctx)  # re-entrant: must refuse
        except WorkflowValidationError as exc:
            nested["type"] = type(exc).__name__
            nested["message"] = str(exc)
            nested["problems"] = list(exc.problems)

    final = engine.run(run.run_id, context=ctx, on_update=on_update)
    assert nested, "the re-entrant run must have raised"
    return {"nested_error": nested, "run": proj_run(final)}


def case_cache_reuse_new_run() -> dict:
    tmp = fresh_case()
    reset_determinism([2001, 2002])
    actions = {"t.compute": make_action("t.compute"),
               "t.cacheable": make_action("t.cacheable", cacheable=True)}
    ex = ScriptedExecutor()
    a_out = {"factor": "porosity", "version_ids": ["v-a-1"]}
    ex.fallback("t.cacheable",
                lambda aid, params, ctx: ok_result(aid, a_out))
    ex.fallback("t.compute",
                lambda aid, params, ctx: ok_result(aid, B_OUTPUTS,
                                                   elapsed_ms=7.25))
    spec = WorkflowSpec(
        workflow_id="wf.cache",
        name="Cache",
        nodes=(
            NodeSpec(node_id="a", action_id="t.cacheable",
                     parameters={"factor": {"$slot": "factor"}}),
            NodeSpec(node_id="b", action_id="t.compute", depends_on=("a",)),
        ),
        slots=(SlotSpec(name="factor", schema={"type": "string"}),),
    )
    engine, store = make_engine(actions, ex, tmp)
    ctx = FakeContext(workspace_id="ws-1", project_path="/proj/one")
    first = engine.create_run(spec, slot_values={"factor": "porosity"},
                              context=ctx)
    engine.run(first.run_id, context=ctx)
    calls_after_first = len(ex.calls)
    second = engine.create_run(spec, slot_values={"factor": "porosity"},
                               context=ctx)
    final = engine.run(second.run_id, context=ctx)
    assert final.node_runs["a"].from_cache is True
    assert len(ex.calls) == calls_after_first + 1  # only b executed
    return {"run": proj_run(final),
            "calls": ex.calls[calls_after_first:]}


CASES = [
    ("run_complete_chain", case_run_complete_chain),
    ("static_validation_unknown_action", case_static_validation),
    ("slot_schema_missing_required", case_slot_schema),
    ("crash_resume_completes", case_crash_resume),
    ("failure_no_resume_revival", case_failure_no_revival),
    ("rerun_carry_all", case_rerun_carry_all),
    ("rerun_slot_override_miss", case_rerun_slot_override),
    ("rerun_from_b", case_rerun_from_b),
    ("conditions", case_conditions),
    ("retry_resource_shed", case_retry_resource_shed),
    ("plain_rejection", case_plain_rejection),
    ("unavailable", case_unavailable),
    ("cancel_mid_run", case_cancel_mid_run),
    ("cancel_no_active", case_cancel_no_active),
    ("checkpoint_failure", case_checkpoint_failure),
    ("project_guard", case_project_guard),
    ("degraded", case_degraded),
    ("context_unavailable", case_context_unavailable),
    ("double_run_guard", case_double_run_guard),
    ("cache_reuse_new_run", case_cache_reuse_new_run),
]


def main() -> None:
    doc = {
        "meta": {
            "environment": dict(FROZEN_ENV),
            "tick_start": TICK_START,
            "tick_step": TICK_STEP,
            "determinism": "uuid4 + time.time globally patched; wait recorded; "
                           "sequential drive only; real WorkflowRunStore per case",
        },
        "cases": {},
    }
    for name, fn in CASES:
        doc["cases"][name] = fn()
        print(f"  froze {name}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(CASES)} cases)")
    for tmp in ALL_TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
