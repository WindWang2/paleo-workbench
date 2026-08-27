"""SQLite-canonical catalog storage (Issue #1027).

``catalog.sqlite`` (WAL) is the canonical metadata store; ``catalog.json`` is
demoted to a checkpoint/export manifest. These tests lock the storage
invariants: mutations persist transactionally per-row (never via a full
document rewrite), the legacy JSON project migrates crash-safely, the model
registry round-trips, and reopening reads from SQLite.
"""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

import pytest

from paleo_workbench.catalog.db import CatalogIndex
from paleo_workbench.catalog.models import CatalogDocument, DataAsset
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import catalog_dir_for
from paleo_workbench.catalog.store import (
    catalog_bak_file_for,
    catalog_file_for,
)


@pytest.fixture
def service(tmp_path):
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project)
    yield svc
    svc.close()


def _db_file(project_path: Path) -> Path:
    return catalog_dir_for(project_path) / "catalog.sqlite"


def _source(parent: Path, name: str, payload: bytes = b"payload") -> Path:
    src = parent / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


# ---------------------------------------------------------------------------
# Mutations are incremental (no canonical JSON rewrite)
# ---------------------------------------------------------------------------


def test_mutation_leaves_catalog_json_untouched(service):
    """A metadata/tag mutation must not rewrite the multi-megabyte manifest."""
    version = service.import_raw(_source(service.project_path.parent, "a.bin"))
    service.close()  # first checkpoint materializes the manifest
    service = DataCatalogService.open(service.project_path)
    json_path = catalog_file_for(service.project_path)
    before = json_path.read_bytes()

    service.update_asset_metadata(version.asset_id, {"quality": "good"})
    service.add_tag("qc", asset_id=version.asset_id)

    assert json_path.read_bytes() == before, (
        "catalog.json was rewritten during a single-row mutation"
    )
    # But the mutation IS durable in the canonical store.
    reopened = DataCatalogService.open(service.project_path)
    assert reopened.get_asset(version.asset_id).metadata["quality"] == "good"
    reopened.close()


def test_reopen_reads_canonical_state_from_sqlite(service):
    """State survives reopen even when the JSON manifest is deleted."""
    version = service.import_raw(_source(service.project_path.parent, "a.bin"))
    service.add_tag("qc", asset_id=version.asset_id)
    service.close()

    catalog_file_for(service.project_path).unlink()
    catalog_bak_file_for(service.project_path).unlink(missing_ok=True)

    reopened = DataCatalogService.open(service.project_path)
    assert reopened.get_asset(version.asset_id) is not None
    assert "qc" in [t.name for t in reopened.list_tags()]
    reopened.close()


def test_batch_save_does_not_deep_copy_document(service, monkeypatch):
    """batch_save must not model_copy(deep=True) the whole graph (#1027)."""
    deep_copies: list[int] = []
    real_model_copy = CatalogDocument.model_copy

    def spy(self, **kwargs):
        if kwargs.get("deep"):
            deep_copies.append(len(self.assets))
        return real_model_copy(self, **kwargs)

    monkeypatch.setattr(CatalogDocument, "model_copy", spy)

    with service.batch_save():
        for i in range(5):
            service.import_raw(
                _source(service.project_path.parent, f"b{i}.bin", f"v{i}".encode())
            )

    assert deep_copies == [], "batch_save performed a full-graph deep copy"
    # And the batch is durably persisted in one go.
    reopened = DataCatalogService.open(service.project_path)
    assert len(reopened.list_assets()) >= 5
    reopened.close()


def test_failed_batch_restores_document_from_canonical(service):
    """A failed batch leaves memory equal to the (untouched) canonical state."""
    version = service.import_raw(_source(service.project_path.parent, "a.bin"))
    before_tags = {t.name for t in service.list_tags()}

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with service.batch_save():
            service.add_tag("doomed", asset_id=version.asset_id)
            service.add_tag("also-doomed", asset_id=version.asset_id)
            raise _Boom()

    assert {t.name for t in service.list_tags()} == before_tags
    reopened = DataCatalogService.open(service.project_path)
    assert {t.name for t in reopened.list_tags()} == before_tags
    reopened.close()


# ---------------------------------------------------------------------------
# Legacy catalog.json migration
# ---------------------------------------------------------------------------


def _legacy_project(tmp_path: Path, n_assets: int = 3) -> Path:
    """A pre-SQLite-canonical project: only catalog.json exists."""
    project = tmp_path / "legacy" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")
    document = CatalogDocument(catalog_revision=7)
    for i in range(n_assets):
        document.assets.append(
            DataAsset(id=f"asset_{i}", name=f"legacy-{i}", type="raw")
        )
    metadata_dir = catalog_dir_for(project)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "catalog.json").write_text(
        json.dumps(document.model_dump(mode="json")), encoding="utf-8"
    )
    return project


def test_legacy_json_migrates_transactionally(tmp_path):
    project = _legacy_project(tmp_path)
    service = DataCatalogService.open(project)

    db_path = _db_file(project)
    assert db_path.is_file()
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT count(*) FROM assets").fetchone()[0] == 3
    assert conn.execute(
        "SELECT value FROM sync_state WHERE key='catalog_revision'"
    ).fetchone()[0] == "7"
    conn.close()

    # Reopen is idempotent and does not need the JSON.
    catalog_file_for(project).unlink()
    reopened = DataCatalogService.open(project)
    assert len(reopened.list_assets()) == 3
    assert reopened.document.catalog_revision == 7
    reopened.close()
    service.close()


