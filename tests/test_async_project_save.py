"""#1040 — project save must not block the GUI thread on file I/O.

``ProjectController.save_project`` used to run the whole persistence chain —
artifact layout creation, full-document ``json.dumps`` (indent=2 forces the
pure-Python encoder), temp-file write, ``fsync``, two ``os.replace`` renames
and a directory ``fsync`` — synchronously inside the Ctrl+S slot. These tests
pin the split that moves the I/O half onto an ``OwnedWorkerJob`` thread:

* ``ProjectManager.prepare_save`` (GUI phase): diff/stale-guard/payload build,
  no heavy I/O, returns ``None`` for a clean document.
* ``ProjectManager.execute_save`` (worker phase): serialize + atomic write,
  touching only detached data — safe off the GUI thread.
* ``ProjectManager.commit_save`` (GUI phase): publish snapshot/updated_at.
* ``ProjectController.save_project_async``: interactive path; event loop keeps
  running while the write happens; re-entrant saves are gated; the save job
  is drained before the session tears down.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.project.manager import ProjectManager  # noqa: E402
from paleo_workbench.project.models import ProjectDocument, ProjectMeta  # noqa: E402


def _project(name: str = "p", created_at: str = "2026-01-01T00:00:00") -> ProjectDocument:
    return ProjectDocument(meta=ProjectMeta(name=name, created_at=created_at))


def test_prepare_save_returns_none_for_clean_document(tmp_path: Path):
    path = tmp_path / "p.paleo.json"
    manager = ProjectManager(path)
    project = _project()
    assert manager.save(project) is True
    stats = manager.last_save_stats
    assert stats.wrote_project_file is True

    # unchanged document → prepare reports nothing to do, no rewrite
    assert ProjectManager(path).prepare_save(project) is None
    assert ProjectManager(path).save(project) is False


def test_execute_save_runs_without_live_document_access(tmp_path: Path):
    """The worker phase must operate purely on the prepared detached payload."""
    path = tmp_path / "p.paleo.json"
    manager = ProjectManager(path)
    project = _project()
    project.meta.name = "async-doc"
    prepared = manager.prepare_save(project)
    assert prepared is not None

    # the live model is not passed to execute at all — only the prepared data
    stats = manager.execute_save(prepared)
    assert stats.wrote_project_file is True
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["meta"]["name"] == "async-doc"


def test_commit_save_records_snapshot_so_next_save_is_clean(tmp_path: Path):
    path = tmp_path / "p.paleo.json"
    manager = ProjectManager(path)
    project = _project()
    prepared = manager.prepare_save(project)
    assert prepared is not None
    stats = manager.execute_save(prepared)
    manager.commit_save(project, prepared, stats)

    assert project.meta.updated_at == prepared.updated_at
    # nothing changed since commit → next save is a no-op (no lost dirty bits
    # and no perpetual meta rewrite)
    assert ProjectManager(path).prepare_save(project) is None


def test_split_save_equivalent_to_legacy_single_call(tmp_path: Path):
    legacy_path = tmp_path / "legacy.paleo.json"
    split_path = tmp_path / "split.paleo.json"

    legacy = _project("same")
    legacy.meta.name = "same"
    ProjectManager(legacy_path).save(legacy)

    split = _project("same", created_at=legacy.meta.created_at)
    split.meta.name = "same"
    mgr = ProjectManager(split_path)
    prepared = mgr.prepare_save(split)
    mgr.execute_save(prepared)
    mgr.commit_save(split, prepared, mgr.last_save_stats)

    legacy_payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    split_payload = json.loads(split_path.read_text(encoding="utf-8"))
    # updated_at legitimately differs between two saves microseconds apart
    legacy_payload["meta"].pop("updated_at")
    split_payload["meta"].pop("updated_at")
    assert legacy_payload == split_payload


# ---------------------------------------------------------------------------
# Controller-level async behavior
# ---------------------------------------------------------------------------

class _StubShell:
    def __init__(self) -> None:
        self.status_messages: list[str] = []

    def shutdown_workers(self) -> bool:
        return True


class _StubWindow:
    """Minimal PaleoWorkbenchWindow double exposing the controller surface."""

    def __init__(self, project: ProjectDocument, project_path: Path | None) -> None:
        self.project = project
        self.project_path = project_path
        self.app_shell = _StubShell()
        self.errors: list[tuple[str, str]] = []

    def _flush_mapping_draft(self) -> bool:
        return True

    def _flush_joint_analysis_state(self) -> None:
        return None

    def _show_project_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))


def test_async_save_writes_file_and_keeps_event_loop_alive(qtbot, tmp_path: Path):
    from paleo_workbench.ui.project_controller import ProjectController

    path = tmp_path / "p.paleo.json"
    window = _StubWindow(_project("async"), path)
    controller = ProjectController(window)  # type: ignore[arg-type]

    # Simulate GUI-thread work queued behind the save start: a timer callback
    # must get a chance to run while the worker holds the I/O phase busy.
    pumped = threading.Event()
    original_execute = ProjectManager.execute_save

    def _slow_execute(self, prepared):
        from PySide6.QtCore import QThread, QCoreApplication

        for _ in range(20):
            QThread.msleep(5)
            QCoreApplication.processEvents()
        return original_execute(self, prepared)

    monkey_execute = pytest.MonkeyPatch()
    monkey_execute.setattr(ProjectManager, "execute_save", _slow_execute)
    try:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, pumped.set)
        controller.save_project_async()
        qtbot.waitUntil(pumped.is_set, timeout=5_000)
        qtbot.waitSignal(
            controller.save_finished, timeout=10_000, check_params_cb=None
        ) if hasattr(controller, "save_finished") else qtbot.wait(1200)
    finally:
        monkey_execute.undo()

    assert path.exists()
    assert not window.errors
    assert controller.save_job_running() is False


def test_async_save_reentrancy_guard(qtbot, tmp_path: Path):
    from PySide6.QtCore import QThread

    from paleo_workbench.ui.project_controller import ProjectController

    path = tmp_path / "p.paleo.json"
    window = _StubWindow(_project("reentrant"), path)
    controller = ProjectController(window)  # type: ignore[arg-type]

    release = threading.Event()
    original_execute = ProjectManager.execute_save

    def _blocking_execute(self, prepared):
        deadline_wait(release, 10.0)
        return original_execute(self, prepared)

    def deadline_wait(event, timeout):
        import time

        end = time.monotonic() + timeout
        while not event.is_set() and time.monotonic() < end:
            QThread.msleep(10)

    patch = pytest.MonkeyPatch()
    patch.setattr(ProjectManager, "execute_save", _blocking_execute)
    try:
        controller.save_project_async()
        qtbot.waitUntil(controller.save_job_running, timeout=5_000)
        second = controller.save_project_async()
        assert second is False, "re-entrant save must be rejected while one runs"
    finally:
        release.set()
        patch.undo()
        qtbot.waitUntil(lambda: not controller.save_job_running(), timeout=10_000)


def test_sync_save_facade_still_writes_synchronously(qtbot, tmp_path: Path):
    """Programmatic/tests/close paths keep the blocking contract."""
    from paleo_workbench.ui.project_controller import ProjectController

    path = tmp_path / "p.paleo.json"
    window = _StubWindow(_project("sync"), path)
    controller = ProjectController(window)  # type: ignore[arg-type]

    result = controller.save_project()

    assert result == path
    assert path.exists()
    assert controller.save_job_running() is False


def test_session_shutdown_drains_in_flight_save(qtbot, tmp_path: Path):
    from PySide6.QtCore import QThread

    from paleo_workbench.ui.project_controller import ProjectController

    path = tmp_path / "p.paleo.json"
    window = _StubWindow(_project("drain"), path)
    controller = ProjectController(window)  # type: ignore[arg-type]

    release = threading.Event()

    def _blocking_execute(self, prepared):
        import time

        end = time.monotonic() + 10.0
        while not release.is_set() and time.monotonic() < end:
            QThread.msleep(10)
        return original_execute_ref(self, prepared)

    original_execute_ref = ProjectManager.execute_save
    patch = pytest.MonkeyPatch()
    patch.setattr(ProjectManager, "execute_save", _blocking_execute)
    try:
        controller.save_project_async()
        qtbot.waitUntil(controller.save_job_running, timeout=5_000)
        release.set()
        # session stop must join the save worker before closing the catalog
        assert controller.shutdown_current_session() is True
        assert controller.save_job_running() is False
    finally:
        release.set()
        patch.undo()
