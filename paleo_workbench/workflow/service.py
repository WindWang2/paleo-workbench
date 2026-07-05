from __future__ import annotations

from collections import Counter

from paleo_workbench.project.models import CompilationRun, ProjectDocument, WorkflowStep


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
        "qc_issue_count": sum(len(report.issues) for report in project.quality_reports),
        "export_count": len(project.export_artifacts),
    }
