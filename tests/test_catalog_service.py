"""Invariant and behavior tests for DataCatalogService (ADR 0056).

These tests pin the non-negotiable rules: RAW immutability, DataVersion
immutability, lifecycle stages, lineage, integrity verification, portable
relative paths, SQLite rebuild, and transactional safety.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataStage,
    ImmutableVersionError,
)
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import catalog_dir_for
from paleo_workbench.catalog.store import CatalogStore, catalog_file_for
from paleo_workbench.project.models import ResourceItem


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str = "well.las", payload: bytes = b"las-bytes") -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def _writable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


# --- managed import -------------------------------------------------------


def test_import_raw_copies_file_into_managed_storage(service, tmp_path):
    src = _make_source(tmp_path)
    version = service.import_raw(src)

    assert version.stage == DataStage.RAW
    assert version.managed is True
    managed = service.resolve_path(version)
    assert managed.is_file()
    assert managed.read_bytes() == b"las-bytes"
    # Lives under <project>.artifacts/raw/, referenced project-relative.
    assert ".artifacts" in str(managed)
    assert not Path(version.path).is_absolute()
    assert version.sha256 == sha256_file(src)
    assert version.size_bytes == len(b"las-bytes")
    assert version.source_uri == src.resolve().as_posix()


def test_import_raw_snapshot_isolated_from_source_edits(service, tmp_path):
    src = _make_source(tmp_path)
    version = service.import_raw(src)
    src.write_bytes(b"tampered-source")

    managed = service.resolve_path(version)
    assert managed.read_bytes() == b"las-bytes"
    report = service.verify_integrity(version.id)
    assert report.status_for(version.id) == "verified"


def test_import_raw_marks_payload_readonly(service, tmp_path):
    src = _make_source(tmp_path)
    version = service.import_raw(src)
    mode = service.resolve_path(version).stat().st_mode
    assert not mode & stat.S_IWUSR


def test_second_import_on_same_asset_creates_new_version(service, tmp_path):
    src = _make_source(tmp_path)
    v1 = service.import_raw(src)
    src.write_bytes(b"new-content")
    v2 = service.import_raw(src, asset_id=v1.asset_id)

    assert v2.asset_id == v1.asset_id
    assert v2.version_number == v1.version_number + 1
    assert v2.id != v1.id
    # v1 untouched.
    assert service.resolve_path(v1).read_bytes() == b"las-bytes"
    versions = service.list_versions(v1.asset_id)
    assert [v.version_number for v in versions] == [1, 2]
    assert service.get_asset(v1.asset_id).current_version_id == v2.id


# --- immutability ----------------------------------------------------------


def test_committed_payload_cannot_be_replaced(service, tmp_path):
    src = _make_source(tmp_path)
    version = service.import_raw(src)
    managed = service.resolve_path(version)
    _writable(managed)
    managed.write_bytes(b"hacked")
    # The catalog never adopts the new bytes; verify flags the tampering.
    assert service.verify_integrity(version.id).status_for(version.id) == "modified"
    assert service.get_version(version.id).sha256 == sha256_file(src)


def test_cannot_commit_over_existing_version_payload(service, tmp_path):
    src = _make_source(tmp_path)
    version = service.import_raw(src)
    other = _make_source(tmp_path, name="las.las", payload=b"other")
    with pytest.raises((FileExistsError, ImmutableVersionError)):
        service.register_version(
            version.asset_id,
            other,
            stage=DataStage.RAW,
            version_id=version.id,
        )


def test_derived_workflow_does_not_modify_parent(service, tmp_path):
    src = _make_source(tmp_path, payload=b"parent-data")
    parent = service.import_raw(src)
    parent_path = service.resolve_path(parent)

    working = service.create_working_copy(parent.id)
    working.write_bytes(b"parent-data-filtered")
    child = service.commit_working_copy(working, asset_id=None, name="filtered")

    assert child.stage == DataStage.DERIVED
    assert child.parent_version_ids == [parent.id]
    assert parent_path.read_bytes() == b"parent-data"
    assert service.get_version(parent.id).sha256 == parent.sha256
    assert service.verify_integrity(parent.id).status_for(parent.id) == "verified"
    # Working copy consumed (promoted), not left behind.
    assert not working.exists()


def test_create_derived_registers_run_and_lineage(service, tmp_path):
    src = _make_source(tmp_path)
    parent = service.import_raw(src)
    derived_src = _make_source(tmp_path, name="derived.csv", payload=b"derived")
    child = service.create_derived(
        derived_src,
        parent_version_ids=[parent.id],
        operation="filter",
        parameters={"cutoff": 5},
        generator="paleo-workbench 0.1.0",
    )

    assert child.stage == DataStage.DERIVED
    assert child.parent_version_ids == [parent.id]
    assert child.run_id is not None
    run = service.get_run(child.run_id)
    assert run.operation == "filter"
    assert run.input_version_ids == [parent.id]
    assert run.output_version_ids == [child.id]
    assert run.parameters == {"cutoff": 5}
    assert run.generator == "paleo-workbench 0.1.0"

    lineage = service.get_lineage(child.id)
    assert [v.id for v in lineage["parents"]] == [parent.id]
    parent_lineage = service.get_lineage(parent.id)
    assert [v.id for v in parent_lineage["children"]] == [child.id]


def test_lifecycle_stages_register_distinctly(service, tmp_path):
    src = _make_source(tmp_path)
    raw = service.import_raw(src)
    intermediate = service.register_intermediate(
        raw.asset_id, _make_source(tmp_path, name="tmp.bin", payload=b"i"),
        parent_version_ids=[raw.id],
    )
    output = service.register_output(
        raw.asset_id, _make_source(tmp_path, name="out.png", payload=b"o"),
        parent_version_ids=[intermediate.id],
    )
    assert intermediate.stage == DataStage.INTERMEDIATE
    assert output.stage == DataStage.OUTPUT
    assert "intermediate" in service.resolve_path(intermediate).as_posix()
    assert "outputs" in service.resolve_path(output).as_posix()


# --- external / link -------------------------------------------------------


def test_link_external_is_explicitly_unmanaged(service, tmp_path):
    src = _make_source(tmp_path)
    version = service.link_external(src)

    assert version.managed is False
    assert version.stage == DataStage.RAW
    assert Path(version.path).is_absolute()
    asset = service.get_asset(version.asset_id)
    assert asset.metadata.get("external") is True or version.managed is False


def test_open_without_index_keeps_canonical_catalog_queryable(tmp_path):
    project_path = _make_project(tmp_path)
    source = _make_source(tmp_path)
    initial = DataCatalogService.open(project_path)
    version = initial.import_raw(source)
    initial.close()

    index_path = catalog_dir_for(project_path) / "catalog.sqlite"
    index_path.unlink()
    deferred = DataCatalogService.open(
        project_path, ensure_index=False, sweep_temp=False
    )
    try:
        assert deferred.get_version(version.id).id == version.id
        assert deferred.index_revision() is None
        deferred.ensure_index_ready()
        assert deferred.index_revision() == deferred.document.catalog_revision
    finally:
        deferred.close()


def test_external_offline_verify_reports_missing(service, tmp_path):
    src = _make_source(tmp_path)
    version = service.link_external(src)
    src.unlink()

    report = service.verify_integrity(version.id)
    assert report.status_for(version.id) == "missing"
    # Project/catalog still opens fine with the external file gone.
    service.close()
    svc2 = DataCatalogService.open(tmp_path / "proj" / "demo.paleo.json")
    assert svc2.get_version(version.id).managed is False
    svc2.close()


def test_materialize_external_creates_managed_raw(service, tmp_path):
    src = _make_source(tmp_path)
    linked = service.link_external(src)
    managed = service.materialize_external(linked.id)

    assert managed.managed is True
    assert managed.stage == DataStage.RAW
    assert managed.asset_id == linked.asset_id
    assert managed.version_number == linked.version_number + 1
    assert managed.parent_version_ids == [linked.id]
    assert managed.source_uri == src.resolve().as_posix()
    # External original can vanish; the managed snapshot survives.
    src.unlink()
    assert service.verify_integrity(managed.id).status_for(managed.id) == "verified"


# --- integrity -------------------------------------------------------------


def test_verify_integrity_batch_statuses(service, tmp_path):
    ok = service.import_raw(_make_source(tmp_path, name="a.las", payload=b"a"))
    tampered = service.import_raw(_make_source(tmp_path, name="b.las", payload=b"b"))
    gone = service.import_raw(_make_source(tmp_path, name="c.las", payload=b"c"))

    t_path = service.resolve_path(tampered)
    _writable(t_path)
    t_path.write_bytes(b"BX")
    g_path = service.resolve_path(gone)
    _writable(g_path)
    g_path.unlink()

    report = service.verify_integrity()
    assert report.status_for(ok.id) == "verified"
    assert report.status_for(tampered.id) == "modified"
    assert report.status_for(gone.id) == "missing"
    # Mismatch never rewrites the recorded checksum.
    assert service.get_version(tampered.id).sha256 == tampered.sha256


# --- persistence / portability --------------------------------------------


def test_catalog_roundtrip_and_relative_paths(service, tmp_path):
    src = _make_source(tmp_path)
    version = service.import_raw(src)
    service.add_tag("Seismic 2026", asset_id=version.asset_id)
    service.close()

    # Move the whole project tree; managed data must still resolve.
    moved_root = tmp_path / "relocated"
    (tmp_path / "proj").rename(moved_root)
    svc = DataCatalogService.open(moved_root / "demo.paleo.json")
    try:
        reloaded = svc.get_version(version.id)
        assert reloaded.sha256 == version.sha256
        resolved = svc.resolve_path(reloaded)
        assert resolved.is_file()
        assert resolved.read_bytes() == b"las-bytes"
        assert svc.verify_integrity(version.id).status_for(version.id) == "verified"
        assert svc.find_assets_by_tag("seismic 2026") == [version.asset_id]
    finally:
        svc.close()


def test_canonical_json_is_single_source_of_truth(service, tmp_path):
    service.import_raw(_make_source(tmp_path))
    service.close()
    canonical = catalog_file_for(tmp_path / "proj" / "demo.paleo.json")
    data = json.loads(canonical.read_text(encoding="utf-8"))
    assert data["catalog_revision"] >= 1
    assert data["schema_version"] >= 1
    assert len(data["assets"]) == 1 and len(data["versions"]) == 1


# --- SQLite index ----------------------------------------------------------


def _index_path(project_path: Path) -> Path:
    return catalog_dir_for(project_path) / "catalog.sqlite"


def test_sqlite_deleted_index_rebuilds(service, tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    version = service.import_raw(_make_source(tmp_path))
    service.add_tag("alpha", asset_id=version.asset_id)
    service.close()

    db = _index_path(project_path)
    assert db.is_file()
    db.unlink()

    svc = DataCatalogService.open(project_path)
    try:
        assert svc.find_assets_by_tag("alpha") == [version.asset_id]
        assert [v.id for v in svc.list_versions(version.asset_id)] == [version.id]
    finally:
        svc.close()


def test_sqlite_stale_revision_rebuilds(service, tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    version = service.import_raw(_make_source(tmp_path))
    service.close()

    # Simulate an index that fell behind the canonical store.
    store = CatalogStore(project_path)
    doc = store.load()
    doc.catalog_revision += 5
    store.save(doc)

    svc = DataCatalogService.open(project_path)
    try:
        assert svc.index_revision() == doc.catalog_revision
        assert [v.id for v in svc.list_versions(version.asset_id)] == [version.id]
    finally:
        svc.close()


def test_corrupt_sqlite_does_not_break_project(service, tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    version = service.import_raw(_make_source(tmp_path))
    service.close()
    _index_path(project_path).write_bytes(b"not-a-sqlite-database")

    svc = DataCatalogService.open(project_path)
    try:
        assert [v.id for v in svc.list_versions(version.asset_id)] == [version.id]
    finally:
        svc.close()


# --- transactional safety --------------------------------------------------


def test_failed_save_leaves_no_partial_state(service, tmp_path, monkeypatch):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    src = _make_source(tmp_path)
    before_revision = service.document.catalog_revision

    def boom(self, document):
        raise OSError("disk full")

    monkeypatch.setattr(CatalogStore, "save", boom)
    with pytest.raises(OSError):
        service.import_raw(src)

    # No managed payload left behind, canonical untouched, revision unchanged.
    raw_root = project_path.parent / "demo.artifacts" / "raw"
    leftovers = [p for p in raw_root.rglob("*") if p.is_file()] if raw_root.exists() else []
    assert leftovers == []
    assert service.document.catalog_revision == before_revision
    assert service.document.versions == []
    assert not catalog_file_for(project_path).exists()


def test_failed_save_rolls_back_new_asset(service, tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    monkeypatch.setattr(
        CatalogStore, "save", lambda self, doc: (_ for _ in ()).throw(OSError("x"))
    )
    with pytest.raises(OSError):
        service.import_raw(src)
    assert service.document.assets == []


# --- tags ------------------------------------------------------------------


def test_tag_add_remove_rename_search(service, tmp_path):
    v1 = service.import_raw(_make_source(tmp_path, name="a.las", payload=b"a"))
    v2 = service.import_raw(_make_source(tmp_path, name="b.las", payload=b"b"))

    t = service.add_tag("  Seismic 2026 ", asset_id=v1.asset_id)
    assert t.name == "seismic 2026"
    # Case/whitespace-insensitive dedup: same normalized tag, no duplicate.
    t2 = service.add_tag("SEISMIC 2026", asset_id=v2.asset_id)
    assert t2.id == t.id
    assert len(service.list_tags()) == 1

    assert sorted(service.find_assets_by_tag("seismic 2026")) == sorted(
        [v1.asset_id, v2.asset_id]
    )

    service.rename_tag("seismic 2026", "Seismic-2027")
    assert service.find_assets_by_tag("seismic-2027") == sorted(
        [v1.asset_id, v2.asset_id]
    ) or set(service.find_assets_by_tag("seismic-2027")) == {v1.asset_id, v2.asset_id}
    assert service.find_assets_by_tag("seismic 2026") == []

    service.remove_tag("seismic-2027", asset_id=v1.asset_id)
    assert service.find_assets_by_tag("seismic-2027") == [v2.asset_id]


def test_rename_tag_merges_case_duplicates(service, tmp_path):
    v = service.import_raw(_make_source(tmp_path))
    service.add_tag("Alpha", asset_id=v.asset_id)
    service.add_tag("beta", asset_id=v.asset_id)
    service.rename_tag("beta", "ALPHA")
    tags = service.list_tags()
    assert len(tags) == 1
    assert service.find_assets_by_tag("alpha") == [v.asset_id]


def test_version_level_tags(service, tmp_path):
    v1 = service.import_raw(_make_source(tmp_path))
    service.add_tag("reviewed", version_id=v1.id)
    assert service.find_versions_by_tag("reviewed") == [v1.id]
    service.remove_tag("reviewed", version_id=v1.id)
    assert service.find_versions_by_tag("reviewed") == []


def test_lifecycle_stage_is_not_a_tag(service, tmp_path):
    v = service.import_raw(_make_source(tmp_path))
    assert service.list_tags() == []
    assert v.stage == DataStage.RAW


# --- search / queries ------------------------------------------------------


def test_search_assets_filters(service, tmp_path):
    a = service.import_raw(_make_source(tmp_path, name="alpha.las", payload=b"a"),
                           type="well_log", format="las")
    b = service.import_raw(_make_source(tmp_path, name="beta.sgy", payload=b"b"),
                           type="seismic", format="segy")
    service.add_tag("frontier", asset_id=b.asset_id)

    assert service.search_assets(text="alph")[0].id == a.asset_id
    assert service.search_assets(type="seismic")[0].id == b.asset_id
    assert service.search_assets(stage=DataStage.RAW)
    assert service.search_assets(tag="frontier")[0].id == b.asset_id
    assert service.search_assets(text="nomatch") == []


# --- legacy migration ------------------------------------------------------


def test_migrate_legacy_resources_via_service(service, tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    legacy_file = tmp_path / "proj" / "data" / "well.las"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_bytes(b"legacy")
    resource = ResourceItem(
        id="res_legacy1",
        name="well.las",
        path=legacy_file.as_posix(),
        type="well_log",
        format="las",
        checksum=sha256_file(legacy_file),
    )
    report = service.migrate_legacy_resources([resource])
    assert report.migrated_count == 1
    asset = service.get_asset("res_legacy1")
    assert asset.legacy_resource_id == "res_legacy1"
    versions = service.list_versions("res_legacy1")
    assert len(versions) == 1 and versions[0].stage == DataStage.RAW

    # Idempotent at the service level too.
    report2 = service.migrate_legacy_resources([resource])
    assert report2.migrated_count == 0
    assert report2.skipped_count == 1


# --- review regression: transactional atomicity ----------------------------


def test_create_derived_failure_leaves_no_orphans(service, tmp_path, monkeypatch):
    """A failing save must not leave an orphaned version/run/payload (review)."""
    src = _make_source(tmp_path)
    parent = service.import_raw(src)
    derived_src = _make_source(tmp_path, name="derived.csv", payload=b"derived")
    before_versions = len(service.document.versions)

    def boom(self, document):
        raise OSError("disk full")

    monkeypatch.setattr(CatalogStore, "save", boom)
    with pytest.raises(OSError):
        service.create_derived(
            derived_src, parent_version_ids=[parent.id], operation="filter"
        )

    assert len(service.document.versions) == before_versions
    assert len(service.document.assets) == 1  # only the RAW asset
    assert service.document.runs == []
    derived_root = tmp_path / "proj" / "demo.artifacts" / "derived"
    leftovers = (
        [p for p in derived_root.rglob("*") if p.is_file()]
        if derived_root.exists()
        else []
    )
    assert leftovers == []


def test_failed_commit_restores_working_copy(service, tmp_path, monkeypatch):
    """move=True commit failure must restore the consumed working copy (review)."""
    src = _make_source(tmp_path, payload=b"precious-data")
    parent = service.import_raw(src)
    working = service.create_working_copy(parent.id)
    working.write_bytes(b"precious-data-edited")

    def boom(self, document):
        raise OSError("disk full")

    monkeypatch.setattr(CatalogStore, "save", boom)
    with pytest.raises(OSError):
        service.commit_working_copy(working)

    assert working.is_file()
    assert working.read_bytes() == b"precious-data-edited"
    assert len(service.document.versions) == 1


def test_commit_working_copy_stores_version_name_in_metadata(service, tmp_path):
    """The New Version dialog's optional name must reach the committed
    version's metadata when committing onto an EXISTING asset (DATA-9)."""
    src = _make_source(tmp_path, payload=b"base")
    parent = service.import_raw(src)
    working = service.create_working_copy(parent.id)
    working.write_bytes(b"edited")

    new_version = service.commit_working_copy(
        working, asset_id=parent.asset_id, name="去毛刺滤波版"
    )

    assert service.get_version(new_version.id).metadata["name"] == "去毛刺滤波版"
    # Stable, queryable through the public listing.
    latest = service.list_versions(parent.asset_id)[-1]
    assert latest.metadata.get("name") == "去毛刺滤波版"


