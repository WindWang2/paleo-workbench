"""Tests for the legacy ResourceItem → catalog projection migration (ADR 0056 D2).

Covers: field mapping, external vs managed paths, robustness (missing file,
checksum=None), idempotence, determinism, mixed inputs, and needs_migration.
"""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.catalog.migration import (
    MigrationReport,
    migrate_resources,
    needs_migration,
)
from paleo_workbench.catalog.models import CatalogDocument, DataStage
from paleo_workbench.project.models import ResourceItem

FIXED_NOW = "2026-01-01T00:00:00+00:00"


def _resource(id_: str = "res_aaa111", **overrides) -> ResourceItem:
    base = dict(
        id=id_,
        name="well.las",
        path="data/well.las",
        type="well_log",
        format="las",
        crs="EPSG:4326",
        status="ready",
        tags=["role_well"],
        source="scan",
        parsed_summary={"size_bytes": 1024},
        checksum="deadbeef" * 4,
    )
    base.update(overrides)
    return ResourceItem(**base)


def test_migrate_local_resource_projects_asset_and_raw_v1(tmp_path: Path):
    project = tmp_path / "proj.paleo.json"
    well = tmp_path / "data" / "well.las"
    well.parent.mkdir(parents=True)
    well.write_bytes(b"\x00\x01")

    resource = _resource(
        id_="res_well_1",
        path=well.as_posix(),  # absolute on disk → stored project-relative
        parsed_summary={"size_bytes": 2},
        checksum="abc123",
    )
    document = CatalogDocument()

    report = migrate_resources([resource], project, document)

    assert isinstance(report, MigrationReport)
    assert report.migrated_count == 1
    assert report.skipped_count == 0
    assert report.asset_ids == ["res_well_1"]
    assert report.warnings == []

    (asset,) = document.assets
    (version,) = document.versions
    assert asset.id == "res_well_1"
    assert asset.legacy_resource_id == "res_well_1"
    assert asset.name == "well.las"
    assert asset.type == "well_log"
    assert asset.current_version_id == version.id
    assert asset.metadata["status"] == "ready"
    assert asset.metadata["source"] == "scan"
    assert asset.metadata["crs"] == "EPSG:4326"
    assert asset.metadata["legacy_tags"] == ["role_well"]

    assert version.id == "ver_res_well_1"
    assert version.asset_id == "res_well_1"
    assert version.version_number == 1
    assert version.stage is DataStage.RAW
    assert version.managed is True
    assert version.path == "data/well.las"
    assert version.format == "las"
    assert version.size_bytes == 2
    assert version.sha256 == "abc123"
    assert version.source_uri == well.as_posix()
    assert version.parent_version_ids == []
    assert version.metadata["legacy_tags"] == ["role_well"]
    assert version.metadata["status"] == "ready"


def test_migrate_external_resource_keeps_absolute_path_unmanaged(tmp_path: Path):
    proj_dir = tmp_path / "projdir"
    proj_dir.mkdir()
    project = proj_dir / "proj.paleo.json"
    ext_dir = tmp_path / "external"
    ext_dir.mkdir()
    segy = ext_dir / "well.sgy"
    segy.write_bytes(b"SEGY")

    resource = _resource(
        id_="res_ext_9",
        name="well.sgy",
        path=segy.as_posix(),
        type="seismic",
        format="sgy",
        external=True,
        parsed_summary={"size_bytes": 4},
        checksum=None,
    )
    document = CatalogDocument()

    report = migrate_resources([resource], project, document)

    assert report.migrated_count == 1
    assert report.warnings == []
    (version,) = document.versions
    assert version.managed is False
    assert version.path == segy.as_posix()
    assert version.sha256 is None
    assert version.source_uri == segy.as_posix()
    (asset,) = document.assets
    assert asset.id == "res_ext_9"
    assert asset.legacy_resource_id == "res_ext_9"


def test_missing_file_warns_and_still_migrates(tmp_path: Path):
    project = tmp_path / "proj.paleo.json"
    resource = _resource(
        id_="res_missing_1",
        path="data/gone.las",  # never created on disk
        checksum=None,
    )
    document = CatalogDocument()

    report = migrate_resources([resource], project, document)

    assert report.migrated_count == 1
    assert len(report.warnings) == 1
    assert "res_missing_1" in report.warnings[0]
    (version,) = document.versions
    assert version.sha256 is None
    # Already-relative input is normalized to a project-relative POSIX path.
    assert version.path == "data/gone.las"
    # No absolute path is derivable from a relative path → source_uri None.
    assert version.source_uri is None


