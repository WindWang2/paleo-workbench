"""V9 — CompilationInputSet：pinned 输入集 + freeze + 预测证据（P0-3）。"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState
from paleo_workbench.project.models import (
    FactorMapTask,
    PredictionTask,
    ProjectDocument,
)
from paleo_workbench.workflow.interpretation.compilation import (
    CompilationInputSet,
    active_input_set,
    create_input_set,
    freeze_input_set,
    input_sets_for_document,
    persist_input_set,
    validate_input_set,
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


def _document() -> ProjectDocument:
    doc = ProjectDocument.new("t")
    task = FactorMapTask(
        name="砂厚", target_horizon="T1", factor_type="砂岩厚度",
        method="idw", status="complete", source_kind="real")
    task.grid_artifact_version_id = "ver_f1"
    doc.factor_map_tasks.append(task)
    pred = PredictionTask(name="地震相预测", status="complete")
    doc.prediction_tasks.append(pred)
    return doc


def test_create_input_set_records_honest_snapshots():
    doc = _document()
    task = doc.factor_map_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1")})
    input_set = create_input_set(
        doc,
        [f"factor:{task.id}:ver_f1", "constraints:current",
         f"prediction:{doc.prediction_tasks[0].id}"],
        created_by="tester", now="2026-09-10T00:00:00", catalog=catalog)
    statuses = {e.selector: e.status_at_add for e in input_set.entries}
    assert statuses[f"factor:{task.id}:ver_f1"] == "resolved"
    assert statuses["constraints:current"] == "unknown"  # 未提交不猜
    assert statuses[f"prediction:{doc.prediction_tasks[0].id}"] == "unpinned"


def test_create_input_set_rejects_malformed_selector():
    doc = _document()
    with pytest.raises(ValueError):
        create_input_set(doc, ["bogus-selector"])


def test_validate_verdicts_block_and_degrade():
    doc = _document()
    task = doc.factor_map_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1")})
    blocked = validate_input_set(
        create_input_set(doc, ["factor:nope:ver_x"], catalog=catalog), doc,
        catalog=catalog)
    assert blocked.verdict == "blocked"
    # 从未提交的约束 = UNKNOWN（诚实）→ blocked（科学运行不可用未知输入）。
    uncommitted = validate_input_set(
        create_input_set(doc, ["constraints:current"], catalog=catalog), doc,
        catalog=catalog)
    assert uncommitted.verdict == "blocked"
    # 预测（run 级溯源、无文件版本）→ UNPINNED → degraded。
    degraded = validate_input_set(
        create_input_set(
            doc, [f"prediction:{doc.prediction_tasks[0].id}"], catalog=catalog),
        doc, catalog=catalog)
    assert degraded.verdict == "degraded"


def test_freeze_pins_resolved_and_refuses_unpinned():
    doc = _document()
    task = doc.factor_map_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1")})
    input_set = create_input_set(
        doc, [f"factor:{task.id}:ver_f1", "factor:missing_task:v"],
        catalog=catalog)
    with pytest.raises(ValueError, match="无法钉住版本"):
        freeze_input_set(input_set, doc, catalog=catalog)
    # 拒绝是原子的：不留半个 pin。
    assert all(e.pinned_version_id == "" for e in input_set.entries)
    assert not input_set.frozen

    ok_set = create_input_set(doc, [f"factor:{task.id}:ver_f1"], catalog=catalog)
    frozen = freeze_input_set(ok_set, doc, catalog=catalog, now="t0")
    assert frozen.frozen and frozen.frozen_at == "t0"
    assert frozen.entries[0].pinned_version_id == "ver_f1"
    with pytest.raises(ValueError, match="已冻结"):
        freeze_input_set(frozen, doc, catalog=catalog)


def test_freeze_floating_constraints_requires_commit():
    doc = _document()
    # 无目录服务/无提交 → constraints:current 不可钉 → 原子拒绝。
    input_set = create_input_set(doc, ["constraints:current"])
    with pytest.raises(ValueError, match="无法钉住版本"):
        freeze_input_set(input_set, doc)
    assert all(e.pinned_version_id == "" for e in input_set.entries)
    assert not input_set.frozen


def test_persistence_roundtrip_and_active_flag():
    doc = _document()
    task = doc.factor_map_tasks[0]
    input_set = create_input_set(
        doc, [f"factor:{task.id}:ver_f1"],
        catalog=_FakeCatalog({"ver_f1": _FakeVersion("ver_f1")}))
    persist_input_set(doc, input_set)
    loaded = active_input_set(doc)
    assert loaded is not None and loaded.id == input_set.id
    assert loaded.entries[0].selector == f"factor:{task.id}:ver_f1"
    # 第二个集合激活时取代第一个。
    second = CompilationInputSet(id="ciset_2", name="v2")
    persist_input_set(doc, second)
    assert active_input_set(doc).id == "ciset_2"
    assert len(input_sets_for_document(doc)) == 2
    # 旧工程（无字段）不炸。
    legacy = ProjectDocument.new("old")
    assert active_input_set(legacy) is None


def test_legacy_view_maps_labels_to_selectors():
    doc = _document()
    input_set = create_input_set(doc, ["constraints:current"])
    view = input_set.legacy_view()
    assert view == {input_set.entries[0].label: "constraints:current"}


def test_fusion_reports_pinned_version_mismatch():
    """P1-7：pin 与当前版本不一致时 qc 诚实记录（不伪称按 pin 计算）。"""
    import numpy as np

    from paleo_workbench.project.factor_grid_artifacts import store_live_factor_grid
    from paleo_workbench.workflow.factor_grid_result import FactorGridResult
    from paleo_workbench.workflow.integrated_compilation import (
        run_integrated_fusion,
    )

    doc = _document()
    task = doc.factor_map_tasks[0]
    grid = FactorGridResult(
        grid_z=np.array([[10.0, 60.0], [70.0, 20.0]], dtype=np.float32),
        grid_x=np.linspace(0, 2, 2), grid_y=np.linspace(0, 2, 2),
        factor_name="砂厚", algorithm_id="idw", crs="EPSG:32650", unit="m",
        source_refs=["w@v1"])
    store_live_factor_grid(task.id, grid)
    # 证据集钉住旧版本 ver_old，任务当前是 ver_f1 → mismatch 进 qc。
    summary = run_integrated_fusion(
        doc, {f"单因素：{task.name}": f"factor:{task.id}:ver_old"},
        catalog=None, register=False)
    assert summary["qc"].get("pinned_version_mismatches")
    assert "ver_old" in summary["qc"]["pinned_version_mismatches"][0]
