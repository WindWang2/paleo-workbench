"""VersionSet finalize workflow (ISS-DOM-04): expert sign-off of map drafts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from paleo_workbench.project.models import (
    ContourDraft,
    PaleoMapDocument,
    ProjectDocument,
    VersionSet,
    VersionSnapshot,
    _now_iso,
)


def _fingerprint_map(doc: PaleoMapDocument) -> str:
    payload = {
        "id": doc.id,
        "horizon": doc.linked_target_horizon,
        "facies": doc.facies_polygons,
        "lines": doc.line_features,
        "wells": doc.well_overlays,
        "labels": doc.label_features,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _count_contour_segments(project: ProjectDocument, draft_id: str | None) -> int:
    if not draft_id:
        return 0
    for draft in project.contour_drafts:
        if draft.id == draft_id:
            return len(draft.segments)
    return 0


def _linked_qc_report(project: ProjectDocument, map_document_id: str):
    for report in reversed(project.quality_reports):
        if report.linked_map_document_id == map_document_id:
            return report
    return None


def _version_set_for_horizon(
    project: ProjectDocument,
    horizon: str,
    *,
    create: bool = True,
) -> VersionSet | None:
    for vs in project.version_sets:
        if vs.target_horizon == horizon and vs.status != "superseded":
            return vs
    if not create:
        return None
    vs = VersionSet(
        name=f"{horizon or '未指定层位'} 定稿版本集",
        target_horizon=horizon or "",
        status="open",
    )
    if project.compilation_runs:
        vs.linked_compilation_run_id = project.compilation_runs[-1].id
    project.version_sets.append(vs)
    return vs


def build_snapshot(
    project: ProjectDocument,
    map_doc: PaleoMapDocument,
    *,
    note: str = "",
    created_by: str = "",
) -> VersionSnapshot:
    draft_id = map_doc.linked_contour_draft_id
    qc = _linked_qc_report(project, map_doc.id)
    contour_n = _count_contour_segments(project, draft_id)
    # Factor tasks matching horizon
    factor_ids = [
        t.id
        for t in project.factor_map_tasks
        if not map_doc.linked_target_horizon
        or t.target_horizon == map_doc.linked_target_horizon
    ]
    return VersionSnapshot(
        map_document_id=map_doc.id,
        contour_draft_id=draft_id,
        quality_report_id=qc.id if qc else None,
        factor_task_ids=factor_ids,
        map_name=map_doc.name,
        target_horizon=map_doc.linked_target_horizon,
        line_feature_count=len(map_doc.line_features or []),
        facies_count=len(map_doc.facies_polygons or []),
        contour_segment_count=contour_n,
        qc_status=getattr(qc, "status", "") if qc else "unchecked",
        note=note,
        content_fingerprint=_fingerprint_map(map_doc),
        created_by=created_by,
    )


def finalize_map_version(
    project: ProjectDocument,
    map_document_id: str,
    *,
    note: str = "",
    operator: str = "expert",
    require_qc_pass: bool = False,
) -> VersionSet:
    """Create a VersionSnapshot and mark the VersionSet as final.

    - Supersedes previous final set for the same horizon (keeps history).
    - Marks linked ContourDraft as ``final``.
    - Bumps active compilation run toward ``export_ready``.
    """
    map_doc = next(
        (d for d in project.paleomap_documents if d.id == map_document_id),
        None,
    )
    if map_doc is None:
        raise ValueError(f"unknown map document: {map_document_id}")

    # Demo drafts must never be expert-finalized as production (H3): the
    # highest-trust step cannot launder heuristic geometry. A no-catalog
    # compile (untracked lineage) is not a demo draft — say so explicitly.
    vs_state = map_doc.view_state or {}
    if vs_state.get("is_demo_draft"):
        raise ValueError(
            "演示草稿图不能专家定稿为生产成果；请先通过生产编图路径生成正式图件"
        )
    if vs_state.get("production") is False:
        if vs_state.get("lineage") == "untracked":
            raise ValueError(
                "该成果的 lineage 未登记（无目录），不能专家定稿；请重新打开目录后通过生产编图生成"
            )
        raise ValueError("非生产成果不能专家定稿为正式图件")

    qc = _linked_qc_report(project, map_document_id)
    if require_qc_pass:
        if qc is None:
            raise ValueError("定稿前需先运行质检")
        if str(qc.status).lower() in {"error", "failed", "critical"}:
            raise ValueError(f"质检未通过（status={qc.status}），不能定稿")

    horizon = map_doc.linked_target_horizon or ""
    # Supersede prior finals for this horizon
    for vs in project.version_sets:
        if vs.target_horizon == horizon and vs.status == "final":
            vs.status = "superseded"
            vs.updated_at = _now_iso()

    vset = _version_set_for_horizon(project, horizon, create=True)
    assert vset is not None
    snap = build_snapshot(project, map_doc, note=note, created_by=operator)
    vset.snapshots.append(snap)
    vset.active_snapshot_id = snap.id
    vset.status = "final"
    vset.finalized_by = operator
    vset.finalized_at = _now_iso()
    vset.updated_at = _now_iso()

    # Contour draft → final
    if map_doc.linked_contour_draft_id:
        for draft in project.contour_drafts:
            if draft.id == map_doc.linked_contour_draft_id:
                draft.status = "final"
                draft.updated_at = _now_iso()
                break

    # Compilation run bookkeeping
    if project.compilation_runs:
        run = project.compilation_runs[-1]
        run.active_paleomap_document_id = map_doc.id
        if qc is not None:
            run.active_quality_report_id = qc.id
        if run.status in {"draft", "running", "review_required", "blocked"}:
            run.status = "export_ready"
        run.updated_at = _now_iso()

    return vset


def active_final_snapshot(
    project: ProjectDocument, *, target_horizon: str | None = None
) -> VersionSnapshot | None:
    """Return the active snapshot of the latest final VersionSet (optional horizon)."""
    candidates = [
        vs
        for vs in project.version_sets
        if vs.status == "final"
        and (not target_horizon or vs.target_horizon == target_horizon)
    ]
    if not candidates:
        return None
    vs = candidates[-1]
    if not vs.active_snapshot_id:
        return vs.snapshots[-1] if vs.snapshots else None
    for snap in vs.snapshots:
        if snap.id == vs.active_snapshot_id:
            return snap
    return vs.snapshots[-1] if vs.snapshots else None


def version_set_summary(project: ProjectDocument) -> dict[str, Any]:
    finals = [vs for vs in project.version_sets if vs.status == "final"]
    return {
        "version_set_count": len(project.version_sets),
        "final_count": len(finals),
        "open_count": sum(1 for vs in project.version_sets if vs.status == "open"),
        "latest_final_horizon": finals[-1].target_horizon if finals else "",
        "latest_final_at": finals[-1].finalized_at if finals else None,
    }
