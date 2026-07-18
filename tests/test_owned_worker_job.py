from __future__ import annotations

import importlib
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication


class _ProbeWorker(QObject):
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.ran_off_gui = False

    @Slot()
    def run(self) -> None:
        app = QApplication.instance()
        assert app is not None
        self.ran_off_gui = QThread.currentThread() is not app.thread()
        self.finished.emit()


class _BlockingWorker(QObject):
    completed = Signal(str)
    finished = Signal()

    def __init__(self, started: Event, release: Event) -> None:
        super().__init__()
        self._started = started
        self._release = release

    @Slot()
    def run(self) -> None:
        self._started.set()
        self._release.wait(timeout=5.0)
        self.completed.emit("stale")
        self.finished.emit()


def test_owned_worker_job_runs_off_gui_and_releases_normal_completion(qtbot):
    module = importlib.import_module("paleo_workbench.ui.owned_worker_job")
    job = module.OwnedWorkerJob()
    worker = _ProbeWorker()
    released: list[bool] = []
    job.released.connect(lambda: released.append(True))

    job.start(worker, terminal_signals=(worker.finished,))

    qtbot.waitUntil(lambda: released == [True], timeout=3_000)
    assert worker.ran_off_gui is True
    assert job.is_running is False
    assert job.thread is None
    assert job.worker is None


def test_shutdown_cancels_disconnects_results_and_detaches_blocked_worker(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    started = Event()
    release = Event()
    cancelled = Event()
    results: list[str] = []
    target = object()
    worker = _BlockingWorker(started, release)
    job = OwnedWorkerJob()
    job.start(
        worker,
        terminal_signals=(worker.finished,),
        result_connections=((worker.completed, results.append),),
        cancel=cancelled.set,
        target=target,
    )
    assert started.wait(timeout=2.0)
    thread = job.thread
    assert thread is not None
    assert job.target is target

    joined = job.shutdown(wait_ms=1)

    keeper = detached_job_keeper()
    assert joined is False
    assert cancelled.is_set()
    assert keeper.owns(thread)
    assert job.thread is None
    assert job.worker is None
    assert job.target is None
    release.set()
    qtbot.waitUntil(lambda: not keeper.owns(thread), timeout=3_000)
    assert results == []


def test_job_remains_running_until_gui_release_is_processed(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

    worker = _ProbeWorker()
    job = OwnedWorkerJob()
    job.start(worker, terminal_signals=(worker.finished,))
    thread = job.thread
    assert thread is not None
    assert thread.wait(3_000)

    assert job.thread is thread
    assert job.is_running is True
    qtbot.waitUntil(lambda: job.thread is None, timeout=3_000)


def test_detached_old_worker_cannot_release_a_new_job(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    first_started = Event()
    first_release = Event()
    first = _BlockingWorker(first_started, first_release)
    job = OwnedWorkerJob()
    job.start(first, terminal_signals=(first.finished,))
    assert first_started.wait(timeout=2.0)
    first_thread = job.thread
    assert first_thread is not None
    assert job.shutdown(wait_ms=1) is False

    second_started = Event()
    second_release = Event()
    second = _BlockingWorker(second_started, second_release)
    job.start(second, terminal_signals=(second.finished,))
    assert second_started.wait(timeout=2.0)
    second_thread = job.thread
    assert second_thread is not None

    first_release.set()
    keeper = detached_job_keeper()
    qtbot.waitUntil(lambda: not keeper.owns(first_thread), timeout=3_000)
    assert job.thread is second_thread
    assert job.worker is second

    second_release.set()
    qtbot.waitUntil(lambda: job.thread is None, timeout=3_000)
