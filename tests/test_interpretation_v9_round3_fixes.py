"""V9 — Round 3 对抗性评审修复的回归测试（R3-F1…F9）。"""
from __future__ import annotations

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.mapping_workspace.dependencies import (
    MappingDependencyService,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import (
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.project.models import (
    FACTOR_TASK_STATUS_COMPLETE,
    FactorMapTask,
    MapProductRecord,
    ProjectDocument,
)
from paleo_workbench.workflow.interpretation.compilation import (
    create_input_set,
    freeze_input_set,
    validate_input_set,
)
from paleo_workbench.workflow.interpretation.evidence import resolve_evidence
from paleo_workbench.workflow.map_product import (
    freeze_map_product,
    product_qa,
    publish_map_product,
    review_map_product,
)


class _FakeVersion:
    def __init__(self, version_id, asset_id="asset"):
        self.id = version_id
        self.asset_id = asset_id


class _FakeCatalog:
    def __init__(self, versions=None):
        self._versions = versions or {}

    def resolve_version(self, version_id):
        return self._versions.get(version_id)

    def list_versions(self, asset_id):
        return [v for v in self._versions.values() if v.asset_id == asset_id]

    def get_run(self, run_id):
        return None


def _doc_with_factor(version: str = "ver_f1"):
    doc = ProjectDocument.new("t")
    task = FactorMapTask(
        name="砂厚", target_horizon="T1", factor_type="砂岩厚度",
        method="idw", status=FACTOR_TASK_STATUS_COMPLETE, source_kind="real")
    task.grid_artifact_version_id = version
    task.quality_metrics = {"unit": "m", "variance_min": 0.1}
    doc.factor_map_tasks.append(task)
    return doc, task


# ---------------------------------------------- R3-F2: 冻结重写无版本选择器


def test_freeze_rewrites_versionless_factor_selector():
    doc, task = _doc_with_factor()
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1"),
                            "ver_f2": _FakeVersion("ver_f2")})
    # 无版本选择器：解析回退任务当前版本 → pin 可行。
    input_set = create_input_set(doc, [f"factor:{task.id}"], catalog=catalog)
    frozen = freeze_input_set(input_set, doc, catalog=catalog)
    entry = frozen.entries[0]
    assert entry.selector == f"factor:{task.id}:ver_f1"
    # 重插值 → selector 携带版本 → 融合/评估都能看见 pin≠current。
    task.grid_artifact_version_id = "ver_f2"
    resolution = resolve_evidence(doc, entry.selector, catalog=catalog)
    assert resolution.status.value == "stale"  # R3-F6 同步覆盖


# ---------------------------------------------- R3-F4: 冻结回滚含选择器


def test_freeze_refusal_rolls_back_selector_rewrite(tmp_path):
    catalog = DataCatalogService.open(tmp_path / "cat")
    try:
        doc, task = _doc_with_factor()
        from paleo_workbench.project.models import ConstraintLayers, ConstraintLine

        group = ConstraintLayers(id="cg", name="g")
        group.lines = [ConstraintLine(
            id="l", name="f", role="break", coordinates=[[0.0, 0.0], [1.0, 1.0]])]
        doc.constraint_layers.append(group)
        from paleo_workbench.workflow.constraint_versions import (
            commit_constraint_group,
        )

        commit_constraint_group(doc, catalog, group, actor="t")
        # [可钉约束(浮动), 不可钉证据] → 拒绝后浮动条目必须回到原选择器。
        input_set = create_input_set(
            doc, ["constraints:current", "factor:ghost:v"], catalog=catalog)
        with pytest.raises(ValueError, match="无法钉住版本"):
            freeze_input_set(input_set, doc, catalog=catalog)
        assert input_set.entries[0].selector == "constraints:current"
        assert input_set.entries[0].pinned_version_id == ""
    finally:
        catalog.close()


# ---------------------------------------------- R3-F3: 缺失 factor 不读作 CURRENT


def test_integrated_missing_factor_is_not_current():
    doc, task = _doc_with_factor()
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="L1", role=LayerRole.INTEGRATED_FACIES))
    state.compilation_input_set["evidence"] = f"factor:{task.id}:ver_f1"
    doc.factor_map_tasks.clear()  # 任务被删除
    summary = MappingDependencyService().evaluate(doc, state, None)
    entry = summary.get("integrated:L1")
    assert entry is not None
    assert entry.status.value == "missing_input"


# ---------------------------------------------- R3-F1: publish 阻断 QA ERROR


def test_publish_refused_on_staleness_error_findings():
    doc, task = _doc_with_factor()
    from paleo_workbench.workflow.map_product import MapProductAssembly

    record = MapProductRecord(
        product_name="p", factor_task_ids=[task.id],
        run_id="run_1", output_version_id="ver_o1",
        lifecycle="frozen", frozen=True)
    record.scientific_fingerprint = MapProductAssembly(
        product_name="p", factor_task_ids=[task.id]).scientific_fingerprint(doc)
    doc.map_products.append(record)
    # 指纹按下烙印；随后 factor 任务被删除 → 产品级 QA ERROR（输入缺失）
    # 而非 BLOCKER（版本不可解析）——publish 必须阻断（R3-F1）。
    doc.factor_map_tasks.clear()
    report = product_qa(record, doc, catalog=_FakeCatalog())
    assert report["has_error"]
    assert not report["has_blocker"]
    with pytest.raises(ValueError, match="cannot be published"):
        publish_map_product(record, doc, catalog=_FakeCatalog())


# ---------------------------------------------- R3-F7: 无目录 → UNKNOWN


def test_phase1_draft_without_catalog_is_unknown():
    doc = ProjectDocument.new("t")
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="D1", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_raw1"))
    summary = MappingDependencyService().evaluate(doc, state, None)
    entry = summary.get("phase1_draft:D1")
    assert entry.status.value == "unknown"
    assert "无目录" in entry.detail


# ---------------------------------------------- R3-F6: factor 取代 → STALE


def test_factor_pin_supersession_detected():
    doc, task = _doc_with_factor(version="ver_f2")
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1"),
                            "ver_f2": _FakeVersion("ver_f2")})
    resolution = resolve_evidence(
        doc, f"factor:{task.id}:ver_f1", catalog=catalog)
    assert resolution.status.value == "stale"
    assert "ver_f2" in resolution.detail
    # 校验也不再把取代读作 ready。
    from paleo_workbench.workflow.interpretation.compilation import (
        create_input_set,
        validate_input_set,
    )

    input_set = create_input_set(
        doc, [f"factor:{task.id}:ver_f1"], catalog=catalog)
    validation = validate_input_set(input_set, doc, catalog=catalog)
    assert validation.verdict == "ready"  # STALE 可用（评估层另行标记）
    statuses = [r.status.value for r in validation.resolutions]
    assert "stale" in statuses
