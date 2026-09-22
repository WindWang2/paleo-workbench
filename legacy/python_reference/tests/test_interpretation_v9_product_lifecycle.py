"""V9 — MapProduct 生命周期阶梯 + 产品级 QA + 新 harness 动作（goal §30/§31）。"""
from __future__ import annotations

import pytest

from paleo_workbench.project.models import (
    FACTOR_TASK_STATUS_COMPLETE,
    FactorMapTask,
    MapProductRecord,
    ProjectDocument,
)


def _complete_factor(project: ProjectDocument, *, version: str = "ver_f1") -> FactorMapTask:
    task = FactorMapTask(
        name="砂岩厚度", target_horizon="T1", factor_type="砂岩厚度",
        method="idw", status=FACTOR_TASK_STATUS_COMPLETE, source_kind="real")
    task.grid_artifact_version_id = version
    task.quality_metrics = {"unit": "m", "variance_min": 0.1}
    project.factor_map_tasks.append(task)
    return task
from paleo_workbench.workflow.map_product import (
    LIFECYCLE_DRAFT,
    LIFECYCLE_FROZEN,
    LIFECYCLE_PUBLISHED,
    LIFECYCLE_REVIEWED,
    effective_lifecycle,
    freeze_map_product,
    product_qa,
    publish_map_product,
    review_map_product,
    supersede_map_product,
)


def _record(**kwargs) -> MapProductRecord:
    return MapProductRecord(product_name="p", **kwargs)


# ------------------------------------------------------------- 阶梯


def test_lifecycle_ladder_requires_ordered_transitions():
    project = ProjectDocument.new("t")
    task = _complete_factor(project)
    record = _record(run_id="run_1", output_version_id="ver_out",
                     factor_task_ids=[task.id])
    assert effective_lifecycle(record) == LIFECYCLE_DRAFT
    # draft 直接 publish → 拒绝（必须 review → freeze）。
    with pytest.raises(ValueError, match="only frozen products publish"):
        publish_map_product(record, project)
    review_map_product(record, project)
    assert effective_lifecycle(record) == LIFECYCLE_REVIEWED
    freeze_map_product(record)
    assert effective_lifecycle(record) == LIFECYCLE_FROZEN
    # reviewed 不能再 review（只有 draft 可评审）。
    with pytest.raises(ValueError, match="only draft products can be reviewed"):
        review_map_product(record, project)


def test_legacy_records_reconcile_on_read():
    legacy_frozen = _record(frozen=True)
    assert effective_lifecycle(legacy_frozen) == LIFECYCLE_FROZEN
    legacy_superseded = _record(status="superseded")
    assert effective_lifecycle(legacy_superseded) == "superseded"
    legacy_final = _record(status="final")
    assert effective_lifecycle(legacy_final) == LIFECYCLE_DRAFT  # 组装≠评审


def test_published_is_immutable_freeze_refused():
    record = _record(lifecycle=LIFECYCLE_PUBLISHED)
    with pytest.raises(ValueError, match="published products are immutable"):
        freeze_map_product(record, frozen=True)


def test_unfreeze_returns_to_draft():
    record = _record(lifecycle=LIFECYCLE_FROZEN)
    freeze_map_product(record, frozen=False)
    assert effective_lifecycle(record) == LIFECYCLE_DRAFT
    assert record.frozen is False


# ------------------------------------------------------------- 产品级 QA


def test_product_qa_severity_vocabulary_and_staleness():
    project = ProjectDocument.new("t")
    # 完整溯源的记录（无 factor）→ input ERROR（无因素）。
    record = _record(run_id="run_1", output_version_id="ver_1")
    report = product_qa(record, project)
    assert report["counts"]["error"] >= 1
    assert report["status"] == "error"
    # 无溯源记录 → provenance ERROR×2。
    bare = _record()
    report = product_qa(bare, project)
    stages = {f["stage"] for f in report["findings"]
              if f["severity"] == "error"}
    assert "provenance" in stages


def test_review_refuses_error_findings():
    project = ProjectDocument.new("t")
    record = _record(run_id="run_1", output_version_id="ver_1")  # 无 factor → ERROR
    with pytest.raises(ValueError, match="cannot pass review"):
        review_map_product(record, project)
    assert effective_lifecycle(record) == LIFECYCLE_DRAFT  # 评审失败不留半阶


class _GhostCatalog:
    """所有版本解析失败（载荷缺失）——BLOCKER 条件。"""

    def resolve_version(self, version_id):
        return None

    def list_versions(self, asset_id):
        return []

    def resolve_run(self, run_id):
        return None


def test_publish_carries_product_qa_and_blocker_gate():
    project = ProjectDocument.new("t")
    task = _complete_factor(project, version="ver_ghost")
    record = _record(run_id="run_1", output_version_id="ver_out",
                     factor_task_ids=[task.id],
                     lifecycle=LIFECYCLE_FROZEN, frozen=True)
    with pytest.raises(ValueError, match="BLOCKER"):
        publish_map_product(record, project, accept_warnings=True,
                            catalog=_GhostCatalog())  # BLOCKER 不可豁免


# ------------------------------------------------------------- 动作面


def test_actions_registered_with_verifiers():
    from paleo_workbench.harness.registry import get_action_registry

    registry = get_action_registry()
    expected = {
        "compilation.create_input_set", "compilation.freeze_input_set",
        "interpretation.commit", "interpretation.compare",
        "map_product.assemble", "map_product.review", "map_product.publish",
    }
    ids = {s.action_id for s in registry.specs()}
    assert expected <= ids
    # WRITE 动作 verifier 声明（goal §26）。
    for action_id in ("interpretation.commit", "map_product.assemble"):
        spec = next(s for s in registry.specs() if s.action_id == action_id)
        assert spec.verifier is not None, action_id


def test_assembly_fingerprint_includes_v9_refs():
    from paleo_workbench.workflow.map_product import MapProductAssembly

    project = ProjectDocument.new("t")
    base = MapProductAssembly(product_name="p", factor_task_ids=["t1"])
    enriched = MapProductAssembly(
        product_name="p", factor_task_ids=["t1"],
        fusion_version_id="ver_f", integrated_interpretation_id="iint_1",
        input_set_id="ciset_1")
    # V9 引用进入配方 → 不同指纹（科学陈述不同）。
    assert base.scientific_fingerprint(project) != enriched.scientific_fingerprint(project)


def test_supersede_syncs_lifecycle():
    project = ProjectDocument.new("t")
    record = _record(id="p1")
    project.map_products.append(record)
    successor = _record(id="p2")
    project.map_products.append(successor)
    supersede_map_product(record, project, successor=successor)
    assert record.lifecycle == "superseded"
