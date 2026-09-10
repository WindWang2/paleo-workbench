"""统一 staleness 词汇与传播（V9 ADR-9，goal §19/§20）。

此前三套词汇（workflow.freshness.FreshnessState、
mapping_workspace.dependencies.FreshnessStatus、constraint pin 六态）
各自为政，Inspector 需临时合并。本模块定义**汇聚层 verdict**（不替换
两旧引擎——它们仍是各自权威域的评估器，这里是统一出口）：

``CURRENT | STALE_CONTENT | STALE_VERSION | MISSING_INPUT | SUPERSEDED
| UNKNOWN``

规则（goal §20）：**没有证据时 UNKNOWN，绝不猜 CURRENT**。

依赖链贯通（goal §19）：
well version → factor version → compilation input set →
integrated interpretation → map product——上游变化沿
``MappingDependencyService`` 的传播式评估 + 产品指纹双路到达 MapProduct。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class StalenessVerdict(str, Enum):
    """统一 staleness 判定词汇。"""

    CURRENT = "current"
    STALE_CONTENT = "stale_content"   # 上游内容变化（约束编辑/样本变化）
    STALE_VERSION = "stale_version"   # 上游已有新版本（pinned ≠ current）
    MISSING_INPUT = "missing_input"   # 钉住的输入缺失/被清理
    SUPERSEDED = "superseded"         # 自身输出已被新版本取代
    UNKNOWN = "unknown"               # 无证据判定（绝不猜 CURRENT）


#: verdict → 是否问题态（Inspector/发布门禁消费）。
VERDICT_IS_PROBLEM = {
    StalenessVerdict.CURRENT: False,
    StalenessVerdict.STALE_CONTENT: True,
    StalenessVerdict.STALE_VERSION: True,
    StalenessVerdict.MISSING_INPUT: True,
    StalenessVerdict.SUPERSEDED: True,
    StalenessVerdict.UNKNOWN: True,  # 未知也是问题（不可签发）
}

VERDICT_LABELS_ZH = {
    StalenessVerdict.CURRENT: "最新",
    StalenessVerdict.STALE_CONTENT: "内容过期",
    StalenessVerdict.STALE_VERSION: "版本过期",
    StalenessVerdict.MISSING_INPUT: "输入缺失",
    StalenessVerdict.SUPERSEDED: "已被取代",
    StalenessVerdict.UNKNOWN: "状态未知",
}


# ----------------------------------------------------------------- 适配器
# 各旧引擎词汇 → 统一 verdict（显式映射表，双向可审计）。


def from_constraint_pin(state: str) -> StalenessVerdict:
    """constraint_versions pin 态（current/unpinned/unknown/missing/
    stale_version/stale_content）→ verdict。"""
    return {
        "current": StalenessVerdict.CURRENT,
        "unpinned": StalenessVerdict.UNKNOWN,  # 未钉=无比较基准=未知
        "unknown": StalenessVerdict.UNKNOWN,
        "missing": StalenessVerdict.MISSING_INPUT,
        "stale_version": StalenessVerdict.STALE_VERSION,
        "stale_content": StalenessVerdict.STALE_CONTENT,
        "uncommitted": StalenessVerdict.UNKNOWN,
    }.get(str(state or ""), StalenessVerdict.UNKNOWN)


def from_workspace_status(status: Any) -> StalenessVerdict:
    """mapping_workspace.dependencies.FreshnessStatus → verdict。"""
    text = str(getattr(status, "value", status) or "")
    return {
        "current": StalenessVerdict.CURRENT,
        "stale": StalenessVerdict.STALE_VERSION,  # 工作区 stale = 上游新版本
        "missing_input": StalenessVerdict.MISSING_INPUT,
        "superseded": StalenessVerdict.SUPERSEDED,
        "unknown": StalenessVerdict.UNKNOWN,
    }.get(text, StalenessVerdict.UNKNOWN)


def from_run_freshness(state: Any) -> StalenessVerdict:
    """workflow.freshness.FreshnessState → verdict。"""
    text = str(getattr(state, "value", state) or "")
    return {
        "fresh": StalenessVerdict.CURRENT,
        "stale": StalenessVerdict.STALE_VERSION,
        "unknown": StalenessVerdict.UNKNOWN,
        "missing": StalenessVerdict.MISSING_INPUT,
        "failed": StalenessVerdict.UNKNOWN,  # run 失败 → 无法判定产物新鲜度
        "running": StalenessVerdict.UNKNOWN,
    }.get(text, StalenessVerdict.UNKNOWN)


# ----------------------------------------------------------------- 评估入口


@dataclass(frozen=True)
class ArtifactVerdict:
    """一个阶段成果的统一判定（含证据细节）。"""

    artifact_key: str
    verdict: StalenessVerdict
    detail: str = ""
    upstream_culprits: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return VERDICT_LABELS_ZH[self.verdict]

    @property
    def is_problem(self) -> bool:
        return VERDICT_IS_PROBLEM[self.verdict]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "verdict": self.verdict.value,
            "label": self.label,
            "is_problem": self.is_problem,
            "detail": self.detail,
            "upstream_culprits": list(self.upstream_culprits),
        }


def evaluate_verdict(
    document: Any,
    artifact_key: str,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> ArtifactVerdict:
    """单一入口：任意 artifact_key（factor:/phase1_draft:/integrated:/
    mapproduct:）→ 统一 verdict（无证据 → UNKNOWN）。"""
    key = str(artifact_key or "")
    if document is None or not key:
        return ArtifactVerdict(key, StalenessVerdict.UNKNOWN, "无工程上下文")
    try:
        from paleo_workbench.mapping_workspace.dependencies import (
            MappingDependencyService,
        )

        summary = MappingDependencyService().evaluate(
            document, workspace_state, catalog)
    except Exception as exc:  # noqa: BLE001 — 评估失败=未知，绝不猜
        return ArtifactVerdict(
            key, StalenessVerdict.UNKNOWN, f"评估失败：{exc}")
    entry = summary.get(key)
    if entry is None:
        return ArtifactVerdict(
            key, StalenessVerdict.UNKNOWN, f"未知的阶段成果键：{key}")
    verdict = from_workspace_status(entry.status)
    return ArtifactVerdict(
        key, verdict, entry.detail,
        tuple(entry.upstream_culprits))


def workspace_verdicts(
    document: Any,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> dict[str, ArtifactVerdict]:
    """全工作区统一判定（单次评估，Inspector/发布门禁消费）。"""
    if document is None:
        return {}
    try:
        from paleo_workbench.mapping_workspace.dependencies import (
            MappingDependencyService,
        )

        summary = MappingDependencyService().evaluate(
            document, workspace_state, catalog)
    except Exception:  # noqa: BLE001 — 评估失败=空表（各键按需 UNKNOWN）
        return {}
    out: dict[str, ArtifactVerdict] = {}
    for entry in summary.artifacts:
        out[entry.artifact_key] = ArtifactVerdict(
            entry.artifact_key,
            from_workspace_status(entry.status),
            entry.detail,
            tuple(entry.upstream_culprits))
    return out


def propagate_to_products(
    document: Any,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> dict[str, ArtifactVerdict]:
    """goal §19：上游变化沿链传播到每个 MapProduct 的判定视图。

    返回 mapproduct:<id> → verdict（含上游 culprit 链：factor/integrated
    的过期即产品过期）。发布门禁消费本函数（goal §31：stale 产品禁发布）。
    """
    verdicts = workspace_verdicts(
        document, catalog=catalog, workspace_state=workspace_state)
    return {key: verdict for key, verdict in verdicts.items()
            if key.startswith("mapproduct:")}