def test_commit_working_copy_empty_name_writes_no_metadata_key(service, tmp_path):
    src = _make_source(tmp_path, payload=b"base")
    parent = service.import_raw(src)
    working = service.create_working_copy(parent.id)
    working.write_bytes(b"edited")

    new_version = service.commit_working_copy(working, asset_id=parent.asset_id, name="")

    assert "name" not in service.get_version(new_version.id).metadata
    # The parent's own name is untouched (no asset rename).
    assert service.get_asset(parent.asset_id).name != ""


def test_commit_working_copy_new_asset_branch_keeps_name_semantics(service, tmp_path):
    """asset_id=None: the name still names the NEW ASSET (existing behavior)."""
    src = _make_source(tmp_path, payload=b"base")
    parent = service.import_raw(src)
    working = service.create_working_copy(parent.id)
    working.write_bytes(b"edited")

    version = service.commit_working_copy(working, asset_id=None, name="my-derived")

    assert service.get_asset(version.asset_id).name == "my-derived"


# --- batch save (bulk registration write amplification, C38) ------------------


def test_batch_save_merges_many_imports_into_one_canonical_write(service, tmp_path, monkeypatch):
    """200 imports inside one batch must persist with a SINGLE canonical
    store write (O(N²) full-document rewrite + fsync per version otherwise)."""
    calls = 0
    real_save = service._store.save

    def counted(document):
        nonlocal calls
        calls += 1
        return real_save(document)

    monkeypatch.setattr(service._store, "save", counted)

    with service.batch_save():
        for i in range(200):
            service.import_raw(
                _make_source(tmp_path, name=f"w{i}.las", payload=f"data-{i}".encode())
            )

    assert calls == 1, calls
    assert len(service.document.assets) == 200
    # Every asset has its version (no zombie), disk equals memory, and the
    # index is fresh for dedup/reads.
    assert all(
        any(v.asset_id == a.id for v in service.document.versions)
        for a in service.document.assets
    )
    disk = CatalogStore(tmp_path / "proj" / "demo.paleo.json").load()
    assert disk.model_dump(mode="json") == service.document.model_dump(mode="json")
    assert service.index_revision() == service.document.catalog_revision