def test_migration_failure_leaves_legacy_project_recoverable(tmp_path, monkeypatch):
    """A crash mid-migration must never damage the legacy catalog.json."""
    project = _legacy_project(tmp_path, n_assets=2)
    original_json = catalog_file_for(project).read_bytes()

    def boom(self, document):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(CatalogIndex, "write_all", boom)
    with pytest.raises(sqlite3.OperationalError):
        DataCatalogService.open(project)
    monkeypatch.undo()

    # The legacy project is fully recoverable: json intact, retry succeeds.
    assert catalog_file_for(project).read_bytes() == original_json
    CatalogIndex(project).reset()  # clear any half-initialized db
    service = DataCatalogService.open(project)
    assert len(service.list_assets()) == 2
    service.close()


def test_newer_legacy_json_wins_over_stale_sqlite(tmp_path):
    """A json newer than the db (old app version wrote it) is re-imported."""
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project)
    service.import_raw(_source(tmp_path, "x.bin"))
    service.close()

    # Simulate an OLD app version (json-canonical) adding one more asset by
    # hand-editing the manifest with a higher revision.
    json_path = catalog_file_for(project)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["catalog_revision"] += 1
    data["assets"].append(
        {
            "id": "asset_foreign",
            "name": "foreign",
            "type": "raw",
            "description": "",
            "current_version_id": None,
            "legacy_resource_id": None,
            "metadata": {},
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "trashed": False,
            "trashed_at": None,
        }
    )
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    reopened = DataCatalogService.open(project)
    ids = {a.id for a in reopened.list_assets()}
    assert "asset_foreign" in ids, "externally-written json revision was dropped"
    reopened.close()


# ---------------------------------------------------------------------------
# Model registry round-trip (was missing from the SQLite schema entirely)
# ---------------------------------------------------------------------------


def test_model_registry_round_trips_through_sqlite(service):
    model = service.register_model(
        model_id="kriging-v1",
        model_name="Kriging",
        capability="interpolation",
        provider="local_asset",
        status="production",
    )
    service.register_model_version(
        model.model_id,
        model_version="1.0",
        artifact_uri="artifacts/kriging.bin",
        checksum="abc123",
        deterministic=True,
    )

    catalog_file_for(service.project_path).unlink(missing_ok=True)
    reopened = DataCatalogService.open(service.project_path)
    assert reopened.get_model("kriging-v1") is not None
    assert reopened.get_model_version("kriging-v1", "1.0").checksum == "abc123"
    reopened.close()


# ---------------------------------------------------------------------------
# Differential equivalence: incremental flush == full rebuild
# ---------------------------------------------------------------------------


def _dump(db_path: Path) -> dict[str, list[tuple]]:
    if not db_path.is_file():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name != 'sqlite_sequence'"
            )
        ]
        dump = {
            t: sorted(conn.execute(f"SELECT * FROM {t}").fetchall()) for t in tables
        }
        # manifest_mtime_ns is open-session bookkeeping, not catalog data.
        dump["sync_state"] = [
            row for row in dump.get("sync_state", [])
            if row[0] != "manifest_mtime_ns"
        ]
        return dump
    finally:
        conn.close()


def test_incremental_flushes_equal_full_rebuild(service, tmp_path):
    """Dirty-set flushes must produce identical tables to a full rebuild."""
    rng = random.Random(42)
    assets = []
    for i in rng.sample(range(60), 12):
        v = service.import_raw(
            _source(service.project_path.parent, f"d{i}.bin", f"d{i}".encode()),
            name=f"asset-{i}",
        )
        assets.append(v.asset_id)
    for i in range(6):
        service.add_tag(f"t{i}", asset_id=assets[i])
    service.update_asset_metadata(assets[0], {"k": "v"})
    run = service.register_run(
        "op-x", input_version_ids=[], output_version_ids=[], status="running"
    )
    service.update_run_status(run.id, "failed")
    service.trash_asset(assets[1])

    incremental_dump = _dump(_db_file(service.project_path))

    ref_project = tmp_path / "ref" / "demo.paleo.json"
    ref_project.parent.mkdir(parents=True, exist_ok=True)
    ref_project.write_text("{}", encoding="utf-8")
    reference = CatalogIndex(ref_project)
    reference.reset()
    reference.write_all(service.document)

    assert incremental_dump == _dump(reference.db_path), (
        "incrementally-flushed tables differ from a full rebuild"
    )
    reference.close()


# ---------------------------------------------------------------------------
# Cross-process stale-write guard (replaces the #411 mtime guard)
# ---------------------------------------------------------------------------


def test_external_writer_advancing_db_blocks_overwrite(service):
    """A revision bumped by another process must refuse the next save."""
    version = service.import_raw(_source(service.project_path.parent, "a.bin"))

    # Simulate an external process committing a new revision.
    conn = sqlite3.connect(_db_file(service.project_path))
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (key, value)"
            " VALUES ('catalog_revision', '999')"
        )
    conn.close()

    with pytest.raises(Exception) as excinfo:
        service.update_asset_metadata(version.asset_id, {"k": "v"})
    assert "stale" in str(excinfo.value).lower() or excinfo.value.__class__.__name__ == (
        "CatalogStaleWriteError"
    )
