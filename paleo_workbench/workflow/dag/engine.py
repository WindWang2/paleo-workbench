"""Workflow DAG engine (H2/H3): validate → schedule → checkpoint → resume.

Contracts:

- **One scheduling authority**: a whole WorkflowRun runs inside ONE task of
  the existing :mod:`paleo_workbench.runtime.task_scheduler` (the app's
  single heavy queue). The engine owns no queue; node parallelism is a
  structural bound (``max_concurrency``, default 1) and every action still
  passes its own :class:`~paleo_workbench.runtime.resource_governor`
  admission inside the executor — resources are governed exactly once.
- **Fail-closed state machine**: unknown action / cycle / missing dep /
  unresolvable binding / cancelled dependency ⇒ the node (and its
  dependents) never pretends to succeed. A node is re-executed unless a
  prior execution is proven complete *and* its outputs are still
  catalog-resolvable.
- **Crash safety**: every node transition is checkpointed to the run store.
  A run found in RUNNING state after a crash maps RUNNING nodes back to
  PENDING (interrupted) — complete outputs are not re-executed, incomplete
  outputs are never mistaken for complete.
- **Project-switch guard**: the engine holds the project document the run
  started with; if the host probe reports a different live project, the
  remaining nodes are cancelled — nothing is written into the new project.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.executor import HarnessExecutor
from paleo_workbench.harness.registry import get_action_registry
from paleo_workbench.providers.execution import validate_parameters
from paleo_workbench.runtime.task_scheduler import TaskCancelled, get_scheduler
from paleo_workbench.workflow.dag.model import (
    TERMINAL_NODE_STATES,
    NodeCondition,
    NodeRun,
    NodeSpec,
    NodeState,
    RunState,
    WorkflowRun,
    WorkflowSpec,
    canonical_hash,
)
from paleo_workbench.workflow.dag.receipt import build_receipt
from paleo_workbench.workflow.dag.store import (
    WorkflowRunStore,
    default_store_root,
    find_reusable_node,
)
from paleo_workbench.workflow.dag.validation import (
    BindingError,
    bind_parameters,
    materialize_slot_defaults,
    slot_schema_problems,
    validate_workflow_spec,
)

logger = logging.getLogger(__name__)


class WorkflowValidationError(ValueError):
    def __init__(self, workflow_id: str, problems: list[str]):
        self.problems = problems
        super().__init__(
            f"workflow {workflow_id!r} invalid: {'; '.join(problems)}"
        )


class _RunCancelToken:
    """Cooperative cancel token for node actions (provider-compatible)."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise TaskCancelled("workflow run cancelled")

    def wait(self, seconds: float) -> bool:
        return self._event.wait(seconds)


class _ActiveRun:
    def __init__(self, cancel_token: _RunCancelToken, project_identity: Any, context: ActionContext,
                 workflow_id: str = ""):
        self.cancel_token = cancel_token
        self.project_identity = project_identity
        self.context = context
        self.workflow_id = workflow_id


