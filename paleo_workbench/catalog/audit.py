"""Lightweight catalog audit (structural consistency checks; reports only).

Companion to :func:`paleo_workbench.catalog.queries.verify_integrity` (payload
hashing) and :func:`paleo_workbench.catalog.gc.plan_gc` (orphan files): this
module cross-checks the CANONICAL DOCUMENT against itself and against the
storage layout, and returns a structured :class:`AuditReport`. Detection
classes (goal: payload missing / broken lineage / dangling tags / invalid
current_version / orphan artifacts / path mismatch):

- ``payload_missing``        — recorded version whose payload file is gone
                               (existence stat only; hashing stays in
                               ``verify_integrity``)
- ``broken_lineage``         — ``parent_version_ids`` referencing unknown ids
- ``broken_run_link``        — run input/output ids referencing unknown
                               versions (may be purge-retained provenance,
                               hence informational)
- ``lineage_cycle``          — parent-chain cycles
- ``unprovenanced_version``  — non-RAW version with no producing run AND no
                               parents (cannot answer "where did this come
                               from")
- ``stale_running_run``      — run stuck in ``running`` status past the
                               staleness window (crashed producer)
- ``multi_claimed_output``   — one version claimed as output by several runs,
                               or the claimed run disagrees with
                               ``version.run_id``
- ``run_lineage_divergence`` — run input×output pair with no matching parent
                               edge on the output version (the version-graph
                               walk will not show that input)
- ``science_run_without_inputs`` — completed factor_map/prediction/
                               map_compile/qc run with zero input versions
                               (chain to RAW unrecorded at this step)
- ``external_path_missing``  — unmanaged version whose source file is gone
                               (existence stat only)
- ``invalid_metadata_value`` — governance field value outside its controlled
                               vocabulary (manual catalog.json edits)
- ``dangling_tag_ref``       — association-map entries whose owner id or tag id
                               is unknown
- ``unused_tag``             — tag entity with zero associations (informational)
- ``invalid_current_version``— ``current_version_id`` unknown / foreign /
                               trashed
- ``path_mismatch``          — managed version path violating the
                               ``{stage_dir}/{asset_id}/{version_id}/`` layout
                               (blob-backed and trashed layouts exempt)
- ``orphan_<kind>``          — files on disk without a catalog record
                               (reuses ``gc.plan_gc`` classifications)

Audit NEVER mutates the catalog (same policy as ``verify_integrity``: a
mismatch is reported, not auto-fixed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from paleo_workbench.catalog import gc as _gc
from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.storage import STAGE_DIRS, is_cas_path
from paleo_workbench.project.paths import artifact_dir_for

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

# A run still ``running`` after this window is almost certainly a crashed
# producer (the adapter books runs as running before executing and completes
# them in a finally-path; nothing legitimately runs this long).
STALE_RUN_AFTER_SECONDS = 24 * 3600


@dataclass
class AuditIssue:
    """One structural inconsistency found by :func:`audit_catalog`."""

    kind: str
    severity: str
    ref_id: str
    detail: str


@dataclass
class AuditReport:
    """Structured audit result (detection only; nothing is auto-repaired)."""

    issues: list[AuditIssue] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)

    def by_kind(self, kind: str) -> list[AuditIssue]:
        return [issue for issue in self.issues if issue.kind == kind]

    def by_severity(self, severity: str) -> list[AuditIssue]:
        return [issue for issue in self.issues if issue.severity == severity]

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.kind] = counts.get(issue.kind, 0) + 1
        return counts

    @property
    def statistics(self) -> dict[str, int]:
        """Aggregated statistics: entity counts, issues per severity and per kind."""
        stats: dict[str, int] = dict(self.checked)
        for severity in (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW):
            stats[f"issues_{severity}"] = len(self.by_severity(severity))
        for kind, count in self.counts_by_kind().items():
            stats[f"kind_{kind}"] = count
        return stats

    @property
    def ok(self) -> bool:
        """True when no high/medium issue was found (low = informational)."""
        return not self.by_severity(SEVERITY_HIGH) and not self.by_severity(
            SEVERITY_MEDIUM
        )


def audit_catalog(
    service, *, deep: bool = False, stale_run_after_seconds: int | None = None
) -> AuditReport:
    """Run all structural checks over the canonical document.

    ``deep=True`` additionally re-hashes every non-trashed managed payload
    (delegates to ``verify_integrity``) and reports ``integrity_mismatch``.
    Structural checks run under the service lock; payload stat/hash work runs
    outside it so a deep audit cannot block concurrent catalog writes.
    """
    report = AuditReport()
    with service._lock:
        document = service.document
        versions = list(document.versions)
        version_ids = {v.id for v in versions}
        assets = list(document.assets)
        asset_ids = {a.id for a in assets}
        report.checked = {
            "assets": len(assets),
            "versions": len(versions),
            "runs": len(document.runs),
            "tags": len(document.tags),
        }

        version_by_id = {v.id: v for v in versions}

        _check_current_versions(report, assets, version_by_id)
        _check_lineage(report, versions, version_ids)
        _check_run_links(report, document.runs, version_ids)
        _check_run_outputs(report, document.runs)
        _check_science_run_inputs(report, document.runs)
        _check_provenance(report, versions)
        _check_stale_runs(
            report, document.runs, version_ids,
            after_seconds=(
                STALE_RUN_AFTER_SECONDS
                if stale_run_after_seconds is None
                else stale_run_after_seconds
            ),
        )
        _check_output_claims(report, document.runs, version_by_id)
        _check_run_lineage_divergence(report, document.runs, version_by_id)
        _check_governance_metadata(report, assets)
        _check_tags(report, document, asset_ids, version_ids)
        _check_paths(report, service, versions)

    _check_payloads(report, service, versions, deep)

    return report


def _check_current_versions(
    report: AuditReport, assets, version_by_id: dict
) -> None:
    for asset in assets:
        current = asset.current_version_id
        if current is None:
            continue
        version = version_by_id.get(current)
        if version is None:
            report.issues.append(
                AuditIssue(
                    "invalid_current_version",
                    SEVERITY_HIGH,
                    asset.id,
                    f"current_version_id {current} does not exist",
                )
            )
        elif version.asset_id != asset.id:
            report.issues.append(
                AuditIssue(
                    "invalid_current_version",
                    SEVERITY_HIGH,
                    asset.id,
                    f"current_version_id {current} belongs to asset "
                    f"{version.asset_id}",
                )
            )
        elif version.trashed:
            report.issues.append(
                AuditIssue(
                    "invalid_current_version",
                    SEVERITY_MEDIUM,
                    asset.id,
                    f"current_version_id {current} is trashed",
                )
            )


def _check_lineage(report: AuditReport, versions, version_ids: set[str]) -> None:
    by_id = {v.id: v for v in versions}
    for version in versions:
        for parent_id in version.parent_version_ids:
            if parent_id not in version_ids:
                report.issues.append(
                    AuditIssue(
                        "broken_lineage",
                        SEVERITY_MEDIUM,
                        version.id,
                        f"parent_version_id {parent_id} does not exist",
                    )
                )
    # Cycle detection over ALL parent edges: iterative three-color DFS
    # (white=unvisited, gray=on stack, black=done). A back-edge to a gray
    # node closes a cycle regardless of which parent slot it came through.
    by_id = {v.id: v for v in versions}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {v.id: WHITE for v in versions}
    for start in versions:
        if color[start.id] != WHITE:
            continue
        stack: list[tuple[str, object]] = [(start.id, iter(start.parent_version_ids))]
        color[start.id] = GRAY
        while stack:
            node_id, parents_iter = stack[-1]
            next_id = next(parents_iter, None)
            if next_id is None:
                color[node_id] = BLACK
                stack.pop()
                continue
            if next_id not in by_id:
                continue  # dangling parent — reported above
            if color[next_id] == GRAY:
                report.issues.append(
                    AuditIssue(
                        "lineage_cycle",
                        SEVERITY_LOW,
                        start.id,
                        f"parent chain revisits {next_id}",
                    )
                )
                for node_id_on_stack, _ in stack:
                    color[node_id_on_stack] = BLACK
                break
            if color[next_id] == WHITE:
                color[next_id] = GRAY
                stack.append((next_id, iter(by_id[next_id].parent_version_ids)))


def _check_run_links(report: AuditReport, runs, version_ids: set[str]) -> None:
    for run in runs:
        for input_id in run.input_version_ids:
            if input_id not in version_ids:
                report.issues.append(
                    AuditIssue(
                        "broken_run_link",
                        SEVERITY_LOW,
                        run.id,
                        f"input_version_id {input_id} does not exist "
                        "(possibly purge-retained provenance)",
                    )
                )
        for output_id in run.output_version_ids:
            if output_id not in version_ids:
                report.issues.append(
                    AuditIssue(
                        "broken_run_link",
                        SEVERITY_LOW,
                        run.id,
                        f"output_version_id {output_id} does not exist "
                        "(possibly purge-retained provenance)",
                    )
                )


def _check_run_outputs(report: AuditReport, runs) -> None:
    """Completed producing runs with zero outputs (phantom provenance).

    Only operations that ALWAYS produce a version when they succeed are
    checked; delivery runs legitimately record a handoff without an output.
    """
    _ALWAYS_PRODUCING = {"materialize", "working_copy_commit"}
    for run in runs:
        if (
            run.operation in _ALWAYS_PRODUCING
            and run.status == "completed"
            and not run.output_version_ids
        ):
            report.issues.append(
                AuditIssue(
                    "orphan_completed_run",
                    SEVERITY_LOW,
                    run.id,
                    f"'{run.operation}' run completed with no output version",
                )
            )


def _check_science_run_inputs(report: AuditReport, runs) -> None:
    """Completed science runs that declare zero input versions.

    factor_map / prediction / map_compile / qc always consume catalog inputs
    in the production flow; a completed run with no inputs means the chain
    from this step back to RAW is unrecorded (the 血缘 walk stops here).
    Runs with status failed/cancelled are legitimately input-less retries;
    ``export`` is exempt (external figure exports may have no resolved
    sources).
    """
    _SCIENCE_OPS = {"factor_map", "prediction", "map_compile", "qc"}
    for run in runs:
        if run.operation not in _SCIENCE_OPS:
            continue
        if run.status not in ("completed", "complete"):
            continue
        if run.input_version_ids:
            continue
        report.issues.append(
            AuditIssue(
                "science_run_without_inputs",
                SEVERITY_MEDIUM,
                run.id,
                f"completed '{run.operation}' run records no input versions — "
                "its outputs cannot be traced to RAW",
            )
        )


def _check_provenance(report: AuditReport, versions) -> None:
    """Non-RAW versions that can never answer "which run/inputs produced me"."""
    for version in versions:
        if version.stage == DataStage.RAW or version.trashed:
            continue
        if version.run_id is None and not version.parent_version_ids:
            report.issues.append(
                AuditIssue(
                    "unprovenanced_version",
                    SEVERITY_MEDIUM,
                    version.id,
                    f"{version.stage.value} version has no producing run and "
                    "no parent versions",
                )
            )


def _check_stale_runs(
    report: AuditReport, runs, version_ids: set, *, after_seconds: int
) -> None:
    """Runs stuck in ``running`` past the staleness window.

    A dangling input/output id on a stale run is already reported by
    ``broken_run_link``; here the run itself never finished.
    """
    now = datetime.now(timezone.utc)
    for run in runs:
        if run.status != "running":
            continue
        started = _parse_iso(run.created_at)
        if started is None:
            continue
        age = (now - started).total_seconds()
        if age > after_seconds:
            report.issues.append(
                AuditIssue(
                    "stale_running_run",
                    SEVERITY_LOW,
                    run.id,
                    f"'{run.operation}' run still running after "
                    f"{int(age / 3600)}h",
                )
            )


def _parse_iso(raw: str | None):
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _check_output_claims(
    report: AuditReport, runs, version_by_id: dict
) -> None:
    """One output version claimed by several runs, or a claim that disagrees
    with the version's own ``run_id`` (its canonical producer)."""
    claims: dict[str, list] = {}
    for run in runs:
        for output_id in run.output_version_ids:
            if output_id in version_by_id:
                claims.setdefault(output_id, []).append(run)
    for output_id, claiming_runs in claims.items():
        version = version_by_id[output_id]
        if len(claiming_runs) > 1:
            names = ", ".join(f"{r.operation}:{r.id}" for r in claiming_runs)
            report.issues.append(
                AuditIssue(
                    "multi_claimed_output",
                    SEVERITY_LOW,
                    output_id,
                    f"version claimed as output by {len(claiming_runs)} runs ({names})",
                )
            )
        elif version.run_id is not None and version.run_id != claiming_runs[0].id:
            report.issues.append(
                AuditIssue(
                    "multi_claimed_output",
                    SEVERITY_LOW,
                    output_id,
                    f"version.run_id {version.run_id} != claiming run "
                    f"{claiming_runs[0].id} ({claiming_runs[0].operation})",
                )
            )


