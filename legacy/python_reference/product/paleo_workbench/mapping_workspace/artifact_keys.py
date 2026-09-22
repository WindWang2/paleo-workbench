"""Artifact-key 唯一解析处（V8 M5）。

``phase1_draft:<layer_id>`` / ``factor:<task_id>`` / ``integrated:<layer_id>``
三族 key 的构造此前散布在 presentation / layer_group_controller /
dependencies / composite_document 四处——任何一处改动都会让成熟度、
新鲜度、依赖评估对同一图层解析出不同 key（静默漂移）。

本模块是唯一构造点；解析顺序（factor 任务 > phase1 草稿 > 综合解释）
也是契约的一部分（消费者按序取第一个命中的 key）。
"""
from __future__ import annotations

from paleo_workbench.mapping_workspace.layer_roles import LayerRole

__all__ = [
    "candidate_artifact_keys",
    "factor_key",
    "integrated_key",
    "phase1_draft_key",
]


def factor_key(task_id: str) -> str:
    return f"factor:{task_id}"


def phase1_draft_key(layer_id: str) -> str:
    return f"phase1_draft:{layer_id}"


def integrated_key(layer_id: str) -> str:
    return f"integrated:{layer_id}"


def candidate_artifact_keys(layer_id: str, record) -> list[str]:
    """membership → artifact_key 候选（有序：factor > phase1 草稿 > 综合）。

    与 ``LayerGroupController.layer_freshness``、
    ``CompositeDocument._layer_maturity_value``、依赖服务评估共用。
    """
    keys: list[str] = []
    if record.factor_task_id:
        keys.append(factor_key(str(record.factor_task_id)))
    if record.role == LayerRole.INITIAL_FACIES_DRAFT:
        keys.append(phase1_draft_key(str(layer_id)))
    if record.role in (LayerRole.INTEGRATED_FACIES, LayerRole.INTEGRATED_BOUNDARY):
        keys.append(integrated_key(str(layer_id)))
    return keys
