from __future__ import annotations

from collections import Counter
from typing import Any

from paleo_workbench.project.models import CompilationRun, ProjectDocument, WorkflowStep


def _active_quality_reports(project: ProjectDocument):
    """Lazy import — QC pulls geoviz topology helpers."""
    from paleo_workbench.workflow.qc import active_quality_reports

    return active_quality_reports(project)


STEP_ORDER = ["data_check", "factor_map", "prediction", "map_compile", "qc", "export"]
REQUIRED_RESOURCE_TYPES = ["well_log", "seismic", "horizon"]

# Step types whose catalog runs participate in derived freshness.
_FRESHNESS_STEP_OPS = {
    "factor_map": "factor_map",
    "prediction": "prediction",
    "map_compile": "map_compile",
    "qc": "qc",
    "export": "export",
}


def create_compilation_run(
    project: ProjectDocument,
    name: str,
    target_horizon: str,
    sequence_scheme: str,
) -> CompilationRun:
    project.stratigraphy.target_horizon = target_horizon
    project.stratigraphy.systems_tract_scheme = sequence_scheme
    run = CompilationRun(
        name=name,
        target_horizon=target_horizon,
        sequence_scheme_ref=sequence_scheme,
        workflow_steps=[WorkflowStep(step_type=step_type) for step_type in STEP_ORDER],
    )
    project.compilation_runs.append(run)
    return run


def _evidence_step_status(project: ProjectDocument, step_type: str) -> str:
    """Legacy evidence-only status: exists / complete / pending / warning / failed."""
    if step_type == "data_check":
        return "complete" if project.resources else "pending"
    if step_type == "factor_map":
        if any(getattr(task, "status", "") == "complete" for task in project.factor_map_tasks):
            return "complete"
        return "running" if project.factor_map_tasks else "pending"
    if step_type == "prediction":
        if any(getattr(task, "status", "") == "complete" for task in project.prediction_tasks):
            return "complete"
        return "running" if project.prediction_tasks else "pending"
    if step_type == "map_compile":
        return "complete" if project.paleomap_documents else "pending"
    if step_type == "qc":
        reports = _active_quality_reports(project)
        if not reports and not project.quality_reports:
            return "pending"
        # ``_status_from_issues`` can yield "error" (a critical issue present);
        # treat it as a failed gate alongside the legacy "failed" status so an
        # error-severity QC report does not fall through to "complete".
        if any(
            getattr(report, "status", "") in ("failed", "error")
            for report in reports
        ):
            return "failed"
        if any(getattr(report, "status", "") == "warning" for report in reports):
            return "warning"
        return "complete" if reports or project.quality_reports else "pending"
    if step_type == "export":
        return "complete" if project.export_artifacts else "pending"
    return "pending"


def _apply_freshness_overlay(
    project: ProjectDocument,
    step_type: str,
    evidence_status: str,
    *,
    catalog: Any | None = None,
    freshness_service: Any | None = None,
) -> str:
    """Overlay catalog-derived freshness onto evidence status.

    When products exist (complete) but are outdated relative to current
    selected upstream versions, surface ``stale`` (UI: 需更新). Never mutates
    DataVersion records. Degrades safely when catalog/lineage is absent.
    """
    if evidence_status not in {"complete", "warning"}:
        return evidence_status
    if step_type not in _FRESHNESS_STEP_OPS:
        return evidence_status
    try:
        if freshness_service is not None:
            svc = freshness_service
        else:
            from paleo_workbench.workflow.freshness import FreshnessService

            svc = FreshnessService.for_project(project, catalog=catalog)
        state = svc.step_freshness(step_type)
        if state is None:
            return evidence_status
        from paleo_workbench.workflow.freshness import FreshnessState

        if state is FreshnessState.STALE:
            return "stale"
        if state is FreshnessState.FAILED:
            return "failed"
        if state is FreshnessState.RUNNING:
            return "running"
        if state is FreshnessState.MISSING:
            return "warning"
        if state is FreshnessState.UNKNOWN:
            # Provenance unknown is not "已完成" (H1): surface the distinct
            # 状态未知 state instead of collapsing into evidence complete.
            return "warning"
        # FRESH → keep evidence complete
        return evidence_status
    except Exception:
        return evidence_status


def infer_workflow_step_status(
    project: ProjectDocument,
    step_type: str,
    *,
    catalog: Any | None = None,
    freshness_service: Any | None = None,
    apply_freshness: bool = True,
) -> str:
    """Derive a step status from project evidence + optional freshness.

    Evidence answers "does a product exist?". Freshness answers "is it current
    relative to selected upstream versions?". Combined statuses include
    ``complete`` (已完成) and ``stale`` (需更新).
    """
    evidence = _evidence_step_status(project, step_type)
    if not apply_freshness:
        return evidence
    return _apply_freshness_overlay(
        project,
        step_type,
        evidence,
        catalog=catalog,
        freshness_service=freshness_service,
    )


