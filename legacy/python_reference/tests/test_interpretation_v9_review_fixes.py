"""V9 — 评审 Round 1/2 P0/P1 修复的回归测试。"""
from __future__ import annotations

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.models import (
    FACTOR_TASK_STATUS_COMPLETE,
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    MapProductRecord,
    ProjectDocument,
)
from paleo_workbench.workflow.interpretation.compilation import (
    create_input_set,
    evidence_view,
    freeze_input_set,
    validate_input_set,
)
from paleo_workbench.workflow.map_product import (
    effective_lifecycle,
    freeze_map_product,
    product_staleness,
    publish_map_product,
    review_map_product,
)
from paleo_workbench.workflow.interpretation.evidence import (
    format_evidence_selector,
    parse_evidence_selector,
)


# --------------------------------------------- R1-F1/R2-F4: 多组浮动 pin


def _two_group_document():
    doc = ProjectDocument.new("t")
    for gid in ("g1", "g2"):
        group = ConstraintLayers(id=gid, name=f"约束{gid}")
        group.lines = [ConstraintLine(
            id="l", name="断层", role="break",
            coordinates=[[0.0, 0.0], [1.0, 1.0]])]
        doc.constraint_layers.append(group)
    return doc


def test_multi_group_floating_constraints_refused_at_freeze(tmp_path):
    """多组提交后 constraints:current 冻结必须拒绝（不许暗洞）。"""
    catalog = DataCatalogService.open(tmp_path / "catalog")
    try:
        doc = _two_group_document()
        from paleo_workbench.workflow.constraint_versions import (
            commit_constraint_group,
        )

        for group in doc.constraint_layers:
            commit_constraint_group(doc, catalog, group, actor="t")
        input_set = create_input_set(doc, ["constraints:current"],
                                     catalog=catalog)
        with pytest.raises(ValueError, match="无法安全钉住"):
            freeze_input_set(input_set, doc, catalog=catalog)
        assert not input_set.frozen
        assert all(e.pinned_version_id == "" for e in input_set.entries)
    finally:
        catalog.close()


def test_single_group_floating_pin_rewrites_explicit_selector(tmp_path):
    """单组提交：冻结把浮动条目重写为显式 constraints:<group>:<ver>。"""
    catalog = DataCatalogService.open(tmp_path / "catalog")
    try:
        doc = _two_group_document()
        doc.constraint_layers.pop()  # 只留一个组
        from paleo_workbench.workflow.constraint_versions import (
            commit_constraint_group,
        )

        group = doc.constraint_layers[0]
        report = commit_constraint_group(doc, catalog, group, actor="t")
        input_set = create_input_set(doc, ["constraints:current"],
                                     catalog=catalog)
        frozen = freeze_input_set(input_set, doc, catalog=catalog)
        entry = frozen.entries[0]
        assert entry.selector == f"constraints:{group.id}:{report.version_id}"
        # 重写后的选择器可解析、可再次验证（R1-F2：绝不产出 constraints::ver）。
        validation = validate_input_set(frozen, doc, catalog=catalog)
        assert validation.verdict == "ready"
    finally:
        catalog.close()


# --------------------------------------------- R1-F6/F7: 阶梯守卫


def _product_doc():
    doc = ProjectDocument.new("t")
    task = FactorMapTask(
        name="砂厚", target_horizon="T1", factor_type="砂岩厚度",
        method="idw", status=FACTOR_TASK_STATUS_COMPLETE, source_kind="real")
    task.grid_artifact_version_id = "ver_f1"
    task.quality_metrics = {"unit": "m", "variance_min": 0.1}
    doc.factor_map_tasks.append(task)
    record = MapProductRecord(
        product_name="p", factor_task_ids=[task.id],
        run_id="run_1", output_version_id="ver_o1")
    from paleo_workbench.workflow.map_product import MapProductAssembly

    record.scientific_fingerprint = MapProductAssembly(
        product_name="p", factor_task_ids=[task.id],
    ).scientific_fingerprint(doc)
    doc.map_products.append(record)
    return doc, record


def test_draft_cannot_skip_review_into_freeze():
    doc, record = _product_doc()
    with pytest.raises(ValueError, match="review before freezing"):
        freeze_map_product(record)  # draft → 直接冻结：拒绝（阶梯）


def test_published_cannot_be_unfrozen():
    doc, record = _product_doc()
    review_map_product(record, doc)
    freeze_map_product(record)
    publish_map_product(record, doc)
    with pytest.raises(ValueError, match="immutable"):
        freeze_map_product(record, frozen=False)  # 发布不可解冻


# --------------------------------------------- R1-F5: V9 引用不砖死发布


def test_v9_refs_do_not_brick_staleness_or_publish():
    from paleo_workbench.workflow.map_product import MapProductAssembly

    doc, record = _product_doc()
    # 带完整 V9 引用组装的记录（引用持久化在记录上）。
    record.fusion_version_id = "ver_fusion"
    record.integrated_interpretation_id = "iint_1"
    record.input_set_id = "ciset_1"
    assembly = MapProductAssembly(
        product_name=record.product_name,
        factor_task_ids=list(record.factor_task_ids),
        fusion_version_id=record.fusion_version_id,
        integrated_interpretation_id=record.integrated_interpretation_id,
        input_set_id=record.input_set_id,
    )
    record.scientific_fingerprint = assembly.scientific_fingerprint(doc)
    staleness = product_staleness(record, doc)
    assert staleness["stale"] is False  # 引用持久化 → 重建指纹一致
    review_map_product(record, doc)
    freeze_map_product(record)
    report = publish_map_product(record, doc)
    assert report["ok"] is True


# --------------------------------------------- R1-F8: 'current' 组名守卫


def test_group_named_current_without_version_refused():
    from paleo_workbench.workflow.interpretation.evidence import EvidenceKind

    with pytest.raises(ValueError, match="collides"):
        format_evidence_selector(
            EvidenceKind.CONSTRAINT_GROUP, "current", "")


# --------------------------------------------- R2-F1: evidence_view 适配


def test_evidence_view_prefers_structured_active_set():
    from paleo_workbench.mapping_workspace.stage_state import (
        MappingWorkspaceState,
    )
    from paleo_workbench.workflow.interpretation.compilation import (
        create_input_set_shell_from_legacy,
        persist_input_set,
    )

    doc, record = _product_doc()
    task = doc.factor_map_tasks[0]
    state = MappingWorkspaceState()
    state.compilation_input_set["legacy 条目"] = f"factor:{task.id}:ver_f1"
    shell = create_input_set_shell_from_legacy(doc, state, created_by="t")
    assert shell is not None
    view = evidence_view(doc, state)
    assert f"factor:{task.id}:ver_f1" in view.values()
    # 新选择只进结构化集 → 适配器立即反映（不再只读 legacy dict）。
    from paleo_workbench.workflow.interpretation.compilation import (
        CompilationInputSetEntry,
    )

    shell.entries.append(CompilationInputSetEntry(
        selector="constraints:current", label="约束",
        evidence_kind="constraint_group"))
    persist_input_set(doc, shell)
    view = evidence_view(doc, state)
    assert "constraints:current" in view.values()
