from __future__ import annotations

from collections import Counter

from paleo_workbench.project.models import CompilationRun, ProjectDocument, WorkflowStep
from paleo_workbench.workflow.qc import active_quality_reports


STEP_ORDER = ["data_check", "factor_map", "prediction", "map_compile", "qc", "export"]
REQUIRED_RESOURCE_TYPES = ["well_log", "seismic", "horizon"]


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


def infer_workflow_step_status(project: ProjectDocument, step_type: str) -> str:
    """Derive a step status from project evidence (not only manual CompilationRun edits).

    Keeps the home dashboard honest when users work through pages without an
    explicit run-state machine advancing steps.
    """
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
        reports = active_quality_reports(project)
        if not reports and not project.quality_reports:
            return "pending"
        if any(getattr(report, "status", "") == "failed" for report in reports):
            return "failed"
        if any(getattr(report, "status", "") == "warning" for report in reports):
            return "warning"
        return "complete" if reports or project.quality_reports else "pending"
    if step_type == "export":
        return "complete" if project.export_artifacts else "pending"
    return "pending"


def home_workflow_steps(project: ProjectDocument) -> list[WorkflowStep]:
    """Return ordered workflow steps for the home page, synced from evidence.

    When a compilation run exists, step statuses on that run are updated in place
    so save/load preserves progress. Without a run, ephemeral steps are built
    purely from project artifacts so the progress strip is never all-pending
    when the user already has data/maps/exports.
    """
    inferred = {
        step_type: infer_workflow_step_status(project, step_type) for step_type in STEP_ORDER
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
            if existing.status in {"failed", "warning"} and status == "complete":
                pass
            else:
                existing.status = status  # type: ignore[assignment]
        ordered.append(existing)
    return ordered


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
            len(report.issues) for report in active_quality_reports(project)
        ),
        "export_count": len(project.export_artifacts),
        "workflow_complete_count": complete_count,
        "workflow_step_count": len(STEP_ORDER),
    }
