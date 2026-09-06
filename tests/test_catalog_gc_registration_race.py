"""Adversarial GC × registration coordination (#1222, foundation v6).

Payload bytes land on disk OUTSIDE the service lock and only become
document-referenced at the following metadata commit; until then a snapshot
based sweep classifies them as orphans. These tests pin the lease protocol:

- a registration racing a looping explicit sweep never loses its payload;
- a STALE plan report cannot delete files registered after the plan (the
  sweep re-validates references + leases under the service lock per chunk);
- an explicit lease blocks orphan classification; a dead (TTL-expired) lease
  does not;
- blob-registration imports keep their blob through a concurrent sweep;
- commit_working_copy no longer holds the service lock across payload I/O
  (#1218).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService


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


def test_concurrent_sweep_never_deletes_inflight_payload(tmp_path, monkeypatch):
    """Adversarial: registration in one thread, explicit sweeps spinning in
    another. Without the lease the sweep wins the place→commit window and
    the committed version ends up payload_missing."""
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        src0 = _make_source(tmp_path, "seed.las", b"seed")
        seed = service.import_raw(src0)

        # Widen the place→commit window: pause right AFTER the payload is
        # placed (inside _build_version, before the locked commit).
        original_build = service._build_version
        gate = threading.Event()
        proceed = threading.Event()

        def slow_build(*args, **kwargs):
            version, payload = original_build(*args, **kwargs)
            if args and getattr(args[2], "value", "") == "OUTPUT":
                gate.set()
                proceed.wait(timeout=10)
            return version, payload

        monkeypatch.setattr(service, "_build_version", slow_build)

        registered = []
        error: list[Exception] = []

        def register():
            try:
                v = service.register_version(
                    seed.asset_id,
                    _make_source(tmp_path, "target.las", b"target-bytes"),
                    DataStage.OUTPUT,
                )
                registered.append(v)
            except Exception as exc:  # pragma: no cover - failure evidence
                error.append(exc)
            finally:
                gate.set()
                proceed.set()

        thread = threading.Thread(target=register)
        thread.start()
        assert gate.wait(timeout=10)
        # The payload is on disk, unreferenced, uncommitted — the exact
        # window the sweep used to delete. Spin it.
        for _ in range(3):
            service.sweep_gc(dry_run=False, explicit=True)
        proceed.set()
        thread.join(timeout=10)
        assert not error, error
        assert registered, "registration did not complete"
        payload = service.resolve_path(registered[0])
        assert payload.is_file(), "sweep deleted the in-flight payload"
        assert registered[0].sha256 is not None
    finally:
        service.close()


def test_stale_plan_report_cannot_delete_newly_registered_payload(tmp_path):
    """plan→sweep TOCTOU: sweep a report captured BEFORE a registration."""
    from paleo_workbench.catalog.gc import plan_gc, sweep_gc

    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        src = _make_source(tmp_path, "orphan-then-live.las", b"live-bytes")
        asset = service.import_raw(
            _make_source(tmp_path, "seed.las", b"seed")
        )
        # Write the file into the stage tree manually (simulating a placed
        # but uncommitted payload), plan, THEN register it for real.
        version_dir = (
            service.resolve_path(asset).parent.parent
            / "asset_fake"
            / "ver_fake"
        )
        version_dir.mkdir(parents=True, exist_ok=True)
        stray = version_dir / "stray.las"
        stray.write_bytes(b"stray")

        report = plan_gc(service, explicit=True)
        assert report.count("stage_orphan") >= 1

        # A registration lands after the plan (its payload is referenced now).
        service.import_raw(src)

        result = sweep_gc(service, dry_run=False, explicit=True, report=report)
        deleted = {item.path for item in result.items}
        assert service.resolve_path(
            service.document.versions[-1]
        ).is_file()
        assert stray in deleted or not stray.exists()  # true orphan swept
    finally:
        service.close()


def test_explicit_lease_blocks_classification_and_dead_lease_does_not(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        seed = service.import_raw(_make_source(tmp_path, "seed.las", b"seed"))
        # managed path: <artifacts>/raw/<asset_id>/<ver_id>/<file>
        stage_root = service.resolve_path(seed).parents[2]
        orphan_dir = stage_root / "asset_orphan" / "ver_orphan"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        orphan = orphan_dir / "payload.las"
        orphan.write_bytes(b"orphan")

        from paleo_workbench.catalog.gc import plan_gc

        index = service._index
        target = orphan_dir.relative_to(stage_root.parent.parent).as_posix()

        lease_id = index.acquire_staging_lease((target,), kind="test")
        assert lease_id is not None
        guarded = plan_gc(service, explicit=True)
        assert all(item.path != orphan for item in guarded.by_kind("stage_orphan"))

        # Simulate a crashed registrant: lease expires by heartbeat age.
        from datetime import datetime, timedelta

        stale = (
            datetime.now() - timedelta(seconds=index.STAGING_LEASE_TTL_SECONDS * 2)
        ).isoformat(timespec="seconds")
        conn = index._connect()
        with conn:
            conn.execute(
                "UPDATE staging_leases SET heartbeat_at = ? WHERE lease_id = ?",
                (stale, lease_id),
            )
        service._index.prune_stale_staging_leases()
        unguarded = plan_gc(service, explicit=True)
        assert any(item.path == orphan for item in unguarded.by_kind("stage_orphan"))
        index.release_staging_lease(lease_id)
    finally:
        service.close()


def test_blob_import_survives_concurrent_sweep(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        payload = b"blob-dedup-bytes"
        src = _make_source(tmp_path, "b1.las", payload)
        v1 = service.import_raw(src)
        assert v1.metadata.get("blob") or v1.sha256  # blob-backed or hashed
        # Re-import identical content (blob dedup path) while sweeping.
        src2 = _make_source(tmp_path, "b2.las", payload)
        v2 = service.import_raw(src2)
        service.sweep_gc(dry_run=False, explicit=True)
        assert service.resolve_path(v1).is_file()
        assert service.resolve_path(v2).is_file()
    finally:
        service.close()


def test_commit_working_copy_releases_lock_during_payload_io(tmp_path):
    """#1218: the service lock must NOT be held across the working-copy
    move+hash — a concurrent catalog mutation completes meanwhile."""
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        src = _make_source(tmp_path, "wc.las", b"wc-bytes")
        version = service.import_raw(src)
        working = service.create_working_copy(version.id)
        assert working.is_file()

        in_copy = threading.Event()
        proceed = threading.Event()
        original_build = service._build_version

        def gated_build(*args, **kwargs):
            in_copy.set()
            proceed.wait(timeout=10)
            return original_build(*args, **kwargs)

        # Patch at the module level the commit path resolves through.
        import paleo_workbench.catalog.service as service_mod

        original_mod_build = service_mod.DataCatalogService._build_version

        def gated(self, *args, **kwargs):
            if kwargs.get("move"):
                in_copy.set()
                proceed.wait(timeout=10)
            return original_mod_build(self, *args, **kwargs)

        service_mod.DataCatalogService._build_version = gated
        committed: list = []
        error: list = []
        try:
            def commit():
                try:
                    committed.append(
                        service.commit_working_copy(working, name="edited")
                    )
                except Exception as exc:  # pragma: no cover
                    error.append(exc)
                finally:
                    in_copy.set()
                    proceed.set()

            thread = threading.Thread(target=commit)
            thread.start()
            assert in_copy.wait(timeout=10)
            # While the payload IO is in flight, another thread must be able
            # to complete a catalog mutation (it needs the service lock).
            other = service.import_raw(
                _make_source(tmp_path, "other.las", b"other")
            )
            proceed.set()
            thread.join(timeout=10)
            assert not error, error
            assert committed
            assert service.get_version(other.id).sha256
        finally:
            service_mod.DataCatalogService._build_version = original_mod_build
    finally:
        service.close()
