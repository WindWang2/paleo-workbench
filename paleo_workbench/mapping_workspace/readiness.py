"""阶段就绪度（Stage Readiness）。

不是硬 wizard —— 就绪度只提示，不阻止切阶段（V5 §18）。检查项：

* 可解释：每项有 status(ok/warning/error/info) + 中文说明；
* 可点击定位：``target`` 携带定位引用（layer_id / task_id / group_id），
  UI 侧点击后选择对应对象。

全部为纯领域函数：输入是 ProjectDocument（duck-typed）与可选的
freshness 摘要（:mod:`mapping_workspace.dependencies` 的产物）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.project.models import FACTOR_TASK_STATUS_COMPLETE


class ReadinessItemStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


class StageReadinessStatus(str, Enum):
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True)
class ReadinessItem:
    """一条就绪度检查结果。"""

    check_id: str
    status: ReadinessItemStatus
    title: str
    detail: str = ""
    #: 定位引用（UI 点击跳转）：layer_id / group_id / task_id 等。
    target: str = ""

    @property
    def sort_weight(self) -> int:
        return {"error": 0, "warning": 1, "info": 2, "ok": 3}[self.status.value]


@dataclass(frozen=True)
class StageReadiness:
    """一个阶段的就绪度汇总。"""

    stage: MappingStage
    items: tuple[ReadinessItem, ...] = ()

    @property
    def status(self) -> StageReadinessStatus:
        has_error = any(item.status == ReadinessItemStatus.ERROR for item in self.items)
        has_warning = any(
            item.status == ReadinessItemStatus.WARNING for item in self.items
        )
        if has_error:
            return StageReadinessStatus.NOT_READY
        if has_warning:
            return StageReadinessStatus.READY_WITH_WARNINGS
        return StageReadinessStatus.READY

    @property
    def label(self) -> str:
        return {
            StageReadinessStatus.READY: "就绪",
            StageReadinessStatus.READY_WITH_WARNINGS: "就绪（有提醒）",
            StageReadinessStatus.NOT_READY: "未就绪",
        }[self.status]

    def warnings(self) -> tuple[ReadinessItem, ...]:
        return tuple(
            item for item in self.items
            if item.status in (ReadinessItemStatus.WARNING, ReadinessItemStatus.ERROR)
        )

    def sorted_items(self) -> tuple[ReadinessItem, ...]:
        return tuple(sorted(self.items, key=lambda item: item.sort_weight))


# ---------------------------------------------------------------------------
# 检查实现（按 StageProfile.readiness_checks 的 id 对应）
# ---------------------------------------------------------------------------

def _iter_polygon_features(document, polygons: list) -> int:
    count = 0
    for polygon in polygons or ():
        geometry = polygon.get("geometry") if isinstance(polygon, dict) else None
        if isinstance(geometry, dict) and geometry.get("type") in (
            "Polygon", "MultiPolygon"
        ):
            count += 1
    return count


def check_initial_facies_present(document) -> ReadinessItem:
    """✓ 初始相图存在：PaleoMapDocument 的 facies_polygons 非空或 RAW 引用。"""
    documents = getattr(document, "paleomap_documents", None) or []
    has = any(_iter_polygon_features(doc, getattr(doc, "facies_polygons", None))
              for doc in documents)
    if has:
        return ReadinessItem(
            "initial_facies_present", ReadinessItemStatus.OK, "初始相图存在",
            f"{len(documents)} 个相图文档含相面多边形")
    return ReadinessItem(
        "initial_facies_present", ReadinessItemStatus.ERROR, "初始相图缺失",
        "未找到初始沉积相图——导入或生成初始相图后才能进行校正")


def check_initial_facies_crs(document) -> ReadinessItem:
    crs = str(getattr(getattr(document, "coordinate", None), "project_crs", "") or "")
    if crs:
        return ReadinessItem(
            "initial_facies_crs", ReadinessItemStatus.OK, "相图 CRS 有效", crs)
    return ReadinessItem(
        "initial_facies_crs", ReadinessItemStatus.ERROR, "工程 CRS 未设置",
        "工程未配置坐标系，叠加与编辑无法进行")


def _geometry_issue_count(features: list) -> int:
    """Real geometry validity (facade: QGIS engine when built, shapely
    otherwise) — the former non-empty check let invalid bowtie/unclosed
    rings pass readiness (v7 P2-16)."""
    from paleo_workbench.mapping.geometry_operations import validate

    issues = 0
    for feature in features or ():
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict):
            issues += 1
            continue
        coordinates = geometry.get("coordinates")
        if not coordinates:
            issues += 1
            continue
        try:
            if not validate(geometry).valid:
                issues += 1
        except Exception:
            issues += 1  # unvalidatable geometry is an issue, never a pass
    return issues


def check_initial_facies_geometry(document) -> ReadinessItem:
    documents = getattr(document, "paleomap_documents", None) or []
    if not any(getattr(doc, "facies_polygons", None) for doc in documents):
        return ReadinessItem(
            "initial_facies_geometry", ReadinessItemStatus.INFO,
            "相图几何检查待相图加载")
    total_issues = sum(
        _geometry_issue_count(getattr(doc, "facies_polygons", None) or [])
        for doc in documents
    )
    if total_issues == 0:
        return ReadinessItem(
            "initial_facies_geometry", ReadinessItemStatus.OK, "相图几何有效")
    return ReadinessItem(
        "initial_facies_geometry", ReadinessItemStatus.WARNING,
        f"{total_issues} 个相面几何异常", "空/缺失几何的相面将被跳过",
        target="phase1.initial_facies")


def check_well_prediction_linked(document) -> ReadinessItem:
    tasks = [
        task for task in (getattr(document, "prediction_tasks", None) or [])
        if str(getattr(task, "adapter_kind", "")) != "mock"
    ]
    if tasks:
        return ReadinessItem(
            "well_prediction_linked", ReadinessItemStatus.OK,
            "测井预测已关联", f"{len(tasks)} 个预测任务")
    return ReadinessItem(
        "well_prediction_linked", ReadinessItemStatus.WARNING, "测井预测未关联",
        "无真实测井预测任务——校正只能基于初始相图人工解释")


def check_seismic_prediction_confidence(document) -> ReadinessItem:
    tasks = [
        task for task in (getattr(document, "prediction_tasks", None) or [])
        if getattr(task, "probability_summary", None)
    ]
    low_confidence = 0
    for task in tasks:
        summary = task.probability_summary or {}
        low_confidence += int(summary.get("low_confidence_regions") or 0)
    if not tasks:
        return ReadinessItem(
            "seismic_prediction_confidence", ReadinessItemStatus.WARNING,
            "地震预测缺失", "未关联地震预测结果")
    if low_confidence:
        return ReadinessItem(
            "seismic_prediction_confidence", ReadinessItemStatus.WARNING,
            f"地震预测存在 {low_confidence} 个低置信度区域",
            "建议优先人工复核低置信度区域",
            target="phase1.seismic_predictions")
    return ReadinessItem(
        "seismic_prediction_confidence", ReadinessItemStatus.OK,
        "地震预测置信度良好")


def check_interpretation_saved(document, workspace_state=None) -> ReadinessItem:
    draft_layers = [
        layer for layer in (getattr(document, "user_vector_layers", None) or [])
        if getattr(layer, "features", None)
        and "相" in str(getattr(layer, "name", "") or "")
    ] if document is not None else []
    # 更权威：membership 里 INITIAL_FACIES_DRAFT 角色的图层有已提交要素。
    if workspace_state is not None:
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole
        draft_layers = [
            layer for layer in (getattr(document, "user_vector_layers", None) or [])
            if workspace_state.role_of(layer.id) == LayerRole.INITIAL_FACIES_DRAFT
            and getattr(layer, "features", None)
        ]
    if draft_layers:
        return ReadinessItem(
            "interpretation_saved", ReadinessItemStatus.OK, "解释草稿已保存",
            f"{len(draft_layers)} 个解释图层含已提交要素")
    return ReadinessItem(
        "interpretation_saved", ReadinessItemStatus.INFO, "尚无解释草稿",
        "从原始相图创建可编辑草稿后开始校正（RAW 保持不可变）",
        target="phase1.interpretation")


def check_phase1_interpretation(document, workspace_state=None) -> ReadinessItem:
    return check_interpretation_saved(document, workspace_state)


def _count_constraints(document) -> int:
    """数有实际几何的约束（空壳登记不算——按钮误点不产生假绿勾）。"""
    total = 0
    for layers in getattr(document, "constraint_layers", None) or []:
        for line in getattr(layers, "lines", None) or []:
            if len(getattr(line, "coordinates", None) or []) >= 2:
                total += 1
    return total


def check_constraints_present(document) -> ReadinessItem:
    total = _count_constraints(document)
    if total:
        return ReadinessItem(
            "constraints_present", ReadinessItemStatus.OK, "地质约束存在",
            f"{total} 条约束线", target="phase2.constraints")
    return ReadinessItem(
        "constraints_present", ReadinessItemStatus.WARNING, "尚无地质约束",
        "物源/展布/岸线/断层等约束为空——单因素建模将缺少地质控制",
        target="phase2.constraints")


def check_factors_complete(document) -> ReadinessItem:
    tasks = getattr(document, "factor_map_tasks", None) or []
    completed = [task for task in tasks if str(task.status) == FACTOR_TASK_STATUS_COMPLETE]
    if not tasks:
        return ReadinessItem(
            "factors_complete", ReadinessItemStatus.WARNING, "无单因素任务",
            "尚未配置任何单因素图任务", target="phase2.factors")
    pending = len(tasks) - len(completed)
    if pending:
        return ReadinessItem(
            "factors_complete", ReadinessItemStatus.WARNING,
            f"{len(completed)}/{len(tasks)} 个单因素完成",
            f"{pending} 个任务未完成", target="phase2.factors")
    return ReadinessItem(
        "factors_complete", ReadinessItemStatus.OK,
        f"{len(completed)} 个单因素完成", target="phase2.factors")


def check_factor_staleness(freshness_summary=None) -> ReadinessItem:
    stale = 0
    if freshness_summary is not None:
        for entry in getattr(freshness_summary, "artifacts", None) or []:
            if str(getattr(entry, "status", "")) == "stale":
                stale += 1
    if stale:
        return ReadinessItem(
            "factor_staleness", ReadinessItemStatus.WARNING,
            f"{stale} 项成果已过期", "上游输入更新——建议重新计算（旧结果保留）",
            target="phase2.factors")
    return ReadinessItem(
        "factor_staleness", ReadinessItemStatus.OK, "单因素均为最新")


def check_evidence_available(document) -> ReadinessItem:
    evidence = 0
    evidence += len([
        task for task in (getattr(document, "factor_map_tasks", None) or [])
        if str(task.status) == FACTOR_TASK_STATUS_COMPLETE
    ])
    evidence += _count_constraints(document)
    if evidence:
        return ReadinessItem(
            "evidence_available", ReadinessItemStatus.OK, "证据可用",
            f"{evidence} 项约束/单因素证据")
    return ReadinessItem(
        "evidence_available", ReadinessItemStatus.ERROR, "无可用证据",
        "综合编图至少需要一项上阶段成果作为证据")


def check_evidence_staleness(freshness_summary=None) -> ReadinessItem:
    return check_factor_staleness(freshness_summary)


def check_integrated_draft(document, workspace_state=None) -> ReadinessItem:
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    drafts = []
    if workspace_state is not None:
        drafts = [
            layer for layer in (getattr(document, "user_vector_layers", None) or [])
            if workspace_state.role_of(layer.id) in (
                LayerRole.INTEGRATED_FACIES, LayerRole.INTEGRATED_BOUNDARY)
        ]
    if drafts:
        return ReadinessItem(
            "integrated_draft", ReadinessItemStatus.OK, "综合解释草稿存在",
            f"{len(drafts)} 个综合解释图层", target="phase3.integrated")
    return ReadinessItem(
        "integrated_draft", ReadinessItemStatus.INFO, "尚无综合解释草稿",
        "选择证据版本后创建综合解释草稿", target="phase3.integrated")


def check_qa_geometry_errors(document) -> ReadinessItem:
    """只看最新一份 QA 报告（历史报告已修复的问题不再永久报警）。"""
    reports = getattr(document, "quality_reports", None) or []
    issues = 0
    if reports:
        for issue in getattr(reports[-1], "issues", None) or []:
            if str(issue.get("kind") or issue.get("type") or "") in (
                "geometry", "topology", "overlap", "gap"
            ):
                issues += 1
    if issues:
        return ReadinessItem(
            "qa_geometry_errors", ReadinessItemStatus.WARNING,
            f"QA 存在 {issues} 个几何/拓扑问题",
            "成图前建议修复", target="phase3.qc")
    return ReadinessItem(
        "qa_geometry_errors", ReadinessItemStatus.OK, "QA 无几何错误")


_CHECK_IMPLEMENTATIONS = {
    "initial_facies_present": lambda doc, ws, fresh: check_initial_facies_present(doc),
    "initial_facies_crs": lambda doc, ws, fresh: check_initial_facies_crs(doc),
    "initial_facies_geometry": lambda doc, ws, fresh: check_initial_facies_geometry(doc),
    "well_prediction_linked": lambda doc, ws, fresh: check_well_prediction_linked(doc),
    "seismic_prediction_confidence": (
        lambda doc, ws, fresh: check_seismic_prediction_confidence(doc)),
    "interpretation_saved": (
        lambda doc, ws, fresh: check_interpretation_saved(doc, ws)),
    "phase1_interpretation": (
        lambda doc, ws, fresh: check_phase1_interpretation(doc, ws)),
    "constraints_present": lambda doc, ws, fresh: check_constraints_present(doc),
    "factors_complete": lambda doc, ws, fresh: check_factors_complete(doc),
    "factor_staleness": lambda doc, ws, fresh: check_factor_staleness(fresh),
    "evidence_available": lambda doc, ws, fresh: check_evidence_available(doc),
    "evidence_staleness": lambda doc, ws, fresh: check_evidence_staleness(fresh),
    "integrated_draft": lambda doc, ws, fresh: check_integrated_draft(doc, ws),
    "qa_geometry_errors": lambda doc, ws, fresh: check_qa_geometry_errors(doc),
}


def evaluate_stage_readiness(
    stage: MappingStage,
    document=None,
    workspace_state=None,
    freshness_summary=None,
) -> StageReadiness:
    """按阶段 profile 的检查清单评估就绪度。

    document / workspace_state / freshness_summary 均可缺省（如工程未
    打开）；缺省输入的相关检查按「未配置」warning 处理而不是崩溃。
    """
    from paleo_workbench.mapping_workspace.stage_profiles import stage_profile

    profile = stage_profile(stage)
    items: list[ReadinessItem] = []
    for check_id in profile.readiness_checks:
        implementation = _CHECK_IMPLEMENTATIONS.get(check_id)
        if implementation is None:
            continue
        try:
            items.append(implementation(document, workspace_state, freshness_summary))
        except Exception as exc:  # 单项检查失败不拖垮整份就绪度
            items.append(ReadinessItem(
                check_id, ReadinessItemStatus.WARNING, "检查失败", str(exc)))
    return StageReadiness(stage=stage, items=tuple(items))
