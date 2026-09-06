"""Provenance atomicity + path identity fail-closed (#1219, #1221, v6 §11/§12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataAsset, DataStage, DataVersion
from paleo_workbench.catalog.service import CatalogError, DataCatalogService
from paleo_workbench.project.models import ResourceItem


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str, payload: bytes) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


# ------------------------------------------------------------- #1219 ghosts

def test_map_product_books_running_and_completes(tmp_path):
    """Source contract: the assembly path books running → registers →
    completes (O before C), so a crash between saves leaves a RUNNING run
    (recoverable), never a completed ghost."""
    import inspect

    from paleo_workbench.workflow import map_product as wmp

    src = inspect.getsource(wmp.assemble_map_product)
    assert 'status="running"' in src
    assert 'update_run_status(run.id, "complete")' in src
    # Failure compensation marks the run failed.
    assert '"failed"' in src


def test_audit_detects_and_repairs_ghosts(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        # A pre-v6 ghost: completed map_product_assembly with no outputs.
        ghost = service.register_run(
            "map_product_assembly", input_version_ids=[], parameters={}
        )
        assert ghost.status == "completed"

        report = service.audit()
        kinds = [issue.kind for issue in report.issues]
        assert "orphan_completed_run" in kinds

        repaired = service.repair_ghost_runs()
        assert ghost.id in repaired
        assert service.get_run(ghost.id).status == "failed"
        assert service.get_run(ghost.id).parameters.get("ghost_repair")

        # Second pass: nothing left to repair; honest runs untouched.
        assert service.repair_ghost_runs() == []
        good = service.import_raw(_make_source(tmp_path, "ok.las", b"ok"))
        assert good.sha256 is not None
    finally:
        service.close()


# ---------------------------------------------------------- #1221 fail-closed

def test_basename_fallback_refused_without_identity_facts(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        # A recorded external path that does not exist, with NO sha and NO
        # size — a same-named stranger inside the project must NOT bind.
        stranger = tmp_path / "proj" / "GR.las"
        stranger.write_bytes(b"totally different science")
        version = DataVersion(
            id="ver_ext1",
            asset_id="asset_x",
            version_number=1,
            stage=DataStage.RAW,
            managed=False,
            path="/definitely/elsewhere/GR.las",
            size_bytes=None,
            sha256=None,
        )
        service.document.versions.append(version)
        service._invalidate_maps()
        resolved = service.resolve_path(version)
        assert not resolved.is_file()  # surfaces missing, not the stranger
        assert resolved.as_posix().endswith("/definitely/elsewhere/GR.las")
    finally:
        service.close()


def test_basename_fallback_still_binds_with_recorded_size(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        moved = tmp_path / "proj" / "GR.las"
        moved.write_bytes(b"same bytes")
        version = DataVersion(
            id="ver_ext2",
            asset_id="asset_x",
            version_number=1,
            stage=DataStage.RAW,
            managed=False,
            path="/old/location/GR.las",
            size_bytes=len(b"same bytes"),
            sha256=None,
        )
        service.document.versions.append(version)
        service._invalidate_maps()
        resolved = service.resolve_path(version)
        assert resolved.is_file()
        assert resolved == moved.resolve()
    finally:
        service.close()


def test_migration_backfills_stat_fingerprint(tmp_path):
    """Legacy external resources without checksum/size gain a measurable
    stat fingerprint instead of arriving identity-less forever."""
    from paleo_workbench.catalog.migration import migrate_resources

    project = _make_project(tmp_path)
    external = tmp_path / "legacy.las"
    external.write_bytes(b"legacy bytes")
    resource = ResourceItem(
        id="res-1",
        name="legacy.las",
        path=str(external),
        type="well_log",
        format="las",
        checksum=None,
    )
    service = DataCatalogService.open(project)
    try:
        report = migrate_resources([resource], project, service.document)
        assert report.migrated_count == 1
        version = service.document.versions[0]
        assert version.size_bytes == len(b"legacy bytes")
        stat = version.metadata.get("external_stat")
        assert stat and "size" in stat and "mtime_ns" in stat
    finally:
        service.close()