def _check_run_lineage_divergence(
    report: AuditReport, runs, version_by_id: dict
) -> None:
    """Run input→output pairs with no matching parent edge on the output.

    The adapter's convention mirrors run inputs into ``parent_version_ids``
    so the version-graph walk (UI 血缘) shows the same chain as the run
    record; a divergence means the walk silently hides a real input.
    Purged inputs are tolerated (purge-retained provenance).
    """
    for run in runs:
        if not run.input_version_ids or not run.output_version_ids:
            continue
        for output_id in run.output_version_ids:
            version = version_by_id.get(output_id)
            if version is None:
                continue
            live_inputs = [
                vid
                for vid in run.input_version_ids
                if vid in version_by_id
            ]
            if not live_inputs:
                continue
            if not set(live_inputs) & set(version.parent_version_ids):
                report.issues.append(
                    AuditIssue(
                        "run_lineage_divergence",
                        SEVERITY_LOW,
                        output_id,
                        f"run {run.id} ({run.operation}) consumed "
                        f"{len(live_inputs)} input(s) but the output version "
                        "has no matching parent edge",
                    )
                )


def _check_governance_metadata(report: AuditReport, assets) -> None:
    """Governance fields carrying values outside their vocabularies.

    Manual ``catalog.json`` edits bypass :meth:`update_asset_metadata`;
    the audit keeps the drift visible instead of silently breaking filters.
    """
    from paleo_workbench.catalog.governance import (
        GOVERNANCE_FIELDS,
        normalize_governance_value,
    )

    for asset in assets:
        for key, spec in GOVERNANCE_FIELDS.items():
            raw = asset.metadata.get(key)
            if raw in (None, "") or spec.vocabulary is None:
                continue
            try:
                normalize_governance_value(key, raw)
            except ValueError:
                report.issues.append(
                    AuditIssue(
                        "invalid_metadata_value",
                        SEVERITY_LOW,
                        asset.id,
                        f"{spec.label}({key})={raw!r} 不在受控词表 "
                        f"{('、'.join(spec.vocabulary))}",
                    )
                )