class WorkflowEngine:
    """Drives WorkflowRuns through the guarded harness action pipeline."""

    def __init__(
        self,
        *,
        registry: Any | None = None,
        executor: HarnessExecutor | None = None,
        store: WorkflowRunStore | None = None,
        catalog: Any | None = None,
    ) -> None:
        self._registry = registry if registry is not None else get_action_registry()
        self._executor = executor if executor is not None else HarnessExecutor(self._registry)
        self._store = store
        self._catalog = catalog
        self._lock = threading.RLock()
        self._active: dict[str, _ActiveRun] = {}
        self._pending_tokens: dict[str, "_SyncedToken"] = {}

    # ---------------------------------------------------------- accessors --
    @property
    def registry(self):
        return self._registry

    @property
    def store(self) -> WorkflowRunStore:
        return self.store_for(ActionContext())

    def store_for(self, context: ActionContext | None) -> WorkflowRunStore:
        if self._store is not None:
            return self._store
        return WorkflowRunStore(default_store_root(context or ActionContext()))

    def set_store(self, store: WorkflowRunStore | None) -> None:
        self._store = store

    # ------------------------------------------------------------- create --
    def create_run(
        self,
        spec: WorkflowSpec,
        *,
        slot_values: dict[str, Any] | None = None,
        context: ActionContext | None = None,
    ) -> WorkflowRun:
        problems = validate_workflow_spec(spec, self._registry)
        if problems:
            raise WorkflowValidationError(spec.workflow_id, problems)
        values = materialize_slot_defaults(spec, dict(slot_values or {}))
        problems = slot_schema_problems(spec, values)
        if problems:
            raise WorkflowValidationError(spec.workflow_id, problems)
        run = WorkflowRun.create(spec, values)
        if context is not None:
            run.project_name = context.workspace_id
            run.project_path = context.project_path
        store = self.store_for(context)
        store.save(run)
        return run

    # ---------------------------------------------------------------- run --
    def run(
        self,
        run_id: str,
        *,
        context: ActionContext | None = None,
        project_probe: Callable[[], Any] | None = None,
        reverify_cache: bool = True,
        on_update: Callable[[WorkflowRun], None] | None = None,
        cancel_token: "_RunCancelToken | None" = None,
        use_cache: bool = True,
        external_cancel: Any = None,
    ) -> WorkflowRun:
        with self._lock:
            if run_id in self._active:
                raise WorkflowValidationError(
                    self._active_run_workflow(run_id),
                    [f"run {run_id} is already executing in this process "
                     "(concurrent run/resume would double-execute nodes)"],
                )
        store = self.store_for(context)
        run = store.load(run_id)
        if run.state in (RunState.COMPLETED,):
            return run
        if run.state == RunState.CANCELLED:
            return run
        if context is None:
            context = ActionContext()
        self._check_project_match(run, context)
        catalog = self._catalog if self._catalog is not None else getattr(context, "catalog", None)
        if cancel_token is None:
            cancel_token = _RunCancelToken()
        if external_cancel is not None:
            # The host's/scheduler's cooperative cancel (any is_cancelled /
            # raise_if_cancelled token, e.g. a TaskContext) feeds the same
            # engine token — one cancel path for panel stop buttons,
            # scheduler cancellation and workflow.cancel.
            cancel_token = _ExternalSyncedToken(cancel_token, external_cancel)
        active = _ActiveRun(cancel_token, context.project, context, workflow_id=run.workflow.workflow_id)
        context.extras["workflow_run_id"] = run_id
        with self._lock:
            self._active[run_id] = active

        try:
            self._prepare_interrupted(run)
            self._checkpoint(store, run)
            try:
                self._drive(
                    run,
                    store,
                    context,
                    catalog=catalog,
                    cancel_token=cancel_token,
                    project_identity=active.project_identity,
                    project_probe=project_probe,
                    reverify_cache=reverify_cache,
                    on_update=on_update,
                    use_cache=use_cache,
                )
            except TaskCancelled:
                # Cancellation is a first-class terminal outcome of the RUN:
                # land the state honestly instead of raising past the caller.
                self._cancel_pending(run, reason="run cancelled")
                self._finalize(run)
        finally:
            context.extras.pop("workflow_run_id", None)
            with self._lock:
                self._active.pop(run_id, None)
            self._checkpoint(store, run)
        return run

    # ------------------------------------------------------------- resume --
    def resume(
        self,
        run_id: str,
        *,
        context: ActionContext | None = None,
        project_probe: Callable[[], Any] | None = None,
        reverify_cache: bool = True,
        on_update: Callable[[WorkflowRun], None] | None = None,
        external_cancel: Any = None,
    ) -> WorkflowRun:
        """Continue an interrupted/failed run: complete nodes keep their
        receipts; interrupted (RUNNING at crash) nodes re-execute."""
        store = self.store_for(context)
        run = store.load(run_id)
        self._check_project_match(run, context)
        return self.run(
            run_id,
            context=context,
            project_probe=project_probe,
            reverify_cache=reverify_cache,
            on_update=on_update,
            external_cancel=external_cancel,
        )

    # -------------------------------------------------------------- rerun --
    def rerun(
        self,
        run_id: str,
        *,
        from_nodes: list[str] | None = None,
        slot_overrides: dict[str, Any] | None = None,
        context: ActionContext | None = None,
        project_probe: Callable[[], Any] | None = None,
        reverify_cache: bool = True,
        on_update: Callable[[WorkflowRun], None] | None = None,
    ) -> WorkflowRun:
        """Partial rerun: a NEW run sharing the spec, where the given nodes
        and all their transitive dependents re-execute; every other node
        whose cache identity is unchanged carries over its completed work."""
        store = self.store_for(context)
        prior = store.load(run_id)
        self._check_project_match(prior, context)
        spec = prior.workflow
        if from_nodes:
            for node_id in from_nodes:
                spec.node(node_id)  # KeyError → honest failure
        affected = self._transitive_dependents(spec, set(from_nodes or ()))

        new_run = WorkflowRun.create(
            spec, materialize_slot_defaults(spec, {**prior.slot_values, **(slot_overrides or {})})
        )
        problems = slot_schema_problems(spec, new_run.slot_values)
        if problems:
            raise WorkflowValidationError(spec.workflow_id, problems)
        new_run.project_name = prior.project_name
        new_run.project_path = prior.project_path
        if context is not None:
            new_run.project_name = context.workspace_id or prior.project_name
            new_run.project_path = context.project_path or prior.project_path

        catalog = self._catalog if self._catalog is not None else getattr(context, "catalog", None)
        for node in spec.nodes:
            new_node_run = new_run.node_runs[node.node_id]
            old = prior.node_runs.get(node.node_id)
            if node.node_id in affected or old is None or old.state is not NodeState.SUCCEEDED:
                continue
            # Carry over only PROVABLY identical work. The PRIOR identity is
            # the one recorded at execution time (bound with that run's real
            # context); the NEW identity binds with the caller's live
            # context. Comparing recorded-vs-freshly-rebound (never
            # re-binding the prior run against a fake context) keeps
            # $context-bound nodes honest across session changes.
            new_identity = self._cache_identity(spec, node, new_run, catalog, context)
            old_identity = old.cache_identity
            if old_identity is None or new_identity is None or old_identity != new_identity:
                continue
            carried = NodeRun(
                node_id=node.node_id,
                state=NodeState.SUCCEEDED,
                attempt=old.attempt,
                action_status=old.action_status,
                from_cache=True,
                parameters=dict(old.parameters),
                input_version_ids=old.input_version_ids,
                cache_identity=new_identity,
                output_version_ids=old.output_version_ids,
                outputs=dict(old.outputs),
                receipt=dict(old.receipt) if old.receipt else None,
            )
            # Restamp the carried receipt so provenance reads correctly.
            if carried.receipt is not None:
                carried.receipt["node_id"] = node.node_id
                carried.receipt["workflow_run_id"] = new_run.run_id
                carried.receipt["from_cache"] = True
            new_run.node_runs[node.node_id] = carried
            self._restore_session_pointers(context or ActionContext(), carried.outputs)
        store.save(new_run)
        return self.run(
            new_run.run_id,
            context=context,
            project_probe=project_probe,
            reverify_cache=reverify_cache,
            on_update=on_update,
        )

    # ------------------------------------------------------------- cancel --
    def cancel(self, run_id: str) -> bool:
        """Cooperative cancel of an in-process run (engine-driven or
        scheduler-driven); for a merely persisted run nothing is running, so
        this returns False — resume will pick the run up instead."""
        with self._lock:
            active = self._active.get(run_id)
            if active is not None:
                active.cancel_token.cancel()
                return True
            pending = self._pending_tokens.get(run_id)
        if pending is not None:
            pending.cancel()
            return True
        return False

    def _active_run_workflow(self, run_id: str) -> str:
        active = self._active.get(run_id)
        return active.workflow_id if active else "unknown"

    # ----------------------------------------------------------- scheduler --
    def submit_to_scheduler(
        self,
        run_id: str,
        *,
        context: ActionContext,
        project_probe: Callable[[], Any] | None = None,
        reverify_cache: bool = True,
        priority: int = 20,
        on_done: Callable[[WorkflowRun], None] | None = None,
        on_fail: Callable[[BaseException], None] | None = None,
    ):
        """Run the whole workflow as ONE task on the global TaskScheduler
        (the app's single heavy queue — no second queue authority).
        Scheduler-side cooperative cancellation propagates into the engine
        token, so running actions stop at their next safe point."""
        store = self.store_for(context)
        spec = store.load(run_id).workflow

        def task(task_ctx: Any) -> WorkflowRun:
            token = _RunCancelToken()
            synced = _SyncedToken(token, task_ctx)
            with self._lock:
                self._pending_tokens[run_id] = synced
            try:
                return self.run(
                    run_id,
                    context=context,
                    project_probe=project_probe,
                    reverify_cache=reverify_cache,
                    cancel_token=synced,
                )
            finally:
                with self._lock:
                    self._pending_tokens.pop(run_id, None)

        return get_scheduler().submit(
            _make_task_spec(
                task,
                title=f"workflow:{spec.name} ({run_id})",
                kind="background.compute",
                priority=priority,
                on_done=on_done,
                on_fail=on_fail,
            )
        )

    # -------------------------------------------------------------- driver --
    def _drive(
        self,
        run: WorkflowRun,
        store: WorkflowRunStore,
        context: ActionContext,
        *,
        catalog: Any,
        cancel_token: _RunCancelToken,
        project_identity: Any,
        project_probe: Callable[[], Any] | None,
        reverify_cache: bool,
        on_update: Callable[[WorkflowRun], None] | None,
        use_cache: bool = True,
    ) -> None:
        max_concurrency = max(1, run.workflow.max_concurrency)
        if max_concurrency == 1:
            self._drive_sequential(
                run, store, context, catalog=catalog, cancel_token=cancel_token,
                project_identity=project_identity, project_probe=project_probe,
                reverify_cache=reverify_cache, on_update=on_update,
                use_cache=use_cache,
            )
        else:
            self._drive_parallel(
                run, store, context, catalog=catalog, cancel_token=cancel_token,
                project_identity=project_identity, project_probe=project_probe,
                reverify_cache=reverify_cache, on_update=on_update,
                workers=max_concurrency, use_cache=use_cache,
            )

    def _drive_sequential(
        self, run, store, context, *, catalog, cancel_token, project_identity,
        project_probe, reverify_cache, on_update, use_cache: bool = True,
    ) -> None:
        run.state = RunState.RUNNING
        while True:
            cancel_token.raise_if_cancelled()
            batch = self._ready_batch(run, limit=1)
            if batch is None:
                break  # no runnable node and no pending work → done
            if not batch:
                continue  # nodes are running (should not happen sequentially)
            node_id = batch[0]
            if not self._guard(run, project_identity, project_probe, cancel_token):
                break
            self._execute_node(
                run, store, node_id, context,
                catalog=catalog, cancel_token=cancel_token,
                project_identity=project_identity, project_probe=project_probe,
                reverify_cache=reverify_cache, use_cache=use_cache,
            )
            try:
                self._checkpoint(store, run)
            except CheckpointFailed:
                return  # run already marked FAILED; stop driving
            self._notify(run, on_update)
        self._finalize(run)

    def _drive_parallel(
        self, run, store, context, *, catalog, cancel_token, project_identity,
        project_probe, reverify_cache, on_update, workers: int,
        use_cache: bool = True,
    ) -> None:
        run.state = RunState.RUNNING
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="paleo-workflow") as pool:
            futures: dict[Any, str] = {}
            while True:
                cancel_token.raise_if_cancelled()
                # Reap finished futures; a worker exception is a node failure,
                # never a silent drop.
                for future in [f for f in futures if f.done()]:
                    node_id = futures.pop(future)
                    exc = future.exception()
                    if exc is not None:
                        node_run = run.node_runs[node_id]
                        if node_run.state is NodeState.RUNNING:
                            if isinstance(exc, TaskCancelled):
                                self._finish_node(
                                    node_run, NodeState.CANCELLED, error=str(exc)
                                )
                            else:
                                self._finish_node(
                                    node_run,
                                    NodeState.FAILED,
                                    error=f"engine error: {type(exc).__name__}: {exc}",
                                )
                                self._skip_dependents(
                                    run, node_id, reason=f"upstream {node_id} failed"
                                )
                            logger.exception(
                                "workflow node %s worker crashed", node_id, exc_info=exc
                            )
                if not self._guard(run, project_identity, project_probe, cancel_token):
                    break
                batch = self._ready_batch(run, limit=workers - len(futures))
                if batch is None:
                    if not futures:
                        break
                    batch = []  # all remaining work is still running
                for node_id in batch:
                    node_run = run.node_runs[node_id]
                    node_run.state = NodeState.RUNNING
                    node_run.started_at = time.time()
                    future = pool.submit(
                        self._execute_node,
                        run,
                        store,
                        node_id,
                        context,
                        catalog=catalog,
                        cancel_token=cancel_token,
                        project_identity=project_identity,
                        project_probe=project_probe,
                        reverify_cache=reverify_cache,
                        use_cache=use_cache,
                    )
                    futures[future] = node_id
                if not batch and futures:
                    time.sleep(0.01)
                    continue
                if not batch and not futures:
                    break
                try:
                    self._checkpoint(store, run)
                except CheckpointFailed:
                    return  # run already marked FAILED; pool drains below
                self._notify(run, on_update)
        self._finalize(run)

    def _guard(self, run, project_identity, project_probe, cancel_token) -> bool:
        """Pre-node guards: cancel requested / project switched. Returns
        False when the loop must stop."""
        if cancel_token.is_cancelled:
            self._cancel_pending(run, reason="run cancelled")
            return False
        if project_probe is not None:
            try:
                current = project_probe()
            except Exception:  # probe failure must not execute nodes unguarded
                logger.exception("project identity probe failed; stopping run %s", run.run_id)
                self._cancel_pending(run, reason="project identity probe failed")
                return False
            if current is not project_identity:
                # The live project changed (or closed). Nothing may be
                # written to the new project — but the run stays resumable:
                # unfinished nodes go back to PENDING and the run lands in
                # INTERRUPTED so a later resume against the matched project
                # can finish it.
                for node_run in run.node_runs.values():
                    if node_run.state in (NodeState.PENDING, NodeState.RUNNING):
                        node_run.state = NodeState.PENDING
                        node_run.error = "project switched during run; re-run pending"
                run.state = RunState.INTERRUPTED
                return False
        return True

    # --------------------------------------------------------- node logic --
    def _execute_node(
        self,
        run: WorkflowRun,
        store: WorkflowRunStore,
        node_id: str,
        context: ActionContext,
        *,
        catalog: Any,
        cancel_token: _RunCancelToken,
        project_identity: Any,
        project_probe: Callable[[], Any] | None,
        reverify_cache: bool,
        use_cache: bool = True,
    ) -> None:
        node = run.workflow.node(node_id)
        node_run = run.node_runs[node_id]
        action_spec = self._registry.get(node.action_id)
        node_run.state = NodeState.RUNNING
        node_run.attempt += 1
        node_run.started_at = time.time()
        node_run.error = None

        # Derived per-node context: own extras (admission lease scope), shared
        # services and stashes; the run cancel token is attached.
        node_context = context.derived()
        node_context.cancel = cancel_token

        try:
            bound = bind_parameters(node, run=_RunView(run, context), results=self._results_view(run))
        except BindingError as exc:
            self._finish_node(node_run, NodeState.FAILED, error=str(exc), action_status="rejected")
            self._skip_dependents(run, node_id, reason=f"upstream {node_id} failed: {exc}")
            return
        node_run.parameters = _jsonable_projection(bound)

        schema_problems = validate_parameters(
            action_spec.input_schema or {"type": "object"}, bound
        )
        if schema_problems:
            self._finish_node(
                node_run, NodeState.FAILED,
                error="bound parameters invalid: " + "; ".join(schema_problems),
                action_status="rejected",
            )
            self._skip_dependents(run, node_id, reason=f"upstream {node_id} failed")
            return

        input_version_ids = self._input_version_ids(run, node)
        # Identity of this execution (cache identity): always recorded on the
        # checkpoint; *reuse* of a prior execution stays gated on the
        # action's cacheable declaration.
        identity = canonical_hash(
            {
                "action_id": action_spec.action_id,
                "action_version": action_spec.version,
                "parameters": node_run.parameters,
                "input_version_ids": sorted(input_version_ids),
            }
        )
        node_run.cache_identity = identity
        if action_spec.cacheable and use_cache:
            hit = find_reusable_node(
                store,
                cache_identity=identity,
                catalog=catalog,
                verify_integrity=reverify_cache,
            )
            if hit is not None:
                receipt = dict(hit.receipt) if hit.receipt else None
                if receipt is not None:
                    receipt["from_cache"] = True
                    receipt["node_id"] = node_id
                    receipt["workflow_run_id"] = run.run_id
                node_run.output_version_ids = hit.output_version_ids
                node_run.outputs = dict(hit.outputs)
                node_run.receipt = receipt
                node_run.finished_at = time.time()
                node_run.state = NodeState.SUCCEEDED
                node_run.action_status = "success"
                node_run.from_cache = True
                self._restore_session_pointers(context, hit.outputs)
                return

        started_at = time.time()
        while True:
            result = self._executor.execute(node.action_id, dict(bound), node_context)
            if result.status in ("success", "degraded"):
                receipt = build_receipt(
                    result,
                    node_id=node_id,
                    workflow_run_id=run.run_id,
                    action_id=action_spec.action_id,
                    action_version=action_spec.version,
                    description=node.description or action_spec.description,
                    parameters=node_run.parameters,
                    input_version_ids=input_version_ids,
                    estimated_resources=action_spec.resource_profile,
                    resource_category=action_spec.category,
                    cache_identity=identity,
                    from_cache=False,
                    attempt=node_run.attempt,
                    started_at=started_at,
                )
                if identity is not None and catalog is not None:
                    self._register_cache_run(catalog, run, node, receipt)
                # Order matters for crash safety: the payload fields land
                # BEFORE the terminal state, so a torn checkpoint can never
                # claim "succeeded" with empty outputs.
                node_run.output_version_ids = receipt.output_version_ids
                node_run.outputs = _jsonable_projection(result.outputs)
                node_run.receipt = receipt.to_dict()
                node_run.finished_at = time.time()
                node_run.state = NodeState.SUCCEEDED
                node_run.action_status = result.status
                self._merge_session_pointers(context, node_context)
                return
            if result.status == "cancelled":
                self._finish_node(node_run, NodeState.CANCELLED, error=result.error, action_status=result.status)
                self._cancel_pending(run, reason=f"cancelled at {node_id}")
                return
            retryable = result.status == "failed" or (
                result.status == "rejected" and _is_resource_shed(result.error)
            )
            if retryable and node_run.attempt < node.retry.max_attempts:
                backoff = max(0.0, node.retry.backoff_seconds)
                if backoff:
                    cancel_token.wait(backoff)
                    cancel_token.raise_if_cancelled()
                node_run.attempt += 1
                node_run.error = result.error
                continue
            state = NodeState.UNAVAILABLE if result.status == "unavailable" else NodeState.FAILED
            self._finish_node(node_run, state, error=result.error, action_status=result.status)
            self._skip_dependents(run, node_id, reason=f"upstream {node_id} {state.value}")
            return

    @staticmethod
    def _merge_session_pointers(context: ActionContext, node_context: ActionContext) -> None:
        """Propagate the session pointers an action mutated (the in-process
        "current document"/active well) back onto the run's shared context —
        the vocabulary downstream nodes read. Guarded by the module lock so
        parallel branches do not tear the pointer."""
        with _MODULE_LOCK:
            context.current_map_id = node_context.current_map_id
            context.active_well_id = node_context.active_well_id

    @staticmethod
    def _restore_session_pointers(context: ActionContext, outputs: dict[str, Any]) -> None:
        """A carried-over/cache-hit node did not execute, so it did not
        (re)publish its in-process handles. When the SAME process still
        holds the handle (the document from the original execution), restore
        the pointer; across a process boundary the pointer is unrecoverable
        and downstream consumers fail honestly instead of binding to a
        wrong document."""
        document_id = outputs.get("document_id")
        if isinstance(document_id, str) and document_id in context.map_documents:
            with _MODULE_LOCK:
                context.current_map_id = document_id

    def _register_cache_run(self, catalog: Any, run: WorkflowRun, node: NodeSpec, receipt) -> None:
        """Put the cacheable node execution on the catalog provenance rail so
        reuse is traceable (begin/complete like any other run)."""
        try:
            run_ref = catalog.begin_run(
                operation=f"workflow.node.{node.action_id}",
                input_version_ids=list(receipt.input_version_ids),
                parameters={
                    "workflow_id": run.workflow.workflow_id,
                    "run_id": run.run_id,
                    "node_id": node.node_id,
                    "cache_identity": receipt.cache_identity,
                },
                generator_version=f"workflow-dag/{run.workflow.schema_version}",
            )
            run_id = getattr(run_ref, "run_id", None) or getattr(run_ref, "id", None)
            catalog.complete_run(run_id, status="complete")
            # The provider's own run id (recorded by build_receipt) is the
            # finer-grained provenance — the workflow-node run complements
            # it, never replaces it.
            if not receipt.catalog_run_id:
                receipt.catalog_run_id = run_id
        except Exception:
            logger.exception(
                "catalog run registration failed for node %s (execution stays valid; "
                "cache reuse for it will be limited to this store)", node.node_id,
            )

    # ------------------------------------------------------ ready/finality --
    def _ready_batch(self, run: WorkflowRun, *, limit: int) -> list[str] | None:
        """Nodes ready to run (≤ limit). None ⇒ nothing left at all."""
        ready: list[str] = []
        pending_left = False
        results = self._results_view(run)
        view = _RunView(run, None)
        for node in run.workflow.nodes:
            node_run = run.node_runs[node.node_id]
            if node_run.state is NodeState.PENDING:
                pending_left = True
                deps = [run.node_runs[d] for d in node.depends_on]
                if not all(d.state in TERMINAL_NODE_STATES for d in deps):
                    continue
                hard_failure = any(
                    d.state in (NodeState.FAILED, NodeState.CANCELLED, NodeState.UNAVAILABLE)
                    for d in deps
                )
                if node.condition is None:
                    if hard_failure or any(d.state is NodeState.SKIPPED for d in deps):
                        self._finish_node(
                            node_run, NodeState.SKIPPED,
                            skip_reason="dependency did not succeed",
                        )
                        continue
                else:
                    # The condition may reference nodes beyond depends_on:
                    # evaluation waits until every referenced node is
                    # terminal, otherwise the node would be judged on
                    # not-yet-produced outputs and skipped forever.
                    cond_nodes = list(node.depends_on) + _condition_node_ids(node.condition)
                    if not all(
                        run.node_runs[ref].state in TERMINAL_NODE_STATES
                        for ref in cond_nodes
                        if ref in run.node_runs
                    ):
                        continue
                    if not _evaluate_condition(node.condition, run, results, view):
                        self._finish_node(
                            node_run, NodeState.SKIPPED, skip_reason="condition false"
                        )
                        continue
                if len(ready) < max(0, limit):
                    ready.append(node.node_id)
            elif node_run.state is NodeState.RUNNING:
                pending_left = True
        if not ready and not pending_left:
            return None
        return ready

    def _skip_dependents(self, run: WorkflowRun, node_id: str, *, reason: str) -> None:
        changed = True
        while changed:
            changed = False
            for node in run.workflow.nodes:
                nr = run.node_runs[node.node_id]
                if nr.state is not NodeState.PENDING or node.condition is not None:
                    continue
                if node_id in node.depends_on or any(
                    run.node_runs[d].state is NodeState.SKIPPED for d in node.depends_on
                ):
                    self._finish_node(nr, NodeState.SKIPPED, skip_reason=reason)
                    changed = True

    def _cancel_pending(self, run: WorkflowRun, *, reason: str) -> None:
        for node_run in run.node_runs.values():
            if node_run.state in (NodeState.PENDING, NodeState.RUNNING):
                self._finish_node(node_run, NodeState.CANCELLED, error=reason)

    def _finalize(self, run: WorkflowRun) -> None:
        states = [nr.state for nr in run.node_runs.values()]
        if any(s in (NodeState.RUNNING, NodeState.PENDING) for s in states):
            # Unfinished work (mid-run abort, project switch): resumable.
            run.state = RunState.INTERRUPTED
            return
        if any(s in (NodeState.FAILED, NodeState.UNAVAILABLE) for s in states):
            run.state = RunState.FAILED
        elif any(s is NodeState.CANCELLED for s in states):
            run.state = RunState.CANCELLED
        else:
            run.state = RunState.COMPLETED

    def _prepare_interrupted(self, run: WorkflowRun) -> None:
        """Crash mapping: RUNNING ⇒ PENDING (interrupted); a persisted RUNNING
        run state resumes instead of doubling."""
        if run.state is RunState.RUNNING:
            run.state = RunState.INTERRUPTED
        if run.state is RunState.INTERRUPTED:
            for node_run in run.node_runs.values():
                if node_run.state is NodeState.RUNNING:
                    node_run.state = NodeState.PENDING
                    node_run.error = "interrupted before completion; re-executing"
                    node_run.started_at = None

    def _check_project_match(self, run: WorkflowRun, context: ActionContext | None) -> None:
        if context is None or not run.project_path:
            return
        current = context.project_path
        if current and current != run.project_path:
            raise WorkflowValidationError(
                run.workflow.workflow_id,
                [
                    f"run {run.run_id} belongs to project {run.project_path!r}, "
                    f"not the current project {current!r} — resume/rerun refused"
                ],
            )

    # -------------------------------------------------------------- helpers --
    def _cache_identity(self, spec: WorkflowSpec, node: NodeSpec, run: WorkflowRun, catalog: Any,
                        context: ActionContext | None = None) -> str | None:
        """Identity of what this node WOULD do (action id+version, bound
        parameters, input version ids). Computed for every node — it drives
        rerun carry-over decisions; cache *reuse* stays gated on the
        action's cacheable declaration. ``context`` is the caller's live
        session (so $context bindings evaluate truthfully); ``None`` makes
        $context bindings fail and the identity None — nodes depending on
        session state are then simply never carried over."""
        try:
            action_spec = self._registry.get(node.action_id)
        except LookupError:
            return None
        try:
            bound = bind_parameters(node, run=_RunView(run, context), results=self._results_view(run))
        except BindingError:
            return None
        input_ids = self._input_version_ids(run, node)
        return canonical_hash(
            {
                "action_id": action_spec.action_id,
                "action_version": action_spec.version,
                "parameters": _jsonable_projection(bound),
                "input_version_ids": sorted(input_ids),
            }
        )

    def _input_version_ids(self, run: WorkflowRun, node: NodeSpec) -> tuple[str, ...]:
        ids: list[str] = []
        for dep in node.depends_on:
            ids.extend(run.node_runs[dep].output_version_ids)
        seen: set[str] = set()
        ordered = [v for v in ids if not (v in seen or seen.add(v))]
        return tuple(ordered)

    def _results_view(self, run: WorkflowRun) -> dict[str, Any]:
        """node_id → outputs for $ref resolution: live JSON-able projections
        persisted on each NodeRun (so resume keeps $ref working)."""
        return {nr.node_id: nr.outputs for nr in run.node_runs.values() if nr.outputs}

    @staticmethod
    def _finish_node(
        node_run: NodeRun,
        state: NodeState,
        *,
        error: str | None = None,
        skip_reason: str | None = None,
        action_status: str | None = None,
    ) -> None:
        node_run.state = state
        node_run.error = error
        node_run.skip_reason = skip_reason
        if action_status:
            node_run.action_status = action_status
        node_run.finished_at = time.time()

    def _transitive_dependents(self, spec: WorkflowSpec, roots: set[str]) -> set[str]:
        affected: set[str] = set(roots)
        changed = True
        while changed:
            changed = False
            for node in spec.nodes:
                if node.node_id in affected:
                    continue
                if any(dep in affected for dep in node.depends_on):
                    affected.add(node.node_id)
                    changed = True
        return affected

    @staticmethod
    def _checkpoint(store: WorkflowRunStore, run: WorkflowRun) -> None:
        """Persist the run. A failing checkpoint ABORTS the run (fail-closed):
        silently continuing would report COMPLETED while every resume/cache
        guarantee is void."""
        try:
            store.save(run)
        except Exception as exc:
            logger.exception("workflow run %s checkpoint failed", run.run_id)
            for node_run in run.node_runs.values():
                if node_run.state in (NodeState.PENDING, NodeState.RUNNING):
                    node_run.state = NodeState.PENDING
            run.state = RunState.FAILED
            run.node_runs["__checkpoint__"] = NodeRun(
                node_id="__checkpoint__",
                state=NodeState.FAILED,
                error=f"checkpoint persistence failed: {type(exc).__name__}: {exc}",
            )
            raise CheckpointFailed(str(exc)) from exc

    @staticmethod
    def _notify(run: WorkflowRun, on_update: Callable[[WorkflowRun], None] | None) -> None:
        if on_update is None:
            return
        try:
            on_update(run)
        except Exception:
            logger.exception("workflow on_update callback failed")


