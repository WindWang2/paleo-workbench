"""Regression nails for the V11 round-1 review fixes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService


@pytest.fixture()
def service(tmp_path: Path) -> DataCatalogService:
    project = tmp_path / "demo.paleo.json"
    project.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project)
    yield svc
    svc.close()


def _make_asset(service, name="fam"):
    asset = service._new_asset(name, "misc", None, None)
    with service._lock:
        service._add_asset(asset)
    return asset


# P1-1: nested-member bundles derive the version dir from the layout -------


def test_nested_member_bundle_paths(service, tmp_path):
    asset = _make_asset(service)
    src = tmp_path / "nested"
    (src / "aaa").mkdir(parents=True)  # sorts BEFORE top-level "z.txt"
    (src / "aaa" / "first.csv").write_bytes(b"aaa")
    (src / "z.txt").write_bytes(b"zzz")
    (src / "m.bin").write_bytes(b"mmm")
    version = service.register_bundle_version(asset.id, src, DataStage.RAW)
    base = service.resolve_path(version)
    assert base.is_dir()
    assert version.members
    rels = {m.rel_path for m in version.members}
    assert rels == {"aaa/first.csv", "z.txt", "m.bin"}
    for rel in rels:
        assert (base / rel).is_file()
    assert service.member_path(version.id, "aaa/first.csv").is_file()


# P1-2/P1-3: failed bundle commit never destroys the source ----------------


def test_over_budget_bundle_rejected_before_any_io(service, tmp_path):
    asset = _make_asset(service)
    src = tmp_path / "huge"
    src.mkdir()
    for i in range(70):
        (src / f"m{i:03d}.bin").write_bytes(b"x")
    with pytest.raises(Exception):
        service.register_bundle_version(asset.id, src, DataStage.RAW, move=True)
    # source intact (move semantics never consumed it)
    assert len(list(src.iterdir())) == 70
    # nothing placed
    placed_root = (
        Path(service.project_path).expanduser().resolve().parent / "demo.artifacts"
    )
    assert not any(placed_root.rglob("m0*.bin"))


def test_duplicate_member_names_rejected_or_disambiguated(service, tmp_path):
    asset = _make_asset(service)
    src = tmp_path / "dupnames"
    (src / "a").mkdir(parents=True)
    (src / "a" / "data.csv").write_bytes(b"1")
    (src / "b").mkdir(parents=True)
    (src / "b" / "data.csv").write_bytes(b"2")
    version = service.register_bundle_version(asset.id, src, DataStage.RAW)
    names = [m.name for m in version.members]
    assert len(names) == len(set(names)), "member names must stay unique"


# F1: DDL-break + missing tables never downgrade a healthy store -----------


def test_missing_v11_tables_do_not_corrupt_open(tmp_path):
    project = tmp_path / "old.paleo.json"
    project.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project)
    src = tmp_path / "a.las"
    src.write_text("las", encoding="utf-8")
    v1 = svc.import_raw(src, name="a.las", type="well_log")
    svc.export_manifest()
    project_path = svc.project_path
    svc.close()

    # Simulate the F1 trigger: strip the V11 tables from a healthy store.
    from paleo_workbench.catalog.db import DB_FILENAME, catalog_dir_for

    db_path = catalog_dir_for(project_path) / DB_FILENAME
    conn = sqlite3.connect(str(db_path))
    conn.execute("DROP TABLE IF EXISTS run_ports")
    conn.execute("DROP TABLE IF EXISTS version_members")
    conn.commit()
    conn.close()

    reopened = DataCatalogService.open(project_path)
    try:
        # the healthy store must NOT be reclassified corrupt (no manifest
        # rebuild) — the version survives and the tables are lazily restored
        assert reopened.get_version(v1.id) is not None
        conn2 = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn2.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn2.close()
        assert {"run_ports", "version_members"} <= tables
    finally:
        reopened.close()


# F5: same-plan re-execution skips already-imported items --------------------


def test_execute_same_plan_twice_is_idempotent(tmp_path):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.resources.ingest_plan import (
        build_ingest_plan,
        execute_ingest_plan,
    )

    project_file = tmp_path / "p.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("p")
    try:
        root = tmp_path / "data"
        root.mkdir()
        (root / "x.las").write_text("~W\nWELL: X\n", encoding="utf-8")
        plan = build_ingest_plan(root, doc, service=svc)
        for item in plan.items:
            item.decision = "accept"
        report1 = execute_ingest_plan(plan, svc, doc)
        assert len(report1.imported_version_ids) == 1
        # THE SAME PLAN OBJECT re-executed (interrupted-ingest recovery):
        report2 = execute_ingest_plan(plan, svc, doc)
        assert report2.imported_version_ids == []
        assert len(report2.skipped) == 1
    finally:
        svc.close()


def test_execute_pending_requires_opt_in(tmp_path):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.resources.ingest_plan import (
        build_ingest_plan,
        execute_ingest_plan,
    )

    project_file = tmp_path / "p.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("p")
    try:
        root = tmp_path / "data"
        root.mkdir()
        (root / "y.las").write_text("~W\nWELL: Y\n", encoding="utf-8")
        plan = build_ingest_plan(root, doc, service=svc)
        # decisions left pending → executes NOTHING by default
        report = execute_ingest_plan(plan, svc, doc)
        assert report.imported_version_ids == []
        # explicit opt-in executes
        report2 = execute_ingest_plan(plan, svc, doc, execute_unconfirmed=True)
        assert len(report2.imported_version_ids) == 1
    finally:
        svc.close()


# 06 §5: migrate_run_ports ---------------------------------------------------


def test_migrate_run_ports_backfills_outputs_only_and_idempotent(service, tmp_path):
    src = tmp_path / "a.las"
    src.write_text("las", encoding="utf-8")
    v = service.import_raw(src, name="a.las", type="well_log")
    out = tmp_path / "pred.json"
    out.write_text("{}", encoding="utf-8")
    run = service.register_run(
        "prediction", input_version_ids=[v.id], output_version_ids=[]
    )
    result = service.register_result_asset(
        name="pred", type="json", format="json", asset_metadata=None,
        source_path=out, stage="derived", run_id=run.id,
    )
    # pre-V11 shape: no ports anywhere
    stored = service.get_run(run.id)
    assert not stored.input_ports and not stored.output_ports

    report1 = service.migrate_run_ports()
    assert report1["runs_annotated"] >= 1
    stored2 = service.get_run(run.id)
    assert [p.role for p in stored2.output_ports] == ["prediction"]
    assert stored2.output_ports[0].version_id == result.id
    assert stored2.input_ports == []  # inputs stay anonymous (honesty)

    report2 = service.migrate_run_ports()
    assert report2 == {"runs_annotated": 0, "ports_added": 0}  # idempotent


# F7: well_view never scans the whole catalog for missing sources -----------


def test_well_view_missing_probe_is_bounded(tmp_path):
    from paleo_workbench.catalog.entity_views import EntityViewService
    from paleo_workbench.project.domain import WellEntity, upsert_entity_asset_link
    from paleo_workbench.project.models import ProjectDocument

    project_file = tmp_path / "p.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("p")
    try:
        well = WellEntity(name="W")
        doc.wells.append(well)
        src = tmp_path / "w.las"
        src.write_text("las", encoding="utf-8")
        v = svc.import_raw(src, name="w.las", type="well_log")
        asset = svc.get_version(v.id).asset_id
        upsert_entity_asset_link(
            doc, entity_type="well", entity_id=well.id, asset_id=asset,
            role="well_log", is_primary=True,
        )
        calls = {"n": 0}
        original = DataCatalogService.find_missing_sources

        def counting(self, **kwargs):
            calls["n"] += 1
            return original(self, **kwargs)

        DataCatalogService.find_missing_sources = counting
        try:
            view = EntityViewService(svc, doc).well_view(well.id)
            assert view is not None
        finally:
            DataCatalogService.find_missing_sources = original
        assert calls["n"] == 0, "well_view must probe its own assets only"
        assert view.missing_source_asset_ids == []
    finally:
        svc.close()
