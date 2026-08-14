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

from paleo_workbench.catalog import gc as _gc
from paleo_workbench.catalog.storage import STAGE_DIRS, is_cas_path
from paleo_workbench.project.paths import artifact_dir_for

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"


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
    def ok(self) -> bool:
        """True when no high/medium issue was found (low = informational)."""
        return not self.by_severity(SEVERITY_HIGH) and not self.by_severity(
            SEVERITY_MEDIUM
        )


def audit_catalog(service, *, deep: bool = False) -> AuditReport:
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
            continue  # external files are outside catalog custody
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