_MODULE_LOCK = threading.RLock()


class CheckpointFailed(RuntimeError):
    """The run store refused a checkpoint write — persistence is void and
    the run cannot honestly continue."""



class _RunView:
    """What bindings may read at run time: slot values + the action context."""

    def __init__(self, run: WorkflowRun, context: ActionContext | None):
        self._run = run
        self.context = context or ActionContext()

    @property
    def slot_values(self) -> dict[str, Any]:
        return self._run.slot_values


class _SyncedToken(_RunCancelToken):
    """Engine token that also fires when the owning scheduler task is
    cancelled (single source: the scheduler event wins, never loses)."""

    def __init__(self, token: _RunCancelToken, task_ctx: Any) -> None:
        super().__init__()
        self._wrapped = token
        self._task_ctx = task_ctx

    @property
    def is_cancelled(self) -> bool:
        if self._task_ctx.cancelled.is_set():
            self._wrapped.cancel()
            self._event.set()
        return self._event.is_set() or self._wrapped.is_cancelled

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TaskCancelled("workflow run cancelled")


class _ExternalSyncedToken(_RunCancelToken):
    """Engine token synced with an external cooperative-cancel token
    (duck-typed: ``is_cancelled`` property / ``raise_if_cancelled``)."""

    def __init__(self, token: _RunCancelToken, external: Any) -> None:
        super().__init__()
        self._wrapped = token
        self._external = external

    def _external_cancelled(self) -> bool:
        check = getattr(self._external, "is_cancelled", None)
        if callable(check):
            return bool(check())
        if isinstance(check, bool):
            # Property form (the standard harness cancel protocol).
            return check
        return bool(
            getattr(self._external, "cancelled", None)
            and getattr(self._external.cancelled, "is_set", lambda: False)()
        )

    @property
    def is_cancelled(self) -> bool:
        if self._external_cancelled():
            self._wrapped.cancel()
            self._event.set()
        return self._event.is_set() or self._wrapped.is_cancelled

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TaskCancelled("workflow run cancelled")


