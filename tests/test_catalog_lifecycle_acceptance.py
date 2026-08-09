"""P1 Data Lifecycle — goal §11 acceptance tests (disk-backed, real Core).

Runs the 22-item acceptance list against the REAL production path:
``CoreCatalogAdapter`` over ``DataCatalogService`` backed by a tmp_path project
(managed storage + canonical ``metadata/catalog.json`` + SQLite index). Each
numbered item maps to one test; the final tests verify full-lifecycle
persistence and rebuild behavior.

Items covered (goal §11):
   1  import RAW                    12  reopen
   2  source changes later          13  still trashed
   3  managed RAW unchanged         14  restore
   4  RAW → working copy            15  payload restored
   5  edit working copy             16  trash asset with references
   6  commit V2                     17  external trash keeps external file
   7  V1 unchanged                  18  save-failure rollback
   8  derived lineage               19  derived failure cannot fall back into RAW dir
   9  promotion                     20  SQLite deleted/corrupt
  10  export/delivery               21  rebuild from catalog.json
  11  trash                         22  lifecycle state preserved
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from paleo_workbench.catalog import (
    CoreCatalogAdapter,
    DataCatalogService,
    DataStage,
    reset_catalog,
    set_catalog,
)
from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.db import DB_FILENAME
from paleo_workbench.catalog.lifecycle import register_export_output
from paleo_workbench.catalog.models import CatalogError
from paleo_workbench.catalog.storage import catalog_dir_for
from paleo_workbench.catalog.store import CatalogStore
from paleo_workbench.project.models import ResourceItem


def _make_project_path(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture()
def project_path(tmp_path: Path) -> Path:
    return _make_project_path(tmp_path)


@pytest.fixture()
def catalog(project_path: Path):
    """CoreCatalogAdapter over a real DataCatalogService, wired as active."""
    service = DataCatalogService.open(project_path)
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    yield adapter
    reset_catalog()
    service.close()


def _reopen(project_path: Path) -> DataCatalogService:
    return DataCatalogService.open(project_path)


def _writable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def _make_source(tmp_path: Path, name: str = "well.las", payload: bytes = b"log data") -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


def _resource(path: Path, *, name: str = "src.las", external: bool = False) -> ResourceItem:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        checksum = sha256_file(path)
    else:
        checksum = None
    return ResourceItem(
        id=f"res_{path.name}",
        name=name,
        path=str(path),
        type="well_log",
        format="las",
        status="parsed",
        checksum=checksum,
        external=external,
    )


def _index_path(project_path: Path) -> Path:
    return catalog_dir_for(project_path) / DB_FILENAME


# ============================================================ 1. import RAW


def test_acceptance_01_import_raw(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"raw payload")
    version = catalog.service.import_raw(src)

    assert version.stage is DataStage.RAW
    assert version.managed is True
    assert version.version_number == 1
    payload = catalog.service.resolve_path(version)
    assert payload.is_file()
    assert payload.read_bytes() == b"raw payload"
    assert version.sha256 == sha256_file(src)
    assert ".artifacts" in str(payload)
    # RAW payload is immutable (read-only bit set).
    assert not payload.stat().st_mode & stat.S_IWUSR


# ================================================ 2. source changes later


def test_acceptance_02_source_changes_later_register_v2_same_asset(
    catalog, tmp_path: Path
):
    """The source file changes after import → the SAME asset gains a V2 with
    parent lineage — never a phantom asset."""
    src = _make_source(tmp_path, payload=b"version one")
    resource = _resource(src, name="well.las")
    v1 = catalog.register_input(
        name=resource.name,
        path=resource.path,
        checksum=resource.checksum,
        legacy_resource_id=resource.id,
    )

    src.write_bytes(b"version two EDITED")
    v2 = catalog.register_input(
        name=resource.name,
        path=resource.path,
        checksum=sha256_file(src),
        legacy_resource_id=resource.id,
    )

    assert v2.version_id != v1.version_id
    assert v2.asset_id == v1.asset_id  # SAME asset, no phantom
    asset = catalog.service.get_asset(v1.asset_id)
    assert asset.current_version_id == v2.version_id
    v2_core = catalog.service.get_version(v2.version_id)
    assert v2_core.version_number == 2
    assert v2_core.parent_version_ids == [v1.version_id]


def test_acceptance_02b_same_content_reimport_idempotent(catalog, tmp_path: Path):
    """Re-importing the same path + checksum returns the existing version."""
    src = _make_source(tmp_path, payload=b"stable")
    resource = _resource(src)
    ref1 = catalog.register_input(
        name=resource.name,
        path=resource.path,
        checksum=resource.checksum,
        legacy_resource_id=resource.id,
    )
    ref2 = catalog.register_input(
        name=resource.name,
        path=resource.path,
        checksum=sha256_file(src),
        legacy_resource_id=resource.id,
    )
    assert ref2.version_id == ref1.version_id
    assert len(catalog.service.list_versions(ref1.asset_id)) == 1


# ================================================= 3. managed RAW unchanged


def test_acceptance_03_managed_raw_unchanged_after_v2(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"original")
    v1 = catalog.service.import_raw(src)
    v1_payload = catalog.service.resolve_path(v1)
    v1_sha = v1.sha256

    src.write_bytes(b"changed content")
    v2 = catalog.service.import_raw(src, asset_id=v1.asset_id)

    assert v2.version_number == 2
    assert v1_payload.read_bytes() == b"original"
    assert catalog.service.get_version(v1.id).sha256 == v1_sha
    report = catalog.service.verify_integrity(v1.id)
    assert report.status_for(v1.id) == "verified"


# ==================================================== 4. RAW → working copy


def test_acceptance_04_raw_to_working_copy(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"parent-data")
    raw = catalog.service.import_raw(src)

    working = catalog.service.create_working_copy(raw.id)

    assert working.is_file()
    assert working.read_bytes() == b"parent-data"
    assert "working" in working.as_posix()
    # The working copy is writable even though the managed payload is read-only.
    assert working.stat().st_mode & stat.S_IWUSR
    raw_payload = catalog.service.resolve_path(raw)
    assert not raw_payload.stat().st_mode & stat.S_IWUSR


# ==================================================== 5. edit working copy


def test_acceptance_05_edit_working_copy(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"parent-data")
    raw = catalog.service.import_raw(src)
    working = catalog.service.create_working_copy(raw.id)

    working.write_bytes(b"parent-data-EDITED")

    assert working.read_bytes() == b"parent-data-EDITED"
    # The managed original is untouched by the edit.
    assert catalog.service.resolve_path(raw).read_bytes() == b"parent-data"


# ===================================================== 6. commit V2


def test_acceptance_06_commit_v2(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"parent-data")
    raw = catalog.service.import_raw(src)
    working = catalog.service.create_working_copy(raw.id)
    working.write_bytes(b"parent-data-filtered")

    child = catalog.service.commit_working_copy(working, asset_id=None, name="filtered")

    assert child.stage is DataStage.DERIVED
    assert child.version_number == 1
    assert child.parent_version_ids == [raw.id]
    # Working copy consumed (move semantics).
    assert not working.exists()
    # The committed DERIVED payload is immutable and correct.
    payload = catalog.service.resolve_path(child)
    assert payload.read_bytes() == b"parent-data-filtered"
    assert child.sha256 == sha256_file(payload)
    assert not payload.stat().st_mode & stat.S_IWUSR


# ========================================================= 7. V1 unchanged


def test_acceptance_07_v1_unchanged_after_commit(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"parent-data")
    raw = catalog.service.import_raw(src)
    raw_payload = catalog.service.resolve_path(raw)
    raw_sha = raw.sha256

    working = catalog.service.create_working_copy(raw.id)
    working.write_bytes(b"filtered")
    catalog.service.commit_working_copy(working)

    assert raw_payload.read_bytes() == b"parent-data"
    assert catalog.service.get_version(raw.id).sha256 == raw_sha
    assert catalog.service.verify_integrity(raw.id).status_for(raw.id) == "verified"


# ==================================================== 8. derived lineage


def test_acceptance_08_derived_lineage(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"raw")
    raw = catalog.service.import_raw(src)
    derived_src = tmp_path / "work" / "derived.csv"
    derived_src.parent.mkdir(parents=True)
    derived_src.write_bytes(b"derived")

    child = catalog.service.create_derived(
        derived_src,
        parent_version_ids=[raw.id],
        operation="derived_copy",
        generator="paleo-workbench test",
    )

    assert child.stage is DataStage.DERIVED
    assert child.run_id is not None
    run = catalog.service.get_run(child.run_id)
    assert run.operation == "derived_copy"
    assert run.input_version_ids == [raw.id]
    assert run.output_version_ids == [child.id]

    lineage = catalog.service.get_lineage(child.id)
    assert [v.id for v in lineage["parents"]] == [raw.id]
    assert lineage["run"] is not None
    parent_lineage = catalog.service.get_lineage(raw.id)
    assert [v.id for v in parent_lineage["children"]] == [child.id]
    # Ancestor walk through the adapter reaches the RAW version.
    ancestors = catalog.query_lineage(child.id, direction="ancestors")
    assert {a.version_id for a in ancestors} == {raw.id}


# ======================================================== 9. promotion


def test_acceptance_09_promotion(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"intermediate data")
    version = catalog.service.import_raw(src)
    catalog.service.register_intermediate(
        version.asset_id,
        _make_source(tmp_path, name="grid.npz", payload=b"grid"),
        parent_version_ids=[version.id],
    )
    intermediate = catalog.service.list_versions(version.asset_id)[-1]
    assert intermediate.stage is DataStage.INTERMEDIATE

    promoted = catalog.service.promote_version(
        intermediate.id, reviewed_by="QC-1", note="approved"
    )

    assert promoted.stage is DataStage.OUTPUT
    assert promoted.version_number == intermediate.version_number + 1
    assert promoted.parent_version_ids == [intermediate.id]
    assert promoted.managed is True
    # Payload is an immutable COPY in the outputs stage.
    payload = catalog.service.resolve_path(promoted)
    assert "outputs" in payload.as_posix()
    assert payload.read_bytes() == b"grid"
    assert not payload.stat().st_mode & stat.S_IWUSR
    # Promote run recorded; source intermediate version untouched.
    runs = [r for r in catalog.service.list_runs() if r.operation == "promote"]
    assert len(runs) == 1
    assert runs[0].input_version_ids == [intermediate.id]
    assert runs[0].output_version_ids == [promoted.id]
    assert runs[0].parameters["reviewed_by"] == "QC-1"
    assert catalog.service.get_version(intermediate.id).stage is DataStage.INTERMEDIATE
    # current_version_id advanced to the promoted OUTPUT.
    asset = catalog.service.get_asset(version.asset_id)
    assert asset.current_version_id == promoted.id


def test_acceptance_09b_promote_asset_current_version(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"x")
    raw = catalog.service.import_raw(src)
    promoted = catalog.service.promote_asset(raw.asset_id)
    assert promoted.stage is DataStage.OUTPUT
    assert promoted.parent_version_ids == [raw.id]


# ================================================== 10. export / delivery


def test_acceptance_10_export_and_delivery(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"workflow raw")
    resource = _resource(src)
    raw = catalog.register_input(
        name=resource.name,
        path=resource.path,
        checksum=resource.checksum,
        legacy_resource_id=resource.id,
    )
    # Export a real OUTPUT file with lineage to the RAW version.
    out = tmp_path / "deliverable.csv"
    out.write_bytes(b"CSV DATA")
    exported = register_export_output(
        name="deliverable.csv",
        output_path=str(out),
        fmt="csv",
        source_version_ids=[raw.version_id],
    )
    assert exported is not None
    assert exported.stage is DataStage.OUTPUT
    assert exported.checksum == sha256_file(out)
    ancestors = catalog.query_lineage(exported.version_id, direction="ancestors")
    assert {a.version_id for a in ancestors} == {raw.version_id}

    # Delivery: copy the OUTPUT payload to a destination + delivery run metadata.
    dest = tmp_path / "handoff" / "deliverable-final.csv"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(catalog.service.resolve_path(
        catalog.service.get_version(exported.version_id)
    ).read_bytes())
    run = catalog.service.register_run(
        "delivery",
        input_version_ids=[exported.version_id],
        parameters={
            "source_version_id": exported.version_id,
            "exported_path": dest.as_posix(),
            "checksum": sha256_file(dest),
            "format": "csv",
            "delivery_status": "exported",
        },
    )
    assert run.operation == "delivery"
    assert run.input_version_ids == [exported.version_id]
    assert run.parameters["delivery_status"] == "exported"
    assert dest.read_bytes() == b"CSV DATA"


# =========================================================== 11. trash


def test_acceptance_11_trash_asset(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"to be trashed")
    version = catalog.service.import_raw(src)
    asset_id = version.asset_id
    original_rel = version.path
    payload = catalog.service.resolve_path(version)
    assert payload.is_file()

    asset = catalog.service.trash_asset(asset_id, reason="cleanup")

    assert asset.trashed is True
    assert asset.trashed_at is not None
    trashed = catalog.service.get_version(version.id)
    assert trashed.trashed is True
    assert trashed.trashed_at is not None
    assert trashed.metadata["trash"]["reason"] == "cleanup"
    assert trashed.metadata["trash"]["original_stage"] == "raw"
    assert trashed.metadata["trash"]["original_path"] == original_rel
    # Payload moved into trash/{version_id}/.
    assert not payload.exists()
    trash_payload = catalog.service.resolve_path(trashed)
    assert "trash" in trash_payload.as_posix()
    assert trash_payload.is_file()
    assert trash_payload.read_bytes() == b"to be trashed"
    # Asset hidden from active listings and search.
    assert catalog.service.list_assets() == []
    assert catalog.service.search_assets(text="to be trashed") == []
    assert [a.id for a in catalog.service.get_trashed_assets()] == [asset_id]


def test_acceptance_11b_trash_version_only(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"v1")
    v1 = catalog.service.import_raw(src)
    src.write_bytes(b"v2")
    v2 = catalog.service.import_raw(src, asset_id=v1.asset_id)

    catalog.service.trash_version(v2.id, reason="redo")

    assert catalog.service.get_version(v2.id).trashed is True
    assert catalog.service.get_version(v1.id).trashed is False
    # current_version_id falls back to the newest active version (v1).
    assert catalog.service.get_asset(v1.asset_id).current_version_id == v1.id


# =========================================================== 12. reopen


def test_acceptance_12_reopen_preserves_catalog(catalog, tmp_path: Path, project_path: Path):
    src = _make_source(tmp_path, payload=b"persistent")
    version = catalog.service.import_raw(src)
    catalog.service.add_tag("important", asset_id=version.asset_id)
    catalog.service.close()

    svc = _reopen(project_path)
    try:
        reloaded = svc.get_version(version.id)
        assert reloaded.sha256 == version.sha256
        assert svc.resolve_path(reloaded).read_bytes() == b"persistent"
        assert svc.find_assets_by_tag("important") == [version.asset_id]
    finally:
        svc.close()


# ======================================================== 13. still trashed


def test_acceptance_13_still_trashed_after_reopen(
    catalog, tmp_path: Path, project_path: Path
):
    src = _make_source(tmp_path, payload=b"trash me")
    version = catalog.service.import_raw(src)
    asset_id = version.asset_id
    catalog.service.trash_asset(asset_id, reason="cleanup")
    catalog.service.close()

    svc = _reopen(project_path)
    try:
        asset = svc.get_asset(asset_id)
        assert asset.trashed is True
        assert svc.get_version(version.id).trashed is True
        assert svc.list_assets() == []
        assert [a.id for a in svc.get_trashed_assets()] == [asset_id]
        # Payload still in trash/ after reopen.
        trash_payload = svc.resolve_path(svc.get_version(version.id))
        assert "trash" in trash_payload.as_posix()
        assert trash_payload.read_bytes() == b"trash me"
    finally:
        svc.close()


# ========================================================== 14. restore


def test_acceptance_14_restore_asset(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"recoverable")
    version = catalog.service.import_raw(src)
    asset_id = version.asset_id
    catalog.service.trash_asset(asset_id, reason="oops")

    asset = catalog.service.restore_asset(asset_id)

    assert asset.trashed is False
    assert asset.trashed_at is None
    assert catalog.service.get_version(version.id).trashed is False
    assert catalog.service.get_version(version.id).metadata.get("trash") is None
    assert catalog.service.list_assets() == [asset]


# =================================================== 15. payload restored


def test_acceptance_15_payload_restored(catalog, tmp_path: Path):
    src = _make_source(tmp_path, payload=b"restore me")
    version = catalog.service.import_raw(src)
    original_rel = version.path
    original_abs = catalog.service.resolve_path(version)
    asset_id = version.asset_id

    catalog.service.trash_asset(asset_id, reason="cleanup")
    assert not original_abs.exists()

    catalog.service.restore_asset(asset_id)

    restored = catalog.service.get_version(version.id)
    assert restored.path == original_rel  # back at its original location
    payload = catalog.service.resolve_path(restored)
    assert payload == original_abs
    assert payload.read_bytes() == b"restore me"
    # Managed immutability restored.
    assert not payload.stat().st_mode & stat.S_IWUSR
    assert catalog.service.verify_integrity(version.id).status_for(version.id) == "verified"


# ======================================= 16. trash asset with references


def test_acceptance_16_trash_asset_with_references_keeps_lineage(
    catalog, tmp_path: Path
):
    src = _make_source(tmp_path, payload=b"parent")
    raw = catalog.service.import_raw(src)
    derived_src = tmp_path / "work" / "child.csv"
    derived_src.parent.mkdir(parents=True)
    derived_src.write_bytes(b"child")
    child = catalog.service.create_derived(
        derived_src, parent_version_ids=[raw.id], operation="derived_copy"
    )
    child_asset_id = child.asset_id

    # Trash the PARENT asset; the derived asset references it.
    catalog.service.trash_asset(raw.asset_id, reason="cleanup")

    assert catalog.service.get_version(raw.id).trashed is True
    # The derived asset/version is untouched and still resolves its parent.
    assert catalog.service.get_version(child.id).trashed is False
    lineage = catalog.service.get_lineage(child.id)
    parent = lineage["parents"][0]
    assert parent.id == raw.id
    assert parent.trashed is True  # lineage retained, marked trashed
    assert catalog.service.get_asset(child_asset_id).trashed is False


# ====================================== 17. external trash keeps external file


def test_acceptance_17_external_trash_keeps_external_file(catalog, tmp_path: Path):
    ext_path = tmp_path / "external" / "ext.las"
    ext_path.parent.mkdir(parents=True)
    ext_path.write_bytes(b"external bytes")
    linked = catalog.service.link_external(ext_path)

    catalog.service.trash_asset(linked.asset_id, reason="cleanup")

    version = catalog.service.get_version(linked.id)
    assert version.trashed is True
    # Metadata-only tombstone: the external file is untouched and the version
    # still points at the absolute external path.
    assert ext_path.is_file()
    assert ext_path.read_bytes() == b"external bytes"
    assert Path(version.path).is_absolute()

    # Restore is metadata-only too.
    catalog.service.restore_asset(linked.asset_id)
    assert catalog.service.get_version(linked.id).trashed is False
    assert ext_path.is_file()


# ================================================ 18. save-failure rollback


def test_acceptance_18_save_failure_rollback(catalog, tmp_path: Path, monkeypatch):
    src = _make_source(tmp_path, payload=b"precious")
    version = catalog.service.import_raw(src)
    asset_id = version.asset_id
    payload = catalog.service.resolve_path(version)
    before_revision = catalog.service.document.catalog_revision

    def boom(self, document):
        raise OSError("disk full")

    monkeypatch.setattr(CatalogStore, "save", boom)
    with pytest.raises(OSError):
        catalog.service.trash_asset(asset_id, reason="cleanup")

    # No tombstone, no payload move, revision unchanged.
    assert catalog.service.get_asset(asset_id).trashed is False
    assert catalog.service.get_version(version.id).trashed is False
    assert catalog.service.get_version(version.id).metadata.get("trash") is None
    assert payload.is_file()
    assert payload.read_bytes() == b"precious"
    assert catalog.service.document.catalog_revision == before_revision


def test_acceptance_18b_restore_save_failure_rollback(
    catalog, tmp_path: Path, monkeypatch
):
    src = _make_source(tmp_path, payload=b"keep")
    version = catalog.service.import_raw(src)
    asset_id = version.asset_id
    catalog.service.trash_asset(asset_id, reason="cleanup")
    trashed = catalog.service.get_version(version.id)
    trash_path = catalog.service.resolve_path(trashed)
    assert trash_path.is_file()

    def boom(self, document):
        raise OSError("disk full")

    monkeypatch.setattr(CatalogStore, "save", boom)
    with pytest.raises(OSError):
        catalog.service.restore_asset(asset_id)

    # Still trashed, payload still in trash/.
    assert catalog.service.get_asset(asset_id).trashed is True
    assert catalog.service.get_version(version.id).trashed is True
    assert trash_path.is_file()


# ======================= 19. derived failure cannot fall back into RAW dir


def test_acceptance_19_derived_failure_cannot_fall_back_into_raw_dir(
    catalog, tmp_path: Path
):
    src = _make_source(tmp_path, payload=b"raw")
    raw = catalog.service.import_raw(src)
    raw_payload = catalog.service.resolve_path(raw)

    missing_src = tmp_path / "work" / "missing.csv"
    with pytest.raises(CatalogError):
        catalog.service.create_derived(
            missing_src, parent_version_ids=[raw.id], operation="derived_copy"
        )

    # No half-state: no derived version/run/payload was created, and the RAW
    # payload was never aliased (the derived result never points into raw/).
    derived_root = tmp_path / "proj" / "demo.artifacts" / "derived"
    leftovers = (
        [p for p in derived_root.rglob("*") if p.is_file()]
        if derived_root.exists()
        else []
    )
    assert leftovers == []
    assert len(catalog.service.document.versions) == 1
    assert catalog.service.document.runs == []
    assert raw_payload.read_bytes() == b"raw"
    # The RAW payload is NOT referenced as a derived result.
    raw_version = catalog.service.get_version(raw.id)
    assert raw_version.stage is DataStage.RAW


# ================================================= 20. SQLite deleted/corrupt


def test_acceptance_20_sqlite_deleted_then_corrupt(
    catalog, tmp_path: Path, project_path: Path
):
    src = _make_source(tmp_path, payload=b"index me")
    version = catalog.service.import_raw(src)
    catalog.service.add_tag("alpha", asset_id=version.asset_id)
    catalog.service.trash_asset(version.asset_id, reason="cleanup")
    catalog.service.close()

    db = _index_path(project_path)
    assert db.is_file()
    db.unlink()

    svc = _reopen(project_path)
    try:
        assert svc.index_revision() == svc.document.catalog_revision
        assert svc.find_assets_by_tag("alpha") == [version.asset_id]
        assert svc.get_asset(version.asset_id).trashed is True
        assert svc.list_assets() == []
    finally:
        svc.close()

    # Corrupt the rebuilt index → still opens and queries correctly.
    svc2 = _reopen(project_path)
    try:
        assert [a.id for a in svc2.get_trashed_assets()] == [version.asset_id]
    finally:
        svc2.close()
    _index_path(project_path).write_bytes(b"not-a-sqlite-database")

    svc3 = _reopen(project_path)
    try:
        assert svc3.get_version(version.id).sha256 == version.sha256
        assert svc3.get_asset(version.asset_id).trashed is True
        assert svc3.find_assets_by_tag("alpha") == [version.asset_id]
    finally:
        svc3.close()


# ============================================= 21. rebuild from catalog.json


def test_acceptance_21_rebuild_index_from_catalog_json(
    catalog, tmp_path: Path, project_path: Path
):
    src = _make_source(tmp_path, payload=b"canonical")
    v1 = catalog.service.import_raw(src)
    catalog.service.add_tag("gold", asset_id=v1.asset_id)
    catalog.service.trash_asset(v1.asset_id, reason="cleanup")
    catalog.service.close()

    # The canonical store is the source of truth; delete the index and rebuild.
    _index_path(project_path).unlink()
    svc = _reopen(project_path)
    try:
        svc.rebuild_index()
        assert svc.index_revision() == svc.document.catalog_revision
        assert svc.find_assets_by_tag("gold") == [v1.asset_id]
        asset = svc.get_asset(v1.asset_id)
        assert asset.trashed is True
        assert svc.get_version(v1.id).trashed is True
        assert svc.get_version(v1.id).metadata["trash"]["original_stage"] == "raw"
        assert svc.list_versions(v1.asset_id) == [svc.get_version(v1.id)]
    finally:
        svc.close()


# ============================================ 22. lifecycle state preserved


def test_acceptance_22_lifecycle_state_preserved_across_reopen(
    catalog, tmp_path: Path, project_path: Path
):
    """Full lifecycle: import RAW → working copy → commit V2 → derived →
    promote → export → trash → restore → reopen; every piece of state survives."""
    src = _make_source(tmp_path, payload=b"lifecycle raw")
    raw = catalog.service.import_raw(src)
    raw_sha = raw.sha256

    working = catalog.service.create_working_copy(raw.id)
    working.write_bytes(b"edited v2")
    v2 = catalog.service.commit_working_copy(working, asset_id=raw.asset_id, name="v2")
    assert v2.version_number == 2 and v2.stage is DataStage.DERIVED

    derived_src = tmp_path / "work" / "derived.npz"
    derived_src.parent.mkdir(parents=True, exist_ok=True)
    derived_src.write_bytes(b"derived data")
    derived = catalog.service.create_derived(
        derived_src, parent_version_ids=[raw.id], operation="derived_copy"
    )
    promoted = catalog.service.promote_version(
        derived.id, reviewed_by="QC", note="final"
    )
    assert promoted.stage is DataStage.OUTPUT

    catalog.service.add_tag("lifecycle", asset_id=raw.asset_id)
    catalog.service.trash_asset(raw.asset_id, reason="archive")
    assert catalog.service.get_version(raw.id).trashed is True
    catalog.service.restore_asset(raw.asset_id)
    catalog.service.close()

    svc = _reopen(project_path)
    try:
        asset = svc.get_asset(raw.asset_id)
        assert asset.trashed is False
        versions = {v.version_number: v for v in svc.list_versions(raw.asset_id)}
        # RAW v1 + committed DERIVED v2 retained on the RAW asset.
        assert 1 in versions and versions[1].stage is DataStage.RAW
        assert 2 in versions and versions[2].stage is DataStage.DERIVED
        assert versions[1].sha256 == raw_sha
        # The derived asset carries the DERIVED version + the promoted OUTPUT.
        derived_asset = svc.get_asset(derived.asset_id)
        assert derived_asset.current_version_id == promoted.id
        derived_versions = {
            v.version_number: v for v in svc.list_versions(derived.asset_id)
        }
        assert 1 in derived_versions and derived_versions[1].stage is DataStage.DERIVED
        assert 2 in derived_versions and derived_versions[2].stage is DataStage.OUTPUT
        runs = {r.operation for r in svc.list_runs()}
        assert {"derived_copy", "promote"} <= runs
        lineage = svc.get_lineage(promoted.id)
        assert [p.id for p in lineage["parents"]] == [derived.id]
        # Tags survive.
        assert svc.find_assets_by_tag("lifecycle") == [raw.asset_id]
        # Integrity still verifies for the restored RAW payload.
        assert svc.verify_integrity(raw.id).status_for(raw.id) == "verified"
    finally:
        svc.close()


# ============================================ model-level invariants (bonus)


def test_trashed_versions_skipped_by_integrity_batch(catalog, tmp_path: Path):
    ok = catalog.service.import_raw(_make_source(tmp_path, name="a.las", payload=b"a"))
    doomed = catalog.service.import_raw(
        _make_source(tmp_path, name="b.las", payload=b"b")
    )
    catalog.service.trash_asset(doomed.asset_id, reason="cleanup")

    report = catalog.service.verify_integrity()
    assert report.status_for(ok.id) == "verified"
    assert doomed.id not in report.statuses  # trashed → skipped
    # Explicit trashed version is also skipped.
    report2 = catalog.service.verify_integrity(doomed.id)
    assert doomed.id not in report2.statuses


def test_purge_trashed_removes_only_trashed(catalog, tmp_path: Path):
    keep = catalog.service.import_raw(_make_source(tmp_path, name="keep.las", payload=b"k"))
    doomed = catalog.service.import_raw(
        _make_source(tmp_path, name="doom.las", payload=b"d")
    )
    doomed_payload = catalog.service.resolve_path(doomed)
    catalog.service.trash_asset(doomed.asset_id, reason="cleanup")

    removed = catalog.service.purge_trashed()

    # The trashed asset plus its single trashed version are both purged.
    assert removed == 2
    # Active asset untouched.
    assert catalog.service.get_asset(keep.asset_id).trashed is False
    assert catalog.service.resolve_path(keep).is_file()
    # Trashed asset + payload gone.
    assert catalog.service.get_trashed_assets() == []
    assert not doomed_payload.exists()
    assert all(not v.trashed for v in catalog.service.document.versions)


def test_reimport_after_trash_never_collides_on_legacy_bridge(catalog, tmp_path: Path):
    """A re-import carrying a legacy id that a TRASHED asset already holds must
    never steal the bridge: the bridge id is set once, so at most one asset can
    resolve through it (no phantom collision)."""
    src = _make_source(tmp_path, payload=b"first import")
    ref1 = catalog.register_input(
        name="well.las",
        path=str(src),
        checksum=sha256_file(src),
        legacy_resource_id="res_shared",
    )
    catalog.service.trash_asset(ref1.asset_id, reason="cleanup")
    assert catalog.service.get_asset(ref1.asset_id).trashed is True

    src.write_bytes(b"re-imported content")
    ref2 = catalog.register_input(
        name="well.las",
        path=str(src),
        checksum=sha256_file(src),
        legacy_resource_id="res_shared",
    )

    # Exactly ONE asset resolves the legacy id (the original trashed one) —
    # the new asset never claimed the already-taken bridge key.
    resolver = CoreCatalogAdapter(catalog.service)
    bridged = resolver._find_asset_by_legacy_id("res_shared")
    assert bridged is not None and bridged.id == ref1.asset_id
    assets_claiming = [
        a
        for a in catalog.service.document.assets
        if a.id == "res_shared" or a.legacy_resource_id == "res_shared"
    ]
    assert len(assets_claiming) == 1
    # The new asset is active and independent.
    new_asset = catalog.service.get_asset(ref2.asset_id)
    assert new_asset.id != ref1.asset_id
    assert new_asset.trashed is False


def test_modeling_run_records_honest_demo_source(catalog, tmp_path: Path):
    """P2: 3D modeling registration seam — synthetic demo run is honest.

    The in-memory synthetic demo result registers a ``modeling`` DataRun with
    explicit ``source="synthetic/demo"`` / ``demo=True`` and NO output version;
    a real payload file can be attached as DERIVED (P3 seam).
    """
    from paleo_workbench.catalog.lifecycle import register_modeling_run

    run, version = register_modeling_run(
        name="三维地质建模（合成演示）",
        source="synthetic/demo",
        demo=True,
        parameters={"density": "中精度 (80x80x80)", "algorithm": "synthetic_demo"},
        catalog=catalog,
    )
    assert run is not None
    assert run.parameters["source"] == "synthetic/demo"
    assert run.parameters["demo"] is True
    assert version is None  # no payload file for the in-memory demo result

    # Real-data seam: attach a payload file → DERIVED version with run linkage.
    payload = tmp_path / "geomodel.json"
    payload.write_text("{}", encoding="utf-8")
    run2, version2 = register_modeling_run(
        name="三维地质建模",
        source="real_data",
        output_path=str(payload),
        output_format="json",
        catalog=catalog,
    )
    assert version2 is not None
    assert version2.stage is DataStage.DERIVED
    assert version2.producing_run_id == run2.run_id
    assert version2.checksum == sha256_file(payload)
