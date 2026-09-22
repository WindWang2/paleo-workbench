"""Extended map QA rules (M12).

Complements ``workflow/qc.BASIC_QC_RULES`` (document content checks) with
production-grade, *locatable* checks for the compiled map chain:

* CRS discipline (D5): undeclared document/layer CRS, layer↔document CRS
  mismatch, per-feature CRS carried in properties vs document CRS;
* renderer/class agreement: categorized styles must cover the feature values
  actually present, so a legend can never silently diverge from the data;
* geometry sanity: features outside the declared extent (locatable via
  feature id + geometry);
* data health: empty well tables, factor tasks without persisted grids
  (stale), missing interpretation references, missing external files;
* fusion uncertainty: confidence statistics below an explicit threshold;
* export honesty (D2): an export report that fell back to the non-QGIS
  renderer surfaces as a QA warning.

Every issue is built by ``workflow.qc.make_issue`` and carries
``layer_id``/``feature_id``/``ref`` where the problem can be located — QA
answers "what is wrong and where", not just a score.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.workflow.qc import make_issue

__all__ = [
    "EXTENDED_QC_RULES",
    "CARTOGRAPHIC_QA_RULES",
    "cartographic_issues",
    "collect_extended_qc_issues",
    "extended_rule_coverage",
    "composition_qa_issues",
]

EXTENDED_QC_RULES: list[str] = [
    "crs_undeclared",
    "crs_mismatch",
    "class_renderer_mismatch",
    "out_of_bound_feature",
    "well_table_empty",
    "stale_inputs",
    "broken_external_reference",
    "low_confidence",
    "export_fallback",
    "composition_incomplete",
]

DEFAULT_CONFIDENCE_THRESHOLD = 0.5


def _layer_crs_issues(project: ProjectDocument, document: PaleoMapDocument) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    map_crs = str(getattr(document, "map_crs", "") or "")
    if not map_crs:
        issues.append(
            make_issue(
                rule="crs_undeclared",
                severity="warning",
                message="图面未声明 CRS——按契约这是合法但需显式确认的状态",
                ref=document.id,
            )
        )
    for layer in getattr(project, "user_vector_layers", None) or []:
        layer_crs = str(getattr(layer, "crs", "") or "")
        if not layer_crs:
            issues.append(
                make_issue(
                    rule="crs_undeclared",
                    severity="warning",
                    message=f"图层 {layer.name} 未声明 CRS",
                    feature_kind="layer",
                    ref=layer.id,
                )
            )
        elif map_crs and layer_crs != map_crs:
            issues.append(
                make_issue(
                    rule="crs_mismatch",
                    severity="error",
                    message=(
                        f"图层 {layer.name} CRS {layer_crs} 与图面 CRS {map_crs} 不一致"
                    ),
                    feature_kind="layer",
                    ref=layer.id,
                )
            )
    return issues


def _renderer_class_issues(project: ProjectDocument, document: PaleoMapDocument) -> list[dict[str, Any]]:
    """Categorized styles must cover the feature values present.

    Two surfaces: user-authored vector layers (style on the layer) and the
    facies polygon surface (``facies_style`` on the map document vs the
    ``facies_name`` values actually present). A style that misses a class
    means the legend cannot be complete — this is the renderer/legend
    agreement check.
    """
    issues: list[dict[str, Any]] = []

    def _check(style, features, *, field, label, ref, kind) -> None:
        if not isinstance(style, Mapping) or style.get("renderer") != "categorized":
            return
        field_name = str(style.get("field") or field)
        if not field_name:
            return
        raw_categories = style.get("categories") or []
        if isinstance(raw_categories, Mapping):
            categories = {str(key) for key in raw_categories}
        else:
            categories = {str(c[0]) for c in raw_categories if c}
        present: set[str] = set()
        for feature in features:
            props = _feature_field(feature, "properties") or {}
            value = props.get(field_name) if isinstance(props, Mapping) else None
            if value is not None:
                present.add(str(value))
        missing = sorted(present - categories)
        if missing:
            issues.append(
                make_issue(
                    rule="class_renderer_mismatch",
                    severity="warning",
                    message=(
                        f"{label}分类样式缺少字段 {field_name} 的值 "
                        f"{missing}（{len(missing)} 项无法按样式呈现）"
                    ),
                    feature_kind=kind,
                    ref=ref,
                    extra={"missing_classes": missing, "field": field_name},
                )
            )

    for layer in getattr(project, "user_vector_layers", None) or []:
        _check(
            getattr(layer, "style", None),
            [f for f in getattr(layer, "features", None) or []],
            field="",
            label=f"图层 {layer.name} ",
            ref=layer.id,
            kind="layer",
        )
    facies_features = [
        {"properties": (p or {}).get("properties") or {"facies_name": (p or {}).get("facies_name")}}
        for p in getattr(document, "facies_polygons", None) or []
        if isinstance(p, Mapping)
    ]
    _check(
        getattr(document, "facies_style", None),
        facies_features,
        field="facies_name",
        label="相带面 ",
        ref=document.id,
        kind="facies",
    )
    return issues


def _extent_issues(
    project: ProjectDocument,
    document: PaleoMapDocument,
    map_extent=None,
) -> list[dict[str, Any]]:
    """Features must sit inside the declared extent (locatable per feature).

    The extent comes explicitly from the caller, or from the document's
    ``view_state``; with neither, out-of-bound checks are impossible and are
    skipped rather than guessed.
    """
    issues: list[dict[str, Any]] = []
    extent = map_extent or (getattr(document, "view_state", None) or {}).get("extent")
    if not extent or len(extent) != 4:
        return issues
    xmin, ymin, xmax, ymax = (float(v) for v in extent)

    def _check_features(layer) -> None:
        for feature in getattr(layer, "features", None) or []:
            geometry = _feature_field(feature, "geometry") or {}
            coordinates = geometry.get("coordinates")
            flat = _flatten_coords(coordinates)
            for x, y in flat:
                if x < xmin or x > xmax or y < ymin or y > ymax:
                    issues.append(
                        make_issue(
                            rule="out_of_bound_feature",
                            severity="warning",
                            message=(
                                f"要素坐标 ({x:.2f}, {y:.2f}) 超出图面范围"
                            ),
                            feature_id=str(_feature_field(feature, "id") or ""),
                            feature_kind="layer",
                            ref=layer.id,
                            geometry=geometry,
                        )
                    )
                    break  # one issue per feature is enough to locate it

    for layer in getattr(project, "user_vector_layers", None) or []:
        _check_features(layer)
    for kind, payload in (
        ("facies", getattr(document, "facies_polygons", None) or []),
        ("line", getattr(document, "line_features", None) or []),
    ):
        for index, feature in enumerate(payload):
            geometry = (feature or {}).get("geometry") or {}
            coordinates = geometry.get("coordinates")
            if not coordinates:
                continue
            for x, y in _flatten_coords(coordinates):
                if x < xmin or x > xmax or y < ymin or y > ymax:
                    issues.append(
                        make_issue(
                            rule="out_of_bound_feature",
                            severity="warning",
                            message=(
                                f"要素坐标 ({x:.2f}, {y:.2f}) 超出图面范围"
                            ),
                            feature_id=str(
                                (feature or {}).get("feature_id")
                                or (feature or {}).get("id")
                                or f"{kind}_{index}"
                            ),
                            feature_kind=kind,
                            ref=document.id,
                            geometry=geometry,
                        )
                    )
                    break
    return issues


def _feature_field(feature: Any, name: str) -> Any:
    """Read a field from a dict OR a pydantic model feature uniformly."""
    if isinstance(feature, Mapping):
        return feature.get(name)
    return getattr(feature, name, None)


def _flatten_coords(coords: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    if (
        isinstance(coords, (list, tuple))
        and len(coords) >= 2
        and all(isinstance(v, (int, float)) for v in coords)
    ):
        return [(float(coords[0]), float(coords[1]))]
    if isinstance(coords, (list, tuple)):
        for item in coords:
            out.extend(_flatten_coords(item))
    return out


def _data_health_issues(project: ProjectDocument) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    tables = {str(t.id): t for t in getattr(project, "well_tables", None) or []}
    for task in getattr(project, "factor_map_tasks", None) or []:
        table_id = getattr(task, "well_table_id", None)
        if table_id:
            table = tables.get(str(table_id))
            if table is not None and not table.rows:
                issues.append(
                    make_issue(
                        rule="well_table_empty",
                        severity="warning",
                        message=f"因子 {task.factor_type} 引用的井表 {table_id} 无数据行",
                        ref=str(task.id),
                    )
                )
        has_grid = bool(getattr(task, "grid_artifact_version_id", None))
        if str(getattr(task, "status", "")) == "complete" and not has_grid:
            issues.append(
                make_issue(
                    rule="stale_inputs",
                    severity="warning",
                    message=(
                        f"因子任务 {task.name} 已完成但无持久化栅格版本（重算后未保存？）"
                    ),
                    ref=str(task.id),
                )
            )
    known_refs: set[str] = set()
    for kind in (
        "horizon_interpretations",
        "correlation_interpretations",
        "fault_interpretations",
    ):
        for ref in getattr(project, kind, None) or []:
            known_refs.add(str(ref.id))
    for record in getattr(project, "map_products", None) or []:
        for ref_id in getattr(record, "interpretation_refs", None) or []:
            if str(ref_id) not in known_refs:
                issues.append(
                    make_issue(
                        rule="broken_external_reference",
                        severity="error",
                        message=f"产品 {record.product_name} 引用的解释 {ref_id} 不存在",
                        feature_kind="interpretation",
                        ref=str(ref_id),
                        extra={"product": str(record.product_name)},
                    )
                )
    return issues


def _confidence_issues(
    confidence_stats: Mapping[str, Any] | None,
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    if not confidence_stats:
        return []
    issues: list[dict[str, Any]] = []
    minimum = confidence_stats.get("min")
    mean = confidence_stats.get("mean")
    if isinstance(minimum, (int, float)) and minimum < threshold:
        issues.append(
            make_issue(
                rule="low_confidence",
                severity="warning",
                message=(
                    f"融合最小置信度 {minimum:.2f} 低于阈值 {threshold:.2f}"
                ),
                extra={
                    "confidence_min": float(minimum),
                    "confidence_mean": mean,
                    "threshold": threshold,
                },
            )
        )
    return issues


def _export_issues(export_report: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not export_report:
        return []
    engine = str(export_report.get("engine") or "")
    if engine in ("fallback", "composer_fallback") or export_report.get("degraded"):
        reason = str(export_report.get("degraded_reason") or "未说明")
        return [
            make_issue(
                rule="export_fallback",
                severity="warning",
                message=f"成图导出使用了回退渲染器（{reason}）——与屏显可能存在符号差异",
                extra={"degraded_reason": reason},
            )
        ]
    return []


def collect_extended_qc_issues(
    project: ProjectDocument,
    document: PaleoMapDocument,
    *,
    map_extent=None,
    fusion_confidence: Mapping[str, Any] | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    export_report: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issues.extend(_layer_crs_issues(project, document))
    issues.extend(_renderer_class_issues(project, document))
    issues.extend(_extent_issues(project, document, map_extent))
    issues.extend(_data_health_issues(project))
    issues.extend(
        _confidence_issues(fusion_confidence, threshold=confidence_threshold)
    )
    issues.extend(_export_issues(export_report))
    return issues


def extended_rule_coverage(
    *,
    map_extent=None,
    fusion_confidence: Mapping[str, Any] | None = None,
    export_report: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """V8 M11: which extended rules actually EVALUATED vs were SKIPPED.

    Mirrors the silent-return conditions of the issue collectors: rules
    whose inputs are absent emit nothing and previously counted as an
    implicit pass. Coverage makes the skip visible with a reason.
    """
    coverage: dict[str, dict[str, Any]] = {}
    for rule in (
        "crs_undeclared",
        "crs_mismatch",
        "class_renderer_mismatch",
        "well_table_empty",
        "stale_inputs",
        "broken_external_reference",
    ):
        coverage[rule] = {"evaluated": True, "reason": ""}
    coverage["out_of_bound_feature"] = (
        {"evaluated": True, "reason": ""}
        if map_extent is not None
        else {"evaluated": False, "reason": "未提供图幅范围（map_extent）"}
    )
    coverage["low_confidence"] = (
        {"evaluated": True, "reason": ""}
        if fusion_confidence is not None
        else {"evaluated": False, "reason": "未提供融合置信度数据"}
    )
    coverage["export_fallback"] = (
        {"evaluated": True, "reason": ""}
        if export_report is not None
        else {"evaluated": False, "reason": "尚未执行导出（无导出报告）"}
    )
    return coverage


def composition_qa_issues(
    composition,
) -> list[dict[str, Any]]:
    """Composite-page QA: a composition must keep its core furniture.

    Missing MAIN_MAP/legend/scale bar are warnings (the page may be a work in
    progress); they locate at the element level so the panel can highlight
    the gap.
    """
    issues: list[dict[str, Any]] = []
    visible = [el for el in getattr(composition, "elements", []) or [] if el.visible]
    types = {el.element_type for el in visible}
    required = (
        ("main_map", "图面主图"),
        ("legend", "图例"),
        ("scale_bar", "比例尺"),
    )
    for type_value, label in required:
        if not any(str(t.value if hasattr(t, "value") else t) == type_value for t in types):
            issues.append(
                make_issue(
                    rule="composition_incomplete",
                    severity="warning",
                    message=f"合成页缺少{label}组件",
                    ref=str(getattr(composition, "id", "") or ""),
                )
            )
    return issues


def cartographic_issues(
    project,
    *,
    snapshot=None,
    capability: Mapping[str, Any] | None = None,
    stale_summary=None,
    catalog=None,
    confidence_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Thin delegate to the §14 cartographic rule set (V7).

    The logic lives in :mod:`paleo_workbench.mapping.cartographic_qa`
    (rule ids ``CARTOGRAPHIC_QA_RULES``); this wrapper keeps the QA-module
    family one-import for stage QA — the stage action
    (``ui/workstation/stage_actions.py`` ``run_qa``, main-agent owned) can
    call ``collect_extended_qc_issues(...)`` and this delegate side by side.
    Never duplicated here.
    """
    # Local import: mapping.cartographic_qa imports workflow.qc/crs_policy —
    # importing at module scope would be fine, but the lazy form keeps
    # test-collection of workflow-only suites independent of mapping deps.
    from paleo_workbench.mapping.cartographic_qa import (
        collect_cartographic_qa_issues,
    )

    return collect_cartographic_qa_issues(
        project,
        snapshot=snapshot,
        capability=capability,
        stale_summary=stale_summary,
        catalog=catalog,
        confidence_threshold=confidence_threshold,
    )
