"""Working-copy lifecycle state machine (#1211, foundation v6 §5).

Pins the contract:
- repeat checkout REUSES a live copy (never silently discards edits);
- identity is the registry id / source version, not display names;
- crash after copy → reopen enumerates the copy;
- crash during commit → recovery decides by evidence (committed → clean,
  not committed → copy back to dirty, file intact);
- explicit discard is the only sanctioned edit destruction;
- allow_replace=True is the explicit recreate path;
- concurrent checkout attempts converge on one copy.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import CatalogError, DataCatalogService


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


def _seed(service: DataCatalogService, tmp_path: Path, payload: bytes = b"v1"):
    return service.import_raw(_make_source(tmp_path, "well.las", payload))


def test_repeat_checkout_reuses_copy_and_keeps_edits(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        version = _seed(service, tmp_path)
        first = service.create_working_copy(version.id)
        first.write_bytes(b"user edits!")  # uncommitted work

        second = service.create_working_copy(version.id)
        assert second == first  # same copy, no silent overwrite
        assert first.read_bytes() == b"user edits!"

        statuses = service.list_working_copies()
        assert len(statuses) == 1
        assert statuses[0]["source_version_id"] == version.id
        assert statuses[0]["state"] in ("checked_out", "dirty")
        assert statuses[0]["dirty_hint"] is True  # mtime/size drifted

        # allow_replace is the explicit discard-and-recreate path.
        third = service.create_working_copy(version.id, allow_replace=True)
        assert third == first
        assert third.read_bytes() == b"v1"  # fresh copy of the source
        assert len(service.list_working_copies()) == 1
    finally:
        service.close()


def test_identity_not_display_name(tmp_path):
    """Two copies with the SAME payload filename stay distinct identities."""
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        v1 = service.import_raw(_make_source(tmp_path, "dup.las", b"one"))
        # second version, same file name, different content
        v2 = service.register_version(
            v1.asset_id,
            _make_source(tmp_path, "dup2.las", b"two"),
            DataStage.RAW,
        )
        c1 = service.create_working_copy(v1.id)
        c2 = service.create_working_copy(v2.id)
        assert c1 != c2
        assert {s["working_id"] for s in service.list_working_copies()} != set()
        assert len(service.list_working_copies()) == 2
        ids = {s["working_id"] for s in service.list_working_copies()}
        assert len(ids) == 2  # distinct registry identities
    finally:
        service.close()


def test_crash_after_copy_enumerated_on_reopen(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    version = _seed(service, tmp_path)
    working = service.create_working_copy(version.id)
    working.write_bytes(b"mid-edit")
    service.close()  # "crash": no commit, no discard

    reopened = DataCatalogService.open(project)
    try:
        statuses = reopened.list_working_copies()
        assert len(statuses) == 1
        assert statuses[0]["exists"] is True
        assert statuses[0]["state"] in ("checked_out", "dirty")
        # and the copy still commits cleanly after recovery
        committed = reopened.commit_working_copy(working, name="recovered")
        assert reopened.get_version(committed.id).sha256 is not None
        assert reopened.list_working_copies() == []
    finally:
        reopened.close()


def test_crash_during_commit_recovers_by_evidence(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    version = _seed(service, tmp_path)
    working = service.create_working_copy(version.id)
    service.close()

    # Case A: the commit landed but the row removal was lost → row dropped.
    service = DataCatalogService.open(project)
    try:
        committed = service.commit_working_copy(working, name="done")
        # Simulate the lost row removal by re-inserting a committing row.
        rel = working.relative_to(
            Path(project).expanduser().resolve().parent
        ).as_posix()
        service._index.register_working_copy(
            source_version_id=version.id,
            path=rel,
            display_name=working.name,
            payload_mtime_ns=None,
            source_size_bytes=None,
        )
        row = service._index.get_working_copy_by_path(rel)
        service._index.update_working_copy_state(row["working_id"], "committing")
        survivors = service.recover_working_copies()
        assert survivors == []  # commit proven → row cleaned
    finally:
        service.close()

    # Case B: the commit never landed (file still in working/) → copy
    # recoverable as dirty with edits intact.
    service = DataCatalogService.open(project)
    try:
        v2 = service.register_version(
            committed.asset_id,
            _make_source(tmp_path, "n2.las", b"n2"),
            DataStage.RAW,
        )
        working2 = service.create_working_copy(v2.id)
        working2.write_bytes(b"interrupted edits")
        # create_working_copy already registered the checkout; simulate the
        # crash by forcing its state to committing without a commit.
        row2 = service._index.get_working_copy_by_path(
            working2.relative_to(
                Path(project).expanduser().resolve().parent
            ).as_posix()
        )
        service._index.update_working_copy_state(row2["working_id"], "committing")
        survivors = service.recover_working_copies()
        assert len(survivors) == 1
        assert survivors[0]["state"] == "dirty"
        assert survivors[0]["exists"] is True
        assert working2.read_bytes() == b"interrupted edits"
    finally:
        service.close()


def test_discard_is_explicit_and_terminal(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        version = _seed(service, tmp_path)
        working = service.create_working_copy(version.id)
        assert service.discard_working_copy(working) is True
        assert not working.exists()
        assert service.list_working_copies() == []
        # After discard a fresh checkout is a NEW copy.
        again = service.create_working_copy(version.id)
        assert again.exists()
        assert len(service.list_working_copies()) == 1
    finally:
        service.close()


def test_concurrent_checkout_attempts_converge(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        version = _seed(service, tmp_path)
        results: list[Path] = []
        lock = threading.Lock()

        def checkout():
            path = service.create_working_copy(version.id)
            with lock:
                results.append(path)

        threads = [threading.Thread(target=checkout) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(results) == 4
        assert len(set(results)) == 1  # one copy, reused
        statuses = service.list_working_copies()
        assert len(statuses) == 1
    finally:
        service.close()


def test_save_as_orphaned_rows_dropped_on_recovery(tmp_path):
    """Packaging/save-as drops working/ — recovery drops the dead rows."""
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    version = _seed(service, tmp_path)
    working = service.create_working_copy(version.id)
    assert service.list_working_copies()  # checkout registered
    service.close()
    working.unlink()  # simulate the save-as relocation dropping working/

    reopened = DataCatalogService.open(project)
    try:
        assert reopened.recover_working_copies() == []
        assert reopened.list_working_copies() == []
    finally:
        reopened.close()