def test_batch_save_body_failure_persists_nothing_and_restores(service, tmp_path, monkeypatch):
    calls = 0
    real_save = service._store.save

    def counted(document):
        nonlocal calls
        calls += 1
        return real_save(document)

    monkeypatch.setattr(service._store, "save", counted)

    with pytest.raises(RuntimeError):
        with service.batch_save():
            service.import_raw(_make_source(tmp_path, name="a.las"))
            raise RuntimeError("boom")

    assert calls == 0  # nothing was ever written to the canonical store
    assert service.document.assets == []
    assert service.document.versions == []
    disk = CatalogStore(tmp_path / "proj" / "demo.paleo.json").load()
    assert disk.model_dump(mode="json") == service.document.model_dump(mode="json")


def test_batch_save_flush_failure_restores_document(service, tmp_path, monkeypatch):
    def boom(document):
        raise OSError("disk full")

    monkeypatch.setattr(service._store, "save", boom)

    with pytest.raises(OSError):
        with service.batch_save():
            service.import_raw(_make_source(tmp_path, name="a.las"))
            service.import_raw(_make_source(tmp_path, name="b.las"))

    # The failed flush must not leave the half-batched document in memory.
    assert service.document.assets == []
    assert service.document.versions == []


def test_batch_save_nested_batches_flush_once(service, tmp_path, monkeypatch):
    calls = 0
    real_save = service._store.save

    def counted(document):
        nonlocal calls
        calls += 1
        return real_save(document)

    monkeypatch.setattr(service._store, "save", counted)

    with service.batch_save():
        service.import_raw(_make_source(tmp_path, name="a.las"))
        with service.batch_save():
            service.import_raw(_make_source(tmp_path, name="b.las"))
        service.import_raw(_make_source(tmp_path, name="c.las"))

    assert calls == 1
    assert len(service.document.assets) == 3