def home_workflow_steps(
    project: ProjectDocument,
    *,
    catalog: Any | None = None,
    apply_freshness: bool = True,
) -> list[WorkflowStep]:
    """Return ordered workflow steps for the home page, synced from evidence.

    When a compilation run exists, step statuses on that run are updated in place
    so save/load preserves progress. Without a run, ephemeral steps are built
    purely from project artifacts so the progress strip is never all-pending
    when the user already has data/maps/exports.

    Freshness (需更新) is derived at query time from catalog lineage; it is not
    persisted as a mutable flag on immutable DataVersions.
    """
    freshness_service = None
    if apply_freshness:
        try:
            from paleo_workbench.workflow.freshness import FreshnessService

            freshness_service = FreshnessService.for_project(project, catalog=catalog)
        except Exception:
            freshness_service = None

    inferred = {
        step_type: infer_workflow_step_status(
            project,
            step_type,
            catalog=catalog,
            freshness_service=freshness_service,
            apply_freshness=apply_freshness,
        )
        for step_type in STEP_ORDER
    }
    active_run = project.compilation_runs[-1] if project.compilation_runs else None
    if active_run is None:
        return [
            WorkflowStep(step_type=step_type, status=inferred[step_type])  # type: ignore[arg-type]
            for step_type in STEP_ORDER
        ]

    by_type = {step.step_type: step for step in active_run.workflow_steps}
    ordered: list[WorkflowStep] = []
    for step_type in STEP_ORDER:
        status = inferred[step_type]
        existing = by_type.get(step_type)
        if existing is None:
            existing = WorkflowStep(step_type=step_type, status=status)  # type: ignore[arg-type]
            active_run.workflow_steps.append(existing)
        else:
            # Evidence can promote progress; never erase a failed/warning flag
            # that was set more specifically than a plain pending/complete.
            # ``stale`` may replace complete when upstream selection advanced.
            if existing.status in {"failed", "warning"} and status in {
                "complete",
                "stale",
            }:
                pass
            else:
                existing.status = status  # type: ignore[assignment]
        ordered.append(existing)
    return ordered


def build_affected_products_plan(
    project: ProjectDocument,
    *,
    changed_version_ids: list[str] | None = None,
    catalog: Any | None = None,
):
    """Build minimal recompute plan for stale products (UI: 更新受影响成果)."""
    from paleo_workbench.workflow.freshness import FreshnessService
    from paleo_workbench.workflow.recompute_plan import build_recompute_plan

    svc = FreshnessService.for_project(project, catalog=catalog)
    return build_recompute_plan(svc, changed_version_ids=changed_version_ids)


def downstream_impact_for_version(
    version_id: str,
    *,
    project: ProjectDocument | None = None,
    catalog: Any | None = None,
) -> list[dict[str, Any]]:
    """Simple dependency panel payload: downstream runs + freshness labels."""
    from paleo_workbench.workflow.freshness import (
        FRESHNESS_UI_LABELS,
        FreshnessService,
    )
    from paleo_workbench.workflow.recompute_plan import OPERATION_LABELS_ZH

    svc = FreshnessService.for_project(project, catalog=catalog)
    rows: list[dict[str, Any]] = []
    for report in svc.downstream_impact([version_id]):
        rows.append(
            {
                "run_id": report.subject_id,
                "operation": report.operation,
                "label": OPERATION_LABELS_ZH.get(report.operation, report.operation),
                "domain_task_id": report.domain_task_id,
                "state": report.state.value,
                "state_label": FRESHNESS_UI_LABELS.get(
                    report.state.value, report.state.value
                ),
                "reasons": [r.to_dict() for r in report.reasons],
            }
        )
    return rows


def dashboard_state(project: ProjectDocument) -> dict[str, object]:
    active_run = project.compilation_runs[-1] if project.compilation_runs else None
    resource_counts = Counter(resource.type for resource in project.resources)
    available_counts = {
        resource_type: resource_counts.get(resource_type, 0)
        for resource_type in REQUIRED_RESOURCE_TYPES
    }
    missing_types = [
        resource_type
        for resource_type, count in available_counts.items()
        if count == 0
    ]
    steps = home_workflow_steps(project)
    complete_count = sum(1 for step in steps if step.status == "complete")
    return {
        "project_name": project.meta.name,
        "active_target_horizon": (
            active_run.target_horizon
            if active_run is not None
            else project.stratigraphy.target_horizon
        ),
        "sequence_scheme": (
            active_run.sequence_scheme_ref
            if active_run is not None
            else project.stratigraphy.systems_tract_scheme
        ),
        "workflow_status": active_run.status if active_run is not None else "draft",
        "resource_counts": dict(resource_counts),
        "resource_readiness": {
            "required_types": REQUIRED_RESOURCE_TYPES,
            "available_counts": available_counts,
            "missing_types": missing_types,
            "ready": not missing_types,
        },
        "factor_map_count": len(project.factor_map_tasks),
        "prediction_count": len(project.prediction_tasks),
        "map_document_count": len(project.paleomap_documents),
        "qc_issue_count": sum(
            len(report.issues) for report in _active_quality_reports(project)
        ),
        "export_count": len(project.export_artifacts),
        "workflow_complete_count": complete_count,
        "workflow_step_count": len(STEP_ORDER),
    }
