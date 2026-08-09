"""End-to-end data-lifecycle acceptance tests against the REAL production path.

``tests/test_data_lifecycle_e2e.py`` runs the same acceptance stories against
the InMemoryCatalog fake. This file mirrors them against the production
backend: ``CoreCatalogAdapter`` over a real ``DataCatalogService`` backed by a
tmp_path project (managed storage + canonical ``metadata/catalog.json`` +
SQLite index).

Stories covered:
  1. Import → managed RAW snapshot immune to source mutation
  2. RAW → derived → derived rerun (old versions retained, RAW untouched)
  3. Working copy edit → commit (new DERIVED version, RAW immutable)
  4. Lineage chain through lifecycle helpers (factor → prediction → export)
  5. Tags persist across close/reopen and SQLite index rebuild
  6. Integrity tamper → MODIFIED, recorded checksum preserved
  7. Legacy ResourceItem migration (deterministic, idempotent, persistent)
  8. External link whose source goes offline → MISSING, no crash
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

from paleo_workbench.catalog import (
    CoreCatalogAdapter,
    DataCatalogService,
    DataStage,
    IntegrityStatus,
    get_catalog,
    reset_catalog,
    set_catalog,
)
from paleo_workbench.catalog.db import DB_FILENAME
from paleo_workbench.catalog.lifecycle import (
    register_export_run,
    register_factor_map_run,
    register_prediction_run,
    register_resource_input,
)
from paleo_workbench.catalog.models import ImmutableVersionError
from paleo_workbench.catalog.storage import catalog_dir_for
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
    """Close-free fresh open of the same project (canonical store on disk)."""
    return DataCatalogService.open(project_path)


def _make_resource(
    path: Path,
    *,
    name: str = "src.las",
    content: bytes = b"log data",
    checksum: str | None = None,
    external: bool = False,
) -> ResourceItem:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return ResourceItem(
        name=name,
        path=str(path),
        type="well_log",
        format="las",
        status="parsed",
        checksum=checksum,
        external=external,
    )


def _writable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


# ===================================================================== Story 1


def test_story1_import_managed_raw_snapshot_immune_to_source_mutation(
    tmp_path: Path, catalog
):
    """Import with checksum=None → managed RAW v1 snapshot with sha256; later
    edits to the original source file cannot affect the snapshot."""
    src = tmp_path / "incoming" / "well.las"
    resource = _make_resource(src, content=b"original log curve", checksum=None)

    raw = register_resource_input(resource)

    assert raw is not None
    assert raw.stage is DataStage.RAW
    assert raw.external is False
    # checksum=None on the resource → computed once from disk at registration.
    assert raw.checksum == hashlib.sha256(b"original log curve").hexdigest()

    # The payload lives in managed storage, isolated from the source.
    version = catalog.service.get_version(raw.version_id)
    managed = catalog.service.resolve_path(version)
    assert managed.is_file()
    assert ".artifacts" in str(managed)

    # The original source file is mutated externally afterwards.
    src.write_bytes(b"HACKED EXTERNAL EDIT")

    # Managed payload content + recorded checksum are unchanged.
    assert managed.read_bytes() == b"original log curve"
    assert catalog.service.get_version(raw.version_id).sha256 == raw.checksum
    assert catalog.verify_integrity(raw.version_id) is IntegrityStatus.VERIFIED


def test_in_project_relative_path_registers_with_cwd_elsewhere(
    tmp_path: Path, catalog, project_path: Path, monkeypatch
):
    """import_service stores in-project files as PROJECT-RELATIVE paths; the
    adapter must resolve them against the project dir, never the process CWD.
    Regression: registration silently failed (CatalogError swallowed) whenever
    CWD != project dir, leaving the resource legacy-only and unmanaged."""
    # CWD deliberately elsewhere (the app never chdir()s to the project).
    monkeypatch.chdir(tmp_path)
    data_dir = project_path.parent / "wells"
    data_dir.mkdir(parents=True)
    las = data_dir / "inproj.las"
    content = b"in-project log"
    las.write_bytes(content)

    # Exactly what import_service._collect_resource stores for in-project files.
    resource = ResourceItem(
        name="inproj.las",
        path="wells/inproj.las",  # project-relative, NOT absolute
        type="well_log",
        format="las",
        status="parsed",
        checksum=None,
        external=False,
    )

    raw = register_resource_input(resource)
    assert raw is not None, "in-project import must register (relative path)"
    version = catalog.service.get_version(raw.version_id)
    assert version.managed is True
    managed = catalog.service.resolve_path(version)
    assert managed.is_file() and ".artifacts" in str(managed)
    assert version.sha256 == hashlib.sha256(content).hexdigest()
    assert catalog.verify_integrity(raw.version_id) is IntegrityStatus.VERIFIED

    # Idempotence: re-registering the same (relative) path + checksum dedups.
    again = register_resource_input(resource)
    assert again is not None and again.version_id == raw.version_id

    # The legacy bridge resolves the relative-path resource to the version.
    bridged = catalog.resolve_legacy_resource(resource.id)
    assert bridged is not None and bridged.version_id == raw.version_id


# ===================================================================== Story 2


def test_story2_derived_rerun_retains_versions_and_raw_untouched(
    tmp_path: Path, catalog
):
    """RAW v1 → derived → derived rerun creates ANOTHER new version; the old
    one is retained and the RAW version checksum is unchanged."""
    service = catalog.service
    src = tmp_path / "incoming" / "well.las"
    raw = register_resource_input(_make_resource(src, content=b"raw"))
    raw_version = service.get_version(raw.version_id)
    raw_sha = raw_version.sha256

    d1_src = tmp_path / "work" / "derived_v1.csv"
    d1_src.parent.mkdir(parents=True)
    d1_src.write_bytes(b"derived one")
    derived1 = service.create_derived(
        d1_src,
        parent_version_ids=[raw.version_id],
        name="filtered",
        operation="derived_copy",
        generator="paleo-workbench test",
    )

    # Rerun → a second, distinct immutable DERIVED version with the same parent.
    d2_src = tmp_path / "work" / "derived_v2.csv"
    d2_src.write_bytes(b"derived two")
    derived2 = service.create_derived(
        d2_src,
        parent_version_ids=[raw.version_id],
        name="filtered",
        operation="derived_copy",
        generator="paleo-workbench test",
    )

    assert derived1.id != derived2.id
    assert derived1.stage is DataStage.DERIVED
    assert derived2.stage is DataStage.DERIVED
    assert derived1.parent_version_ids == [raw.version_id]
    assert derived2.parent_version_ids == [raw.version_id]
    # Both retained and resolvable through the adapter.
    assert catalog.resolve_version(derived1.id) is not None
    assert catalog.resolve_version(derived2.id) is not None
    # Provenance runs recorded for both.
    runs = {r.operation for r in catalog.list_runs()}
    assert "derived_copy" in runs
    # RAW untouched.
    assert service.get_version(raw.version_id).sha256 == raw_sha
    assert catalog.verify_integrity(raw.version_id) is IntegrityStatus.VERIFIED


# ===================================================================== Story 3


def test_story3_working_copy_commit_creates_new_immutable_version(
    tmp_path: Path, catalog
):
    """create_working_copy → edit bytes → commit_working_copy → new immutable
    DERIVED version; RAW payload + checksum unchanged; committing over the same
    version id raises."""
    service = catalog.service
    src = tmp_path / "incoming" / "well.las"
    raw = register_resource_input(_make_resource(src, content=b"parent-data"))
    raw_version = service.get_version(raw.version_id)
    raw_payload = service.resolve_path(raw_version)

    working = service.create_working_copy(raw.version_id)
    working.write_bytes(b"parent-data-filtered")
    child = service.commit_working_copy(working, asset_id=None, name="filtered")

    assert child.stage == DataStage.DERIVED
    assert child.parent_version_ids == [raw.version_id]
    assert not working.exists()  # consumed (move semantics)
    # Parent RAW payload + recorded checksum unchanged.
    assert raw_payload.read_bytes() == b"parent-data"
    assert service.get_version(raw.version_id).sha256 == raw_version.sha256
    assert catalog.verify_integrity(raw.version_id) is IntegrityStatus.VERIFIED

    # Committing over an existing (committed) version id raises — immutability.
    other = tmp_path / "work" / "other.las"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(b"other")
    with pytest.raises((FileExistsError, ImmutableVersionError)):
        service.register_version(
            raw_version.asset_id,
            other,
            stage=DataStage.RAW,
            version_id=raw_version.id,
        )


# ===================================================================== Story 4


def test_story4_lineage_chain_through_lifecycle_helpers(tmp_path: Path, catalog):
    """RAW input → factor_map run (+ INTERMEDIATE grid) → prediction run →
    export OUTPUT; the OUTPUT's ancestors reach back to the RAW version."""
    from paleo_workbench.project.models import (
        ExportArtifact,
        FactorMapTask,
        PredictionTask,
    )

    src = tmp_path / "incoming" / "wf.las"
    resource = _make_resource(src, content=b"workflow raw")
    raw = register_resource_input(resource)

    # Factor map run consumes the RAW input (legacy bridge) and persists a
    # real INTERMEDIATE grid file.
    factor_task = FactorMapTask(
        name="H1 砂岩含量",
        target_horizon="H1",
        factor_type="砂岩含量",
        input_resource_ids=[resource.id],
        method="IDW",
        status="complete",
        generator_version="factor-interp-v1",
        input_snapshot_hash="abc",
    )
    grid_path = tmp_path / "work" / "grid.npz"
    grid_path.parent.mkdir(parents=True)
    grid_path.write_bytes(b"NPZ grid")
    factor_run, grid = register_factor_map_run(
        factor_task, intermediate_path=str(grid_path)
    )
    assert factor_run is not None
    assert grid is not None and grid.stage is DataStage.INTERMEDIATE

    # Prediction consumes the factor run's versions through the run graph.
    pred_task = PredictionTask(
        name="pred",
        adapter_kind="mock",
        status="complete",
        generator_version="mock-prediction-v1",
        input_snapshot_hash="def",
    )
    pred_run, _ = register_prediction_run(pred_task, factor_task_ids=[factor_task.id])
    assert pred_run is not None

    # Export a real OUTPUT file sourced from the prediction task + raw resource.
    out = tmp_path / "deliverable.png"
    out.write_bytes(b"PNG DATA")
    artifact = ExportArtifact(
        format="png",
        output_path=str(out),
        linked_id=resource.id,
        source_task_ids=[pred_task.id],
    )
    export_run, export_version = register_export_run(
        artifact=artifact, source_task_ids=[pred_task.id]
    )
    assert export_run is not None
    assert export_version.stage is DataStage.OUTPUT

    # From the OUTPUT, ancestors reach back (transitively) to the RAW version.
    ancestors = catalog.query_lineage(export_version.version_id, direction="ancestors")
    ancestor_ids = {a.version_id for a in ancestors}
    assert raw.version_id in ancestor_ids
    assert grid.version_id in ancestor_ids
    assert DataStage.RAW in {a.stage for a in ancestors}
    # Direct ancestors of the export output are non-empty.
    assert catalog.direct_ancestors(export_version.version_id)
    # All three runs recorded.
    runs = {r.operation for r in catalog.list_runs()}
    assert {"factor_map", "prediction", "export"} <= runs


