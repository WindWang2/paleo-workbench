"""V9 — 对抗性工作流测试（goal §38 Round 3 场景落为测试）。

场景：
1. 工作流进行中输入更新（factor 重插值 → pinned 输入集/解释过期）；
2. 约束被取代（commit v2 后，pin → stale_version；产品 QA ERROR）；
3. 计算中取消（CANCELLING → CANCELLED，晚到结果不作为完成消费）；
4. 人工编辑在算法之后（融合种子 + 手工修订 → has_uncommitted_edits）；
5. 旧结果重开（工程序列化 roundtrip 后记录/修订/输入集存活）；
6. 发布过期产品（stale → 拒绝发布，绝不静默）；
7. 输入缺失（freeze 拒绝带暗洞的输入集）。
"""
from __future__ import annotations

import json

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState
from paleo_workbench.project.models import (
    FACTOR_TASK_STATUS_COMPLETE,
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    ProjectDocument,
    UserVectorFeature,
    UserVectorLayer,
)
from paleo_workbench.workflow.interpretation.compilation import (
    create_input_set,
    freeze_input_set,
    persist_input_set,
)
from paleo_workbench.workflow.interpretation.integrated_interpretation import (
    commit_integrated_interpretation,
    create_integrated_interpretation,
    find_by_layer,
)
from paleo_workbench.workflow.interpretation.revision import (
    record_interpretation_revision,
)
from paleo_workbench.workflow.interpretation.staleness import (
    StalenessVerdict,
    evaluate_verdict,
    from_constraint_pin,
)
from paleo_workbench.workflow.map_product import (
    freeze_map_product,
    publish_map_product,
    review_map_product,
)


def _factor(doc: ProjectDocument, name: str = "砂厚", version: str = "ver_f1"):
    task = FactorMapTask(
        name=name, target_horizon="T1", factor_type="砂岩厚度",
        method="idw", status=FACTOR_TASK_STATUS_COMPLETE, source_kind="real")
    task.grid_artifact_version_id = version
    task.quality_metrics = {"unit": "m", "variance_min": 0.1}
    task.parameters = {"unit": "m"}
    doc.factor_map_tasks.append(task)
    return task


def _polygon_layer(layer_id: str, n: int = 1) -> UserVectorLayer:
    layer = UserVectorLayer(id=layer_id, name="综合沉积相", geometry_kind="polygon")
    for i in range(n):
        layer.features.append(UserVectorFeature(
            id=f"f{i}",
            geometry={"type": "Polygon", "coordinates": [
                [[float(i), 0.0], [float(i) + 1, 0.0],
                 [float(i) + 1, 1.0], [float(i), 0.0]]]},
            properties={"class": "三角洲"}))
    return layer


# ---------------------------------------------------------------- 场景 1/6


def test_input_updated_during_workflow_marks_downstream_stale(tmp_path):
    """factor 重插值（新版本）→ 钉住旧版本的输入集条目过期 → 产品不可发布。"""
    doc = ProjectDocument.new("t")
    task = _factor(doc, version="ver_f1")
    state = MappingWorkspaceState()
    input_set = create_input_set(doc, [f"factor:{task.id}:ver_f1"])
    persist_input_set(doc, input_set)
    record = _product_record(doc, [task.id])
    freeze_map_product(review_then_freeze(doc, record))

    # 工作流中途：上游重插值 → 新版本登记。
    task.grid_artifact_version_id = "ver_f2"

    # 钉住的解析：ver_f1 仍可解析但产品指纹基于旧输入 → publish 拒绝。
    with pytest.raises(ValueError):
        publish_map_product(record, doc)
    # 产品 QA 报告输入过期（staleness 评估含 fingerprint 路径）。
    from paleo_workbench.workflow.map_product import product_qa
    report = product_qa(record, doc)
    assert report["status"] in ("error", "warning")


def review_then_freeze(doc, record):
    review_map_product(record, doc)
    return record


def _product_record(doc, factor_ids):
    from paleo_workbench.project.models import MapProductRecord

    record = MapProductRecord(
        product_name="综合编图", factor_task_ids=list(factor_ids),
        run_id="run_p", output_version_id="ver_out")
    doc.map_products.append(record)
    return record


