"""Minimal incremental recomputation plans (Stage 9).

The planner decides *what* needs scientific recomputation and in which
topological order. Domain modules (factor scheduler, prediction adapters,
map compile, QC, export) decide *how*. Style/display changes never appear
here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Sequence

from paleo_workbench.workflow.dependency_graph import DependencyGraph, DependencyGraphError
from paleo_workbench.workflow.freshness import (
    FreshnessReason,
    FreshnessReasonType,
    FreshnessReport,
    FreshnessService,
    FreshnessState,
)


class PlanAction(str, Enum):
    REQUIRES_COMPUTE = "requires_compute"
    REUSE_EXISTING = "reuse_existing"
    SKIP_DISPLAY_ONLY = "skip_display_only"
    BLOCKED = "blocked"


@dataclass
class RecomputeStep:
    """One node in a minimal recompute plan."""

    order: int
    run_id: str | None
    operation: str
    domain_task_id: str | None
    action: PlanAction
    reason: FreshnessReason | None = None
    reuse_run_id: str | None = None
    reuse_output_version_ids: list[str] = field(default_factory=list)
    input_version_ids: list[str] = field(default_factory=list)
    output_version_ids: list[str] = field(default_factory=list)
    label: str = ""
    can_reuse_existing: bool = False
    requires_compute: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "run_id": self.run_id,
            "operation": self.operation,
            "domain_task_id": self.domain_task_id,
            "action": self.action.value,
            "reason": self.reason.to_dict() if self.reason else None,
            "reuse_run_id": self.reuse_run_id,
            "reuse_output_version_ids": list(self.reuse_output_version_ids),
            "input_version_ids": list(self.input_version_ids),
            "output_version_ids": list(self.output_version_ids),
            "label": self.label,
            "can_reuse_existing": self.can_reuse_existing,
            "requires_compute": self.requires_compute,
        }


@dataclass
class RecomputePlan:
    """Topologically ordered minimal recompute plan."""

    steps: list[RecomputeStep] = field(default_factory=list)
    changed_version_ids: list[str] = field(default_factory=list)
    cycle_error: str | None = None
    # Execution bookkeeping (filled by PlanExecutor)
    completed_run_ids: list[str] = field(default_factory=list)
    failed_run_ids: list[str] = field(default_factory=list)
    skipped_run_ids: list[str] = field(default_factory=list)

    @property
    def compute_steps(self) -> list[RecomputeStep]:
        return [s for s in self.steps if s.requires_compute]

    def summary_zh(self) -> str:
        n = len(self.compute_steps)
        if n == 0:
            return "无需更新"
        lines = [f"{n} 个步骤需要更新", ""]
        for s in self.compute_steps:
            label = s.label or s.operation or s.domain_task_id or s.run_id or "?"
            lines.append(f"{s.order}. {label}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "changed_version_ids": list(self.changed_version_ids),
            "cycle_error": self.cycle_error,
            "completed_run_ids": list(self.completed_run_ids),
            "failed_run_ids": list(self.failed_run_ids),
            "skipped_run_ids": list(self.skipped_run_ids),
        }


# Human-readable operation labels (Chinese UI)
OPERATION_LABELS_ZH: dict[str, str] = {
    "factor_map": "单因素图",
    "prediction": "地震相预测",
    "map_compile": "古地理图编绘",
    "qc": "质量检查",
    "export": "成果导出",
    "horizon_interpretation": "层位解释",
    "modeling": "三维建模",
    "stratigraphic_correlation": "连井对比",
    "fault_interpretation": "断层解释",
}


def _task_consumer_links(
    project: Any,
    affected_task_ids: set[str],
) -> dict[str, set[str]]:
    """Map consumer domain-task id -> producer task ids it consumes at the
    TASK level (prediction.input_factor_map_ids, map.linked_prediction_task_id).
    These links exist even when the consumer's run-graph lineage is empty (a
    prediction executed before its factor grid was registered records no
    input versions — H11).
    """
    links: dict[str, set[str]] = {}
    if not affected_task_ids:
        return links

    for task in getattr(project, "prediction_tasks", None) or []:
        factor_ids = set(getattr(task, "input_factor_map_ids", None) or [])
        producers = factor_ids & affected_task_ids
        if producers:
            links.setdefault(task.id, set()).update(producers)

    pred_consumers = set(links.keys())
    for doc in getattr(project, "paleomap_documents", None) or []:
        linked = getattr(doc, "linked_prediction_task_id", None)
        producers = {linked} & (affected_task_ids | pred_consumers) if linked else set()
        if producers:
            links.setdefault(doc.id, set()).update(producers)
    return links


def _task_linked_run_ids(
    graph: DependencyGraph,
    task_links: dict[str, set[str]],
) -> set[str]:
    out: set[str] = set()
    for tid in task_links:
        for rid in graph.domain_task_runs.get(tid, ()):
            out.add(rid)
    return out


def build_recompute_plan(
    freshness: FreshnessService,
    *,
    changed_version_ids: Sequence[str] | None = None,
    stale_only: bool = True,
    operations: Sequence[str] | None = None,
    project: Any | None = None,
) -> RecomputePlan:
    """Build a minimal plan for affected / stale scientific products.

    If *changed_version_ids* is given, only transitive dependents of those
    versions are considered. Otherwise all STALE runs in the graph are planned.
    *project* enables task-level dependency expansion for runs whose lineage
    is empty (see :func:`_task_linked_run_ids`).
    """
    graph = freshness.graph
    plan = RecomputePlan(changed_version_ids=list(changed_version_ids or []))

    if graph.has_cycle():
        # Still try to plan unaffected subsets; flag the cycle
        plan.cycle_error = (
            f"provenance cycle involving: {', '.join(sorted(graph.cycle_nodes)[:8])}"
        )

    candidate_runs: list[Any]
    task_forced: set[str] = set()
    task_links: dict[str, set[str]] = {}
    if changed_version_ids:
        # Roots include the new tip *and* prior versions of the same asset so
        # dependents of superseded versions (e.g. Factor from H1 v2 after H1
        # advances to v3) are included in the plan.
        roots: set[str] = set()
        for vid in changed_version_ids:
            roots.add(vid)
            asset = graph.asset_id_for(vid)
            if asset:
                for other in graph.asset_versions.get(asset, ()):
                    roots.add(other)
            # Domain-task siblings (multi-asset interpretation history)
            prod = graph.producing_run.get(vid)
            if prod and prod in graph.runs:
                domain = graph.runs[prod].domain_task_id
                if domain:
                    for rid in graph.domain_task_runs.get(domain, ()):
                        for out in graph.run_outputs.get(rid, ()):
                            roots.add(out)
        candidate_runs = graph.transitive_downstream_runs(roots)
        if project is not None:
            # Empty-lineage consumers still depend on the changed versions at
            # the task level: include their runs as candidates (H11).
            affected_task_ids = {
                r.domain_task_id
                for r in candidate_runs
                if getattr(r, "domain_task_id", None)
            }
            task_links = _task_consumer_links(project, affected_task_ids)
            task_forced = _task_linked_run_ids(graph, task_links)
            seen_ids = {r.run_id for r in candidate_runs}
            for rid in sorted(task_forced):
                if rid not in seen_ids and rid in graph.runs:
                    candidate_runs.append(graph.runs[rid])
    else:
        candidate_runs = list(graph.runs.values())

    op_filter = set(operations) if operations else None
    stale_run_ids: list[str] = []
    reports: dict[str, FreshnessReport] = {}

    for run in candidate_runs:
        if op_filter is not None and run.operation not in op_filter:
            continue
        report = freshness.evaluate_run(run.run_id)
        reports[run.run_id] = report
        if stale_only and report.state not in {
            FreshnessState.STALE,
            FreshnessState.MISSING,
            FreshnessState.FAILED,
        }:
            # UNKNOWN runs are not forced — EXCEPT task-linked consumers
            # included above: recomputing them re-establishes lineage (H11).
            if not (
                report.state is FreshnessState.UNKNOWN
                and run.run_id in task_forced
            ):
                continue
        stale_run_ids.append(run.run_id)

    try:
        ordered = graph.topological_runs(
            stale_run_ids, task_consumers=task_links if task_links else None
        )
    except DependencyGraphError as exc:
        plan.cycle_error = str(exc)
        ordered = [graph.runs[rid] for rid in stale_run_ids if rid in graph.runs]

    steps: list[RecomputeStep] = []
    order = 0
    for run in ordered:
        report = reports.get(run.run_id) or freshness.evaluate_run(run.run_id)
        reason = report.primary_reason()
        # Try provenance reuse with *current* inputs for the same identity
        current_inputs = _current_inputs_for_run(run, freshness)
        reuse = graph.find_reuse_run(
            operation=run.operation or "",
            input_version_ids=current_inputs,
            generator_version=run.generator_version,
            input_snapshot_hash=run.input_snapshot_hash,
            parameters=None,
            require_outputs=True,
        )
        # Only reuse a *different* completed run that already matches current inputs
        can_reuse = (
            reuse is not None
            and reuse.run_id != run.run_id
            and list(reuse.input_version_ids or []) == current_inputs
        )
        order += 1
        label = _step_label(run, freshness)
        # Outputs are version-namespace ids (`ver_…`), distinct from run ids
        # (`run_…`): the executor poisons these so downstream steps whose
        # input_version_ids intersect them are skipped after a failure
        # (audit #847-4 — poisoning run_id never intersects inputs).
        output_ids = list(graph.run_outputs.get(run.run_id, ()))
        if can_reuse and reuse is not None:
            steps.append(
                RecomputeStep(
                    order=order,
                    run_id=run.run_id,
                    operation=run.operation or "",
                    domain_task_id=run.domain_task_id,
                    action=PlanAction.REUSE_EXISTING,
                    reason=reason,
                    reuse_run_id=reuse.run_id,
                    reuse_output_version_ids=list(reuse.output_version_ids or []),
                    input_version_ids=current_inputs,
                    output_version_ids=output_ids,
                    label=label,
                    can_reuse_existing=True,
                    requires_compute=False,
                )
            )
        else:
            steps.append(
                RecomputeStep(
                    order=order,
                    run_id=run.run_id,
                    operation=run.operation or "",
                    domain_task_id=run.domain_task_id,
                    action=PlanAction.REQUIRES_COMPUTE,
                    reason=reason,
                    input_version_ids=current_inputs,
                    output_version_ids=output_ids,
                    label=label,
                    can_reuse_existing=False,
                    requires_compute=True,
                )
            )

    plan.steps = steps
    return plan


def _current_inputs_for_run(run: Any, freshness: FreshnessService) -> list[str]:
    """Map each historical input to the currently selected version of its product."""
    result: list[str] = []
    for in_vid in run.input_version_ids or []:
        mismatch = freshness._selection_mismatch(in_vid)
        if mismatch is not None:
            result.append(mismatch[0])
        else:
            result.append(in_vid)
    return result


def _step_label(run: Any, freshness: FreshnessService) -> str:
    op = run.operation or ""
    base = OPERATION_LABELS_ZH.get(op, op)
    # Prefer domain task name from expected identity labels / version names
    if run.domain_task_id:
        return f"{base} ({run.domain_task_id})"
    outs = run.output_version_ids or []
    if outs:
        name = freshness.context.labels.get(outs[0]) or ""
        if not name:
            ver = freshness.graph.versions.get(outs[0])
            name = getattr(ver, "name", "") if ver else ""
        if name:
            return f"{base} {name}"
    return base


@dataclass
class PlanExecutionResult:
    plan: RecomputePlan
    stopped_early: bool = False
    messages: list[str] = field(default_factory=list)


class PlanExecutor:
    """Execute a recompute plan in topological order with failure isolation.

    *generation* guards cancel mid-flight work when a newer plan supersedes.
    Domain *handlers* are callables ``(step) -> None`` keyed by operation;
    missing handlers mark the step failed without inventing compute.

    Partial failure: successful steps stay done; dependents of a failed step
    are skipped (remain STALE), matching Stage-9 semantics.
    """

    def __init__(
        self,
        handlers: dict[str, Callable[[RecomputeStep], Any]] | None = None,
        *,
        generation: int = 0,
        stop_on_failure: bool = True,
        skip_dependents_on_failure: bool = True,
    ) -> None:
        self.handlers = dict(handlers or {})
        self.generation = generation
        self.stop_on_failure = stop_on_failure
        self.skip_dependents_on_failure = skip_dependents_on_failure
        self._cancelled = False
        self._active_generation = generation

    def cancel(self) -> None:
        self._cancelled = True

    def bump_generation(self) -> int:
        self.generation += 1
        self._active_generation = self.generation
        self._cancelled = True
        return self.generation

    def execute(
        self,
        plan: RecomputePlan,
        *,
        generation: int | None = None,
    ) -> PlanExecutionResult:
        gen = self.generation if generation is None else generation
        result = PlanExecutionResult(plan=plan)
        failed_ops: set[str] = set()
        failed_run_ids: set[str] = set()
        poisoned_versions: set[str] = set()

        for step in plan.steps:
            if self._cancelled or gen != self._active_generation:
                result.stopped_early = True
                result.messages.append("cancelled by generation guard")
                break

            if step.action is PlanAction.REUSE_EXISTING:
                plan.completed_run_ids.append(step.run_id or step.reuse_run_id or "")
                result.messages.append(f"reuse {step.label}")
                continue

            if not step.requires_compute:
                plan.skipped_run_ids.append(step.run_id or "")
                continue

            if self.skip_dependents_on_failure and poisoned_versions:
                if any(vid in poisoned_versions for vid in step.input_version_ids):
                    plan.skipped_run_ids.append(step.run_id or "")
                    result.messages.append(f"skip {step.label} (upstream failure)")
                    continue

            if self.stop_on_failure and failed_run_ids:
                plan.skipped_run_ids.append(step.run_id or "")
                result.messages.append(f"skip {step.label} (upstream failure)")
                continue

            handler = self.handlers.get(step.operation)
            if handler is None:
                plan.failed_run_ids.append(step.run_id or "")
                failed_run_ids.add(step.run_id or "")
                failed_ops.add(step.operation)
                # Poison the step's OUTPUT VERSIONS — downstream steps declare
                # those ids in input_version_ids. A run_id (`run_…`) lives in
                # a disjoint namespace and never intersects (audit #847-4).
                poisoned_versions.update(step.output_version_ids)
                poisoned_versions.update(step.reuse_output_version_ids)
                result.messages.append(
                    f"no handler for operation {step.operation!r}; mark failed"
                )
                if self.stop_on_failure:
                    result.stopped_early = True
                continue

            try:
                handler(step)
                plan.completed_run_ids.append(step.run_id or "")
                result.messages.append(f"ok {step.label}")
            except Exception as exc:  # domain handler failures
                plan.failed_run_ids.append(step.run_id or "")
                failed_run_ids.add(step.run_id or "")
                failed_ops.add(step.operation)
                # Same version-namespace poisoning as above: dependents that
                # consumed this run's outputs must be skipped.
                poisoned_versions.update(step.output_version_ids)
                poisoned_versions.update(step.reuse_output_version_ids)
                result.messages.append(f"failed {step.label}: {exc}")
                if self.stop_on_failure:
                    result.stopped_early = True
                    # Continue loop only to mark skips
                    continue

        return result


def plan_for_changed_versions(
    project: Any | None,
    changed_version_ids: Sequence[str],
    *,
    catalog: Any | None = None,
) -> RecomputePlan:
    """Convenience: freshness service + plan for upstream version changes."""
    svc = FreshnessService.for_project(project, catalog=catalog)
    return build_recompute_plan(
        svc,
        changed_version_ids=list(changed_version_ids),
        project=project,
    )