# ===================================================================== Story 5


def test_story5_tags_persist_across_reopen_and_index_rebuild(
    tmp_path: Path, catalog, project_path: Path
):
    """Tags survive close → reopen, and survive deletion + rebuild of the
    SQLite index (canonical catalog.json is the source of truth)."""
    src = tmp_path / "incoming" / "tagged.las"
    raw = register_resource_input(_make_resource(src, content=b"tagged"))
    catalog.add_tags(raw.version_id, ["sand"])
    catalog.service.close()

    # Reopen from the canonical store: tag association intact.
    service2 = _reopen(project_path)
    try:
        assert raw.version_id in service2.find_versions_by_tag("sand")

        # Delete the SQLite index and rebuild it from the canonical store.
        db_path = catalog_dir_for(project_path) / DB_FILENAME
        assert db_path.exists()
        db_path.unlink()
        service2.rebuild_index()

        assert raw.version_id in service2.find_versions_by_tag("sand")
        # Assets / versions / lineage all intact after the rebuild.
        asset = service2.get_asset(raw.asset_id)
        assert asset.current_version_id == raw.version_id
        versions = service2.list_versions(raw.asset_id)
        assert [v.id for v in versions] == [raw.version_id]
        lineage = service2.get_lineage(raw.version_id)
        assert lineage["version"].id == raw.version_id
    finally:
        service2.close()