def _check_tags(report: AuditReport, document, asset_ids: set, version_ids: set) -> None:
    tag_ids = {t.id for t in document.tags}
    for asset_id, ids in document.asset_tags.items():
        if asset_id not in asset_ids:
            report.issues.append(
                AuditIssue(
                    "dangling_tag_ref",
                    SEVERITY_MEDIUM,
                    asset_id,
                    "asset_tags entry for unknown asset",
                )
            )
        for tag_id in ids:
            if tag_id not in tag_ids:
                report.issues.append(
                    AuditIssue(
                        "dangling_tag_ref",
                        SEVERITY_MEDIUM,
                        asset_id,
                        f"asset_tags references unknown tag {tag_id}",
                    )
                )
    for version_id, ids in document.version_tags.items():
        if version_id not in version_ids:
            report.issues.append(
                AuditIssue(
                    "dangling_tag_ref",
                    SEVERITY_MEDIUM,
                    version_id,
                    "version_tags entry for unknown version",
                )
            )
        for tag_id in ids:
            if tag_id not in tag_ids:
                report.issues.append(
                    AuditIssue(
                        "dangling_tag_ref",
                        SEVERITY_MEDIUM,
                        version_id,
                        f"version_tags references unknown tag {tag_id}",
                    )
                )
    used = set()
    for ids in document.asset_tags.values():
        used.update(ids)
    for ids in document.version_tags.values():
        used.update(ids)
    for tag in document.tags:
        if tag.id not in used:
            report.issues.append(
                AuditIssue(
                    "unused_tag",
                    SEVERITY_LOW,
                    tag.id,
                    f"tag '{tag.name}' has no associations",
                )
            )


