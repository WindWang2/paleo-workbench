"""Transaction / crash-safety tests for the catalog (P4).

Pins the guarantee that a crash or failure at ANY point of a save never leaves
a half-written canonical store, a metadata claim without a payload, or an
unrecoverable project:

- ``catalog.json.bak`` keeps the previous revision before the atomic replace;
- ``load()`` recovers the backup when the canonical file is missing;
- a subprocess SIGKILL mid-save reopens consistent (document + index +
  payload tree);
- rename/fsync failures leave no half-written ``catalog.json``;
- failed copy / metadata / sqlite / rename / checksum each roll back cleanly.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import CatalogError
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import catalog_dir_for, safe_unlink
from paleo_workbench.catalog.store import (
    CatalogStore,
    catalog_bak_file_for,
    catalog_file_for,
)
from paleo_workbench.catalog import store as store_module

_HELPER = Path(__file__).parent / "crash_kill_helper.py"
_PYTHON = Path(sys.executable)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def _source(tmp_path: Path, name: str, payload: bytes) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


# ------------------------------------------------------------------ .bak + load


def test_save_keeps_previous_revision_as_bak(service):
    service.import_raw(_source(service.project_path.parent, "a.bin", b"v1"))
    path = catalog_file_for(service.project_path)
    first_rev = json.loads(path.read_text(encoding="utf-8"))["catalog_revision"]

    service.import_raw(_source(service.project_path.parent, "b.bin", b"v2"))
    second_rev = json.loads(path.read_text(encoding="utf-8"))["catalog_revision"]
    assert second_rev == first_rev + 1

    bak = catalog_bak_file_for(service.project_path)
    assert bak.is_file()
    bak_rev = json.loads(bak.read_text(encoding="utf-8"))["catalog_revision"]
    assert bak_rev == first_rev  # backup holds the PREVIOUS revision


def test_load_falls_back_to_bak_when_canonical_missing(tmp_path):
    project = _make_project(tmp_path)
    svc = DataCatalogService.open(project)
    svc.import_raw(_source(tmp_path, "a.bin", b"precious"))
    svc.import_raw(_source(tmp_path, "b.bin", b"also precious"))
    svc.close()

    path = catalog_file_for(project)
    bak = catalog_bak_file_for(project)
    assert bak.is_file()
    # Simulate a crash between the two renames: canonical gone, backup intact.
    path.unlink()

    reopened = CatalogStore(project).load()
    assert len(reopened.versions) == 1
    assert reopened.versions[0].path.endswith("a.bin")
    # The backup is re-promoted so the project keeps working.
    assert path.is_file()


def test_load_returns_empty_when_both_missing(tmp_path):
    project = _make_project(tmp_path)
    assert CatalogStore(project).load().catalog_revision == 0


# ------------------------------------------------------------- SIGKILL mid-save


@pytest.mark.parametrize("mode", ["replace", "bak"])
def test_sigkill_mid_save_reopens_consistent(tmp_path: Path, mode: str):
    project = _make_project(tmp_path)
    env = dict(os.environ)
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_PROJECT_ROOT}:{existing_pythonpath}" if existing_pythonpath else str(_PROJECT_ROOT)
    proc = subprocess.run(
        [_PYTHON, str(_HELPER), mode, str(project)],
        capture_output=True,
        cwd=str(_PROJECT_ROOT),
        env=env,
        timeout=120,
    )
    if sys.platform == "win32":
        assert proc.returncode == signal.SIGTERM, proc.stderr.decode()
    else:
        assert proc.returncode in (-signal.SIGKILL, -9), proc.stderr.decode()

    path = catalog_file_for(project)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data["catalog_revision"], int)  # never half-written
    # The previous revision is recoverable (either as canonical or backup).
    assert path.is_file() or catalog_bak_file_for(project).is_file()

    # Reopen: the catalog must be consistent and functional.
    svc = DataCatalogService.open(project)
    try:
        assert svc.document.catalog_revision >= 1
        if mode == "replace":
            # The killer struck after catalog.json moved aside but before the
            # new file landed → backup recovery, first import present.
            assert len(svc.document.versions) == 1
        assert svc.document.versions[0].path.endswith("x.bin")
        for version in svc.document.versions:
            assert svc.resolve_path(version).is_file()
            status = svc.verify_integrity(version.id).status_for(version.id)
            assert status in ("verified", "unknown")
        # The index rebuilt/primed from the recovered document.
        assert svc.index_revision() == svc.document.catalog_revision
        # The project is writable again (self-healing).
        extra = svc.import_raw(_source(tmp_path, "c.bin", b"post-crash"))
        assert svc.get_version(extra.id) is not None
    finally:
        svc.close()


# ---------------------------------------------------------- failure injection


def test_fsync_failure_leaves_catalog_unchanged(service):
    service.import_raw(_source(service.project_path.parent, "a.bin", b"v1"))
    path = catalog_file_for(service.project_path)
    before = path.read_bytes()

    real_fsync = store_module.os.fsync

    def _boom(fd):
        raise OSError("injected fsync failure")

    store_module.os.fsync = _boom  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            CatalogStore(service.project_path).save(service.document)
    finally:
        store_module.os.fsync = real_fsync  # type: ignore[assignment]

    assert path.read_bytes() == before  # no half-written file observed
    # No temp leftovers.
    leftovers = [p for p in catalog_dir_for(service.project_path).iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == []


def test_rename_failure_restores_previous_revision(service):
    service.import_raw(_source(service.project_path.parent, "a.bin", b"v1"))
    path = catalog_file_for(service.project_path)
    first = json.loads(path.read_text(encoding="utf-8"))["catalog_revision"]

    real_replace = store_module.os.replace
    state = {"failures": 0}

    def _boom(src, dst):
        # Fail ONLY the first rename onto catalog.json; the store's rollback
        # (bak → catalog.json) must succeed to restore the previous revision.
        if str(dst).endswith("catalog.json"):
            state["failures"] += 1
            if state["failures"] == 1:
                raise OSError("injected rename failure")
        return real_replace(src, dst)

    store_module.os.replace = _boom  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            CatalogStore(service.project_path).save(service.document)
    finally:
        store_module.os.replace = real_replace  # type: ignore[assignment]

    # The previous revision is back in place (renamed back from .bak).
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["catalog_revision"] == first
    assert path.is_file()
    # No temp leftovers.
    leftovers = [p for p in catalog_dir_for(service.project_path).iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == []


def test_failed_metadata_save_rolls_back_version_and_payload(service):
    src = _source(service.project_path.parent, "a.bin", b"v1")
    real_save = service._store.save

    def _boom(document):
        raise OSError("injected metadata failure")

    service._store.save = _boom  # type: ignore[method-assign]
    try:
        with pytest.raises(OSError):
            service.import_raw(src)
    finally:
        service._store.save = real_save  # type: ignore[method-assign]

    # Nothing committed: no version, no asset, no payload.
    assert len(service.document.versions) == 0
    assert len(service.document.assets) == 0
    leftovers = [
        p
        for p in service.project_path.parent.rglob("*")
        if p.is_file()
        and "incoming" not in p.parts
        and p.suffix in {".bin", ".las"}
        and p.name != "demo.paleo.json"
    ]
    assert leftovers == []
    assert service.plan_gc().count("stage_orphan") == 0


def test_failed_copy_rolls_back_cleanly(service, tmp_path):
    src = _source(tmp_path, "a.bin", b"v1")
    import paleo_workbench.catalog.storage as storage_module

    real_replace = storage_module.os.replace

    def _boom(src_path, dst_path):
        if ".place-" in str(src_path):
            raise OSError("injected copy failure")
        return real_replace(src_path, dst_path)

    storage_module.os.replace = _boom  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            service.import_raw(src)
    finally:
        storage_module.os.replace = real_replace  # type: ignore[assignment]

    assert len(service.document.versions) == 0
    assert len(service.document.assets) == 0
    # No .place- leftovers, no orphan payloads.
    assert service.plan_gc().count("stage_orphan") == 0
    assert service.plan_gc().count("temp_orphan") == 0


def test_failed_sqlite_sync_self_heals(service, tmp_path):
    src = _source(tmp_path, "a.bin", b"v1")
    index = service._index
    original_sync = index.sync

    def _boom(document):
        raise RuntimeError("injected sqlite failure")

    index.sync = _boom  # type: ignore[method-assign]
    try:
        version = service.import_raw(src)
        assert version is not None  # canonical save still succeeded
    finally:
        index.sync = original_sync  # type: ignore[method-assign]

    # The index was reset+rebuilt by the best-effort fallback.
    assert service.index_revision() == service.document.catalog_revision
    assert len(index.search_assets()) == 1


def test_failed_checksum_rolls_back_cleanly(service, tmp_path):
    src = _source(tmp_path, "a.bin", b"real content")
    with pytest.raises(CatalogError):
        service.import_raw(src, known_sha256="f" * 64)
    assert len(service.document.versions) == 0
    assert len(service.document.assets) == 0
    assert service.plan_gc().count("stage_orphan") == 0


def test_committed_version_never_claims_missing_payload(service):
    """Payload placement precedes metadata commit, so a committed record's
    payload always exists (a missing one is a tamper, reported as missing)."""
    src = _source(service.project_path.parent, "a.bin", b"v1")
    version = service.import_raw(src)
    payload = service.resolve_path(version)
    assert payload.is_file()

    # Simulate post-commit loss: integrity reports missing, never fabricates.
    safe_unlink(payload)
    assert service.verify_integrity(version.id).status_for(version.id) == "missing"
    # The canonical document is untouched (report-only).
    assert service.get_version(version.id).sha256 is not None


# ------------------------------------------------------------------ failed-save rollback (mutators)


def _assert_memory_matches_disk(service) -> None:
    """Reload the canonical store and require byte-identical state."""
    disk = CatalogStore(service.project_path).load()
    assert disk.model_dump(mode="json") == service.document.model_dump(mode="json")


def test_remove_tag_rolls_back_on_failed_save(service, monkeypatch):
    version = service.import_raw(_source(service.project_path.parent, "a.bin", b"v1"))
    service.add_tag("qc", asset_id=version.asset_id)
    before = list(service.document.asset_tags[version.asset_id])

    real_save = service._store.save

    def boom(_document):
        raise OSError("disk full")

    monkeypatch.setattr(service._store, "save", boom)
    with pytest.raises(OSError):
        service.remove_tag("qc", asset_id=version.asset_id)
    monkeypatch.setattr(service._store, "save", real_save)

    # No half-applied removal in memory; disk agrees.
    assert service.document.asset_tags[version.asset_id] == before
    _assert_memory_matches_disk(service)


def test_update_run_status_rolls_back_on_failed_save(service, monkeypatch):
    run = service.register_run("op", status="running", parameters={"k": "v"})

    real_save = service._store.save

    def boom(_document):
        raise OSError("disk full")

    monkeypatch.setattr(service._store, "save", boom)
    with pytest.raises(OSError):
        service.update_run_status(run.id, "failed", extra_parameters={"x": "1"})
    monkeypatch.setattr(service._store, "save", real_save)

    # The run must not be half-updated (stuck-RUNNING compensation contract):
    # status/parameters revert in memory and match the disk.
    assert service.get_run(run.id).status == "running"
    assert service.get_run(run.id).parameters == {"k": "v"}
    _assert_memory_matches_disk(service)


def test_attach_lineage_rolls_back_on_failed_save(service, monkeypatch):
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter

    src1 = _source(service.project_path.parent, "a.bin", b"v1")
    src2 = _source(service.project_path.parent, "b.bin", b"v2")
    v1 = service.import_raw(src1)
    v2 = service.import_raw(src2)
    adapter = CoreCatalogAdapter(service)

    real_save = service._store.save

    def boom(_document):
        raise OSError("disk full")

    monkeypatch.setattr(service._store, "save", boom)
    with pytest.raises(OSError):
        adapter.attach_lineage(source_version_id=v1.id, target_version_id=v2.id)
    monkeypatch.setattr(service._store, "save", real_save)

    # The edge must not linger in memory; disk agrees (reopen would drop it).
    assert v1.id not in service.get_version(v2.id).parent_version_ids
    assert service.get_lineage(v2.id)["parents"] == []
    _assert_memory_matches_disk(service)


def test_attach_lineage_children_map_rolls_back_with_edge(service, monkeypatch):
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter

    src1 = _source(service.project_path.parent, "a.bin", b"v1")
    src2 = _source(service.project_path.parent, "b.bin", b"v2")
    v1 = service.import_raw(src1)
    v2 = service.import_raw(src2)
    adapter = CoreCatalogAdapter(service)
    service._ensure_maps()

    real_save = service._store.save

    def boom(_document):
        raise OSError("disk full")

    monkeypatch.setattr(service._store, "save", boom)
    with pytest.raises(OSError):
        adapter.attach_lineage(source_version_id=v1.id, target_version_id=v2.id)
    monkeypatch.setattr(service._store, "save", real_save)

    # The maintained children index must not keep a phantom child entry.
    assert service._children_by_parent.get(v1.id, []) == []
    assert service.get_lineage(v2.id)["parents"] == []
    _assert_memory_matches_disk(service)


# ------------------------------------------------------------------ trash crash window (finding #3)


def test_trash_crash_before_payload_move_restores_in_place(service, tmp_path):
    """Crash between tombstone save and payload move: the canonical record is
    tombstoned but the payload never moved. Restore must succeed and leave the
    payload at its original location (no probe needed, nothing lost)."""
    src = _source(tmp_path, "a.bin", b"precious")
    version = service.import_raw(src)
    version_id = version.id
    original_rel = version.path
    payload = service.resolve_path(version)
    assert payload.is_file()

    # Simulate the crash window: tombstone persisted, payload NOT moved yet.
    service._tombstone_version(version, "crash-window")
    service._save()
    service.close()

    svc = DataCatalogService.open(service.project_path)
    try:
        restored = svc.restore_version(version_id)
        assert restored.trashed is False
        assert restored.path == original_rel
        assert svc.resolve_path(restored).is_file()
        assert svc.resolve_path(restored).read_bytes() == b"precious"
    finally:
        svc.close()


def test_trash_crash_after_payload_move_restores_from_trash(service, tmp_path):
    """Crash between payload move and path-update save: the canonical record is
    tombstoned with the ORIGINAL path, but the payload physically sits in
    trash/{version_id}/. Restore must probe the trash dir and recover the
    payload (no ghost missing state, no orphaned trash payload)."""
    src = _source(tmp_path, "a.bin", b"precious")
    version = service.import_raw(src)
    version_id = version.id
    original_rel = version.path
    payload = service.resolve_path(version)
    assert payload.is_file()

    # Simulate the crash window: tombstone saved, payload moved, path-update
    # save never happened (process died between the two saves).
    service._tombstone_version(version, "crash-window")
    service._save()
    moved = service._move_payload_to_trash(version)
    assert moved is True
    trash_payload = service.resolve_path(version)
    assert "trash" in trash_payload.as_posix()
    assert not payload.exists()
    # The canonical document still records the ORIGINAL path (path-update save
    # was skipped) — close() does not save, mirroring a process crash.
    version.path = original_rel
    service.close()

    svc = DataCatalogService.open(service.project_path)
    try:
        # Canonical record: trashed, path = original (missing payload).
        assert svc.get_version(version_id).trashed is True
        assert svc.get_version(version_id).path == original_rel
        assert not svc.resolve_path(svc.get_version(version_id)).is_file()
        # plan_gc must NOT classify the recoverable trash payload as orphan
        # (the version record still exists).
        assert svc.plan_gc().count("trash_orphan") == 0
        # Restore probes trash/{version_id}/ and recovers the payload.
        restored = svc.restore_version(version_id)
        assert restored.trashed is False
        assert restored.path == original_rel
        assert svc.resolve_path(restored).is_file()
        assert svc.resolve_path(restored).read_bytes() == b"precious"
        # Trash dir is empty again after restore.
        trash_root = catalog_dir_for(service.project_path).parent / "trash"
        assert not any(trash_root.rglob("*.bin")) if trash_root.exists() else True
    finally:
        svc.close()


def test_load_falls_back_to_bak_when_canonical_corrupt(tmp_path):
    """A corrupt-but-present catalog.json (torn write / manual edit) must not
    block project open: the previous revision is recovered from .bak (review
    finding M3)."""
    project_path = _make_project(tmp_path)
    svc = DataCatalogService.open(project_path)
    src = _source(tmp_path, "a.bin", b"precious")
    svc.import_raw(src)
    svc.import_raw(_source(tmp_path, "b.bin", b"also precious"))
    svc.close()

    # Corrupt the canonical file but keep the .bak intact.
    canonical = catalog_file_for(project_path)
    bak = catalog_bak_file_for(project_path)
    assert bak.is_file()
    canonical.write_text("{ this is not valid json !!!", encoding="utf-8")

    svc2 = DataCatalogService.open(project_path)
    try:
        # The project opens with the backup revision (assets preserved).
        assert len(svc2.document.assets) == 1
        assert svc2.document.versions
        # The canonical file was re-promoted from the backup.
        import json as _json
        _json.loads(canonical.read_text(encoding="utf-8"))
    finally:
        svc2.close()


# ------------------------------------------------ first-save backup + corrupt


def test_first_save_seeds_backup(tmp_path):
    """A once-saved catalog must already have a .bak (same revision), so a
    corrupt canonical file never sits in a no-backup window (issue #372)."""
    project = _make_project(tmp_path)
    svc = DataCatalogService.open(project)
    svc.import_raw(_source(tmp_path, "a.bin", b"v1"))
    svc.close()

    canonical = catalog_file_for(project)
    bak = catalog_bak_file_for(project)
    assert canonical.is_file()
    assert bak.is_file()
    assert json.loads(bak.read_text(encoding="utf-8")) == json.loads(
        canonical.read_text(encoding="utf-8")
    )


def test_load_raises_when_canonical_corrupt_and_no_backup(tmp_path):
    """Corrupt canonical without a .bak must fail loudly and isolate the
    corrupt bytes, never silently return an empty catalog (issue #372)."""
    project = _make_project(tmp_path)
    canonical = catalog_file_for(project)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    corrupt = b'{"truncated": '
    canonical.write_bytes(corrupt)

    with pytest.raises(CatalogError, match="corrupt and no backup"):
        CatalogStore(project).load()

    # The corrupt bytes are preserved in an isolated file, not overwritten.
    assert not canonical.exists()
    isolated = [p for p in canonical.parent.iterdir()
                if p.name.startswith("catalog.json.corrupt-")]
    assert len(isolated) == 1
    assert isolated[0].read_bytes() == corrupt


def test_load_raises_on_schema_invalid_without_backup(tmp_path):
    """Valid JSON with an invalid shape (pydantic ValidationError) is treated
    the same as torn JSON: raise + isolate, never an empty catalog."""
    project = _make_project(tmp_path)
    canonical = catalog_file_for(project)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(
        '{"catalog_revision": "x", "assets": [{"id": 12345}]}',
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="corrupt and no backup"):
        DataCatalogService.open(project)

    assert not canonical.exists()
    isolated = [p for p in canonical.parent.iterdir()
                if p.name.startswith("catalog.json.corrupt-")]
    assert len(isolated) == 1


def test_open_never_saves_empty_catalog_over_corrupt(tmp_path):
    """After a loud failure, a subsequent mutation save must not destroy the
    corrupt bytes: no service is installed, so no save can run."""
    project = _make_project(tmp_path)
    canonical = catalog_file_for(project)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    corrupt = b'{"truncated": '
    canonical.write_bytes(corrupt)

    with pytest.raises(CatalogError):
        DataCatalogService.open(project)

    isolated = [p for p in canonical.parent.iterdir()
                if p.name.startswith("catalog.json.corrupt-")]
    assert len(isolated) == 1
    assert isolated[0].read_bytes() == corrupt
    # Nothing was written to the canonical path or the .bak.
    assert not canonical.exists()
    assert not catalog_bak_file_for(project).exists()