# ===================================================================== Story 6


def test_story6_integrity_tamper_reports_modified_checksum_preserved(
    tmp_path: Path, catalog
):
    """Tamper the managed RAW payload on disk → MODIFIED; the recorded
    checksum is never overwritten by verification."""
    service = catalog.service
    src = tmp_path / "incoming" / "integrity.las"
    raw = register_resource_input(_make_resource(src, content=b"pristine"))
    recorded = raw.checksum

    payload = service.resolve_path(service.get_version(raw.version_id))
    _writable(payload)  # managed payloads are read-only
    payload.write_bytes(b"tampered")

    assert catalog.verify_integrity(raw.version_id) is IntegrityStatus.MODIFIED
    assert service.get_version(raw.version_id).sha256 == recorded


# ===================================================================== Story 7


def test_story7_legacy_migration_deterministic_idempotent_persistent(
    tmp_path: Path, catalog, project_path: Path
):
    """Two legacy ResourceItems (checksum=None + external) migrate once;
    a second run migrates 0; the legacy bridge resolves both after reopen."""
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Legacy")
    managed_res = _make_resource(
        tmp_path / "incoming" / "legacy.las", content=b"legacy data", checksum=None
    )
    external_res = _make_resource(
        tmp_path / "external" / "ext.las",
        name="ext.las",
        content=b"external data",
        external=True,
    )
    project.resources.extend([managed_res, external_res])

    report1 = catalog.service.migrate_legacy_resources(project.resources)
    assert report1.migrated_count == 2

    # Idempotent: a second run migrates nothing.
    report2 = catalog.service.migrate_legacy_resources(project.resources)
    assert report2.migrated_count == 0
    assert report2.skipped_count == 2

    # The legacy bridge resolves both resources.
    managed_ref = catalog.resolve_legacy_resource(managed_res.id)
    external_ref = catalog.resolve_legacy_resource(external_res.id)
    assert managed_ref is not None and managed_ref.stage is DataStage.RAW
    assert external_ref is not None and external_ref.external is True

    # Save/reopen → Data Manager-facing data intact.
    catalog.service.close()
    service2 = _reopen(project_path)
    try:
        adapter2 = CoreCatalogAdapter(service2)
        assert adapter2.resolve_legacy_resource(managed_res.id) is not None
        ext_ref2 = adapter2.resolve_legacy_resource(external_res.id)
        assert ext_ref2 is not None and ext_ref2.external is True
        assert len(service2.list_assets()) == 2
    finally:
        service2.close()


