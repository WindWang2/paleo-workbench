"""Tests for conservative catalog GC (P4): plan_gc / sweep_gc / working copies.

Each orphan class is exercised: stage payloads without version records,
abandoned working copies, stale temp/placement files, unreferenced trash
payloads, unreferenced blobs, and empty dirs. The sweep must NEVER remove a
reachable committed DataVersion payload or an external source file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog import dedup
from paleo_workbench.catalog.gc import (
    BLOB_ORPHAN,
    EMPTY_DIR,
    STAGE_ORPHAN,
    TEMP_ORPHAN,
    TRASH_ORPHAN,
    WORKING_ORPHAN,
)
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import (
    catalog_dir_for,
    trash_dir_for,
    working_dir_for,
)


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


def _make_source(tmp_path: Path, name: str, payload: bytes = b"data") -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


def _stage_root(project_path: Path) -> Path:
    return catalog_dir_for(project_path).parent


# ---------------------------------------------------------------- each class


def test_stage_orphan_payload_without_version_record(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path, "a.bin"))
    # Simulate a crash after payload placement but before metadata commit:
    root = _stage_root(service.project_path)
    ghost_dir = root / "raw" / "ghost_asset" / "ghost_version"
    ghost_dir.mkdir(parents=True)
    (ghost_dir / "leftover.bin").write_bytes(b"orphan")

    report = service.plan_gc()
    orphans = report.by_kind(STAGE_ORPHAN)
    assert len(orphans) == 1
    assert orphans[0].path.name == "leftover.bin"
    # The committed version's payload is NOT an orphan.
    assert not any(o.path.name == "a.bin" for o in orphans)
    # Dry-run deletes nothing.
    assert service.resolve_path(version).is_file()


def test_working_copy_orphan_requires_explicit_hook(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path, "a.bin"))
    live = service.create_working_copy(version.id)
    # A working copy whose version id does not exist at all:
    wc_dir = working_dir_for(service.project_path) / "ver_ghost"
    wc_dir.mkdir(parents=True)
    (wc_dir / "wip.txt").write_bytes(b"abandoned")

    report = service.plan_gc()
    assert len(report.by_kind(WORKING_ORPHAN)) == 1
    # The sweep never touches working copies (even explicit sweep excludes them).
    swept = service.sweep_gc(dry_run=False, explicit=True)
    assert swept.count(WORKING_ORPHAN) == 0
    assert wc_dir.exists()
    assert live.exists()

    cleaned = service.cleanup_working_copies()
    assert len(cleaned.by_kind(WORKING_ORPHAN)) == 1
    assert not (wc_dir / "wip.txt").exists()
    # Live working copies survive the explicit hook.
    assert live.exists()


def test_temp_files_classified_and_swept(service, tmp_path):
    service.import_raw(_make_source(tmp_path, "a.bin"))
    root = _stage_root(service.project_path)
    leftovers = [
        root / "raw" / ".place-abc123",
        root / "derived" / ".place-xyz",
        catalog_dir_for(service.project_path) / ".catalog.json.abc123.tmp",
    ]
    for path in leftovers:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stale")

    report = service.plan_gc()
    assert len(report.by_kind(TEMP_ORPHAN)) == len(leftovers)

    swept = service.sweep_gc(dry_run=False)  # conservative sweep (like on open)
    assert swept.count(TEMP_ORPHAN) == len(leftovers)
    for path in leftovers:
        assert not path.exists()
    # Payloads untouched by the conservative sweep.
    assert service.verify_integrity(
        service.document.versions[0].id
    ).status_for(service.document.versions[0].id) == "verified"


def test_auto_sweep_does_not_classify_stage_working_trash_or_blobs(
    service, tmp_path, monkeypatch
):
    """#618: open-time sweep only plans TEMP_ORPHAN + EMPTY_DIR.

    Full stage/working/trash/blob classification is for explicit GC, not the
    every-open auto path that used to walk the entire artifacts tree.
    """
    from paleo_workbench.catalog import dedup
    from paleo_workbench.catalog import gc as gc_mod

    service.import_raw(_make_source(tmp_path, "a.bin"))
    blob_calls: list[int] = []
    monkeypatch.setattr(
        dedup, "plan_blob_gc", lambda *a, **k: blob_calls.append(1) or []
    )
    walked: list[str] = []
    real_walk = gc_mod._walk_files

    def spy_walk(directory):
        walked.append(Path(directory).name)
        return real_walk(directory)

    monkeypatch.setattr(gc_mod, "_walk_files", spy_walk)

    report = service.sweep_gc(dry_run=True, explicit=False)
    assert blob_calls == []
    assert report.count(STAGE_ORPHAN) == 0
    assert report.count(WORKING_ORPHAN) == 0
    assert report.count(TRASH_ORPHAN) == 0
    assert report.count(BLOB_ORPHAN) == 0
    assert not any(
        name in {"raw", "derived", "intermediate", "outputs", "working", "trash"}
        for name in walked
    )


def test_trash_orphan_unreferenced_payload(service, tmp_path):
    service.import_raw(_make_source(tmp_path, "a.bin"))
    trash = trash_dir_for(service.project_path)
    ghost = trash / "ver_ghost"
    ghost.mkdir(parents=True)
    (ghost / "payload.bin").write_bytes(b"orphan")

    report = service.plan_gc()
    assert len(report.by_kind(TRASH_ORPHAN)) == 1
    swept = service.sweep_gc(dry_run=False, explicit=True)
    assert swept.count(TRASH_ORPHAN) == 1
    assert not (ghost / "payload.bin").exists()


def test_trashed_payload_with_live_record_is_never_orphan(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path, "a.bin"))
    service.trash_version(version.id, reason="kept")
    assert service.plan_gc().count(TRASH_ORPHAN) == 0
    # Restore still works after planning.
    service.restore_version(version.id)
    assert service.verify_integrity(version.id).status_for(version.id) == "verified"


def test_blob_orphan_swept_by_reachability(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path, "a.bin"))
    digest = version.sha256
    # Register an unreferenced blob.
    dedup.place_blob(
        service.project_path,
        _make_source(tmp_path, "junk.bin", b"unreferenced blob bytes"),
    )
    report = service.plan_gc()
    assert len(report.by_kind(BLOB_ORPHAN)) == 1
    # The referenced blob is NOT an orphan.
    assert all(d != digest for item in report.by_kind(BLOB_ORPHAN)
               for d in [item.path.name])
    swept = service.sweep_gc(dry_run=False, explicit=True)
    assert swept.count(BLOB_ORPHAN) == 1
    assert dedup.has_blob(service.project_path, digest) is True


def test_empty_dirs_swept(service, tmp_path):
    service.import_raw(_make_source(tmp_path, "a.bin"))
    root = _stage_root(service.project_path)
    empty = root / "raw" / "ghost_asset" / "ghost_version"
    empty.mkdir(parents=True)

    report = service.plan_gc()
    assert len(report.by_kind(EMPTY_DIR)) >= 1
    swept = service.sweep_gc(dry_run=False)  # conservative sweep
    assert swept.count(EMPTY_DIR) >= 1
    assert not empty.exists()


def test_external_source_file_never_touched(service, tmp_path):
    external = _make_source(tmp_path, "ext.las", b"external bytes")
    svc_external = service.link_external(external)
    before = external.read_bytes()
    service.plan_gc()
    service.sweep_gc(dry_run=False, explicit=True)
    assert external.read_bytes() == before
    # External links are unhashed by design → unknown integrity is fine; the
    # key assertion is that the source file was never moved or deleted.
    status = service.verify_integrity(svc_external.id).status_for(svc_external.id)
    assert status in ("verified", "unknown")


def test_plan_gc_never_deletes_anything(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path, "a.bin"))
    root = _stage_root(service.project_path)
    ghost_dir = root / "raw" / "ghost" / "ghost"
    ghost_dir.mkdir(parents=True)
    (ghost_dir / "x.bin").write_bytes(b"x")
    working_dir_for(service.project_path).joinpath("ver_z").mkdir(parents=True)
    working_dir_for(service.project_path).joinpath("ver_z", "w.bin").write_bytes(b"w")

    report = service.plan_gc()
    assert report.count() >= 1
    assert service.resolve_path(version).is_file()
    assert (ghost_dir / "x.bin").exists()
    assert service.verify_integrity(version.id).status_for(version.id) == "verified"


def test_open_runs_conservative_sweep_but_keeps_payloads(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    version = svc.import_raw(_make_source(tmp_path, "a.bin"))
    svc.close()

    root = _stage_root(project_path)
    stale = root / "raw" / ".place-stale"
    stale.write_bytes(b"stale")
    svc2 = DataCatalogService.open(project_path)
    try:
        assert not stale.exists()  # open swept the temp leftover
        assert svc2.verify_integrity(version.id).status_for(version.id) == "verified"
    finally:
        svc2.close()


def test_open_sweep_keeps_referenced_temp_named_payload(tmp_path):
    """A managed payload whose NAME matches the temp pattern (e.g. an imported
    ``well_data.tmp``) must survive the on-open conservative sweep: it is
    referenced by a version record, so it is never a TEMP_ORPHAN. The real
    (unreferenced) temp leftover is still swept. Regression for the review
    finding where the auto-sweep deleted referenced payloads on open."""
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    for name in ("well_data.tmp", ".blob-notes", ".place-notes"):
        version = svc.import_raw(_make_source(tmp_path, name, payload=f"keep {name}".encode()))
        assert svc.verify_integrity(version.id).status_for(version.id) == "verified"
    svc.close()

    root = _stage_root(project_path)
    stale = root / "raw" / ".place-stale"
    stale.write_bytes(b"stale")

    svc2 = DataCatalogService.open(project_path)
    try:
        assert not stale.exists()  # the REAL leftover is still swept
        for name in ("well_data.tmp", ".blob-notes", ".place-notes"):
            version = next(
                v for v in svc2.document.versions
                if Path(v.path).name == name
            )
            assert svc2.verify_integrity(version.id).status_for(version.id) == "verified"
            assert svc2.resolve_path(version).read_bytes() == f"keep {name}".encode()
    finally:
        svc2.close()


def test_plan_gc_does_not_classify_referenced_temp_named_payload(service, tmp_path):
    version = service.import_raw(_make_source(tmp_path, "data.tmp"))
    report = service.plan_gc()
    temp_items = [i for i in report.items if i.kind == TEMP_ORPHAN]
    assert not any(Path(i.path).name == "data.tmp" for i in temp_items)
    assert service.verify_integrity(version.id).status_for(version.id) == "verified"