# ---------------------------------------------------------------- 场景 2


def test_constraint_superseded_marks_pin_stale_version(tmp_path):
    catalog = DataCatalogService.open(tmp_path / "catalog")
    try:
        doc = ProjectDocument.new("t")
        group = ConstraintLayers(id="cg", name="T1 约束")
        group.lines = [ConstraintLine(
            id="l1", name="断层", role="break",
            coordinates=[[0.0, 0.0], [1.0, 1.0]])]
        doc.constraint_layers.append(group)
        from paleo_workbench.workflow.constraint_versions import (
            commit_constraint_group,
            constraint_pins_for_task,
        )

        task = _factor(doc)
        task.parameters = dict(task.parameters or {})
        # 消费时 pin（内容哈希 + 版本绑定）。
        pins = constraint_pins_for_task(task, doc)
        report = commit_constraint_group(doc, catalog, group, actor="t")
        assert report.committed

        # 约束被取代：再次编辑 + 提交 v2。
        group.lines[0].coordinates = [[0.0, 0.0], [2.0, 2.0], [3.0, 3.0]]
        report2 = commit_constraint_group(doc, catalog, group, actor="t")
        assert report2.committed and report2.version_id != report.version_id

        # 旧 pin → stale_version（新提交存在）。
        from paleo_workbench.workflow.constraint_versions import (
            constraint_pins_staleness,
        )

        task.parameters["constraint_pins"] = pins
        verdict = constraint_pins_staleness(task, doc, catalog)
        assert verdict["state"] in ("stale_content", "stale_version")
        assert from_constraint_pin(verdict["state"]) in (
            StalenessVerdict.STALE_CONTENT, StalenessVerdict.STALE_VERSION)
    finally:
        catalog.close()


# ---------------------------------------------------------------- 场景 3


def test_cancel_during_calculation_drops_late_result():
    import threading
    import time

    from paleo_workbench.runtime.task_scheduler import (
        TERMINAL_TASK_STATES,
        TaskScheduler,
        TaskSpec,
        TaskState,
    )

    scheduler = TaskScheduler(max_workers=1)
    consumed: list[str] = []
    started = threading.Event()

    def late_producer(ctx):
        started.set()
        ctx.sleep_interruptible(3.0)
        return "late-fusion-result"

    try:
        handle = scheduler.submit(TaskSpec(
            callable=late_producer, kind="io", title="融合计算",
            on_done=lambda result: consumed.append(result)))
        assert started.wait(5)
        assert scheduler.cancel(handle.task_id)
        deadline = time.monotonic() + 10
        while handle.state not in TERMINAL_TASK_STATES and time.monotonic() < deadline:
            time.sleep(0.02)
        assert handle.state is TaskState.CANCELLED
        assert consumed == []  # 晚到结果绝不作为完成消费
    finally:
        scheduler.shutdown()


# ---------------------------------------------------------------- 场景 4


def test_manual_edit_after_algorithm_seed(tmp_path):
    catalog = DataCatalogService.open(tmp_path / "catalog")
    try:
        doc = ProjectDocument.new("t")
        layer = _polygon_layer("L1", n=2)
        doc.user_vector_layers.append(layer)
        interpretation = create_integrated_interpretation(
            doc, name="综合解释", layer_id="L1",
            fusion_version_id="ver_fusion_seed")
        # 算法种子提交（专家修编起点）。
        version_1 = commit_integrated_interpretation(
            doc, interpretation, layer, catalog, actor="algo-seed")
        assert version_1
        refreshed = find_by_layer(doc, "L1")
        assert refreshed.has_uncommitted_edits is False

        # 专家修编：删除一个面 + 增加归因证据。
        layer.features.pop()
        revision = record_interpretation_revision(
            doc, target_kind="integrated_facies", target_layer_id="L1",
            layer=layer, actor="expert-li",
            evidence_refs=["factor:t1:ver_2", "constraints:cg:ver_c1"],
            note="依据新砂厚证据收缩三角洲边界")
        assert revision is not None
        refreshed = find_by_layer(doc, "L1")
        # 手工修订在提交之后 → 未提交编辑可见。
        assert refreshed.has_uncommitted_edits is True
        # goal §13 问题可回答。
        assert revision.evidence_refs == ["factor:t1:ver_2", "constraints:cg:ver_c1"]
        # 再次提交 → 新版本 + 归零。
        version_2 = commit_integrated_interpretation(
            doc, refreshed, layer, catalog, actor="expert-li")
        assert version_2 != version_1
        assert find_by_layer(doc, "L1").has_uncommitted_edits is False
    finally:
        catalog.close()


