"""M10 — MapProduct lifecycle V2: clone / rerun / compare / freeze /
supersede / stale / promote / publish gate.

A clone is an independent record over the SAME catalog versions; a rerun
re-assembles through the existing run graph and supersedes the predecessor;
compare diffs inputs/parameters/versions/hashes; frozen records refuse
mutation; the publish gate refuses stale or superseded products.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.models import (
    FactorMapTask,
    ProjectDocument,
    ProjectMeta,
)
from paleo_workbench.workflow.map_product import (
    MapProductAssembly,
    assemble_map_product,
    clone_map_product,
    compare_map_products,
    find_map_product,
    freeze_map_product,
    product_staleness,
    promote_map_product,
    publish_map_product,
    rerun_map_product,
    supersede_map_product,
)


def _task(task_id: str, *, source: str = "real", grid: str | None = None) -> FactorMapTask:
    return FactorMapTask(
        id=task_id,
        name=f"task {task_id}",
        target_horizon="H1",
        factor_type="sand_ratio",
        method="kriging",
        parameters={"grid_n": 32},
        status="complete",
        source_kind=source,
        grid_artifact_version_id=grid or f"ver_{task_id}",
    )


@pytest.fixture()
def project() -> ProjectDocument:
    project = ProjectDocument(id="p1", name="产品工程", meta=ProjectMeta(name="产品工程"))
    project.factor_map_tasks = [_task("t1"), _task("t2")]
    return project


@pytest.fixture()
def catalog(tmp_path: Path) -> DataCatalogService:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


def _assemble(project, catalog, tmp_path, name="古地理图 v1", task_ids=None):
    payload = tmp_path / f"{name}.json"
    payload.write_text(json.dumps({"product": name}), encoding="utf-8")
    return assemble_map_product(
        project,
        assembly=MapProductAssembly(
            product_name=name,
            factor_task_ids=task_ids or ["t1", "t2"],
            notes="n",
        ),
        catalog=catalog,
        payload_path=payload,
    )


# ---------------------------------------------------------------------------
# clone
# ---------------------------------------------------------------------------


def test_clone_is_independent_record_over_same_versions(project, catalog, tmp_path):
    result = _assemble(project, catalog, tmp_path)
    record = find_map_product(project, result.record_id)
    clone = clone_map_product(record, project, new_name="古地理图 v1 副本")
    assert clone.id != record.id
    assert clone.cloned_from == record.id
    assert clone.output_version_id == record.output_version_id
    assert clone.run_id == record.run_id
    assert clone.factor_task_ids == record.factor_task_ids
    assert len(project.map_products) == 2


def test_clone_frozen_record_refused(project, catalog, tmp_path):
    result = _assemble(project, catalog, tmp_path)
    record = find_map_product(project, result.record_id)
    freeze_map_product(record)
    with pytest.raises(ValueError, match="frozen"):
        clone_map_product(record, project)


# ---------------------------------------------------------------------------
# rerun
# ---------------------------------------------------------------------------


def test_rerun_creates_successor_and_supersedes(project, catalog, tmp_path):
    result = _assemble(project, catalog, tmp_path)
    record = find_map_product(project, result.record_id)

    project.factor_map_tasks[0] = _task("t1", grid="ver_t1_v2")
    (tmp_path / "v2.json").write_text("{}", encoding="utf-8")
    rerun = rerun_map_product(
        project, record=record, catalog=catalog,
        payload_path=tmp_path / "v2.json",
    )
    assert rerun.record_id != record.id
    assert rerun.superseded_record_id == record.id
    assert record.status == "superseded"
    assert record.superseded_by == rerun.record_id
    # the rerun consumed the NEW grid version
    successor = find_map_product(project, rerun.record_id)
    assert "ver_t1_v2" in rerun.scientific_fingerprint or (
        successor.factor_task_ids == record.factor_task_ids
    )
    run = catalog.get_run(rerun.run_id)
    assert "ver_t1_v2" in run.input_version_ids


def test_rerun_superseded_record_refused(project, catalog, tmp_path):
    result = _assemble(project, catalog, tmp_path)
    record = find_map_product(project, result.record_id)
    record.status = "superseded"
    record.superseded_by = "other"
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="superseded"):
        rerun_map_product(
            project, record=record, catalog=catalog,
            payload_path=tmp_path / "x.json",
        )


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def test_compare_reports_factor_and_hash_differences(project, catalog, tmp_path):
    first = _assemble(project, catalog, tmp_path, name="v1")
    record_a = find_map_product(project, first.record_id)

    project.factor_map_tasks[1] = _task("t2", grid="ver_t2_v2", )
    project.factor_map_tasks[1].method = "IDW"
    project.factor_map_tasks.append(_task("t3", grid="ver_t3"))
    second = _assemble(
        project, catalog, tmp_path, name="v2", task_ids=["t1", "t2", "t3"]
    )
    record_b = find_map_product(project, second.record_id)

    report = compare_map_products(record_a, record_b, project, catalog=catalog)
    assert report["scientific_fingerprint_equal"] is False
    assert report["factor_tasks"]["changed"]["t2"]["method"]["a"] == "kriging"
    assert report["factor_tasks"]["changed"]["t2"]["method"]["b"] == "IDW"
    assert "t3" in report["factor_tasks"]["only_in_b"]
    assert report["output"]["checksum_a"] is not None
    assert report["output"]["checksum_b"] is not None
    assert report["output"]["checksum_a"] != report["output"]["checksum_b"]


def test_compare_identical_products_reports_equal(project, catalog, tmp_path):
    first = _assemble(project, catalog, tmp_path, name="v1")
    record_a = find_map_product(project, first.record_id)
    clone = clone_map_product(record_a, project)
    report = compare_map_products(record_a, clone, project, catalog=catalog)
    assert report["scientific_fingerprint_equal"] is True
    assert report["factor_tasks"]["changed"] == {}
    assert report["factor_tasks"]["only_in_a"] == []
    assert report["output"]["checksum_a"] == report["output"]["checksum_b"]


# ---------------------------------------------------------------------------
# stale / freeze / supersede / promote / publish
# ---------------------------------------------------------------------------


def test_staleness_detects_rerendered_inputs(project, catalog, tmp_path):
    result = _assemble(project, catalog, tmp_path)
    record = find_map_product(project, result.record_id)
    before = product_staleness(record, project)
    assert before["stale"] is False
    project.factor_map_tasks[0] = _task("t1", grid="ver_t1_v2")
    after = product_staleness(record, project)
    assert after["stale"] is True
    assert "changed" in after["reason"]


def test_freeze_blocks_rerun(project, catalog, tmp_path):
    result = _assemble(project, catalog, tmp_path)
    record = find_map_product(project, result.record_id)
    freeze_map_product(record)
    assert record.frozen is True
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen"):
        rerun_map_product(
            project, record=record, catalog=catalog,
            payload_path=tmp_path / "x.json",
        )


def test_supersede_explicit_pair(project):
    result_a = type("R", (), {"record_id": "a"})()
    record_a = _record("a", project)
    record_b = _record("b", project)
    supersede_map_product(record_a, project, successor=record_b)
    assert record_a.status == "superseded"
    assert record_a.superseded_by == "b"
    with pytest.raises(ValueError, match="itself"):
        supersede_map_product(record_b, project, successor=record_b)


def _record(rid, project):
    from paleo_workbench.project.models import MapProductRecord

    record = MapProductRecord(product_name=rid, id=rid)
    project.map_products = [*list(project.map_products or []), record]
    return record


def test_publish_gate_blocks_stale(project, catalog, tmp_path):
    result = _assemble(project, catalog, tmp_path)
    record = find_map_product(project, result.record_id)
    report = publish_map_product(record, project, export_path="/tmp/out.png")
    assert report["ok"] is True

    project.factor_map_tasks[0] = _task("t1", grid="ver_t1_v2")
    with pytest.raises(ValueError, match="stale|changed"):
        publish_map_product(record, project)


def test_promote_uses_catalog_authority(project, catalog, tmp_path):
    result = _assemble(project, catalog, tmp_path)
    record = find_map_product(project, result.record_id)
    promoted_id = promote_map_product(record, catalog=catalog)
    assert promoted_id != record.output_version_id
    promoted = catalog.get_version(promoted_id)
    original = catalog.get_version(record.output_version_id)
    assert promoted.parent_version_ids == [original.id]
    assert promoted.sha256 == original.sha256


def test_staleness_honours_manual_adjustments(project, catalog, tmp_path):
    """R1-P2: an adjusted product must not read stale forever."""
    payload = tmp_path / "adj.json"
    payload.write_text("{}", encoding="utf-8")
    result = assemble_map_product(
        project,
        assembly=MapProductAssembly(
            product_name="adj",
            factor_task_ids=["t1", "t2"],
            manual_adjustments=[{"author": "专家", "what": "河道外推", "why": "岩心"}],
        ),
        catalog=catalog,
        payload_path=payload,
    )
    record = find_map_product(project, result.record_id)
    assert record.manual_adjustments
    assert product_staleness(record, project)["stale"] is False


def test_supersede_frozen_and_double_supersede_refused(project):
    record_a = _record("sa", project)
    record_b = _record("sb", project)
    record_c = _record("sc", project)
    freeze_map_product(record_a)
    with pytest.raises(ValueError, match="frozen"):
        supersede_map_product(record_a, project, successor=record_b)
    unfrozen = _record("sd", project)
    supersede_map_product(unfrozen, project, successor=record_b)
    with pytest.raises(ValueError, match="already superseded"):
        supersede_map_product(unfrozen, project, successor=record_c)