def _check_paths(report: AuditReport, service, versions) -> None:
    artifacts_name = artifact_dir_for(service.project_path).name
    for version in versions:
        if not version.managed:
            if version.path and not version.path.startswith("/"):
                report.issues.append(
                    AuditIssue(
                        "path_mismatch",
                        SEVERITY_LOW,
                        version.id,
                        f"external version path is not absolute: {version.path}",
                    )
                )
            continue
        if is_cas_path(service.project_path, version.path):
            continue  # blob-backed layout is valid anywhere under blobs/
        posix = version.path or ""
        if version.trashed:
            expected = f"{artifacts_name}/trash/{version.id}/"
            trash = version.metadata.get("trash")
            original = trash.get("original_path") if isinstance(trash, dict) else None
            if posix.startswith(expected):
                continue  # payload already moved to trash
            if original and posix == original:
                # Documented crash window (tombstone saved before the payload
                # move — a consistent state restored by _probe_trash_payload).
                continue
            report.issues.append(
                AuditIssue(
                    "path_mismatch",
                    SEVERITY_MEDIUM,
                    version.id,
                    f"trashed managed payload not under {expected}: {posix}",
                )
            )
            continue
        expected = (
            f"{artifacts_name}/{STAGE_DIRS.get(version.stage, version.stage.value)}/"
            f"{version.asset_id}/{version.id}/"
        )
        if not posix.startswith(expected):
            report.issues.append(
                AuditIssue(
                    "path_mismatch",
                    SEVERITY_MEDIUM,
                    version.id,
                    f"managed payload not under {expected}: {posix}",
                )
            )


