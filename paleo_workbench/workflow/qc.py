"""Map quality checks for review / dashboard (ISS-QC-01)."""

from __future__ import annotations

from typing import Any

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, QualityReport, _now_iso

# Ordered rule keys stored on QualityReport.rules (engine keys, not Chinese chips).
BASIC_QC_RULES: list[str] = [
    "target_horizon_present",
    "facies_polygons_present",
    "facies_geometry_valid",
    "well_overlays_present",
    "contour_lines_present",
    "well_table_qc_clean",
]


def _facies_ring(poly: dict[str, Any]) -> list[list[float]] | None:
    coords = poly.get("coordinates")
    if isinstance(coords, list) and coords:
        # Editor ring [[x,y],...] or GeoJSON Polygon first ring
        first = coords[0]
        if isinstance(first, (int, float)):
            return None
        if isinstance(first, list) and first and isinstance(first[0], (int, float)):
            return coords  # type: ignore[return-value]
        if isinstance(first, list) and first and isinstance(first[0], list):
            return first  # type: ignore[return-value]
    geom = poly.get("geometry")
    if isinstance(geom, dict) and geom.get("type") == "Polygon":
        rings = geom.get("coordinates") or []
        if rings and isinstance(rings[0], list):
            return rings[0]  # type: ignore[return-value]
    return None


def _count_contour_lines(document: PaleoMapDocument) -> int:
    n = 0
    for feat in document.line_features or []:
        if not isinstance(feat, dict):
            continue
        role = str(feat.get("role") or "")
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
        prop_role = str(props.get("role") or props.get("constraint_role") or "")
        if role == "contour" or prop_role == "contour":
            n += 1
    return n


def _collect_issues(project: ProjectDocument, document: PaleoMapDocument) -> list[dict]:
    issues: list[dict] = []

    # 1) Target horizon
    if not (document.linked_target_horizon or "").strip():
        issues.append(
            {
                "rule": "target_horizon_present",
                "severity": "error",
                "message": "古地理图未关联目标层位",
            }
        )

    # 2) Facies presence
    if not document.facies_polygons:
        issues.append(
            {
                "rule": "facies_polygons_present",
                "severity": "warning",
                "message": "古地理图尚无相带多边形",
            }
        )
    else:
        # 3) Facies geometry validity
        from paleo_workbench.mapping.map_edit_api import validate_ring

        bad = 0
        for poly in document.facies_polygons:
            if not isinstance(poly, dict):
                bad += 1
                continue
            ring = _facies_ring(poly)
            if ring is None or len(ring) < 3:
                bad += 1
                continue
            ring_issues = validate_ring(ring)
            if any(i.get("code") == "self_intersection" for i in ring_issues):
                bad += 1
        if bad:
            issues.append(
                {
                    "rule": "facies_geometry_valid",
                    "severity": "error",
                    "message": f"{bad} 个相带多边形几何无效（自交或顶点数不足）",
                    "count": bad,
                }
            )

    # 4) Well overlays
    if not document.well_overlays:
        issues.append(
            {
                "rule": "well_overlays_present",
                "severity": "warning",
                "message": "图面无井位叠加，编图证据不足",
            }
        )

    # 5) Contour isolines (from ContourDraft push or manual)
    contour_n = _count_contour_lines(document)
    if contour_n == 0:
        issues.append(
            {
                "rule": "contour_lines_present",
                "severity": "warning",
                "message": "尚无等值线（ContourDraft）线要素，建议从制备生成初稿",
            }
        )

    # 6) WellTable QC cleanliness for same horizon (if any table exists)
    horizon = (document.linked_target_horizon or "").strip()
    flagged = 0
    for table in project.well_tables or []:
        table_h = (table.target_horizon or "").strip()
        if horizon and table_h and table_h != horizon:
            continue
        for row in table.rows or []:
            if getattr(row, "qc_flag", "ok") not in {"ok", ""}:
                flagged += 1
    if flagged:
        issues.append(
            {
                "rule": "well_table_qc_clean",
                "severity": "warning",
                "message": f"井点表存在 {flagged} 个异常/无效样本（MAD 或砂地比）",
                "count": flagged,
            }
        )

    return issues


def _status_from_issues(issues: list[dict]) -> str:
    severities = {str(issue.get("severity", "")).lower() for issue in issues}
    if "error" in severities or "critical" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    return "pass"


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

    Rules (ISS-QC-01): horizon, facies presence/geometry, wells, contour lines,
    well-table MAD/ratio flags for the map horizon.
    """
    document = next(
        (doc for doc in project.paleomap_documents if doc.id == map_document_id),
        None,
    )
    if document is None:
        raise ValueError(f"unknown map document: {map_document_id}")

    issues = _collect_issues(project, document)
    status = _status_from_issues(issues)

    existing_idx: int | None = None
    previous_id: str | None = None
    for index, report in enumerate(project.quality_reports):
        if report.linked_map_document_id == map_document_id:
            existing_idx = index
            previous_id = report.id
            break

    kwargs: dict = {
        "linked_map_document_id": map_document_id,
        "rules": list(BASIC_QC_RULES),
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
