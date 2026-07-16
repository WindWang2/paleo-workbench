from __future__ import annotations

from paleo_workbench.project.models import ProjectDocument, QualityReport, _now_iso


def run_basic_qc(
    project: ProjectDocument,
    map_document_id: str,
    *,
    bind_active_run: bool = True,
) -> QualityReport:
    """Run basic map QC and upsert by linked_map_document_id.

    Re-running QC for the same map replaces the previous report (stable id)
    so dashboards do not inflate issue counts. Optionally binds the active
    compilation run active_quality_report_id.
    """
    document = next(
        (doc for doc in project.paleomap_documents if doc.id == map_document_id),
        None,
    )
    if document is None:
        raise ValueError(f"unknown map document: {map_document_id}")

    issues: list[dict] = []
    if not document.facies_polygons:
        issues.append(
            {
                "rule": "facies_polygons_present",
                "severity": "warning",
                "message": "古地理图尚无相带多边形",
            }
        )
    if not document.linked_target_horizon:
        issues.append(
            {
                "rule": "target_horizon_present",
                "severity": "error",
                "message": "古地理图未关联目标层位",
            }
        )

    severities = {str(issue.get("severity", "")).lower() for issue in issues}
    if "error" in severities or "critical" in severities:
        status = "error"
    elif "warning" in severities:
        status = "warning"
    else:
        status = "pass"

    existing_idx: int | None = None
    previous_id: str | None = None
    for index, report in enumerate(project.quality_reports):
        if report.linked_map_document_id == map_document_id:
            existing_idx = index
            previous_id = report.id
            break

    kwargs: dict = {
        "linked_map_document_id": map_document_id,
        "rules": ["facies_polygons_present", "target_horizon_present"],
        "issues": issues,
        "status": status,
    }
    if previous_id is not None:
        kwargs["id"] = previous_id
    report = QualityReport(**kwargs)

    if existing_idx is not None:
        project.quality_reports[existing_idx] = report
    else:
        project.quality_reports.append(report)

    if bind_active_run and project.compilation_runs:
        run = project.compilation_runs[-1]
        run.active_quality_report_id = report.id
        run.active_paleomap_document_id = map_document_id
        run.updated_at = _now_iso()

    return report


def active_quality_reports(project: ProjectDocument) -> list[QualityReport]:
    """Reports that should count toward dashboard QC metrics."""
    run = project.compilation_runs[-1] if project.compilation_runs else None
    if run is not None and run.active_quality_report_id:
        for report in project.quality_reports:
            if report.id == run.active_quality_report_id:
                return [report]
    by_map: dict[str, QualityReport] = {}
    for report in project.quality_reports:
        by_map[report.linked_map_document_id] = report
    return list(by_map.values())