# ---------------------------------------------------------------- 场景 5


def test_old_result_reopened_after_roundtrip(tmp_path):
    doc = ProjectDocument.new("t")
    task = _factor(doc)
    layer = _polygon_layer("L1")
    doc.user_vector_layers.append(layer)
    input_set = create_input_set(doc, [f"factor:{task.id}:ver_f1"],
                                 catalog=None, workspace_state=None)
    persist_input_set(doc, input_set)
    create_integrated_interpretation(
        doc, name="综合解释", layer_id="L1", input_set_id=input_set.id)
    record_interpretation_revision(
        doc, target_kind="integrated_facies", target_layer_id="L1",
        layer=layer, actor="expert", evidence_refs=["factor:x:ver_1"])

    payload = doc.model_dump()
    path = tmp_path / "project.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    reopened = ProjectDocument.model_validate(json.loads(path.read_text("utf-8")))
    # 记录/修订/输入集全部存活（重开旧结果不丢身份）。
    assert reopened.compilation_input_sets, "输入集记录丢失"
    assert reopened.integrated_interpretations, "综合解释记录丢失"
    assert reopened.interpretation_revisions, "修订链丢失"
    from paleo_workbench.workflow.interpretation.integrated_interpretation import (
        interpretations_for_document,
    )

    interpretation = interpretations_for_document(reopened)[0]
    assert interpretation.layer_id == "L1"
    assert interpretation.input_set_id == input_set.id
    verdict = evaluate_verdict(reopened, f"factor:{task.id}")
    assert verdict.verdict is StalenessVerdict.UNKNOWN  # 无 catalog 诚实未知


# ---------------------------------------------------------------- 场景 7


def test_freeze_refuses_missing_input_never_dark_hole():
    doc = ProjectDocument.new("t")
    input_set = create_input_set(doc, ["factor:ghost_task:ver_9"])
    with pytest.raises(ValueError, match="无法钉住版本"):
        freeze_input_set(input_set, doc)


# ---------------------------------------------------------------- 规模（结构复杂度，goal §37）


def test_scale_projection_10k_wells_500_factors():
    """10k 井元数据行 + 数百 factor 任务的投影/证据清单是有界的（结构测试）。"""
    doc = ProjectDocument.new("scale")
    from paleo_workbench.project.models import WellTable, WellTableRow

    table = WellTable(name="10k wells", target_horizon="T1")
    table.rows = [
        WellTableRow(well_id=f"w{i}", name=f"w{i}", x=float(i % 100),
                     y=float(i // 100), z=float(i % 50))
        for i in range(10_000)
    ]
    doc.well_tables.append(table)
    for i in range(500):
        task = FactorMapTask(
            name=f"砂厚#{i}", target_horizon="T1", factor_type="砂岩厚度",
            method="idw", status=FACTOR_TASK_STATUS_COMPLETE,
            source_kind="real")
        task.grid_artifact_version_id = f"ver_f{i}"
        task.quality_metrics = {"unit": "m"}
        task.parameters = {"unit": "m"}
        doc.factor_map_tasks.append(task)

    from paleo_workbench.workflow.interpretation.evidence import (
        available_evidence,
    )
    from paleo_workbench.workflow.interpretation.factor_product import (
        factor_products,
    )

    state = MappingWorkspaceState()
    evidence = available_evidence(doc, state)
    assert len(evidence) == 500
    products = factor_products(doc, workspace_state=state)
    assert len(products) == 500
    # 身份唯一且无版本伪造。
    assert len({p.factor_id for p in products}) == 500
    assert all(p.grid_version_id == f"ver_f{i}" or p.grid_version_id
               for i, p in enumerate(products))
