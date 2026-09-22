"""Inspector 摘要契约（V9 ADR：goal §25）。

UI 不再到处读取内部模型——每个领域对象提供一份可直接展示的
summary（Method/Unit/CRS/Inputs/Version/State/QC/Confidence/Uncertainty）。
本模块只做投影：输入 domain 对象，输出 plain dict / dataclass；
UI（Inspector/面板）可以零领域依赖地消费。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.workflow.interpretation.factor_product import (
    FactorProduct,
    factor_product_for_task,
)


@dataclass(frozen=True)
class SummaryRow:
    """一行摘要条目（label + value + 诚实状态标志）。"""

    label: str
    value: str
    #: "ok" | "missing" | "unknown" | "warn" —— 控制展示样式。
    state: str = "ok"


@dataclass(frozen=True)
class FactorSummary:
    """单因素产品摘要（Inspector 直接消费）。"""

    factor_id: str
    title: str
    rows: tuple[SummaryRow, ...] = field(default_factory=tuple)

    def to_display_dict(self) -> dict[str, Any]:
        return {
            "kind": "factor",
            "factor_id": self.factor_id,
            "title": self.title,
            "rows": [
                {"label": r.label, "value": r.value, "state": r.state}
                for r in self.rows
            ],
        }


def _row(label: str, value: Any, *, state: str = "ok") -> SummaryRow:
    return SummaryRow(label, str(value), state)


def factor_summary(
    product: FactorProduct | None,
) -> FactorSummary:
    """FactorProduct → 展示行（product 缺失时诚实回报）。"""
    if product is None:
        return FactorSummary("", "单因素（不存在）", (
            _row("状态", "任务不存在", state="missing"),))
    from paleo_workbench.workflow.interpretation.algorithm_registry import (
        display_label,
    )

    method = display_label(product.algorithm_id) if product.algorithm_id \
        else f"{product.method_label}（未注册方法）"
    rows = [
        _row("方法", method,
             state="ok" if product.algorithm_id else "unknown"),
        _row("单位",
             product.unit if product.unit_declared
             else (f"{product.unit or '未知'}（家族默认/未声明）"
                   if product.unit else "未声明"),
             state="ok" if product.unit_declared
             else ("unknown" if product.unit else "missing")),
        _row("CRS", product.crs if product.crs_declared else "未声明",
             state="ok" if product.crs_declared else "unknown"),
        _row("输入版本",
             f"{len(product.input_version_ids)} 项已钉住"
             if product.input_version_ids else "未登记（保存后登记）",
             state="ok" if product.input_version_ids else "unknown"),
        _row("结果版本", product.grid_version_id or "未登记（保存后登记）",
             state="ok" if product.grid_version_id else "unknown"),
        _row("Run", product.run_id or "无", 
             state="ok" if product.run_id else "unknown"),
        _row("成熟度", product.maturity),
        _row("新鲜度", product.freshness or "未评估",
             state="warn" if product.freshness in ("stale", "missing_input",
                                                   "superseded")
             else ("unknown" if product.freshness in ("", "unknown") else "ok")),
        _row("不确定度",
             "方差面（kriging）" if product.has_uncertainty
             else "无（方法不产生/任务无方差记录）",
             state="ok" if product.has_uncertainty else "unknown"),
        _row("数据来源",
             f"{product.source_kind}" + ("（含模拟数据）" if product.is_mock else ""),
             state="warn" if product.is_mock else "ok"),
    ]
    for key in ("r_squared", "n_points", "backend", "distance_policy"):
        if key in product.qc:
            rows.append(_row(f"QC·{key}", product.qc[key]))
    if product.freshness_detail:
        rows.append(_row("说明", product.freshness_detail))
    return FactorSummary(product.factor_id, f"{product.name}（{product.factor_type}）",
                         tuple(rows))


def factor_summary_for_task(
    document: Any,
    task_id: str,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> FactorSummary:
    return factor_summary(factor_product_for_task(
        document, task_id, catalog=catalog, workspace_state=workspace_state))


@dataclass(frozen=True)
class InterpretationSummary:
    """综合解释成果摘要（Inspector 直接消费）。"""

    interpretation_id: str
    title: str
    rows: tuple[SummaryRow, ...] = field(default_factory=tuple)

    def to_display_dict(self) -> dict[str, Any]:
        return {
            "kind": "integrated_interpretation",
            "interpretation_id": self.interpretation_id,
            "title": self.title,
            "rows": [
                {"label": r.label, "value": r.value, "state": r.state}
                for r in self.rows
            ],
        }


def interpretation_summary_rows(document: Any, layer_id: str) -> InterpretationSummary:
    from paleo_workbench.workflow.interpretation.integrated_interpretation import (
        find_by_layer,
    )
    from paleo_workbench.workflow.interpretation.revision import (
        latest_revision_for_layer,
    )

    interpretation = find_by_layer(document, layer_id)
    if interpretation is None:
        return InterpretationSummary("", "综合解释（无记录）", (
            _row("状态", "无综合解释记录（旧工程或未创建）", state="missing"),))
    revision = latest_revision_for_layer(document, layer_id)
    rows = [
        _row("输入集", interpretation.input_set_id or "未绑定（旧工程）",
             state="ok" if interpretation.input_set_id else "unknown"),
        _row("算法种子",
             interpretation.fusion_version_id or "人工起草（无算法种子）",
             state="ok" if interpretation.fusion_version_id else "unknown"),
        _row("提交版本",
             interpretation.committed_version_id or "未提交（编辑中）",
             state="ok" if interpretation.committed_version_id else "unknown"),
        _row("成熟度", interpretation.maturity),
        _row("分类", "、".join(interpretation.class_schema) or "未声明",
             state="ok" if interpretation.class_schema else "unknown"),
        _row("未提交编辑", "有" if interpretation.has_uncommitted_edits else "无",
             state="warn" if interpretation.has_uncommitted_edits else "ok"),
        _row("修订", f"{len(interpretation.revision_ids)} 条"),
    ]
    if revision is not None:
        rows.append(_row("最近修订",
                         f"{revision.actor or '未知'} @ {revision.created_at or '?'}"
                         f"（base={revision.base_kind}"
                         f"{':' + revision.base_version_id[:12] if revision.base_version_id else ''}）"))
        if revision.evidence_refs:
            rows.append(_row("依据证据", "；".join(revision.evidence_refs)))
    from paleo_workbench.workflow.interpretation.integrated_interpretation import (
        FUSION_CONFLICT_KEYS,
    )

    for key in FUSION_CONFLICT_KEYS:
        if key in interpretation.conflicts:
            rows.append(_row(f"冲突·{key}", interpretation.conflicts[key]))
    return InterpretationSummary(
        interpretation.interpretation_id,
        f"{interpretation.name}（{interpretation.layer_id}）",
        tuple(rows))
