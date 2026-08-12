"""Map quality checks for review / dashboard (ISS-QC-01 / ISS-QC-02).

Issues may carry spatial fields for IssueLayer locate:
  feature_id, feature_kind, geometry (GeoJSON), centroid [x,y], ref
"""

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


def make_issue(
    *,
    rule: str,
    severity: str,
    message: str,
    feature_id: str | None = None,
    feature_kind: str | None = None,
    geometry: dict[str, Any] | None = None,
    ref: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a QC issue dict with optional spatial IssueLayer fields."""
    issue: dict[str, Any] = {
        "rule": rule,
        "severity": severity,
        "message": message,
    }
    if feature_id is not None:
        issue["feature_id"] = str(feature_id)
    if feature_kind is not None:
        issue["feature_kind"] = str(feature_kind)
    if ref is not None:
        issue["ref"] = str(ref)
    if geometry is not None:
        issue["geometry"] = geometry
        centroid = _geometry_centroid(geometry)
        if centroid is not None:
            issue["centroid"] = centroid
    if extra:
        issue.update(extra)
    return issue


def _geometry_centroid(geometry: dict[str, Any]) -> list[float] | None:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    try:
        if gtype == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            return [float(coords[0]), float(coords[1])]
        if gtype == "LineString" and isinstance(coords, list) and coords:
            xs = [float(p[0]) for p in coords if isinstance(p, (list, tuple)) and len(p) >= 2]
            ys = [float(p[1]) for p in coords if isinstance(p, (list, tuple)) and len(p) >= 2]
            if xs:
                return [sum(xs) / len(xs), sum(ys) / len(ys)]
        if gtype == "Polygon" and isinstance(coords, list) and coords:
            ring = coords[0]
            xs = [float(p[0]) for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
            ys = [float(p[1]) for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
            # Drop closing duplicate for mean
            if len(xs) >= 2 and xs[0] == xs[-1] and ys[0] == ys[-1]:
                xs, ys = xs[:-1], ys[:-1]
            if xs:
                return [sum(xs) / len(xs), sum(ys) / len(ys)]
    except (TypeError, ValueError, IndexError):
        return None
    return None


def _facies_ring(poly: dict[str, Any]) -> list[list[float]] | None:
    coords = poly.get("coordinates")
    if isinstance(coords, list) and coords:
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


def _ring_to_polygon_geometry(ring: list[list[float]]) -> dict[str, Any]:
    coords = [[float(p[0]), float(p[1])] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    if coords and (coords[0][0] != coords[-1][0] or coords[0][1] != coords[-1][1]):
        coords = coords + [coords[0]]
    return {"type": "Polygon", "coordinates": [coords]}


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
    map_ref = f"map:{document.id}"

    # 1) Target horizon (map-level, no geometry)
    if not (document.linked_target_horizon or "").strip():
        issues.append(
            make_issue(
                rule="target_horizon_present",
                severity="error",
                message="古地理图未关联目标层位",
                feature_kind="map",
                feature_id=document.id,
                ref=map_ref,
            )
        )

    # 2–3) Facies presence + per-polygon geometry
    if not document.facies_polygons:
        issues.append(
            make_issue(
                rule="facies_polygons_present",
                severity="warning",
                message="古地理图尚无相带多边形",
                feature_kind="map",
                feature_id=document.id,
                ref=map_ref,
            )
        )
    else:
        for poly in document.facies_polygons:
            if not isinstance(poly, dict):
                issues.append(
                    make_issue(
                        rule="facies_geometry_valid",
                        severity="error",
                        message="相带记录格式无效",
                        feature_kind="facies",
                        ref=map_ref,
                    )
                )
                continue
            fid = str(poly.get("id") or poly.get("name") or "")
            ring = _facies_ring(poly)
            if ring is None or len(ring) < 3:
                issues.append(
                    make_issue(
                        rule="facies_geometry_valid",
                        severity="error",
                        message=f"相带 {fid or '?'} 顶点不足或缺少坐标",
                        feature_id=fid or None,
                        feature_kind="facies",
                        ref=f"{map_ref}/facies/{fid}" if fid else map_ref,
                    )
                )
                continue
            from geoviz import validate_ring

            ring_issues = validate_ring(ring)
            if any(i.get("code") == "self_intersection" for i in ring_issues):
                geom = _ring_to_polygon_geometry(ring)
                issues.append(
                    make_issue(
                        rule="facies_geometry_valid",
                        severity="error",
                        message=f"相带 {fid or '?'} 自相交",
                        feature_id=fid or None,
                        feature_kind="facies",
                        geometry=geom,
                        ref=f"{map_ref}/facies/{fid}" if fid else map_ref,
                        extra={"code": "self_intersection"},
                    )
                )

    # 4) Well overlays
    if not document.well_overlays:
        issues.append(
            make_issue(
                rule="well_overlays_present",
                severity="warning",
                message="图面无井位叠加，编图证据不足",
                feature_kind="map",
                feature_id=document.id,
                ref=map_ref,
            )
        )

    # 5) Contour isolines
    contour_n = _count_contour_lines(document)
    if contour_n == 0:
        issues.append(
            make_issue(
                rule="contour_lines_present",
                severity="warning",
                message="尚无等值线（ContourDraft）线要素，建议从制备生成初稿",
                feature_kind="map",
                feature_id=document.id,
                ref=map_ref,
            )
        )

    # 6) WellTable QC: one spatial issue per flagged sample
    horizon = (document.linked_target_horizon or "").strip()
    for table in project.well_tables or []:
        table_h = (table.target_horizon or "").strip()
        if horizon and table_h and table_h != horizon:
            continue
        for row in table.rows or []:
            flag = getattr(row, "qc_flag", "ok")
            if flag in {"ok", ""}:
                continue
            wid = str(getattr(row, "well_id", "") or getattr(row, "name", "") or "")
            try:
                x, y = float(row.x), float(row.y)
                geom: dict[str, Any] | None = {
                    "type": "Point",
                    "coordinates": [x, y],
                }
            except (TypeError, ValueError):
                geom = None
            issues.append(
                make_issue(
                    rule="well_table_qc_clean",
                    severity="warning",
                    message=f"井点 {getattr(row, 'name', wid) or wid} 质控={flag}",
                    feature_id=wid or None,
                    feature_kind="well",
                    geometry=geom,
                    ref=f"well_table:{table.id}/{wid}" if wid else f"well_table:{table.id}",
                    extra={"qc_flag": flag, "qc_z_star": getattr(row, "qc_z_star", None)},
                )
            )

    return issues


def spatial_issues(issues: list[dict] | None) -> list[dict]:
    """Issues that can be located on a map (have geometry or centroid)."""
    out: list[dict] = []
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        if issue.get("geometry") or issue.get("centroid"):
            out.append(issue)
    return out


def issue_layer_geojson(
    report: QualityReport | None,
    *,
    map_document_id: str | None = None,
) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection from spatially located QC issues."""
    features: list[dict[str, Any]] = []
    if report is None:
        return {"type": "FeatureCollection", "features": features}
    for issue in spatial_issues(report.issues):
        geom = issue.get("geometry")
        if not isinstance(geom, dict):
            continue
        props = {
            "rule": issue.get("rule"),
            "severity": issue.get("severity"),
            "message": issue.get("message"),
            "feature_id": issue.get("feature_id"),
            "feature_kind": issue.get("feature_kind"),
            "ref": issue.get("ref"),
            "map_document_id": map_document_id or report.linked_map_document_id,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": props,
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "report_id": report.id,
            "linked_map_document_id": report.linked_map_document_id,
            "status": report.status,
        },
    }


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
    well-table MAD/ratio flags. Spatial issues include geometry/ref (ISS-QC-02).
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