def _make_task_spec(task, *, title: str, kind: str, priority: int, on_done, on_fail):
    from paleo_workbench.runtime.task_scheduler import TaskSpec

    return TaskSpec(
        callable=task,
        kind=kind,
        title=title,
        priority=priority,
        on_done=on_done,
        on_fail=on_fail,
    )


def _condition_node_ids(condition: NodeCondition) -> list[str]:
    ids: list[str] = []
    def walk(cond: NodeCondition) -> None:
        if cond.node:
            ids.append(cond.node)
        for sub in cond.conditions:
            walk(sub)
        if cond.condition is not None:
            walk(cond.condition)
    walk(condition)
    return ids


def _evaluate_condition(
    condition: NodeCondition, run: WorkflowRun, results: dict[str, Any], view: _RunView
) -> bool:
    kind = condition.kind
    if kind == "node_succeeded":
        target = run.node_runs.get(condition.node)
        return target is not None and target.state is NodeState.SUCCEEDED
    if kind == "node_output_equals":
        target = run.node_runs.get(condition.node)
        if target is None:
            return False
        value = (target.outputs or {}).get(condition.key)
        return value == condition.value
    if kind == "node_state":
        target = run.node_runs.get(condition.node)
        return target is not None and target.state.value == condition.state
    if kind == "all_of":
        return all(_evaluate_condition(c, run, results, view) for c in condition.conditions)
    if kind == "any_of":
        return any(_evaluate_condition(c, run, results, view) for c in condition.conditions)
    if kind == "not":
        return condition.condition is not None and not _evaluate_condition(
            condition.condition, run, results, view
        )
    return False


_RESOURCE_SHED_MARKERS = ("resourceexhausted", "cpu:", "ram:", "io:", "vram:", "pressure")


def _is_resource_shed(error: str | None) -> bool:
    """True for a governor admission refusal (retryable under the retry
    policy); plain guard rejections (schema/permission/context) never retry."""
    if not error:
        return False
    lowered = error.lower()
    return any(marker in lowered for marker in _RESOURCE_SHED_MARKERS)


def _jsonable_projection(value: Any) -> dict[str, Any]:
    """JSON-safe projection of a dict of outputs (used for checkpoints and
    $ref after resume)."""
    from paleo_workbench.harness.executor import _jsonable

    if not isinstance(value, dict):
        return {}
    try:
        return _jsonable(value)
    except Exception:
        return {}
