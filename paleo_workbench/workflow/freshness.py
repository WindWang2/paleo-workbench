"""Derived scientific freshness (Stage 9).

Integrity (file payload checksum) and freshness (up-to-date vs current
project selection) are distinct dimensions. Historical DataVersions are
never mutated with a ``stale`` flag — status is always recomputed from
catalog lineage + :class:`CurrentProjectVersionContext`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from paleo_workbench.workflow.current_context import (
    CurrentProjectVersionContext,
    resolve_current_project_version_context,
)
from paleo_workbench.workflow.dependency_graph import DependencyGraph, DependencyGraphError


class FreshnessState(str, Enum):
    """Freshness relative to *current project inputs* (not file integrity)."""

    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    MISSING = "MISSING"
    FAILED = "FAILED"
    RUNNING = "RUNNING"


class FreshnessReasonType(str, Enum):
    UPSTREAM_VERSION_CHANGED = "UPSTREAM_VERSION_CHANGED"
    PARAMETERS_CHANGED = "PARAMETERS_CHANGED"
    MODEL_VERSION_CHANGED = "MODEL_VERSION_CHANGED"
    GENERATOR_CHANGED = "GENERATOR_CHANGED"
    MISSING_LINEAGE = "MISSING_LINEAGE"
    MISSING_PAYLOAD = "MISSING_PAYLOAD"
    INTEGRITY_MODIFIED = "INTEGRITY_MODIFIED"
    RUN_FAILED = "RUN_FAILED"
    RUN_RUNNING = "RUN_RUNNING"
    GRAPH_CYCLE = "GRAPH_CYCLE"
    TRANSITIVE_UPSTREAM_STALE = "TRANSITIVE_UPSTREAM_STALE"
    OK = "OK"


# Operations that *should* declare inputs; empty input list → UNKNOWN
_LINEAGE_EXPECTED_OPS = frozenset(
    {
        "factor_map",
        "prediction",
        "export",
        "horizon_interpretation",
        "map_compile",
        "qc",
        "modeling",
    }
)


@dataclass(frozen=True, slots=True)
class FreshnessReason:
    type: FreshnessReasonType
    upstream_version_id: str | None = None
    current_version_id: str | None = None
    operation: str = ""
    detail: str = ""
    asset_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "upstream_version_id": self.upstream_version_id,
            "current_version_id": self.current_version_id,
            "operation": self.operation,
            "detail": self.detail,
            "asset_id": self.asset_id,
        }


@dataclass
class FreshnessReport:
    """Freshness evaluation for one run or one output version."""

    state: FreshnessState
    subject_kind: str  # "run" | "version" | "domain_task"
    subject_id: str
    reasons: list[FreshnessReason] = field(default_factory=list)
    operation: str = ""
    domain_task_id: str | None = None
    output_version_ids: list[str] = field(default_factory=list)
    input_version_ids: list[str] = field(default_factory=list)
    # Integrity dimension (orthogonal to freshness)
    integrity: str | None = None  # verified | modified | missing | unknown

    @property
    def is_fresh(self) -> bool:
        return self.state is FreshnessState.FRESH

    @property
    def is_stale(self) -> bool:
        return self.state is FreshnessState.STALE

    def primary_reason(self) -> FreshnessReason | None:
        return self.reasons[0] if self.reasons else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "reasons": [r.to_dict() for r in self.reasons],
            "operation": self.operation,
            "domain_task_id": self.domain_task_id,
            "output_version_ids": list(self.output_version_ids),
            "input_version_ids": list(self.input_version_ids),
            "integrity": self.integrity,
        }


# Chinese UI labels for workflow / dashboard
FRESHNESS_UI_LABELS: dict[str, str] = {
    FreshnessState.FRESH.value: "已完成",
    FreshnessState.STALE.value: "需更新",
    FreshnessState.UNKNOWN.value: "状态未知",
    FreshnessState.MISSING.value: "缺失",
    FreshnessState.FAILED.value: "异常",
    FreshnessState.RUNNING.value: "处理中",
}

# Workflow step status strings (project models Literal)
WORKFLOW_STATUS_FOR_FRESHNESS: dict[FreshnessState, str] = {
    FreshnessState.FRESH: "complete",
    FreshnessState.STALE: "stale",
    # UNKNOWN must not render as complete: provenance-less results are not
    # "已完成" (H1). "warning" maps to the existing 状态未知 label.
    FreshnessState.UNKNOWN: "warning",
    FreshnessState.MISSING: "warning",
    FreshnessState.FAILED: "failed",
    FreshnessState.RUNNING: "running",
}


class FreshnessService:
    """Evaluate run/version freshness against current project selection."""

    def __init__(
        self,
        graph: DependencyGraph,
        context: CurrentProjectVersionContext,
        *,
        catalog: Any | None = None,
        check_integrity: bool = False,
    ) -> None:
        self.graph = graph
        self.context = context
        self.catalog = catalog
        # Integrity re-hash is orthogonal and expensive — off for UI/dashboard.
        self.check_integrity = check_integrity
        self._run_cache: dict[str, FreshnessReport] = {}
        self._version_cache: dict[str, FreshnessReport] = {}
        # Index of selected versions by producing domain task / parent link,
        # so _selection_mismatch rules 3/4 are O(1) lookups instead of full
        # scans per input (perf: plan build was O(runs × selections)).
        self._selected_by_key: dict[tuple, list[str]] | None = None

    def _index_selected(self) -> None:
        if self._selected_by_key is not None:
            return
        index: dict[tuple, list[str]] = {}
        for sel in self.context.selected_version_ids:
            prod = self.graph.producing_run.get(sel)
            run = self.graph.runs.get(prod) if prod else None
            if run is None:
                continue
            if run.domain_task_id:
                index.setdefault(("domain", run.domain_task_id), []).append(sel)
            parent = (run.parameters or {}).get("parent_version_id")
            if parent:
                index.setdefault(("parent", str(parent)), []).append(sel)
        self._selected_by_key = index

    @classmethod
    def for_project(
        cls,
        project: Any | None = None,
        *,
        catalog: Any | None = None,
        service: Any | None = None,
        extra_selected: dict[str, str] | None = None,
        check_integrity: bool = False,
    ) -> "FreshnessService":
        from paleo_workbench.catalog.runtime import get_catalog

        cat = catalog if catalog is not None else get_catalog()
        if cat is None:
            # Empty graph — everything UNKNOWN when queried
            graph = DependencyGraph()
            ctx = resolve_current_project_version_context(
                project, catalog=None, service=service, extra_selected=extra_selected
            )
            return cls(graph, ctx, catalog=None, check_integrity=check_integrity)
        graph = DependencyGraph.from_catalog(cat)
        ctx = resolve_current_project_version_context(
            project, catalog=cat, service=service, extra_selected=extra_selected
        )
        return cls(graph, ctx, catalog=cat, check_integrity=check_integrity)

    def clear_cache(self) -> None:
        self._run_cache.clear()
        self._version_cache.clear()
        self._selected_by_key = None

    def _input_is_withdrawn(self, input_version_id: str) -> bool:
        """True when the input version is gone from the catalog or trashed.

        A downstream product must never stay FRESH on top of a withdrawn
        input (H1): trashing/purging an upstream RAW/derived version makes
        every consumer's lineage reference dangling, which is a provenance
        defect, not "no mismatch".
        """
        ver = self.graph.versions.get(input_version_id)
        if ver is None and self.catalog is not None:
            ver = self.catalog.resolve_version(input_version_id)
        if ver is None:
            return True  # purged / unknown version
        if getattr(ver, "trashed", False):
            return True
        return False

    def _checksum_for(self, version_id: str) -> str | None:
        """Recorded payload checksum for *version_id*, or None when unknown."""
        ver = self.graph.versions.get(version_id)
        if ver is not None:
            return getattr(ver, "checksum", None) or None
        if self.catalog is not None:
            try:
                resolved = self.catalog.resolve_version(version_id)
            except Exception:
                return None
            return getattr(resolved, "checksum", None) or None
        return None

    def _content_identical(self, a: str, b: str) -> bool:
        """True when both versions record the SAME payload checksum.

        A byte-identical supersession (e.g. promote copies the payload and
        records the same SHA-256) does not change what a consumer actually
        ran on, so it must not invalidate freshness (issue #373 / C15).
        Unknown checksums keep the mismatch (conservative).
        """
        first = self._checksum_for(a)
        if not first:
            return False
        return first == self._checksum_for(b)

    def _selection_mismatch(
        self, input_version_id: str
    ) -> tuple[str, str | None] | None:
        """Return ``(current_version_id, asset_id)`` when *input* is not current.

        Matching rules (first hit wins):

        1. Project domain-task product pointer differs from input (multi-asset
           recompute: each run may create a new asset).
        2. Same asset: catalog/project ``current_by_asset`` differs from input.
        3. Domain-task supersession via producing runs / selected tips.
        4. Parent-link supersession via run parameters.
        5. Input itself is selected with no competing tip → current.
        6. Unknown → no mismatch (do not guess STALE).

        Rules 1–3 tolerate content-identical supersession: when the candidate
        "current" version records the same payload checksum as the input, the
        consumer's scientific input has not changed, so no mismatch is
        reported.
        """
        prod = self.graph.producing_run.get(input_version_id)
        domain_id = None
        if prod and prod in self.graph.runs:
            domain_id = self.graph.runs[prod].domain_task_id

        # 1. Explicit project product tip for this domain task
        if domain_id:
            tip = self.context.current_by_domain_task.get(domain_id)
            if tip and tip != input_version_id:
                if self._content_identical(tip, input_version_id):
                    return None
                return tip, self.graph.asset_id_for(tip)

        asset_id = self.graph.asset_id_for(input_version_id)
        current = self.context.current_for_asset(asset_id) if asset_id else None
        if current is not None and current != input_version_id:
            if self._content_identical(current, input_version_id):
                return None
            return current, asset_id

        # 3. Domain-task supersession among selected tips only (do not force
        # "latest run" — user may intentionally select an older tip).
        if domain_id:
            self._index_selected()
            for sel in self._selected_by_key.get(("domain", domain_id), ()):
                if sel == input_version_id:
                    continue
                if self._content_identical(sel, input_version_id):
                    continue
                return sel, self.graph.asset_id_for(sel)

        # 4. Parent-link supersession
        if prod and prod in self.graph.runs:
            self._index_selected()
            for sel in self._selected_by_key.get(("parent", input_version_id), ()):
                return sel, self.graph.asset_id_for(sel)

        if input_version_id in self.context.selected_version_ids:
            return None

        return None

    def evaluate_run(self, run_id: str, *, _stack: frozenset[str] | None = None) -> FreshnessReport:
        if run_id in self._run_cache:
            return self._run_cache[run_id]
        stack = _stack or frozenset()
        if run_id in stack:
            report = FreshnessReport(
                state=FreshnessState.UNKNOWN,
                subject_kind="run",
                subject_id=run_id,
                reasons=[
                    FreshnessReason(
                        type=FreshnessReasonType.GRAPH_CYCLE,
                        detail="cycle while evaluating run freshness",
                        operation="",
                    )
                ],
            )
            return report

        run = self.graph.runs.get(run_id)
        if run is None and self.catalog is not None:
            run = self.catalog.resolve_run(run_id)
        if run is None:
            report = FreshnessReport(
                state=FreshnessState.UNKNOWN,
                subject_kind="run",
                subject_id=run_id,
                reasons=[
                    FreshnessReason(
                        type=FreshnessReasonType.MISSING_LINEAGE,
                        detail="run not found in catalog",
                    )
                ],
            )
            self._run_cache[run_id] = report
            return report

        if self.graph.has_cycle() and run_id in {
            self.graph.producing_run.get(v) for v in self.graph.cycle_nodes
        }:
            report = FreshnessReport(
                state=FreshnessState.UNKNOWN,
                subject_kind="run",
                subject_id=run_id,
                operation=run.operation or "",
                domain_task_id=run.domain_task_id,
                input_version_ids=list(run.input_version_ids or []),
                output_version_ids=list(run.output_version_ids or []),
                reasons=[
                    FreshnessReason(
                        type=FreshnessReasonType.GRAPH_CYCLE,
                        operation=run.operation or "",
                        detail="provenance cycle detected",
                    )
                ],
            )
            self._run_cache[run_id] = report
            return report

        reasons: list[FreshnessReason] = []
        status = (run.status or "").lower()
        if status in {"failed", "error", "cancelled", "canceled"}:
            report = FreshnessReport(
                state=FreshnessState.FAILED,
                subject_kind="run",
                subject_id=run_id,
                operation=run.operation or "",
                domain_task_id=run.domain_task_id,
                input_version_ids=list(run.input_version_ids or []),
                output_version_ids=list(run.output_version_ids or []),
                reasons=[
                    FreshnessReason(
                        type=FreshnessReasonType.RUN_FAILED,
                        operation=run.operation or "",
                    )
                ],
            )
            self._run_cache[run_id] = report
            return report
        if status in {"running", "pending"}:
            report = FreshnessReport(
                state=FreshnessState.RUNNING,
                subject_kind="run",
                subject_id=run_id,
                operation=run.operation or "",
                domain_task_id=run.domain_task_id,
                input_version_ids=list(run.input_version_ids or []),
                output_version_ids=list(run.output_version_ids or []),
                reasons=[
                    FreshnessReason(
                        type=FreshnessReasonType.RUN_RUNNING,
                        operation=run.operation or "",
                    )
                ],
            )
            self._run_cache[run_id] = report
            return report

        inputs = list(run.input_version_ids or [])
        if not inputs and (run.operation or "") in _LINEAGE_EXPECTED_OPS:
            report = FreshnessReport(
                state=FreshnessState.UNKNOWN,
                subject_kind="run",
                subject_id=run_id,
                operation=run.operation or "",
                domain_task_id=run.domain_task_id,
                input_version_ids=inputs,
                output_version_ids=list(run.output_version_ids or []),
                reasons=[
                    FreshnessReason(
                        type=FreshnessReasonType.MISSING_LINEAGE,
                        operation=run.operation or "",
                        detail="run has no input_version_ids",
                    )
                ],
            )
            self._run_cache[run_id] = report
            return report

        next_stack = stack | {run_id}

        # Output assets of this run — parent versions of the same asset are
        # lineage history (branch-from), not external upstream selection.
        output_assets = {
            a
            for a in (self.graph.asset_id_for(o) for o in (run.output_version_ids or []))
            if a
        }
        # Direct upstream version selection mismatches
        for in_vid in inputs:
            in_asset = self.graph.asset_id_for(in_vid)
            if in_asset and in_asset in output_assets:
                continue
            if self._input_is_withdrawn(in_vid):
                # Trashed/purged upstream: the product's lineage is dangling —
                # report it as a provenance defect instead of FRESH (H1).
                reasons.append(
                    FreshnessReason(
                        type=FreshnessReasonType.MISSING_LINEAGE,
                        upstream_version_id=in_vid,
                        operation=run.operation or "",
                        detail=f"input {in_vid} withdrawn/trashed from catalog",
                    )
                )
                continue
            mismatch = self._selection_mismatch(in_vid)
            if mismatch is None:
                continue
            current_vid, asset_id = mismatch
            reasons.append(
                FreshnessReason(
                    type=FreshnessReasonType.UPSTREAM_VERSION_CHANGED,
                    upstream_version_id=in_vid,
                    current_version_id=current_vid,
                    operation=run.operation or "",
                    asset_id=asset_id,
                    detail=f"run used {in_vid}; current is {current_vid}",
                )
            )

        # Transitive: if any input was produced by a stale run, this run is stale
        if not reasons:
            for in_vid in inputs:
                prod = self.graph.producing_run.get(in_vid)
                if not prod or prod == run_id:
                    continue
                up = self.evaluate_run(prod, _stack=next_stack)
                if up.state is FreshnessState.STALE:
                    reasons.append(
                        FreshnessReason(
                            type=FreshnessReasonType.TRANSITIVE_UPSTREAM_STALE,
                            upstream_version_id=in_vid,
                            operation=run.operation or "",
                            detail=f"upstream run {prod} is STALE",
                        )
                    )
                    break
                if up.state is FreshnessState.UNKNOWN and up.primary_reason() and (
                    up.primary_reason().type is FreshnessReasonType.GRAPH_CYCLE
                ):
                    reasons.append(up.primary_reason())  # type: ignore[arg-type]
                    break

        # Computation identity (parameters / model / generator)
        identity_key = run.domain_task_id or run_id
        expected = self.context.expected_identity.get(identity_key)
        if expected:
            if (
                "generator_version" in expected
                and expected["generator_version"] is not None
                and (run.generator_version or "") != (expected["generator_version"] or "")
            ):
                reasons.append(
                    FreshnessReason(
                        type=FreshnessReasonType.GENERATOR_CHANGED,
                        operation=run.operation or "",
                        detail=(
                            f"run generator={run.generator_version!r} "
                            f"expected={expected['generator_version']!r}"
                        ),
                    )
                )
            if (
                "input_snapshot_hash" in expected
                and expected["input_snapshot_hash"]
                and (run.input_snapshot_hash or "") != expected["input_snapshot_hash"]
            ):
                reasons.append(
                    FreshnessReason(
                        type=FreshnessReasonType.PARAMETERS_CHANGED,
                        operation=run.operation or "",
                        detail="input_snapshot_hash mismatch",
                    )
                )
            exp_params = expected.get("parameters") or {}
            if exp_params:
                run_params = dict(run.parameters or {})
                for k, v in exp_params.items():
                    if k in self.context.display_only_keys:
                        continue
                    if k in run_params and run_params.get(k) != v:
                        reasons.append(
                            FreshnessReason(
                                type=FreshnessReasonType.PARAMETERS_CHANGED,
                                operation=run.operation or "",
                                detail=f"parameter {k!r} changed",
                            )
                        )
                        break
            exp_model = expected.get("model_ref")
            if exp_model:
                run_params = dict(run.parameters or {})
                run_model = run_params.get("model_ref")
                if not isinstance(run_model, dict):
                    run_model = {
                        k: run_params[k]
                        for k in (
                            "model_id",
                            "model_version",
                            "model_version_id",
                            "preprocessing_version",
                        )
                        if k in run_params
                    }
                for mk in ("model_version_id", "model_version", "model_id"):
                    if mk not in exp_model:
                        continue
                    if run_model.get(mk) != exp_model[mk]:
                        reasons.append(
                            FreshnessReason(
                                type=FreshnessReasonType.MODEL_VERSION_CHANGED,
                                operation=run.operation or "",
                                detail=f"{mk} changed",
                            )
                        )
                        break

        # Payload / integrity on outputs (orthogonal to scientific freshness).
        # Default off on UI paths — full SHA re-hash blocks the main thread.
        integrity_note: str | None = None
        if self.check_integrity:
            for out_vid in run.output_version_ids or []:
                ver = self.graph.versions.get(out_vid)
                if ver is None and self.catalog is not None:
                    ver = self.catalog.resolve_version(out_vid)
                if ver is None:
                    continue
                path = getattr(ver, "path", "") or ""
                if not path:
                    continue
                if self.catalog is not None and hasattr(self.catalog, "verify_integrity"):
                    try:
                        from pathlib import Path as _Path

                        exists = _Path(path).is_file()
                        checksum = getattr(ver, "checksum", None) or ""
                        real_digest = len(checksum) == 64 and all(
                            c in "0123456789abcdef" for c in checksum.lower()
                        )
                        if not exists:
                            if real_digest:
                                integrity_note = "missing"
                                reasons.append(
                                    FreshnessReason(
                                        type=FreshnessReasonType.MISSING_PAYLOAD,
                                        operation=run.operation or "",
                                        detail=f"output {out_vid} payload missing",
                                    )
                                )
                            continue
                        status_i = self.catalog.verify_integrity(out_vid)
                        integrity_note = getattr(status_i, "value", str(status_i))
                        if integrity_note == "modified":
                            reasons.append(
                                FreshnessReason(
                                    type=FreshnessReasonType.INTEGRITY_MODIFIED,
                                    operation=run.operation or "",
                                    detail=f"output {out_vid} integrity modified",
                                )
                            )
                    except Exception:
                        pass

        if any(r.type is FreshnessReasonType.MISSING_PAYLOAD for r in reasons) and not any(
            r.type
            in {
                FreshnessReasonType.UPSTREAM_VERSION_CHANGED,
                FreshnessReasonType.TRANSITIVE_UPSTREAM_STALE,
                FreshnessReasonType.PARAMETERS_CHANGED,
                FreshnessReasonType.MODEL_VERSION_CHANGED,
                FreshnessReasonType.GENERATOR_CHANGED,
            }
            for r in reasons
        ):
            state = FreshnessState.MISSING
        elif any(
            r.type is FreshnessReasonType.GRAPH_CYCLE for r in reasons
        ):
            state = FreshnessState.UNKNOWN
        elif reasons and any(
            r.type is not FreshnessReasonType.INTEGRITY_MODIFIED for r in reasons
        ):
            # integrity-modified alone → still FRESH scientifically but note integrity
            sci_reasons = [
                r
                for r in reasons
                if r.type is not FreshnessReasonType.INTEGRITY_MODIFIED
            ]
            if sci_reasons:
                state = FreshnessState.STALE
            else:
                state = FreshnessState.FRESH
        elif reasons:
            state = FreshnessState.FRESH  # only integrity notes
        else:
            state = FreshnessState.FRESH
            reasons = [
                FreshnessReason(type=FreshnessReasonType.OK, operation=run.operation or "")
            ]

        report = FreshnessReport(
            state=state,
            subject_kind="run",
            subject_id=run_id,
            reasons=reasons,
            operation=run.operation or "",
            domain_task_id=run.domain_task_id,
            input_version_ids=list(run.input_version_ids or []),
            output_version_ids=list(run.output_version_ids or []),
            integrity=integrity_note,
        )
        self._run_cache[run_id] = report
        return report

    def evaluate_version(self, version_id: str) -> FreshnessReport:
        if version_id in self._version_cache:
            return self._version_cache[version_id]
        prod = self.graph.producing_run.get(version_id)
        if not prod:
            # RAW / root versions are always "fresh" relative to themselves
            report = FreshnessReport(
                state=FreshnessState.FRESH,
                subject_kind="version",
                subject_id=version_id,
                reasons=[
                    FreshnessReason(
                        type=FreshnessReasonType.OK,
                        detail="root/raw version (no producing run)",
                    )
                ],
            )
            self._version_cache[version_id] = report
            return report
        run_report = self.evaluate_run(prod)
        report = FreshnessReport(
            state=run_report.state,
            subject_kind="version",
            subject_id=version_id,
            reasons=list(run_report.reasons),
            operation=run_report.operation,
            domain_task_id=run_report.domain_task_id,
            input_version_ids=list(run_report.input_version_ids),
            output_version_ids=list(run_report.output_version_ids),
            integrity=run_report.integrity,
        )
        self._version_cache[version_id] = report
        return report

    def evaluate_domain_task(self, domain_task_id: str) -> FreshnessReport:
        run = self.graph.latest_run_for_domain_task(domain_task_id)
        if run is None:
            return FreshnessReport(
                state=FreshnessState.UNKNOWN,
                subject_kind="domain_task",
                subject_id=domain_task_id,
                domain_task_id=domain_task_id,
                reasons=[
                    FreshnessReason(
                        type=FreshnessReasonType.MISSING_LINEAGE,
                        detail="no DataRun linked to domain task",
                    )
                ],
            )
        base = self.evaluate_run(run.run_id)
        return FreshnessReport(
            state=base.state,
            subject_kind="domain_task",
            subject_id=domain_task_id,
            reasons=list(base.reasons),
            operation=base.operation,
            domain_task_id=domain_task_id,
            input_version_ids=list(base.input_version_ids),
            output_version_ids=list(base.output_version_ids),
            integrity=base.integrity,
        )

    def downstream_impact(
        self, version_ids: Sequence[str]
    ) -> list[FreshnessReport]:
        """Reports for all runs transitively depending on *version_ids*."""
        reports: list[FreshnessReport] = []
        for run in self.graph.transitive_downstream_runs(version_ids):
            reports.append(self.evaluate_run(run.run_id))
        return reports

    def stale_downstream(
        self, version_ids: Sequence[str]
    ) -> list[FreshnessReport]:
        return [r for r in self.downstream_impact(version_ids) if r.is_stale]

    def evaluate_operation(self, operation: str) -> list[FreshnessReport]:
        return [
            self.evaluate_run(rid)
            for rid, run in self.graph.runs.items()
            if run.operation == operation
        ]

    def step_freshness(self, step_type: str) -> FreshnessState | None:
        """Aggregate freshness for a workflow step type.

        Returns None when no catalog runs exist for that step (caller keeps
        evidence-based exists/complete semantics).
        """
        op_map = {
            "factor_map": "factor_map",
            "prediction": "prediction",
            "map_compile": "map_compile",
            "qc": "qc",
            "export": "export",
        }
        op = op_map.get(step_type)
        if op is None:
            return None
        reports = list(self.evaluate_operation(op))
        # Stage-13: inference_service historically used operation="inference";
        # treat those runs as prediction for freshness until fully migrated.
        if op == "prediction":
            reports.extend(self.evaluate_operation("inference"))
        if not reports:
            return None
        # Superseded runs must not poison the step: within each domain task
        # only the most recent run participates, so a failed attempt followed
        # by a successful retry (or vice versa) reports the latest state.
        # Untasked (legacy) runs keep their own slot.
        latest: dict[str, tuple[str, FreshnessReport]] = {}
        for r in reports:
            run = self.graph.runs.get(r.subject_id)
            started = run.started_at if run is not None else ""
            # Equal timestamps (imported/rounded) resolve to the later entry
            # in catalog order, which is deterministic for a given file.
            key = r.domain_task_id or f"run:{r.subject_id}"
            prev = latest.get(key)
            if prev is None or started >= prev[0]:
                latest[key] = (started, r)
        selected = [r for (_s, r) in latest.values()]
        selected = [r for (_created, r) in latest.values()]
        if any(r.state is FreshnessState.FAILED for r in selected):
            return FreshnessState.FAILED
        if any(r.state is FreshnessState.RUNNING for r in selected):
            return FreshnessState.RUNNING
        if any(r.state is FreshnessState.STALE for r in selected):
            return FreshnessState.STALE
        if any(r.state is FreshnessState.MISSING for r in selected):
            return FreshnessState.MISSING
        if all(r.state is FreshnessState.FRESH for r in selected):
            return FreshnessState.FRESH
        if any(r.state is FreshnessState.UNKNOWN for r in selected):
            return FreshnessState.UNKNOWN
        return FreshnessState.FRESH