def _check_payloads(
    report: AuditReport, service, versions, deep: bool
) -> None:
    """Existence/orphan checks (stat only) + optional deep hashing.

    Runs OUTSIDE the service lock: plan_gc walks the artifacts tree and deep
    mode re-hashes payloads; holding the write lock through that would block
    every catalog write for the duration.
    """
    for version in versions:
        if not version.managed:
            # External files are outside catalog custody, but a missing
            # source still breaks every consumer — report it (stat only).
            if version.path and not Path(version.path).exists():
                report.issues.append(
                    AuditIssue(
                        "external_path_missing",
                        SEVERITY_MEDIUM,
                        version.id,
                        f"external payload not found: {version.path}",
                    )
                )
            continue
        payload = service.resolve_path(version)
        if not payload.exists():
            # A trashed version's payload may legitimately be missing (a
            # metadata-only tombstone — e.g. the file was already gone when
            # trashed); it is recoverable metadata, not active data loss.
            report.issues.append(
                AuditIssue(
                    "payload_missing",
                    SEVERITY_LOW if version.trashed else SEVERITY_HIGH,
                    version.id,
                    f"payload not found: {payload}",
                )
            )
    # Orphan files on disk (payload without a catalog record).
    gc_report = _gc.plan_gc(service)
    for item in gc_report.items:
        report.issues.append(
            AuditIssue(
                f"orphan_{item.kind}",
                SEVERITY_LOW,
                item.path.name,
                str(item.path),
            )
        )
    if deep:
        from paleo_workbench.catalog.queries import verify_integrity

        integrity = verify_integrity(service)
        for version_id, status in integrity.statuses.items():
            if status == "modified":
                report.issues.append(
                    AuditIssue(
                        "integrity_mismatch",
                        SEVERITY_HIGH,
                        version_id,
                        "recorded sha256 does not match payload content",
                    )
                )
