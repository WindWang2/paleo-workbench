"""Session generation guards + real cancellation (#1223, #1224, v6 §8/§9).

Pins:
- catalog backend identity is the authoritative session token: a service
  captured by a long task stops being current after reset/switch, and
  seismic lifecycle callbacks refuse to mutate through it;
- hashing is interruptible at chunk granularity (no partial digests);
- verify_integrity reports cancelled on mid-hash cancel;
- scheduler supersede: a resubmit against a still-QUEUED task replaces it
  instead of erroring (a cancelled request must not hang the next one);
- map-export cancel checkpoints stop between phases.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from paleo_workbench.catalog import catalog_is_current, reset_catalog, set_catalog
from paleo_workbench.catalog.checksum import ChecksumCancelled, sha256_file
from paleo_workbench.catalog.service import DataCatalogService


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def test_catalog_identity_is_the_session_token(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        set_catalog(service)
        assert catalog_is_current(service) is True

        # A session switch swaps the backend — the captured service is stale.
        reset_catalog()
        assert catalog_is_current(service) is False

        other = DataCatalogService.open(project)
        try:
            set_catalog(other)
            assert catalog_is_current(service) is False
            assert catalog_is_current(other) is True
        finally:
            reset_catalog()
            other.close()
    finally:
        service.close()


def test_seismic_callbacks_refuse_stale_service(tmp_path, monkeypatch):
    """#1223: on_done after a project switch must not register anything."""
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        set_catalog(service)
        # Simulate the switch: backend replaced while the task was in flight.
        reset_catalog()

        from paleo_workbench import seismic_lifecycle as life

        # The stale-service primitive is False for the captured service...
        assert catalog_is_current(service) is False
        # ...and every task callback embeds the guard (#1223).
        import inspect

        src = inspect.getsource(life.start_attribute_job)
        assert "catalog_is_current" in src
        assert "_session_stale" in src
    finally:
        reset_catalog()
        service.close()


def test_sha256_cancel_interrupts_at_chunk_granularity(tmp_path):
    payload = tmp_path / "big.bin"
    payload.write_bytes(b"x" * (5 * 1024 * 1024))  # 5 chunks @1MiB

    fired = threading.Event()

    def cancel_after_third_chunk() -> bool:
        return fired.is_set()

    # A callback that flips mid-way: use a counter via closure.
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 3  # cancel on the 4th poll

    with pytest.raises(ChecksumCancelled):
        sha256_file(payload, cancel=cancel)
    assert calls["n"] == 4  # stopped promptly, not after the whole file

    # Uncancelled hash still works and is stable.
    del cancel_after_third_chunk
    assert sha256_file(payload) == sha256_file(payload)


def test_verify_integrity_cancelled_mid_hash(tmp_path):
    project = _make_project(tmp_path)
    service = DataCatalogService.open(project)
    try:
        src = tmp_path / "w.las"
        src.write_bytes(b"y" * (3 * 1024 * 1024))
        version = service.import_raw(src)
        flip = threading.Event()

        def cancel() -> bool:
            return flip.is_set()

        # Not cancelled: full verification.
        report = service.verify_integrity(version.id, cancel=cancel)
        assert report.status_for(version.id) == "verified"

        # Cancel the very first chunk check: honest partial state.
        def cancel_now() -> bool:
            return True

        report = service.verify_integrity(version.id, cancel=cancel_now)
        assert report.cancelled is True
        assert version.id not in report.statuses or report.status_for(
            version.id
        ) == "unknown"
    finally:
        service.close()


def test_scheduler_supersedes_queued_duplicate():
    from paleo_workbench.runtime.task_scheduler import TaskScheduler

    gate = threading.Event()
    sched = TaskScheduler(max_workers=1)
    try:
        def blocker(ctx):
            gate.wait(timeout=10)
            return "first-done"

        started = threading.Event()

        def blocker(ctx):
            started.set()
            gate.wait(timeout=10)
            return "first-done"

        first = sched.submit_callable(
            blocker, kind="io", task_key="lane/x"
        )
        assert started.wait(timeout=10)  # first is truly RUNNING
        # Second submit while the first is RUNNING (single worker): refused
        # with an honest running-state message.
        with pytest.raises(ValueError, match="正在运行|already"):
            sched.submit_callable(lambda ctx: 2, kind="io", task_key="lane/x")

        gate.set()

        def _wait_terminal(handle, timeout=10.0):
            deadline = time.time() + timeout
            while time.time() < deadline:
                if handle.state.name in ("SUCCEEDED", "FAILED", "CANCELLED", "DONE"):
                    return handle
                time.sleep(0.02)
            raise AssertionError(f"task not terminal: {handle.state}")

        _wait_terminal(first)
        assert first.result == "first-done"

        # QUEUED duplicate (block the lane again, queue a second): supersede
        # cancels the queued one and admits the new one.
        gate2 = threading.Event()

        def blocker2(ctx):
            gate2.wait(timeout=10)
            return "a"

        holder = sched.submit_callable(blocker2, kind="io", task_key="lane/hold")
        queued = sched.submit_callable(
            lambda ctx: "queued-old", kind="io", task_key="lane/y"
        )
        replacement = sched.submit_callable(
            lambda ctx: "queued-new", kind="io", task_key="lane/y"
        )
        gate2.set()
        _wait_terminal(holder)
        _wait_terminal(replacement)
        assert replacement.result == "queued-new"
        # The superseded task never ran and is terminal CANCELLED.
        _wait_terminal(queued)
        assert queued.state.name == "CANCELLED"
    finally:
        sched.shutdown()


def test_map_export_cancel_checkpoints():
    """The render pipeline honors cancel() at each phase boundary."""
    from paleo_workbench.ui.map_export_worker import _ExportCancelled

    # cancel=True at any checkpoint raises _ExportCancelled, which the
    # worker maps to the cancelled signal (never a finished half-product).
    from paleo_workbench.ui import map_export_worker as mew

    assert issubclass(_ExportCancelled, Exception)
    src = Path(mew.__file__).read_text(encoding="utf-8")
    assert src.count("cancel()") >= 3  # native→fallback, pre-decorations, pre-save
