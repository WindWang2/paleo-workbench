"""V9 — InterpretationRevision + IntegratedInterpretation（P0-4/P0-6）。"""
from __future__ import annotations

import pytest

from paleo_workbench.project.models import ProjectDocument, UserVectorFeature, UserVectorLayer
from paleo_workbench.workflow.interpretation.integrated_interpretation import (
    IntegratedInterpretation,
    commit_integrated_interpretation,
    create_integrated_interpretation,
    find_by_layer,
    interpretation_summary,
    interpretations_for_document,
)
from paleo_workbench.workflow.interpretation.revision import (
    InterpretationRevision,
    layer_content_fingerprint,
    latest_revision_for_layer,
    record_interpretation_revision,
    revision_summary,
    revisions_for_layer,
)


def _layer(layer_id: str = "L1", polys: int = 1) -> UserVectorLayer:
    layer = UserVectorLayer(id=layer_id, name="综合沉积相", geometry_kind="polygon")
    for i in range(polys):
        layer.features.append(UserVectorFeature(
            id=f"f{i}",
            geometry={"type": "Polygon", "coordinates": [
                [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]},
            properties={"class": "三角洲"},
        ))
    return layer


# ------------------------------------------------------------ 修订链


def test_revision_records_only_content_changes():
    doc = ProjectDocument.new("t")
    layer = _layer()
    first = record_interpretation_revision(
        doc, target_kind="integrated_facies", target_layer_id="L1", layer=layer,
        actor="geologist-a", now="t1",
        base_kind="fusion", base_version_id="ver_fusion_1",
        evidence_refs=["factor:t1:ver_1", "constraints:current"])
    assert first is not None
    assert first.base_kind == "fusion"
    assert first.evidence_refs == ["factor:t1:ver_1", "constraints:current"]
    # 内容未变 → 无空修订。
    assert record_interpretation_revision(
        doc, target_kind="integrated_facies", target_layer_id="L1", layer=layer,
        now="t2") is None
    # 编辑（加一个面）→ 第二条修订，父链 + delta。
    layer.features.append(UserVectorFeature(
        id="f1", geometry={"type": "Polygon", "coordinates": [
            [[2.0, 2.0], [3.0, 2.0], [3.0, 3.0], [2.0, 2.0]]]},
        properties={"class": "湖泊"}))
    second = record_interpretation_revision(
        doc, target_kind="integrated_facies", target_layer_id="L1", layer=layer,
        actor="geologist-b", now="t3")
    assert second is not None
    assert second.parent_revision_id == first.revision_id
    assert second.delta["features"] == 1
    chain = revisions_for_layer(doc, "L1")
    assert [r.revision_id for r in chain] == [first.revision_id, second.revision_id]
    assert latest_revision_for_layer(doc, "L1").revision_id == second.revision_id


def test_revision_answers_goal_questions():
    """goal §13：谁改的？基于哪个 factor/constraint？从哪个版本开始？"""
    doc = ProjectDocument.new("t")
    layer = _layer()
    record_interpretation_revision(
        doc, target_kind="integrated_facies", target_layer_id="L1", layer=layer,
        actor="expert-wang", now="2026-09-10T10:00:00",
        base_kind="fusion", base_version_id="ver_fusion_9",
        evidence_refs=["factor:task_7:ver_3", "constraints:T1组:ver_c2"])
    summary = revision_summary(doc, "L1")
    assert summary["latest_actor"] == "expert-wang"
    assert summary["base_version_id"] == "ver_fusion_9"
    assert "factor:task_7:ver_3" in summary["evidence_refs"]
    assert summary["revisions"] == 1


def test_fingerprint_stable_and_counts_vertices():
    layer_a, layer_b = _layer("a"), _layer("b")
    fa, ca = layer_content_fingerprint(layer_a)
    fb, cb = layer_content_fingerprint(layer_b)
    assert fa == fb  # 同内容同指纹
    assert ca == {"features": 1, "vertices": 4}


def test_fingerprint_supports_features_method_layers():
    class MethodLayer:
        def features(self):
            return _layer().features
    digest, counts = layer_content_fingerprint(MethodLayer())
    assert counts["features"] == 1


# ------------------------------------------------------------ 综合解释一等成果


def test_create_and_find_interpretation():
    doc = ProjectDocument.new("t")
    created = create_integrated_interpretation(
        doc, name="综合解释 v1", layer_id="L9", input_set_id="ciset_1",
        fusion_version_id="ver_f1", class_schema=["低", "中", "高"],
        conflicts={"high_conflict_fraction": 0.12})
    assert created.maturity == "draft"
    assert created.committed_version_id == ""
    found = find_by_layer(doc, "L9")
    assert found is not None and found.interpretation_id == created.interpretation_id
    assert interpretations_for_document(doc)[0].conflicts["high_conflict_fraction"] == 0.12
    with pytest.raises(ValueError, match="不可重复创建"):
        create_integrated_interpretation(doc, name="dup", layer_id="L9")


def test_interpretation_summary_honest_for_missing():
    doc = ProjectDocument.new("t")
    assert interpretation_summary(doc, "nope")["status"] == "missing"


def test_commit_integrated_interpretation_registers_version_and_revision(tmp_path):
    from paleo_workbench.catalog.service import DataCatalogService

    catalog = DataCatalogService.open(tmp_path / "catalog")
    try:
        doc = ProjectDocument.new("t")
        layer = _layer("L5", polys=2)
        doc.user_vector_layers.append(layer)
        interpretation = create_integrated_interpretation(
            doc, name="综合解释", layer_id="L5", input_set_id="ciset_1",
            fusion_version_id="ver_seed")
        version_id = commit_integrated_interpretation(
            doc, interpretation, layer, catalog,
            actor="expert", now="2026-09-10T12:00:00",
            evidence_refs=["factor:t:ver_1"])
        assert version_id.startswith("ver_")
        refreshed = find_by_layer(doc, "L5")
        assert refreshed.committed_version_id == version_id
        assert refreshed.run_id
        assert refreshed.revision_ids  # commit 记录了 revision
        # run 输入含 fusion 种子版本 + 操作词汇进入 lineage。
        run = catalog.get_run(refreshed.run_id)
        assert run.operation == "integrated_interpretation"
        assert "ver_seed" in run.input_version_ids
        # 二次提交（几何变化）→ 新版本 + 第二条 revision。
        layer.features.append(UserVectorFeature(
            id="fx", geometry={"type": "Polygon", "coordinates": [
                [[5.0, 5.0], [6.0, 5.0], [6.0, 6.0], [5.0, 5.0]]]},
            properties={}))
        version_2 = commit_integrated_interpretation(
            doc, refreshed, layer, catalog, actor="expert", now="t2")
        assert version_2 != version_id
        refreshed_2 = find_by_layer(doc, "L5")
        assert refreshed_2.committed_version_id == version_2
        assert len(refreshed_2.revision_ids) == 2
        assert refreshed_2.has_uncommitted_edits is False
    finally:
        catalog.close()


def test_commit_refuses_empty_geometry_and_missing_catalog():
    doc = ProjectDocument.new("t")
    empty = UserVectorLayer(id="L0", name="空")
    doc.user_vector_layers.append(empty)
    interpretation = create_integrated_interpretation(
        doc, name="空解释", layer_id="L0")
    with pytest.raises(ValueError, match="目录服务不可用"):
        commit_integrated_interpretation(doc, interpretation, empty, None)
    # 有 catalog 但空几何 → 拒绝。
    class _NullCatalog:
        def list_assets(self):
            return []
    with pytest.raises(ValueError, match="没有要素"):
        commit_integrated_interpretation(
            doc, interpretation, empty, _NullCatalog())