# ===================================================================== Story 8


def test_story8_external_link_source_offline_reports_missing(
    tmp_path: Path, catalog, project_path: Path
):
    """An external (unmanaged) link whose source file is deleted reports
    MISSING — no exception — and the project still opens."""
    ext_path = tmp_path / "external" / "ext.sgy"
    ext_path.parent.mkdir(parents=True)
    ext_path.write_bytes(b"external cube")

    ref = catalog.register_input(
        name="ext.sgy",
        path=str(ext_path),
        checksum=None,
        kind="seismic",
        format="sgy",
        external=True,
    )
    assert ref.external is True
    # External links record no hash, so integrity is UNKNOWN while online.
    assert catalog.verify_integrity(ref.version_id) is IntegrityStatus.UNKNOWN

    ext_path.unlink()

    # Missing source → MISSING, no exception.
    assert catalog.verify_integrity(ref.version_id) is IntegrityStatus.MISSING

    # The project still opens cleanly with the offline link.
    catalog.service.close()
    service2 = _reopen(project_path)
    try:
        version = service2.get_version(ref.version_id)
        assert version.managed is False
        report = service2.verify_integrity(ref.version_id)
        assert report.status_for(ref.version_id) == "missing"
    finally:
        service2.close()


# ============================================== no-fallback runtime contract


def test_get_catalog_none_after_reset_and_lifecycle_degrades(
    tmp_path: Path, monkeypatch
):
    """Production has no in-memory fallback: after reset_catalog() with no
    injection, get_catalog() is None and lifecycle helpers return None."""
    monkeypatch.delenv("PALEO_DATA_CATALOG", raising=False)
    reset_catalog()

    assert get_catalog() is None

    src = tmp_path / "orphan.las"
    resource = _make_resource(src, content=b"orphan")
    assert register_resource_input(resource) is None


