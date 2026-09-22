"""InterpretationRevision — 人工解释一等溯源（V9 ADR-8，goal §13/§17）。

人工修改不再是"算法结果被覆盖"：每次保存一个解释面（Phase 1 草稿 /
综合解释 / 相带边界），记录一条 revision——

* **base**：算法种子（fusion 版本 / RAW 版本 / 父草稿）；
* **evidence_refs**：本修订依据的证据选择器（factor/constraint/draft）；
* **delta**：与上一 revision 的内容指纹 + 要素计数差异；
* **parent_revision_id**：revision 链（可回答"从哪个版本开始"）。

持久化于 ``ProjectDocument.interpretation_revisions``（dict 载体）。
不建第二数据库：指纹与版本引用都指向既有权威（catalog / 文档几何）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

#: 目标类型（解释面种类）。
TARGET_PHASE1_DRAFT = "phase1_draft"
TARGET_INTEGRATED_FACIES = "integrated_facies"
TARGET_INTEGRATED_BOUNDARY = "integrated_boundary"

#: base 种类（修订基于什么）。
BASE_RAW = "raw"
BASE_FUSION = "fusion"
BASE_FACTOR = "factor"
BASE_DRAFT = "draft"
BASE_MANUAL = "manual"  # 无算法种子（纯人工起草）


@dataclass
class InterpretationRevision:
    """一次解释面修订（算法结果 + 人工 delta 的溯源单元）。"""

    revision_id: str
    target_kind: str                     # TARGET_* 词汇
    target_layer_id: str
    #: 关联的 IntegratedInterpretation id（integrated 目标时非空）。
    interpretation_id: str = ""
    parent_revision_id: str = ""
    #: 算法种子（BASE_* 词汇 + 版本 id）；纯人工起草 base_kind=manual。
    base_kind: str = BASE_MANUAL
    base_version_id: str = ""
    #: 本修订依据的证据选择器（evidence 契约词汇）。
    evidence_refs: list[str] = field(default_factory=list)
    actor: str = ""
    created_at: str = ""
    #: 内容指纹（几何+属性的稳定哈希——同 interpolation_fingerprint 判据）。
    content_fingerprint: str = ""
    #: 与父修订的要素计数差异（{"features": +2, "vertices": -14}）。
    delta: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "target_kind": self.target_kind,
            "target_layer_id": self.target_layer_id,
            "interpretation_id": self.interpretation_id,
            "parent_revision_id": self.parent_revision_id,
            "base_kind": self.base_kind,
            "base_version_id": self.base_version_id,
            "evidence_refs": list(self.evidence_refs),
            "actor": self.actor,
            "created_at": self.created_at,
            "content_fingerprint": self.content_fingerprint,
            "delta": dict(self.delta),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterpretationRevision":
        return cls(
            revision_id=str(data.get("revision_id") or ""),
            target_kind=str(data.get("target_kind") or ""),
            target_layer_id=str(data.get("target_layer_id") or ""),
            interpretation_id=str(data.get("interpretation_id") or ""),
            parent_revision_id=str(data.get("parent_revision_id") or ""),
            base_kind=str(data.get("base_kind") or BASE_MANUAL),
            base_version_id=str(data.get("base_version_id") or ""),
            evidence_refs=[str(r) for r in (data.get("evidence_refs") or [])],
            actor=str(data.get("actor") or ""),
            created_at=str(data.get("created_at") or ""),
            content_fingerprint=str(data.get("content_fingerprint") or ""),
            delta=dict(data.get("delta") or {}),
            note=str(data.get("note") or ""),
        )


def layer_content_fingerprint(layer: Any) -> tuple[str, dict[str, int]]:
    """解释层内容的稳定指纹（几何+属性；round-trip 9 位小数如约束）。

    兼容两种层形态：edit_controller 层（``features()`` 方法）与文档
    ``UserVectorLayer``（``features`` 属性）。
    """
    counts = {"features": 0, "vertices": 0}
    raw_features = getattr(layer, "features", None)
    if callable(raw_features):
        try:
            raw_features = raw_features()
        except Exception:  # noqa: BLE001 — 枚举失败=空内容（诚实指纹）
            raw_features = []
    payload: list[Any] = []
    for feature in raw_features or []:
        counts["features"] += 1
        geometry = getattr(feature, "geometry", None) or {}
        # GeoJSON 坐标稳定化：round 9dp（与 constraint fingerprint 同判据）。
        def _stab(node: Any) -> Any:
            if isinstance(node, (int, float)):
                return round(float(node), 9)
            if isinstance(node, (list, tuple)):
                return [_stab(item) for item in node]
            return node

        stable_geom = _stab(geometry)
        def _count_vertices(node: Any) -> None:
            if isinstance(node, dict):
                for value in node.values():
                    _count_vertices(value)
            elif isinstance(node, (list, tuple)) and len(node) == 2 \
                    and all(isinstance(v, (int, float)) for v in node):
                counts["vertices"] += 1
            elif isinstance(node, (list, tuple)):
                for item in node:
                    _count_vertices(item)

        _count_vertices(geometry)
        attributes = getattr(feature, "attributes", None) or {}
        payload.append({
            "id": str(getattr(feature, "feature_id", "")
                      or getattr(feature, "id", "") or ""),
            "geometry": stable_geom,
            "attributes": {str(k): _stab(v)
                           for k, v in sorted(dict(attributes).items())},
        })
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return digest, counts


def record_interpretation_revision(
    document: Any,
    *,
    target_kind: str,
    target_layer_id: str,
    layer: Any,
    actor: str = "",
    now: str = "",
    interpretation_id: str = "",
    base_kind: str = BASE_MANUAL,
    base_version_id: str = "",
    evidence_refs: list[str] | None = None,
    note: str = "",
) -> InterpretationRevision | None:
    """记录一条修订（内容未变 → None，绝不产生空修订）。"""
    previous = latest_revision_for_layer(document, target_layer_id)
    fingerprint, counts = layer_content_fingerprint(layer)
    if previous is not None \
            and previous.content_fingerprint == fingerprint:
        return None  # 显式保存但内容未变——不是一次修订
    delta = dict(counts)
    if previous is not None:
        prev_counts = dict(previous.delta or {})
        delta = {
            "features": counts["features"] - int(prev_counts.get("features", 0)),
            "vertices": counts["vertices"] - int(prev_counts.get("vertices", 0)),
        }
    import uuid

    revision = InterpretationRevision(
        revision_id=f"irev_{uuid.uuid4().hex[:12]}",
        target_kind=str(target_kind),
        target_layer_id=str(target_layer_id),
        interpretation_id=str(interpretation_id or ""),
        parent_revision_id=previous.revision_id if previous else "",
        base_kind=str(base_kind),
        base_version_id=str(base_version_id or ""),
        evidence_refs=[str(r) for r in (evidence_refs or [])],
        actor=str(actor or ""),
        created_at=str(now or ""),
        content_fingerprint=fingerprint,
        delta=delta,
        note=str(note or ""),
    )
    revisions = list(getattr(document, "interpretation_revisions", None) or [])
    revisions.append(revision.to_dict())
    try:
        document.interpretation_revisions = revisions
    except AttributeError:
        setattr(document, "interpretation_revisions", revisions)
    # 领域链接：integrated 目标的修订自动挂到对应解释记录（UI 接线不再
    # 各自追加，杜绝双写漂移）。
    if interpretation_id or target_kind in (
            "integrated_facies", "integrated_boundary"):
        try:
            from paleo_workbench.workflow.interpretation.integrated_interpretation import (
                _upsert_interpretation,
                interpretations_for_document,
            )

            for interpretation in interpretations_for_document(document):
                if interpretation.layer_id != str(target_layer_id):
                    continue
                if revision.revision_id not in interpretation.revision_ids:
                    interpretation.revision_ids.append(revision.revision_id)
                _upsert_interpretation(document, interpretation)
        except Exception:  # noqa: BLE001 — 链接失败不阻断修订本身
            pass
    return revision


def revisions_for_layer(document: Any, layer_id: str) -> list[InterpretationRevision]:
    """某解释面的修订链（时间序）。"""
    out = [
        InterpretationRevision.from_dict(r)
        for r in (getattr(document, "interpretation_revisions", None) or [])
        if isinstance(r, dict)
        and str(r.get("target_layer_id") or "") == str(layer_id)
    ]
    return out


def latest_revision_for_layer(
    document: Any, layer_id: str,
) -> InterpretationRevision | None:
    chain = revisions_for_layer(document, layer_id)
    return chain[-1] if chain else None


def revision_summary(document: Any, layer_id: str) -> dict[str, Any]:
    """Inspector 摘要：这个面被谁改过、基于什么证据、从哪个版本开始。"""
    chain = revisions_for_layer(document, layer_id)
    if not chain:
        return {"layer_id": str(layer_id), "revisions": 0,
                "detail": "无修订记录（未保存或旧工程）"}
    last = chain[-1]
    return {
        "layer_id": str(layer_id),
        "revisions": len(chain),
        "first_revision_id": chain[0].revision_id,
        "latest_revision_id": last.revision_id,
        "latest_actor": last.actor,
        "latest_created_at": last.created_at,
        "base_kind": last.base_kind,
        "base_version_id": last.base_version_id,
        "evidence_refs": list(last.evidence_refs),
        "delta": dict(last.delta),
    }
