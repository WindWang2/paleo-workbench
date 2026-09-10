"""IntegratedInterpretation — 综合解释一等成果（V9 ADR-8，goal §15）。

综合成果不再是"一个 polygon 层 + 一个 dict"：IntegratedInterpretation 绑定

* **input_set**（CompilationInputSet id——pinned 输入）；
* **run**（fusion DataRun / catalog 版本）；
* **geometry artifact**（QGIS 编辑层 layer_id + 提交后的 catalog DERIVED 版本）；
* **class schema / confidence / uncertainty / conflicts**（goal §18 领域事实）；
* **manual edits**（InterpretationRevision 链引用）；
* **QA / version / maturity**。

提交 (:func:`commit_integrated_interpretation`) 把层几何注册为 catalog
DERIVED 版本 + ``integrated_interpretation`` DataRun（operation 词汇进入
freshness/recompute 的 lineage 期望集——见 staleness 模块）。
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.workflow.interpretation.revision import (
    InterpretationRevision,
    latest_revision_for_layer,
    record_interpretation_revision,
)

OPERATION_INTEGRATED_INTERPRETATION = "integrated_interpretation"

#: fusion QC → 综合解释 conflicts 摘要的键（stage/summary 共用，防漂移）。
FUSION_CONFLICT_KEYS: tuple[str, ...] = (
    "low_confidence_fraction",
    "mean_conflict_fraction",
    "high_conflict_fraction",
    "low_margin_fraction",
)
ASSET_TYPE_INTEGRATED_INTERPRETATION = "integrated_interpretation"

#: 成熟度（goal §31 与 MapProduct 对齐的语义阶梯）。
MATURITY_DRAFT = "draft"
MATURITY_REVIEWED = "reviewed"
MATURITY_FROZEN = "frozen"
MATURITY_PUBLISHED = "published"
MATURITY_SUPERSEDED = "superseded"


@dataclass
class IntegratedInterpretation:
    """一个综合解释成果的领域身份（dict 载体持久化）。"""

    interpretation_id: str
    name: str = ""
    #: CompilationInputSet id（pinned 输入；""=旧工程无结构化输入集）。
    input_set_id: str = ""
    #: QGIS/文档编辑层（authoring surface）。
    layer_id: str = ""
    #: fusion catalog 版本（算法种子；""=人工起草）。
    fusion_version_id: str = ""
    run_id: str = ""
    #: 提交后的 catalog DERIVED 版本（""=从未提交）。
    committed_version_id: str = ""
    class_schema: list[str] = field(default_factory=list)
    confidence_summary: dict[str, Any] = field(default_factory=dict)
    uncertainty_summary: dict[str, Any] = field(default_factory=dict)
    #: goal §18：agreement/conflict/support count（fusion QC 提取）。
    conflicts: dict[str, Any] = field(default_factory=dict)
    revision_ids: list[str] = field(default_factory=list)
    #: 最近一次 commit 对应的修订 id（其后的修订 = 未提交编辑）。
    last_committed_revision_id: str = ""
    qa_report_ref: str = ""
    maturity: str = MATURITY_DRAFT
    created_at: str = ""
    created_by: str = ""
    committed_at: str = ""

    @property
    def has_uncommitted_edits(self) -> bool:
        """已提交且有后续修订 → live 层 ≠ 最新提交。"""
        return bool(self.committed_version_id) and bool(self.revision_ids)             and self.revision_ids[-1] != self.last_committed_revision_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "interpretation_id": self.interpretation_id,
            "name": self.name,
            "input_set_id": self.input_set_id,
            "layer_id": self.layer_id,
            "fusion_version_id": self.fusion_version_id,
            "run_id": self.run_id,
            "committed_version_id": self.committed_version_id,
            "class_schema": list(self.class_schema),
            "confidence_summary": dict(self.confidence_summary),
            "uncertainty_summary": dict(self.uncertainty_summary),
            "conflicts": dict(self.conflicts),
            "revision_ids": list(self.revision_ids),
            "last_committed_revision_id": self.last_committed_revision_id,
            "qa_report_ref": self.qa_report_ref,
            "maturity": self.maturity,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "committed_at": self.committed_at,
            "active": True,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntegratedInterpretation":
        return cls(
            interpretation_id=str(data.get("interpretation_id") or ""),
            name=str(data.get("name") or ""),
            input_set_id=str(data.get("input_set_id") or ""),
            layer_id=str(data.get("layer_id") or ""),
            fusion_version_id=str(data.get("fusion_version_id") or ""),
            run_id=str(data.get("run_id") or ""),
            committed_version_id=str(data.get("committed_version_id") or ""),
            class_schema=[str(c) for c in (data.get("class_schema") or [])],
            confidence_summary=dict(data.get("confidence_summary") or {}),
            uncertainty_summary=dict(data.get("uncertainty_summary") or {}),
            conflicts=dict(data.get("conflicts") or {}),
            revision_ids=[str(r) for r in (data.get("revision_ids") or [])],
            last_committed_revision_id=str(
                data.get("last_committed_revision_id") or ""),
            qa_report_ref=str(data.get("qa_report_ref") or ""),
            maturity=str(data.get("maturity") or MATURITY_DRAFT),
            created_at=str(data.get("created_at") or ""),
            created_by=str(data.get("created_by") or ""),
            committed_at=str(data.get("committed_at") or ""),
        )


def create_integrated_interpretation(
    document: Any,
    *,
    name: str,
    layer_id: str,
    input_set_id: str = "",
    fusion_version_id: str = "",
    run_id: str = "",
    class_schema: list[str] | None = None,
    confidence_summary: dict[str, Any] | None = None,
    conflicts: dict[str, Any] | None = None,
    created_by: str = "",
    created_at: str = "",
) -> IntegratedInterpretation:
    """创建综合解释记录（同层重复创建 → ValueError）。"""
    if find_by_layer(document, layer_id) is not None:
        raise ValueError(f"层 {layer_id} 已有综合解释记录（不可重复创建）")
    import uuid

    interpretation = IntegratedInterpretation(
        interpretation_id=f"iint_{uuid.uuid4().hex[:12]}",
        name=str(name or "综合解释"),
        layer_id=str(layer_id),
        input_set_id=str(input_set_id or ""),
        fusion_version_id=str(fusion_version_id or ""),
        run_id=str(run_id or ""),
        class_schema=[str(c) for c in (class_schema or [])],
        confidence_summary=dict(confidence_summary or {}),
        conflicts=dict(conflicts or {}),
        created_by=str(created_by or ""),
        created_at=str(created_at or ""),
    )
    records = list(
        getattr(document, "integrated_interpretations", None) or [])
    records.append(interpretation.to_dict())
    try:
        document.integrated_interpretations = records
    except AttributeError:
        setattr(document, "integrated_interpretations", records)
    return interpretation


def interpretations_for_document(
    document: Any,
) -> list[IntegratedInterpretation]:
    return [IntegratedInterpretation.from_dict(r)
            for r in (getattr(document, "integrated_interpretations", None) or [])
            if isinstance(r, dict) and r.get("interpretation_id")]


def find_by_layer(
    document: Any, layer_id: str,
) -> IntegratedInterpretation | None:
    for interpretation in interpretations_for_document(document):
        if interpretation.layer_id == str(layer_id):
            return interpretation
    return None


def _layer_payload(interpretation: IntegratedInterpretation,
                   layer: Any) -> dict[str, Any]:
    """提交载荷：几何 + 分类 schema + 输入集/种子引用（快照）。

    兼容 edit_controller 层（``features()`` 方法）与文档 UserVectorLayer
    （``features`` 属性）。
    """
    raw_features = getattr(layer, "features", None)
    if callable(raw_features):
        raw_features = raw_features()
    features = []
    for feature in raw_features or []:
        features.append({
            "id": str(getattr(feature, "feature_id", "")
                      or getattr(feature, "id", "") or ""),
            "geometry": getattr(feature, "geometry", None) or {},
            "properties": dict(getattr(feature, "attributes", None)
                               or getattr(feature, "properties", None) or {}),
        })
    return {
        "schema": 1,
        "interpretation_id": interpretation.interpretation_id,
        "layer_id": interpretation.layer_id,
        "class_schema": list(interpretation.class_schema),
        "input_set_id": interpretation.input_set_id,
        "fusion_version_id": interpretation.fusion_version_id,
        "features": features,
    }


def _interpretation_assets(catalog: Any) -> list[Any]:
    # Lazy-safe PUBLIC lookup (constraint_versions precedent): catalog.document
    # is EMPTY pre-warm on a lazy-opened service — list_assets() is the
    # sanctioned path, never document.assets.
    return [
        asset
        for asset in catalog.list_assets()
        if str(getattr(asset, "type", "") or "") == ASSET_TYPE_INTEGRATED_INTERPRETATION
    ]


def _asset_for_interpretation(catalog: Any, interpretation_id: str) -> Any | None:
    for asset in _interpretation_assets(catalog):
        meta = dict(getattr(asset, "metadata", None) or {})
        if str(meta.get("interpretation_id") or "") == str(interpretation_id):
            return asset
    return None


def commit_integrated_interpretation(
    document: Any,
    interpretation: IntegratedInterpretation,
    layer: Any,
    catalog: Any,
    *,
    actor: str = "",
    now: str = "",
    evidence_refs: list[str] | None = None,
) -> str:
    """提交综合解释：层几何 → catalog DERIVED 版本 + DataRun + revision。

    返回新版本 id。载荷快照含 class schema 与 input_set/fusion 引用，
    使版本自含科学身份（future re-open 可追溯输入）。同时记录
    InterpretationRevision（base=本提交版本，人工 delta 链的父节点）。
    """
    if catalog is None:
        raise ValueError("目录服务不可用——综合解释提交需要 catalog（不伪称已提交）")
    payload = _layer_payload(interpretation, layer)
    if not payload["features"]:
        raise ValueError("解释层没有要素——拒绝提交空几何")

    with tempfile.TemporaryDirectory(prefix="iint_commit_") as tmp:
        payload_path = Path(tmp) / "interpretation.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
        asset = _asset_for_interpretation(catalog, interpretation.interpretation_id)
        previous_version = ""
        if asset is not None:
            # 评审 R2-F6：用 catalog 认可的当前版本指针（而非自行推导
            # max(version_number)——两套"最新"会漂移）。
            current = str(getattr(asset, "current_version_id", "") or "")
            previous_version = current
        run = catalog.register_run(
            OPERATION_INTEGRATED_INTERPRETATION,
            input_version_ids=[v for v in (
                interpretation.fusion_version_id, previous_version) if v],
            parameters={
                "interpretation_id": interpretation.interpretation_id,
                "layer_id": interpretation.layer_id,
                "input_set_id": interpretation.input_set_id,
                "n_features": len(payload["features"]),
                "actor": str(actor or ""),
            },
            generator="interpretation-v9",
            status="running",
        )
        from paleo_workbench.catalog.models import DataStage

        try:
            if asset is None:
                version = catalog.register_result_asset(
                    name=f"interpretation:{interpretation.name}",
                    type=ASSET_TYPE_INTEGRATED_INTERPRETATION,
                    format="json",
                    asset_metadata={
                        "interpretation_id": interpretation.interpretation_id,
                    },
                    source_path=payload_path,
                    stage=DataStage.DERIVED,
                    run_id=str(run.id),
                    version_metadata={
                        "interpretation_id": interpretation.interpretation_id,
                        "actor": str(actor or ""),
                    },
                )
                version_id = str(getattr(version, "id", "") or "")
            else:
                version = catalog.register_version(
                    str(asset.id), payload_path, DataStage.DERIVED,
                    parent_version_ids=[previous_version]
                    if previous_version else [],
                    run_id=str(run.id),
                    metadata={
                        "interpretation_id": interpretation.interpretation_id,
                        "actor": str(actor or ""),
                    },
                )
                version_id = str(getattr(version, "id", "") or "")
            catalog.update_run_status(str(run.id), "complete")
        except Exception:
            try:
                catalog.update_run_status(str(run.id), "failed")
            except Exception:  # noqa: BLE001
                pass
            raise

    # 文档侧同步（记录 + revision 链）。
    interpretation.committed_version_id = version_id
    interpretation.run_id = str(run.id)
    interpretation.committed_at = str(now or "")
    _upsert_interpretation(document, interpretation)
    revision = record_interpretation_revision(
        document,
        target_kind="integrated_facies",
        target_layer_id=interpretation.layer_id,
        layer=layer,
        actor=actor or "commit",
        now=now,
        interpretation_id=interpretation.interpretation_id,
        base_kind="commit",
        base_version_id=version_id,
        evidence_refs=evidence_refs or [],
        note="综合解释提交（commit → DERIVED 版本）",
    )
    if revision is not None:
        # revision 链接已由领域函数维护（防止拷贝双写）；此处只钉
        # last_committed 锚点——重读文档侧对象避免覆盖中间状态。
        fresh = find_by_layer(document, interpretation.layer_id)
        target = fresh if fresh is not None else interpretation
        if revision.revision_id not in target.revision_ids:
            target.revision_ids.append(revision.revision_id)
        target.last_committed_revision_id = revision.revision_id
        _upsert_interpretation(document, target)
    else:
        # 内容自上次修订未变（例如：手工保存已记录修订、commit 紧随其后）
        # ——仍推进 last_committed 锚点到链尾：本次提交覆盖了该内容。
        latest = latest_revision_for_layer(document, interpretation.layer_id)
        if latest is not None:
            fresh = find_by_layer(document, interpretation.layer_id)
            target = fresh if fresh is not None else interpretation
            target.last_committed_revision_id = latest.revision_id
            _upsert_interpretation(document, target)
    return version_id


def _upsert_interpretation(document: Any,
                           interpretation: IntegratedInterpretation) -> None:
    records = list(
        getattr(document, "integrated_interpretations", None) or [])
    payload = interpretation.to_dict()
    for i, existing in enumerate(records):
        if isinstance(existing, dict) and \
                str(existing.get("interpretation_id")) == interpretation.interpretation_id:
            records[i] = payload
            break
    else:
        records.append(payload)
    try:
        document.integrated_interpretations = records
    except AttributeError:
        setattr(document, "integrated_interpretations", records)


def interpretation_summary(document: Any, layer_id: str) -> dict[str, Any]:
    """Inspector 摘要（goal §15/§25）。"""
    from paleo_workbench.workflow.interpretation.revision import (
        revision_summary,
    )

    interpretation = find_by_layer(document, layer_id)
    if interpretation is None:
        return {"layer_id": str(layer_id), "status": "missing",
                "detail": "无综合解释记录（旧工程或未创建）"}
    return {
        "layer_id": str(layer_id),
        "status": "ok",
        "interpretation_id": interpretation.interpretation_id,
        "name": interpretation.name,
        "input_set_id": interpretation.input_set_id,
        "fusion_version_id": interpretation.fusion_version_id,
        "committed_version_id": interpretation.committed_version_id,
        "maturity": interpretation.maturity,
        "class_schema": list(interpretation.class_schema),
        "confidence_summary": dict(interpretation.confidence_summary),
        "conflicts": dict(interpretation.conflicts),
        "has_uncommitted_edits": interpretation.has_uncommitted_edits,
        "revisions": revision_summary(document, layer_id),
    }
