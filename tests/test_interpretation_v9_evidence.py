"""V9 — 统一 Evidence 契约测试（ADR-3）。

选择器解析（向后兼容旧词汇）、诚实解析状态（绝不猜测）、可选证据清单。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping_workspace.stage_state import (
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.models import (
    FactorMapTask,
    PredictionTask,
    ProjectDocument,
    UserVectorLayer,
)
from paleo_workbench.workflow.interpretation.evidence import (
    EvidenceKind,
    EvidenceStatus,
    available_evidence,
    format_evidence_selector,
    parse_evidence_selector,
    resolve_evidence,
)


# ------------------------------------------------------------------ 选择器


def test_parse_legacy_vocabulary_roundtrip():
    cases = {
        "draft:layer_1": (EvidenceKind.PHASE1_DRAFT, "layer_1", ""),
        "factor:task_9:ver_abc": (EvidenceKind.FACTOR, "task_9", "ver_abc"),
        "factor:task_9": (EvidenceKind.FACTOR, "task_9", ""),
        "constraints:current": (EvidenceKind.CONSTRAINT_GROUP, "", ""),
        "constraints:g1:ver_x": (EvidenceKind.CONSTRAINT_GROUP, "g1", "ver_x"),
        "prediction:pred_1": (EvidenceKind.PREDICTION, "pred_1", ""),
        "prediction:pred_1:ver_y": (EvidenceKind.PREDICTION, "pred_1", "ver_y"),
        "version:ver_zzz": (EvidenceKind.CATALOG_VERSION, "ver_zzz", "ver_zzz"),
    }
    for raw, (kind, ref, version) in cases.items():
        selector = parse_evidence_selector(raw)
        assert selector.kind is kind
        assert selector.ref_id == ref
        assert selector.version_id == version
        # 格式化往返（canonical 形态）
        assert parse_evidence_selector(selector.raw) == selector


def test_parse_bare_version_id_compat():
    selector = parse_evidence_selector("ver_0123456789abcdef")
    assert selector.kind is EvidenceKind.CATALOG_VERSION


def test_parse_rejects_malformed():
    for bad in ("", "draft:", "factor:", "unknown-kind:x", "factor:a:b:c"):
        with pytest.raises(ValueError):
            parse_evidence_selector(bad)


def test_format_floating_constraint_current():
    assert format_evidence_selector(
        EvidenceKind.CONSTRAINT_GROUP, "", "", floating=True) == "constraints:current"


# -------------------------------------------------------------------- 解析


def _document_with_factor(*, version_id: str = "") -> ProjectDocument:
    doc = ProjectDocument.new("t")
    task = FactorMapTask(
        name="砂厚", target_horizon="T1", factor_type="sand_thickness",
        method="idw", status="complete", source_kind="real")
    task.grid_artifact_version_id = version_id
    doc.factor_map_tasks.append(task)
    return doc, task


class _FakeVersion:
    def __init__(self, version_id: str, asset_id: str):
        self.id = version_id
        self.asset_id = asset_id
        self.name = "asset"


class _FakeCatalog:
    def __init__(self, versions: dict[str, _FakeVersion] | None = None):
        self._versions = versions or {}

    def resolve_version(self, version_id):
        return self._versions.get(version_id)


def test_resolve_factor_missing_task():
    doc = ProjectDocument.new("t")
    resolution = resolve_evidence(doc, "factor:nope")
    assert resolution.status is EvidenceStatus.MISSING


def test_resolve_factor_unpinned_is_honest():
    doc, task = _document_with_factor(version_id="")
    resolution = resolve_evidence(doc, f"factor:{task.id}")
    assert resolution.status is EvidenceStatus.UNPINNED
    assert "尚未登记版本" in resolution.detail


def test_resolve_factor_resolved_with_quality():
    doc, task = _document_with_factor(version_id="ver_1")
    task.quality_metrics = {"r2": 0.9, "n_points": 12}
    catalog = _FakeCatalog({"ver_1": _FakeVersion("ver_1", "asset_1")})
    resolution = resolve_evidence(
        doc, f"factor:{task.id}:ver_1", catalog=catalog)
    assert resolution.status is EvidenceStatus.RESOLVED
    assert resolution.pinned_version_id == "ver_1"
    assert resolution.asset_id == "asset_1"
    assert resolution.quality["r2"] == 0.9


def test_resolve_factor_version_missing():
    doc, task = _document_with_factor(version_id="ver_gone")
    resolution = resolve_evidence(
        doc, f"factor:{task.id}:ver_gone", catalog=_FakeCatalog())
    assert resolution.status is EvidenceStatus.MISSING


def test_resolve_factor_without_catalog_is_unknown_not_resolved():
    doc, task = _document_with_factor(version_id="ver_1")
    resolution = resolve_evidence(doc, f"factor:{task.id}:ver_1", catalog=None)
    assert resolution.status is EvidenceStatus.UNKNOWN


def test_resolve_prediction_mock_honesty():
    doc = ProjectDocument.new("t")
    task = PredictionTask(
        name="地震相预测", adapter_kind="mock", status="complete",
        probability_summary={"classes": ["A", "B"]})
    doc.prediction_tasks.append(task)
    resolution = resolve_evidence(doc, f"prediction:{task.id}")
    assert resolution.status is EvidenceStatus.UNPINNED
    assert resolution.quality.get("mock_data") is True
    assert resolution.quality.get("classes") == ["A", "B"]


def test_resolve_prediction_incomplete_is_missing():
    doc = ProjectDocument.new("t")
    task = PredictionTask(name="p", status="pending")
    doc.prediction_tasks.append(task)
    assert resolve_evidence(
        doc, f"prediction:{task.id}").status is EvidenceStatus.MISSING


def test_resolve_draft_pin_chain():
    doc = ProjectDocument.new("t")
    doc.user_vector_layers.append(UserVectorLayer(id="L1", name="相草稿"))
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="L1", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_raw1"))
    catalog = _FakeCatalog({"ver_raw1": _FakeVersion("ver_raw1", "asset_raw")})
    resolution = resolve_evidence(
        doc, "draft:L1", catalog=catalog, workspace_state=state)
    assert resolution.status is EvidenceStatus.RESOLVED
    assert resolution.pinned_version_id == "ver_raw1"
    assert resolution.display == "相草稿"


def test_resolve_draft_unpinned_and_missing():
    doc = ProjectDocument.new("t")
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="L2", role=LayerRole.INITIAL_FACIES_DRAFT))
    assert resolve_evidence(
        doc, "draft:L2", workspace_state=state).status is EvidenceStatus.UNPINNED
    assert resolve_evidence(
        doc, "draft:L3", workspace_state=state).status is EvidenceStatus.MISSING


def test_resolve_catalog_version_direct():
    doc = ProjectDocument.new("t")
    catalog = _FakeCatalog({"ver_9": _FakeVersion("ver_9", "asset_9")})
    resolution = resolve_evidence(doc, "version:ver_9", catalog=catalog)
    assert resolution.status is EvidenceStatus.RESOLVED
    assert resolve_evidence(
        doc, "version:ver_none", catalog=catalog).status is EvidenceStatus.MISSING
    assert resolve_evidence(
        doc, "version:ver_9", catalog=None).status is EvidenceStatus.UNKNOWN


# ------------------------------------------------------------------ 清单


def test_available_evidence_lists_predictions_and_factors():
    doc, task = _document_with_factor(version_id="ver_1")
    pred = PredictionTask(name="p", status="complete")
    doc.prediction_tasks.append(pred)
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="L1", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_raw1"))
    kinds = [r.selector.kind for r in available_evidence(doc, state)]
    assert EvidenceKind.PREDICTION in kinds
    assert EvidenceKind.FACTOR in kinds
    assert EvidenceKind.PHASE1_DRAFT in kinds


def test_resolution_to_dict_is_serializable():
    doc, task = _document_with_factor(version_id="ver_1")
    payload = resolve_evidence(doc, f"factor:{task.id}:ver_1").to_dict()
    assert payload["selector"] == f"factor:{task.id}:ver_1"
    assert payload["status"] == "unknown"