# ==================================== idempotent-hit legacy bridge (Review)


def test_idempotent_external_hit_refreshes_legacy_bridge(tmp_path: Path, catalog):
    """An external dedup hit must record legacy_resource_id when the caller
    provides one and the asset lacks it (protocol semantics, matches the fake)."""
    ext_path = tmp_path / "external" / "ext.las"
    ext_path.parent.mkdir(parents=True)
    ext_path.write_bytes(b"external")

    # First registration without a legacy id.
    ref1 = catalog.register_input(
        name="ext.las", path=str(ext_path), checksum=None, external=True
    )
    assert catalog.resolve_legacy_resource("res_late") is None

    # Re-register the same external path WITH a legacy id → same version, and
    # the bridge is now recorded.
    ref2 = catalog.register_input(
        name="ext.las",
        path=str(ext_path),
        checksum=None,
        external=True,
        legacy_resource_id="res_late",
    )
    assert ref2.version_id == ref1.version_id
    bridged = catalog.resolve_legacy_resource("res_late")
    assert bridged is not None
    assert bridged.version_id == ref1.version_id


def test_idempotent_managed_hit_refreshes_legacy_bridge(tmp_path: Path, catalog):
    """Same for the managed (source_uri + sha256) dedup path."""
    import hashlib

    src = tmp_path / "incoming" / "managed.las"
    src.parent.mkdir(parents=True)
    content = b"managed bytes"
    src.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()

    ref1 = catalog.register_input(
        name="managed.las", path=str(src), checksum=checksum, external=False
    )
    ref2 = catalog.register_input(
        name="managed.las",
        path=str(src),
        checksum=checksum,
        external=False,
        legacy_resource_id="res_managed",
    )
    assert ref2.version_id == ref1.version_id
    bridged = catalog.resolve_legacy_resource("res_managed")
    assert bridged is not None
    assert bridged.version_id == ref1.version_id


def test_idempotent_hit_never_overwrites_existing_bridge(tmp_path: Path, catalog):
    """First wins: an asset that already carries a legacy id keeps it."""
    ext_path = tmp_path / "external" / "kept.las"
    ext_path.parent.mkdir(parents=True)
    ext_path.write_bytes(b"external")

    ref1 = catalog.register_input(
        name="kept.las",
        path=str(ext_path),
        checksum=None,
        external=True,
        legacy_resource_id="res_first",
    )
    ref2 = catalog.register_input(
        name="kept.las",
        path=str(ext_path),
        checksum=None,
        external=True,
        legacy_resource_id="res_second",
    )
    assert ref2.version_id == ref1.version_id
    assert catalog.resolve_legacy_resource("res_first") is not None
    assert catalog.resolve_legacy_resource("res_second") is None


# ============================================ lineage guard regressions (Review)


def test_attach_lineage_rejects_self_loop(tmp_path: Path, catalog):
    from paleo_workbench.catalog.models import CatalogError

    raw = register_resource_input(
        _make_resource(tmp_path / "incoming" / "self.las", content=b"self")
    )
    with pytest.raises(CatalogError):
        catalog.attach_lineage(
            source_version_id=raw.version_id, target_version_id=raw.version_id
        )


def test_query_lineage_cycle_never_lists_start_as_own_ancestor(
    tmp_path: Path, catalog
):
    """Even with a manual cyclic edge, a version is never its own ancestor."""
    r1 = register_resource_input(
        _make_resource(tmp_path / "incoming" / "a.las", name="a.las", content=b"a")
    )
    r2 = register_resource_input(
        _make_resource(tmp_path / "incoming" / "b.las", name="b.las", content=b"b")
    )
    catalog.attach_lineage(source_version_id=r2.version_id, target_version_id=r1.version_id)
    catalog.attach_lineage(source_version_id=r1.version_id, target_version_id=r2.version_id)

    ancestors = catalog.query_lineage(r1.version_id, direction="ancestors")
    ancestor_ids = {a.version_id for a in ancestors}
    assert r2.version_id in ancestor_ids
    assert r1.version_id not in ancestor_ids

    descendants = catalog.query_lineage(r1.version_id, direction="descendants")
    descendant_ids = {d.version_id for d in descendants}
    assert r2.version_id in descendant_ids
    assert r1.version_id not in descendant_ids