def test_checksum_none_never_rehashes_file(tmp_path: Path, monkeypatch):
    import paleo_workbench.catalog.checksum as checksum_module

    project = tmp_path / "proj.paleo.json"
    well = tmp_path / "well.las"
    well.write_bytes(b"x" * 5)
    resource = _resource(
        id_="res_nohash",
        path=well.as_posix(),
        checksum=None,
        parsed_summary={"size_bytes": 5},
    )

    def fail_hash(*_args, **_kwargs):
        raise AssertionError("migration must not hash files")

    monkeypatch.setattr(checksum_module, "sha256_file", fail_hash)

    document = CatalogDocument()
    report = migrate_resources([resource], project, document)

    assert report.warnings == []
    (version,) = document.versions
    assert version.sha256 is None
    assert version.size_bytes == 5


def test_migration_writes_nothing_to_disk(tmp_path: Path):
    project = tmp_path / "proj.paleo.json"
    well = tmp_path / "data" / "well.las"
    well.parent.mkdir()
    well.write_bytes(b"data")
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    resource = _resource(id_="res_ro", path=well.as_posix())
    document = CatalogDocument()
    migrate_resources([resource], project, document)

    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before


def test_second_migration_is_idempotent(tmp_path: Path):
    project = tmp_path / "proj.paleo.json"
    resources = [
        _resource(id_="res_a"),
        _resource(id_="res_b", name="b.las", path="data/b.las"),
    ]
    document = CatalogDocument()

    first = migrate_resources(resources, project, document)
    assert first.migrated_count == 2
    before = document.model_dump()

    second = migrate_resources(resources, project, document)

    assert second.migrated_count == 0
    assert second.skipped_count == len(resources)
    assert second.asset_ids == []
    assert len(document.assets) == 2
    assert len(document.versions) == 2
    assert document.model_dump() == before


def test_migration_is_deterministic_across_documents(tmp_path: Path):
    project = tmp_path / "proj.paleo.json"
    resources = [
        _resource(id_="res_a"),
        _resource(id_="res_b", name="b.las", path="data/b.las"),
    ]
    doc_a = CatalogDocument()
    doc_b = CatalogDocument()

    migrate_resources(resources, project, doc_a, now=lambda: FIXED_NOW)
    migrate_resources(resources, project, doc_b, now=lambda: FIXED_NOW)

    assert doc_a.model_dump() == doc_b.model_dump()


def test_mixed_resources_external_missing_and_local(tmp_path: Path):
    proj_dir = tmp_path / "projdir"
    proj_dir.mkdir()
    project = proj_dir / "proj.paleo.json"
    local = proj_dir / "data" / "local.las"
    local.parent.mkdir()
    local.write_bytes(b"local")
    ext_dir = tmp_path / "external"
    ext_dir.mkdir()
    ext = ext_dir / "ext.sgy"
    ext.write_bytes(b"ext")

    resources = [
        _resource(
            id_="res_local",
            name="local.las",
            path=local.as_posix(),
            checksum="c1",
            parsed_summary={"size_bytes": 5},
        ),
        _resource(
            id_="res_ext",
            name="ext.sgy",
            path=ext.as_posix(),
            type="seismic",
            format="sgy",
            external=True,
            checksum=None,
            parsed_summary={"size_bytes": 3},
        ),
        _resource(
            id_="res_missing",
            name="gone.txt",
            path="gone.txt",
            format="txt",
            checksum="c3",
        ),
    ]
    document = CatalogDocument()

    report = migrate_resources(resources, project, document)

    assert report.migrated_count == 3
    assert report.skipped_count == 0
    assert report.asset_ids == ["res_local", "res_ext", "res_missing"]
    assert len(report.warnings) == 1
    assert "res_missing" in report.warnings[0]

    (local_v, ext_v, missing_v) = document.versions
    assert local_v.managed is True
    assert local_v.path == "data/local.las"
    assert ext_v.managed is False
    assert ext_v.path == ext.as_posix()
    # A recorded checksum is preserved even when the file is gone.
    assert missing_v.sha256 == "c3"


def test_empty_resources_returns_empty_report(tmp_path: Path):
    project = tmp_path / "proj.paleo.json"
    document = CatalogDocument()

    report = migrate_resources([], project, document)

    assert report.migrated_count == 0
    assert report.skipped_count == 0
    assert report.asset_ids == []
    assert report.warnings == []
    assert document.assets == []
    assert document.versions == []


def test_needs_migration_filters_unmigrated_resources(tmp_path: Path):
    project = tmp_path / "proj.paleo.json"
    r1 = _resource(id_="res_a")
    r2 = _resource(id_="res_b")
    r3 = _resource(id_="res_c")
    document = CatalogDocument()
    migrate_resources([r1], project, document)

    assert needs_migration([r1, r2, r3], document) == [r2, r3]
    assert needs_migration([r3, r1], document) == [r3]
    assert needs_migration([], document) == []


def test_migration_never_mutates_resource_items(tmp_path: Path):
    project = tmp_path / "proj.paleo.json"
    resource = _resource(id_="res_keep")
    before = resource.model_dump()

    document = CatalogDocument()
    migrate_resources([resource], project, document)

    assert resource.model_dump() == before