def test_find_versions_by_tag_uses_index(service, tmp_path):
    v = service.import_raw(_make_source(tmp_path))
    service.add_tag("reviewed", version_id=v.id)
    # Served from the SQLite index (falls back to memory when unavailable).
    assert service.find_versions_by_tag("Reviewed") == [v.id]
    service.close()
    svc = DataCatalogService.open(tmp_path / "proj" / "demo.paleo.json")
    try:
        assert svc.find_versions_by_tag("reviewed") == [v.id]
    finally:
        svc.close()


def test_open_without_index_keeps_canonical_queries_usable(tmp_path: Path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    version = service.import_raw(_make_source(tmp_path))
    service.close()

    deferred = DataCatalogService.open(project, ensure_index=False)
    try:
        # SQLite is an acceleration cache only; the canonical document still
        # answers lookup/query requests before a deferred rebuild.
        deferred._index.reset()
        assert deferred.get_version(version.id).id == version.id
        assert len(deferred.search_assets()) == 1
        assert deferred.index_revision() is None
        deferred.ensure_index_ready()
        assert deferred.index_revision() == deferred.document.catalog_revision
    finally:
        deferred.close()


def test_add_tags_batches_one_canonical_write(service, tmp_path, monkeypatch):
    version = service.import_raw(_make_source(tmp_path))
    calls = 0
    real_save = service._store.save

    def counted(document):
        nonlocal calls
        calls += 1
        return real_save(document)

    monkeypatch.setattr(service._store, "save", counted)
    service.add_tags(["one", "two", "three"], version_id=version.id)

    assert calls == 1
    assert {tag.name for tag in service.document.tags} == {"one", "two", "three"}
    assert service.find_versions_by_tag("two") == [version.id]


def test_add_tags_batch_rolls_back_on_canonical_failure(service, tmp_path, monkeypatch):
    version = service.import_raw(_make_source(tmp_path))

    def fail(_document):
        raise OSError("injected catalog failure")

    monkeypatch.setattr(service._store, "save", fail)
    with pytest.raises(OSError):
        service.add_tags(["one", "two"], version_id=version.id)

    assert service.document.tags == []
    assert service.document.version_tags.get(version.id, []) == []


# --- lock discipline (zombie-asset prevention) ------------------------------


def test_import_raw_adds_asset_under_service_lock(service, tmp_path, monkeypatch):
    """The asset must enter the document inside the service lock, so a
    concurrent save can never persist an asset with zero versions."""
    import threading

    from paleo_workbench.catalog.service import DataCatalogService

    lock_state: dict[str, bool] = {}
    original = DataCatalogService._add_asset

    def spy(self, asset):
        # _is_owned() is True exactly when the current thread holds the lock
        # (re-entrant acquire would succeed either way, so it cannot probe).
        lock_state["held"] = self._lock._is_owned()
        return original(self, asset)

    monkeypatch.setattr(DataCatalogService, "_add_asset", spy)
    service.import_raw(_make_source(tmp_path))

    assert lock_state.get("held") is True


def test_concurrent_import_and_tag_untag_never_persists_zombie(service, tmp_path, monkeypatch):
    """Two threads alternating import_raw with add_tag/remove_tag for 200
    rounds: every canonical save must persist a consistent document (never an
    asset with zero versions), the save count must match the operation count,
    and the on-disk document must equal the in-memory one at the end."""
    import threading

    # A stable tag target so the tagger thread always has a valid asset id.
    anchor = service.import_raw(_make_source(tmp_path, name="anchor.las"))

    saves = []
    real_save = service._store.save

    def checked(document):
        # Every persisted snapshot must be consistent: no asset may exist
        # without at least one version (the zombie torn state).
        assets = {a.id for a in document.assets}
        versions = {v.asset_id for v in document.versions}
        zombies = assets - versions
        assert not zombies, f"save persisted zombie asset(s): {zombies}"
        saves.append(document.catalog_revision)
        return real_save(document)

    monkeypatch.setattr(service._store, "save", checked)

    rounds = 200
    errors: list[BaseException] = []

    def importer():
        try:
            for i in range(rounds):
                service.import_raw(
                    _make_source(tmp_path, name=f"w{i}.las", payload=f"data-{i}".encode())
                )
        except BaseException as exc:  # pragma: no cover - failure detail
            errors.append(exc)

    def tagger():
        try:
            for i in range(rounds):
                if i % 2 == 0:
                    service.add_tag("qc", asset_id=anchor.asset_id)
                else:
                    service.remove_tag("qc", asset_id=anchor.asset_id)
        except BaseException as exc:  # pragma: no cover - failure detail
            errors.append(exc)

    threads = [threading.Thread(target=importer), threading.Thread(target=tagger)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not errors, errors
    assert not any(t.is_alive() for t in threads)

    # Save count is exact: one canonical write per import_raw plus one per
    # effective tag mutation (alternating add/remove always changes state).
    assert len(saves) == rounds * 2, len(saves)

    # Every asset carries at least one version; on-disk state == memory.
    assert all(
        any(v.asset_id == a.id for v in service.document.versions)
        for a in service.document.assets
    )
    disk = CatalogStore(tmp_path / "proj" / "demo.paleo.json").load()
    assert disk.model_dump(mode="json") == service.document.model_dump(mode="json")
def test_result_asset_registration_does_not_hold_lock_across_payload_io(
    service, tmp_path, monkeypatch
):
    """C70: ``register_result_asset`` (the worker-thread registration path)
    must not hold the catalog lock while the payload is copied+hashed; a
    concurrent GUI-thread call such as ``add_tags`` must not stall for the
    duration of that disk I/O."""
    import threading
    import time as time_mod

    import paleo_workbench.catalog.service as service_mod

    existing = service.import_raw(_make_source(tmp_path, name="existing.las"))
    src = _make_source(tmp_path, name="worker-result.json", payload=b"x" * 4096)

    entered_placement = threading.Event()
    real_place = service_mod.place_managed_file

    def slow_place(*args, **kwargs):
        # Stand-in for a large payload: the copy+hash+fsync takes ~0.5 s.
        entered_placement.set()
        time_mod.sleep(0.5)
        return real_place(*args, **kwargs)

    monkeypatch.setattr(service_mod, "place_managed_file", slow_place)

    errors: list[str] = []

    def register_in_worker() -> None:
        try:
            service.register_result_asset(
                name="worker result",
                type="prediction",
                format="json",
                asset_metadata={},
                source_path=src,
                stage=DataStage.OUTPUT,
            )
        except Exception as exc:  # noqa: BLE001 — surface to the main thread
            errors.append(repr(exc))

    worker = threading.Thread(target=register_in_worker)
    worker.start()
    assert entered_placement.wait(timeout=5.0), "worker never reached payload placement"

    started = time_mod.perf_counter()
    service.add_tags(["audit-label"], asset_id=existing.asset_id)
    elapsed_ms = (time_mod.perf_counter() - started) * 1000

    worker.join(timeout=10.0)
    assert not worker.is_alive()
    assert errors == []

    # The GUI-thread call finished well inside the 0.5 s placement window:
    # its lock wait is decoupled from the worker's disk I/O.
    assert elapsed_ms < 250, (
        f"GUI add_tags stalled {elapsed_ms:.0f} ms while worker payload "
        "I/O (0.5 s) was in flight — lock still spans copy+hash"
    )
    # The concurrent registration still commits a consistent document.
    assert {"audit-label"} <= {tag.name for tag in service.document.tags}
    assert any(v.asset_id == existing.asset_id for v in service.document.versions)
    registered = [
        a for a in service.document.assets if a.name == "worker result"
    ]
    assert len(registered) == 1
    assert registered[0].current_version_id is not None


# --- batch flush staleness (#516) ------------------------------------------


def test_batch_save_then_regular_save_does_not_false_positive(service, tmp_path):
    """#516: the batch flush used to bypass _save's mtime-baseline refresh,
    so the FIRST regular save after any batch raised a spurious
    CatalogStaleWriteError against our own batch write."""
    with service.batch_save():
        service.import_raw(_make_source(tmp_path, name="a.las"))

    # The very next ordinary mutator must save cleanly, not refuse.
    v = service.import_raw(_make_source(tmp_path, name="b.las"))
    service.add_tag("post-batch", version_id=v.id)
    assert v.id in service.find_versions_by_tag("post-batch")


def test_batch_flush_stale_write_raises_and_restores(service, tmp_path):
    """#516 red/green core: external advance during the batch makes the exit
    raise CatalogStaleWriteError and restore the pre-batch document."""
    import os

    from paleo_workbench.catalog.service import CatalogStaleWriteError

    seed = service.import_raw(_make_source(tmp_path, name="seed.las"))
    n_assets_before = len(service.document.assets)

    with pytest.raises(CatalogStaleWriteError):
        with service.batch_save():
            service.import_raw(_make_source(tmp_path, name="a.las"))
            catalog_file = catalog_file_for(service.project_path)
            stat = catalog_file.stat()
            os.utime(
                catalog_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000)
            )

    # Snapshot restored: the batch's mutation is gone, the seed survives.
    assert len(service.document.assets) == n_assets_before
    assert any(v.id == seed.id for v in service.document.versions)


# --- producer locking (#517) ------------------------------------------------


def test_concurrent_save_never_persists_zero_version_asset(
    service, tmp_path, monkeypatch
):
    """#517: a locked mutator holding the catalog lock must never observe a
    version-less asset appended by _register_produced — the append now
    happens inside the same critical section."""
    import threading

    from paleo_workbench.catalog.adapter import CoreCatalogAdapter

    seed = service.import_raw(_make_source(tmp_path, name="seed.las"))

    entered = threading.Event()
    release = threading.Event()
    real_add_tag = service.add_tag

    def holding_add_tag(*args, **kwargs):
        # Hold the CATALOG LOCK while waiting, so the producer below must
        # block at its critical section (the real mutator runs after the
        # release, outside the hold).
        with service._lock:
            entered.set()
            release.wait(10)
        return real_add_tag(*args, **kwargs)

    monkeypatch.setattr(service, "add_tag", holding_add_tag)

    adapter = CoreCatalogAdapter(service)
    run = adapter.begin_run(operation="test", input_version_ids=[seed.id])
    out = _make_source(tmp_path, name="out.las", payload=b"result")

    b = threading.Thread(
        target=lambda: service.add_tag("holder", version_id=seed.id)
    )
    b.start()
    assert entered.wait(5), "holder thread must enter the locked mutator"

    a_done = threading.Event()

    def producer():
        adapter.register_output(
            run_id=run.run_id, name="out.las", path=str(out), kind="", format=""
        )
        a_done.set()

    a = threading.Thread(target=producer)
    a.start()
    a.join(0.6)  # give the producer a moment to reach the lock

    # While the lock is held by the tag mutator, the producer must NOT have
    # appended its asset yet (old code: _add_asset ran unlocked → zero-version
    # asset visible to every concurrent save).
    zero = [
        asset.id
        for asset in service.document.assets
        if asset.current_version_id is None
    ]
    assert zero == [], f"version-less assets visible mid-flight: {zero}"

    release.set()
    b.join(10)
    assert a_done.wait(10), "producer must complete after the lock is released"
    a.join(10)
    # Final state: producer's asset registered with a version.
    assert all(
        any(v.asset_id == asset.id for v in service.document.versions)
        for asset in service.document.assets
    )


# --- modeling run compensation (#518) ---------------------------------------


def test_register_modeling_run_failure_fails_the_run(service, tmp_path):
    """#518: a registration failure must compensate the booked run to
    status=failed instead of leaving phantom RUNNING provenance."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.lifecycle import register_modeling_run

    adapter = CoreCatalogAdapter(service)
    missing = tmp_path / "gone.output"

    with pytest.raises(Exception):
        register_modeling_run(
            name="m1",
            source="real",
            output_path=str(missing),
            catalog=adapter,
        )

    runs = [r for r in service.document.runs if r.operation == "modeling"]
    assert runs, "the run was booked"
    assert runs[-1].status == "failed", runs[-1].status
