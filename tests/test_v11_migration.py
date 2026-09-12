"""V11 migration & compatibility (goal §18): old projects open and upgrade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.domain import WellEntity, links_for_entity
from paleo_workbench.project.models import ProjectDocument, ResourceItem


def test_schema_v1_document_with_resources_upgrades(tmp_path: Path):
    """A pre-domain legacy document (schema 1, resources only) loads, gains
    the workarea layer, and its resources remain intact."""
    from paleo_workbench.catalog.migration import migrate_resources
    from paleo_workbench.catalog.models import CatalogDocument

    legacy = ProjectDocument.new("legacy")
    legacy.schema_version = 1
    src = tmp_path / "w1.las"
    src.write_text("~W\nWELL: W1\n", encoding="utf-8")
    legacy.resources.append(
        ResourceItem(name="w1.las", path=str(src), type="well_log", format="las")
    )

    # open-time catalog projection of the legacy resources
    document = CatalogDocument()
    migrate_resources(legacy.resources, tmp_path, document)
    assert len(document.assets) == 1
    assert document.assets[0].legacy_resource_id == legacy.resources[0].id

    # domain migration still marks the document upgraded
    from paleo_workbench.project.domain_migration import (
        migrate_project_to_workarea,
    )

    report = migrate_project_to_workarea(
        legacy,
        asset_id_by_legacy={legacy.resources[0].id: document.assets[0].id},
        project_path=tmp_path / "legacy.paleo.json",
        staged=[],
    )
    assert report.already_migrated or report.migrated
    assert len(legacy.resources) == 1  # resources untouched (reversible)


def test_v11_store_roundtrip_with_old_document(tmp_path: Path):
    """A catalog.json written by a PRE-V11 app version loads under V11 and
    survives a save→reopen cycle with ports/members intact afterwards."""
    project_file = tmp_path / "old.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    src = tmp_path / "a.las"
    src.write_text("las", encoding="utf-8")
    v1 = service.import_raw(src, name="a.las", type="well_log")
    service.export_manifest()
    service.close()

    # Simulate a pre-V11 manifest: strip the new keys entirely.
    from paleo_workbench.catalog.store import catalog_file_for

    manifest_path = catalog_file_for(project_file)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for run in data.get("runs", []):
        run.pop("input_ports", None)
        run.pop("output_ports", None)
    for version in data.get("versions", []):
        version.pop("members", None)
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    # V11 opens it (older revision honored via manifest mtime change)…
    store_path = project_file.parent / "old.artifacts" / "metadata" / "catalog.sqlite"
    if store_path.is_file():
        store_path.unlink()  # force the manifest re-import path
    reopened = DataCatalogService.open(project_file)
    try:
        assert reopened.get_version(v1.id) is not None
        assert reopened.get_version(v1.id).members == []
    finally:
        reopened.close()


def test_roles_backfill_is_idempotent(tmp_path: Path):
    """role_backfill (10-migration §3): missing primaries on required_single
    roles get exactly one candidate; ambiguous stays unresolved."""
    from paleo_workbench.catalog.roles_backfill import backfill_role_primaries

    doc = ProjectDocument.new("d")
    well = WellEntity(name="W1")
    doc.wells.append(well)
    from paleo_workbench.project.domain import EntityAssetLink, upsert_entity_asset_link

    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id="a1",
        role="well_head",
    )
    report = backfill_role_primaries(doc)
    assert report.get("well_head", 0) == 1
    primaries = [
        l for l in links_for_entity(doc, "well", well.id)
        if l.role == "well_head" and l.is_primary
    ]
    assert len(primaries) == 1

    # second asset in the role: NOT auto-promoted (ambiguous for a human)
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id="a2",
        role="well_head",
    )
    report2 = backfill_role_primaries(doc)
    assert report2.get("well_head", 0) == 0
    # re-run changes nothing (idempotent)
    report3 = backfill_role_primaries(doc)
    assert report3 == report2
