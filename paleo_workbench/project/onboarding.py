"""新建工程向导纯逻辑层 — 零 Qt，可在后台线程整体调用。

Onboarding pure logic (thread-safe, no Qt): import → stage/bind →
convex hull boundary → well-location map sync → report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paleo_workbench.project.models import ProjectDocument


@dataclass
class OnboardingResult:
    document: ProjectDocument
    report: dict[str, Any]
    imported: int


# ---------------------------------------------------------------------------
# 中文类型标签 — 复用 io_registry 的 TYPE_LABELS（非 Qt），避免引入 UI 依赖
# ---------------------------------------------------------------------------

try:
    from paleo_workbench.resources.io_registry import TYPE_LABELS as _TYPE_LABELS
except Exception:  # pragma: no cover
    _TYPE_LABELS: dict[str, str] = {}


def _label_for_type(rt: str) -> str:
    return _TYPE_LABELS.get(rt, rt)


# ---------------------------------------------------------------------------
# Convex hull — monotonic chain 纯 Python 实现，零依赖
# ---------------------------------------------------------------------------


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def boundary_from_wells(doc: ProjectDocument) -> list[list[float]]:
    """计算井位凸包并在条件满足时回填 WorkArea 边界。

    Convex hull via monotonic chain.  Collects wells with coordinates
    (project_x/y preferred, surface_x/y fallback).  Returns a closed ring
    (first == last) when >=3 non-collinear points exist, otherwise ``[]``.
    When ``doc.workarea`` exists and its boundary is empty, fills it with
    the computed ring and sets ``boundary_crs`` to the project CRS.
    """
    points: list[tuple[float, float]] = []
    for well in getattr(doc, "wells", None) or []:
        # Regional/reference wells provide context but cannot define or expand
        # the target WorkArea boundary.
        if getattr(well, "spatial_scope", "workarea") == "reference":
            continue
        x = getattr(well, "project_x", None)
        y = getattr(well, "project_y", None)
        if x is None or y is None:
            x = getattr(well, "surface_x", None)
            y = getattr(well, "surface_y", None)
        if x is None or y is None:
            continue
        try:
            points.append((float(x), float(y)))
        except (TypeError, ValueError):
            continue

    # Deduplicate while preserving order not needed for hull; use set for correctness
    unique = sorted(set(points))
    if len(unique) < 3:
        return []

    # Deduplicate already; but set already
    pts = unique
    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    # Concatenate without duplicate endpoints
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return []

    ring: list[list[float]] = [[float(x), float(y)] for x, y in hull]
    ring.append([float(hull[0][0]), float(hull[0][1])])

    # 回填 workarea 边界（仅当为空时）
    workarea = getattr(doc, "workarea", None)
    if workarea is not None:
        try:
            existing = getattr(workarea, "boundary", None)
        except Exception:
            existing = None
        if not existing:
            workarea.boundary = [list(pt) for pt in ring]
            # 使用项目的 project_crs 作为边界 CRS
            try:
                crs = str(getattr(getattr(doc, "coordinate", None), "project_crs", "") or "")
            except Exception:
                crs = ""
            workarea.boundary_crs = crs

    return ring


def build_onboarding_report(
    doc,
    import_report,
    binding_report,
    *,
    source_folder: str,
    intermediate_folder: str,
) -> dict[str, Any]:
    """构建向导盘点报告 dict（Build onboarding summary report）。

    Keys: generated_at, source_folder, intermediate_folder, imported_count,
    by_type, skipped, warnings, wells_total, wells_with_coords, surveys,
    entities, ambiguous, issues(≤20), extent.
    """
    generated_at = datetime.now(timezone.utc).isoformat()

    imported_count = 0
    try:
        imported_count = int(getattr(import_report, "added_count", len(getattr(import_report, "added", []) or [])))
    except Exception:
        try:
            imported_count = len(getattr(import_report, "added", []) or [])
        except Exception:
            imported_count = 0

    # by_type 中文标签映射
    by_type: dict[str, int] = {}
    try:
        raw_by_type = getattr(import_report, "by_type", None)
        if callable(raw_by_type):
            raw_by_type = raw_by_type()
        if isinstance(raw_by_type, dict):
            source_bt = raw_by_type
        else:
            # property
            source_bt = dict(getattr(import_report, "by_type", {}) or {})
    except Exception:
        source_bt = {}
    # Fallback: if by_type empty but added exists, count manually
    if not source_bt:
        try:
            from collections import Counter

            source_bt = dict(Counter(getattr(r, "type", "unknown") for r in getattr(import_report, "added", []) or []))
        except Exception:
            source_bt = {}
    for k, v in source_bt.items():
        label = _label_for_type(str(k))
        by_type[label] = by_type.get(label, 0) + int(v)

    skipped = 0
    try:
        skipped = int(getattr(import_report, "skipped_count", 0))
        if not skipped:
            # sum lenses
            skipped = len(getattr(import_report, "skipped_path", []) or []) + len(
                getattr(import_report, "skipped_checksum", []) or []
            ) + len(getattr(import_report, "skipped_filter", []) or [])
    except Exception:
        skipped = 0

    warnings = list(getattr(import_report, "warnings", []) or [])

    wells = getattr(doc, "wells", None) or []
    wells_total = len(wells)
    wells_with_coords = 0
    xs: list[float] = []
    ys: list[float] = []
    for w in wells:
        x = getattr(w, "project_x", None)
        y = getattr(w, "project_y", None)
        if x is None or y is None:
            x = getattr(w, "surface_x", None)
            y = getattr(w, "surface_y", None)
        if x is not None and y is not None:
            wells_with_coords += 1
            try:
                xs.append(float(x))
                ys.append(float(y))
            except (TypeError, ValueError):
                pass

    surveys = len(getattr(doc, "seismic_surveys", None) or [])
    # entities 包含地质与辅助实体
    geo = getattr(doc, "geological_entities", None) or []
    aux = getattr(doc, "auxiliary_entities", None) or []
    entities = len(geo) + len(aux)
    # 若 doc 尚无实体但 binding 有计数，回退到 binding 值
    if entities == 0:
        try:
            entities = int(getattr(binding_report, "entities_created", 0) or 0)
        except Exception:
            pass

    ambiguous = 0
    try:
        ambiguous = int(getattr(binding_report, "ambiguous_assets", 0) or 0)
    except Exception:
        ambiguous = 0

    issues_all = list(getattr(binding_report, "issues", []) or [])
    issues = issues_all[:20]

    extent: list[float] | None = None
    if xs and ys:
        extent = [float(min(xs)), float(max(xs)), float(min(ys)), float(max(ys))]

    return {
        "generated_at": generated_at,
        "source_folder": str(source_folder),
        "intermediate_folder": str(intermediate_folder),
        "imported_count": int(imported_count),
        "by_type": dict(by_type),
        "skipped": int(skipped),
        "warnings": list(warnings),
        "wells_total": int(wells_total),
        "wells_with_coords": int(wells_with_coords),
        "surveys": int(surveys),
        "entities": int(entities),
        "ambiguous": int(ambiguous),
        "issues": list(issues),
        "extent": extent,
    }


def analyze_data_folder(
    root: Path | str,
    *,
    project_name: str,
    engine=None,
) -> OnboardingResult:
    """端到端分析数据文件夹并构建工程文档（Analyze folder → document + report）。

    Steps: ProjectDocument.new → ensure_workarea → import_folder →
    resources.extend → stage_resources → bind_staged → boundary_from_wells →
    sync_well_location_map → build_onboarding_report.
    Pure logic, no Qt, safe to run in a background thread.
    """
    from paleo_workbench.resources.import_service import import_folder
    from paleo_workbench.catalog.domain_binding import bind_staged, stage_resources

    root_path = Path(root)
    doc = ProjectDocument.new(project_name)

    # 确保 workarea 存在（复用 domain.ensure_workarea）
    try:
        from paleo_workbench.project.domain import ensure_workarea

        ensure_workarea(doc)
    except Exception:
        pass

    report_import = import_folder(root_path, existing=(), project_path=None)
    # 资源入库
    try:
        doc.resources.extend(report_import.added)
    except Exception:
        doc.resources = list(report_import.added)

    # 解析与绑定
    def _path_resolver(p: str) -> Path:
        # 导入路径此时为绝对路径，直接包装
        raw = Path(p)
        return raw

    staged = stage_resources(doc, report_import.added, path_resolver=_path_resolver, engine=engine)
    binding = bind_staged(doc, staged, asset_id_by_legacy={})

    # 工区边界凸包
    boundary_from_wells(doc)

    # 落井位矢量文档
    try:
        from paleo_workbench.project.well_location_map import sync_well_location_map

        sync_well_location_map(doc)
    except Exception:
        pass

    report = build_onboarding_report(
        doc,
        report_import,
        binding,
        source_folder=str(root_path),
        intermediate_folder=str(root_path),
    )
    doc.onboarding_report = report
    return OnboardingResult(document=doc, report=report, imported=len(report_import.added))
