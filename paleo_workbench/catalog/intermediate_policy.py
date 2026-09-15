"""Intermediate artifact lifecycle policy（V13 W-D）.

「什么必须登记、什么可以缓存、什么属于 working state、什么是科学结果」
的单一决策表。与两套既有词汇正交且互不替代：

- ``DataStage``（RAW/INTERMEDIATE/DERIVED/OUTPUT）：**已入库**版本的阶段；
- ``retention_class``（cache/recomputable/retain/user）：**已入库**版本的
  保留策略（``catalog/service_v11.py``）。

本模块回答的是**写入时**的前置问题：一个即将产生的文件按什么口径处理——

===========  ===============  =========================  =====================
分类         必须入库         DataStage                  保留口径
===========  ===============  =========================  =====================
EPHEMERAL    否（任务期存续） —（绝不进 catalog）        会话/任务结束可消失
CACHE        否（可重算）     —（或入库存 cache）        可删除；可由 lineage
                                                         重算
INTERMEDIATE 是               INTERMEDIATE               recomputable（默认）
DERIVED      是               DERIVED                    user
OUTPUT       是               OUTPUT                     user
===========  ===============  =========================  =====================

明确不做：把所有 tempfile 强行 catalog 化（渲染临时体、指北针缓存就是
EPHEMERAL/CACHE，登记它们只制造噪音）。

生产方约定：新产生的科学文件在写入前用 :func:`policy_for` 查口径；
``must_register`` 为真的路径必须落到 ``catalog/lifecycle.py`` 的注册助手
（那里负责 run + version + retention 默认值）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from paleo_workbench.catalog.models import DataStage

# 分类词汇（稳定字符串，序列化/查询用）。
CLASS_EPHEMERAL = "ephemeral"
CLASS_CACHE = "cache"
CLASS_INTERMEDIATE = "intermediate"
CLASS_DERIVED = "derived"
CLASS_OUTPUT = "output"


@dataclass(frozen=True)
class ArtifactPolicy:
    """一种产物口径的完整决策。"""

    artifact_class: str
    must_register: bool
    data_stage: Optional[DataStage] = None
    retention_class: str = ""
    rationale: str = ""


_EPHEMERAL = ArtifactPolicy(
    artifact_class=CLASS_EPHEMERAL, must_register=False,
    rationale="任务/会话期存续，结束即弃（渲染临时体、预览缓存）")
_CACHE = ArtifactPolicy(
    artifact_class=CLASS_CACHE, must_register=False,
    rationale="可由上游重算的本地缓存；删除无损（指北针 SVG、缩放金字塔）")
_INTERMEDIATE = ArtifactPolicy(
    artifact_class=CLASS_INTERMEDIATE, must_register=True,
    data_stage=DataStage.INTERMEDIATE, retention_class="recomputable",
    rationale="科学过程正式中间成果（因子格网、预测中间体）")
_DERIVED = ArtifactPolicy(
    artifact_class=CLASS_DERIVED, must_register=True,
    data_stage=DataStage.DERIVED, retention_class="user",
    rationale="具科学语义的衍生成果（解释、属性体）")
_OUTPUT = ArtifactPolicy(
    artifact_class=CLASS_OUTPUT, must_register=True,
    data_stage=DataStage.OUTPUT, retention_class="user",
    rationale="用户认可的最终成果（成图产品、导出件）")

#: 产物 kind → 口径。kind 字符串与注册助手/生产方使用的 ``kind=`` 一致；
#: 未知 kind 查询返回 None（不猜——调用方按 INTERMEDIATE 兜底并补表）。
KNOWN_ARTIFACT_POLICIES: dict[str, ArtifactPolicy] = {
    # -- EPHEMERAL：渲染/交互临时体 ------------------------------------------
    "render_temp_svg": _EPHEMERAL,        # unified_map_canvas 地图体 SVG
    "north_arrow_cache": _CACHE,          # layout_export 指北针（机器级缓存）
    "atomic_write_tmp": _EPHEMERAL,       # storage/store 的 .tmp 原子替换
    "workflow_checkpoint": _EPHEMERAL,    # %TEMP%\paleo-workflow-runs 断点
    "seismic_attribute_temp": _EPHEMERAL, # 无工程时 p2-attribute-* 降级产物
    # -- CACHE ----------------------------------------------------------------
    "preview_cache": _CACHE,
    # -- INTERMEDIATE：科学中间成果 ------------------------------------------
    "factor_map_grid": _INTERMEDIATE,     # lifecycle.register_factor_map_run
    "prediction_intermediate": _INTERMEDIATE,
    "interchange_workdir": _EPHEMERAL,    # interchange 导入/导出工作目录
    # -- DERIVED -------------------------------------------------------------
    "seismic_attribute": _DERIVED,        # providers/builtin/seismic_attribute
    "curve_interpretation": _DERIVED,
    "horizon_interpretation": _DERIVED,
    "fault_interpretation": _DERIVED,
    "constraint_group": _DERIVED,
    "geomodel": _DERIVED,
    # -- OUTPUT --------------------------------------------------------------
    "map_product": _OUTPUT,
    "qc_report": _OUTPUT,
    "export": _OUTPUT,
    "map_compile": _OUTPUT,
}

#: 未登记 kind 的兜底口径（新产物默认按正式中间成果处理——宁登记勿丢失）。
DEFAULT_POLICY = _INTERMEDIATE


def policy_for(kind: str) -> ArtifactPolicy:
    """产物 kind → 口径决策（未知 kind 用 INTERMEDIATE 兜底并如实标注）。"""
    key = str(kind or "").strip()
    policy = KNOWN_ARTIFACT_POLICIES.get(key)
    if policy is not None:
        return policy
    fallback = ArtifactPolicy(
        artifact_class=DEFAULT_POLICY.artifact_class,
        must_register=DEFAULT_POLICY.must_register,
        data_stage=DEFAULT_POLICY.data_stage,
        retention_class=DEFAULT_POLICY.retention_class,
        rationale=f"未登记 kind {key!r}——按 INTERMEDIATE 兜底（请补 KNOWN_ARTIFACT_POLICIES）",
    )
    return fallback


def is_registered_kind(kind: str) -> bool:
    return str(kind or "").strip() in KNOWN_ARTIFACT_POLICIES
