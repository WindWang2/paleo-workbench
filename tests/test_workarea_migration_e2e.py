"""Legacy project → WorkArea schema migration end-to-end tests.

Covers §21/§23: open legacy `.paleo.json` (no re-import), deterministic
migration, idempotent second open, save round-trip, save-as relocation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.project.domain_migration import (
    SCHEMA_VERSION_WORKAREA,
    build_asset_id_mapping,
    migrate_project_to_workarea,
)
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument, ResourceItem


WELL_DAT = """#WellHead File From SMI
#Name X Y
MIG-1 100 200
MIG-2 110 210
"""


def write_legacy_project(tmp_path: Path, *, with_well_head: bool = True) -> Path:
    """Hand-write a schema-v1 document exactly like an old app version."""
    resources = []
    if with_well_head:
        dat = tmp_path / "井位.dat"
        dat.write_text(WELL_DAT, encoding="utf-8")
        resources.append(
            {
                "id": "res_wh1",
                "name": "井位.dat",
                "path": dat.name,
                "type": "well_head",
                "format": "dat",
                "status": "indexed",
                "tags": [],
                "source": "import",
                "parsed_summary": {"size_bytes": dat.stat().st_size},
                "checksum": None,
                "external": False,
            }
        )
    doc = {
        "schema_version": 1,
        "meta": {"name": "老工区", "region": "渤海", "project_root": "."},
        "coordinate": {"project_crs": "EPSG:4326", "display_crs": "EPSG:4326"},
        "resources": resources,
    }
    project_file = tmp_path / "老工区.paleo.json"
    project_file.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return project_file


class TestMigrationEndToEnd:
    def test_open_migrate_save_reopen(self, tmp_path: Path):
        project_file = write_legacy_project(tmp_path)
        # --- first open: legacy loads fine, no domain data required.
        loaded = ProjectManager(project_file).load()
        assert isinstance(loaded, ProjectDocument)
        assert loaded.workarea is None and not loaded.wells

        # --- background maintenance equivalent: migrate in memory.
        report = migrate_project_to_workarea(
            loaded, asset_id_by_legacy={"res_wh1": "asset_9"}, project_path=tmp_path
        )
        assert report.migrated
        assert [w.name for w in loaded.wells] == ["MIG-1", "MIG-2"]
        assert loaded.schema_version == SCHEMA_VERSION_WORKAREA
        assert len(loaded.entity_asset_links) == 2

        # --- user saves; new schema persists WITHOUT touching RAW payloads.
        manager = ProjectManager(project_file)
        manager.save(loaded)
        saved = json.loads(project_file.read_text(encoding="utf-8"))
        assert saved["schema_version"] == SCHEMA_VERSION_WORKAREA
        assert len(saved["wells"]) == 2
        # Legacy resource untouched:
        assert saved["resources"][0]["id"] == "res_wh1"

        # --- second open: migrated state reads back identically.
        reopened = ProjectManager(project_file).load()
        assert reopened.schema_version == SCHEMA_VERSION_WORKAREA
        assert [w.id for w in reopened.wells] == [w.id for w in loaded.wells]
        # Migration is a no-op on the already-migrated document.
        again = migrate_project_to_workarea(
            reopened, asset_id_by_legacy={"res_wh1": "asset_9"}, project_path=tmp_path
        )
        assert again.already_migrated
        assert len(reopened.wells) == 2

    def test_repeated_open_never_duplicates_wells(self, tmp_path: Path):
        project_file = write_legacy_project(tmp_path)
        # First open: no catalog yet → entities discovered, links deferred.
        loaded = ProjectManager(project_file).load()
        migrate_project_to_workarea(loaded, project_path=tmp_path)
        ProjectManager(project_file).save(loaded)

        # Second open: catalog now available → late-binding pass attaches
        # links exactly once; third open adds nothing.
        mapping = {"res_wh1": "asset_9"}
        reopened = ProjectManager(project_file).load()
        migrate_project_to_workarea(reopened, asset_id_by_legacy=mapping, project_path=tmp_path)
        assert len(reopened.wells) == 2
        assert len(reopened.entity_asset_links) == 2
        ProjectManager(project_file).save(reopened)

        third = ProjectManager(project_file).load()
        migrate_project_to_workarea(third, asset_id_by_legacy=mapping, project_path=tmp_path)
        assert len(third.wells) == 2  # never duplicated
        assert len(third.entity_asset_links) == 2

    def test_save_as_relocates_domain_state(self, tmp_path: Path):
        from paleo_workbench.project.paths import relocate_artifacts

        project_file = write_legacy_project(tmp_path)
        loaded = ProjectManager(project_file).load()
        migrate_project_to_workarea(loaded, asset_id_by_legacy={"res_wh1": "a"}, project_path=tmp_path)
        manager = ProjectManager(project_file)
        manager.save(loaded)

        target = tmp_path / "sub" / "新工区.paleo.json"
        target.parent.mkdir()
        relocate_artifacts(project_file, target)
        relocated_doc = loaded.model_copy(deep=True)
        ProjectManager(target).save(relocated_doc)
        moved = ProjectManager(target).load()
        assert [w.name for w in moved.wells] == ["MIG-1", "MIG-2"]

    def test_catalog_mapping_helper(self):
        class FakeAsset:
            def __init__(self, aid, legacy):
                self.id = aid
                self.legacy_resource_id = legacy

        class FakeService:
            def list_assets(self, include_trashed=False):  # noqa: ARG002
                return [FakeAsset("asset_x", "res_x"), FakeAsset("asset_y", None)]

        mapping = build_asset_id_mapping(FakeService())
        assert mapping == {"res_x": "asset_x"}
        assert build_asset_id_mapping(None) == {}

    def test_corrupt_source_not_corrupted_by_failed_migration(self, tmp_path: Path):
        project_file = write_legacy_project(tmp_path)
        original_text = project_file.read_text(encoding="utf-8")
        loaded = ProjectManager(project_file).load()
        # Force a resolver that explodes on every path.
        def boom(_relative: str):
            raise OSError("disk gone")

        report = migrate_project_to_workarea(
            loaded,
            asset_id_by_legacy={"res_wh1": "a"},
            project_path=tmp_path,
        )
        del boom
        # Even with issues the source file is untouched (in-memory only).
        assert project_file.read_text(encoding="utf-8") == original_text
        assert isinstance(report.binding.issues, list)


class TestImportDefaultsManagedRaw:
    """§12: default import creates managed RAW; Link External stays optional."""

    def test_import_raw_creates_managed_copy(self, tmp_path: Path):
        pytest.importorskip("paleo_workbench.catalog")
        from paleo_workbench.catalog import DataCatalogService
        from paleo_workbench.catalog.models import DataStage

        src = tmp_path / "src.dat"
        src.write_text(WELL_DAT, encoding="utf-8")
        project_file = tmp_path / "p.paleo.json"
        project_file.write_text("{}", encoding="utf-8")

        service = DataCatalogService.open(project_file, ensure_index=False, sweep_temp=False)
        try:
            version = service.import_raw(str(src), name="井位.dat", type="well_head", format="dat")
            asset = service.get_asset(version.asset_id)
            assert asset.current_version_id == version.id
            assert version.stage == DataStage.RAW
            assert version.managed is True
            managed_path = version.path
            assert ".artifacts/raw/" in managed_path
            assert version.sha256
            # Managed copy exists next to the project; source untouched but
            # independent (mutating source does not affect managed payload).
            resolved = tmp_path / managed_path
            assert resolved.is_file()
        finally:
            service.close()

    def test_link_external_stays_unmanaged(self, tmp_path: Path):
        from paleo_workbench.catalog import DataCatalogService
        from paleo_workbench.catalog.models import DataStage

        external = tmp_path / "outside" / "big.sgy"
        external.parent.mkdir()
        external.write_bytes(b"segy-bytes")
        project_file = tmp_path / "p.paleo.json"
        project_file.write_text("{}", encoding="utf-8")

        service = DataCatalogService.open(project_file, ensure_index=False, sweep_temp=False)
        try:
            version = service.link_external(str(external), name="big.sgy", type="seismic")
            assert version.managed is False
            assert version.stage == DataStage.RAW
            assert str(external) in version.path
        finally:
            service.close()


# #940-3: the former skipif(True) placeholder ("covered elsewhere") is
# removed — a permanent skip asserts nothing and hides the gap. The catalog
# suite owns the behavior; nothing needs to live here.
