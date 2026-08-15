from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.project_controller import ProjectController


class _BlockingWorker(QObject):
    finished = Signal()

    def __init__(self, started: Event, release: Event) -> None:
        super().__init__()
        self._started = started
        self._release = release

    @Slot()
    def run(self) -> None:
        self._started.set()
        self._release.wait(timeout=5.0)
        self.finished.emit()


class _Shell:
    def __init__(self, *, joined: bool = True) -> None:
        self.joined = joined
        self.calls = 0

    def shutdown_workers(self, _wait_ms=3_000) -> bool:
        self.calls += 1
        return self.joined


class _Window:
    def __init__(self, project: ProjectDocument, path: Path | None = None) -> None:
        self.project = project
        self.project_path = path
        self.app_shell = _Shell()
        self.errors: list[tuple[str, str]] = []
        self.refresh_calls: list[bool] = []

    def _refresh_shell(self, *, defer_nonvisible_bindings: bool = False) -> None:
        self.refresh_calls.append(defer_nonvisible_bindings)
        self.app_shell = _Shell()

    def _show_project_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def _flush_mapping_draft(self) -> bool:
        return True

    def _flush_joint_analysis_state(self) -> None:
        pass


def test_open_aborts_without_closing_catalog_when_worker_does_not_join(tmp_path):
    source = tmp_path / "source.paleo.json"
    target = tmp_path / "target.paleo.json"
    ProjectManager(target).save(ProjectDocument.new("Target"))
    window = _Window(ProjectDocument.new("Source"), source)
    window.app_shell = _Shell(joined=False)
    controller = ProjectController(window)

    assert controller.open_project_path(target) is False
    assert window.project.meta.name == "Source"
    assert window.project_path == source
    assert window.refresh_calls == [True]
    assert "后台任务" in (controller._last_open_error or "")


def test_queued_catalog_maintenance_is_ignored_after_session_replacement(qtbot, tmp_path):
    target = tmp_path / "target.paleo.json"
    loaded = ProjectDocument.new("Target")
    window = _Window(loaded, target)
    controller = ProjectController(window)
    controller._session_generation = 3
    controller._schedule_catalog_maintenance(target, loaded)
    controller._session_generation += 1

    # A queued callback may run later, but generation mismatch is a no-op.
    qtbot.wait(10)
    assert window.project is loaded


def test_session_end_rejected_while_detached_threads_are_alive(qtbot, tmp_path):
    """A second close after a timed-out detach must keep rejecting the session
    end until the detached thread actually finishes (C18).

    Regression: the join gate only consulted jobs still owned by pages, so a
    second close saw every job as joined and proceeded to tear down
    QApplication while a detached QThread was still running
    ("QThread: Destroyed while thread is still running", SIGABRT).
    """
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    source = tmp_path / "source.paleo.json"
    source.write_text("{}", encoding="utf-8")
    window = _Window(ProjectDocument.new("Source"), source)
    controller = ProjectController(window)

    started = Event()
    release = Event()
    worker = _BlockingWorker(started, release)
    job = OwnedWorkerJob()
    job.start(worker, terminal_signals=(worker.finished,))
    assert started.wait(timeout=2.0)
    thread = job.thread
    assert thread is not None
    try:
        # First close: the worker exceeds the wait budget and is detached.
        assert job.shutdown(wait_ms=1) is False
        keeper = detached_job_keeper()
        assert keeper.owns(thread)

        # Second close: the shell reports its (now detached) jobs as joined,
        # but the keeper gate must still refuse to end the session.
        assert controller.shutdown_current_session() is False

        # Once the detached thread finishes and the keeper drains, the
        # session may end.
        release.set()
        qtbot.waitUntil(lambda: keeper.job_count() == 0, timeout=3_000)
        assert controller.shutdown_current_session() is True
    finally:
        # Never leave a running thread in the keeper: a leaked running
        # QThread would crash the whole test process at teardown.
        release.set()
        qtbot.waitUntil(lambda: detached_job_keeper().job_count() == 0, timeout=3_000)
