from __future__ import annotations

from paleo_workbench.project.models import ProjectDocument, QualityReport


def run_basic_qc(project: ProjectDocument, map_document_id: str) -> QualityReport:
    document = next(doc for doc in project.paleomap_documents if doc.id == map_document_id)
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
    report = QualityReport(
        linked_map_document_id=map_document_id,
        rules=["facies_polygons_present", "target_horizon_present"],
        issues=issues,
        status="pass" if not issues else "warning",
    )
    project.quality_reports.append(report)
    return report