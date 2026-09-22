"""Regression tests for DetachedJobKeeper adoption/release semantics."""

from __future__ import annotations

import random
import time
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication


class _ImmediateThread(QThread):
    """A thread whose run() returns right away: it finishes without ever
    running an event loop, deterministically exercising the finished-before-
    adopt TOCTOU window."""

    def run(self) -> None:
        pass


class _SleepyWorker(QObject):
    finished = Signal()

    def __init__(self, started: Event, delay_ms: int) -> None:
        super().__init__()
        self._started = started
        self._delay = delay_ms / 1000.0

    @Slot()
    def run(self) -> None:
        self._started.set()
        time.sleep(self._delay)
        self.finished.emit()


def test_adopt_of_already_finished_thread_is_released(qtbot):
    """Adopting a thread whose finished signal was already emitted must not
    leak the registry entry (C77 TOCTOU).

    ``OwnedWorkerJob.shutdown`` adopts after ``wait()`` times out; if the
    thread finished inside that window, ``QThread.finished`` was already
    emitted and never replays — only the ``isFinished`` check in ``adopt``
    can release the entry.  A thread that finished before ``adopt`` is the
    deterministic extreme of that window.
    """
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    thread = _ImmediateThread()
    worker = QObject()
    thread.start()
    assert thread.wait(3_000)
    assert thread.isFinished()

    keeper = detached_job_keeper()
    keeper.adopt(thread, worker)
    assert keeper.owns(thread)
    assert keeper.job_count() == 1
    # The isFinished check in adopt queues the release; drain the event loop.
    qtbot.waitUntil(lambda: keeper.job_count() == 0, timeout=3_000)
    assert not keeper.owns(thread)


def test_timed_out_shutdown_stress_never_leaks_keeper_entries(qtbot):
    """400 timed-out shutdowns with randomized worker completion timing must
    leave the keeper registry empty once all threads finish (C77).

    Regression: a worker finishing between ``wait()`` returning False and the
    ``finished`` connection inside ``adopt`` leaked a permanent entry.
    """
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    rng = random.Random(20260815)
    keeper = detached_job_keeper()
    for _ in range(400):
        started = Event()
        worker = _SleepyWorker(started, rng.randint(0, 8))
        job = OwnedWorkerJob()
        job.start(worker, terminal_signals=(worker.finished,))
        assert started.wait(timeout=2.0)
        job.shutdown(wait_ms=1)
        # Let queued release_requested deliveries land while the loop runs.
        QApplication.processEvents()

    # All detached threads finish within a few ms of their randomized sleep;
    # every adopted thread must be released (registry returns to zero).
    qtbot.waitUntil(lambda: keeper.job_count() == 0, timeout=10_000)


def test_detached_worker_returns_to_app_thread_and_is_deleted(qtbot):
    """#1057: a detached worker must be pushed back to the app thread from
    its own thread (DirectConnection on ``finished``) and then deleted via
    ``deleteLater`` on the app thread.

    Regression: ``_release`` used to pull the worker with
    ``moveToThread(app.thread())`` while running on the GUI thread — Qt
    rejects that cross-thread pull, so ``deleteLater`` was posted to the
    finished thread's event queue and the QObject leaked.
    """
    import shiboken6

    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    started = Event()
    worker = _SleepyWorker(started, 80)
    job = OwnedWorkerJob()
    job.start(worker, terminal_signals=(worker.finished,))
    assert started.wait(timeout=2.0)
    # Time the shutdown out so the running job is handed to the keeper.
    assert job.shutdown(wait_ms=1) is False
    keeper = detached_job_keeper()
    assert keeper.job_count() >= 1

    # The worker thread outlives the timed-out shutdown; once it finishes,
    # the keeper releases the entry and the worker must actually be
    # destroyed — proving the deleteLater landed on a live (app-thread)
    # event queue.  Under the pre-#1057 bug the deleteLater was posted to
    # the finished thread's dead queue and the QObject leaked forever.
    qtbot.waitUntil(lambda: keeper.job_count() == 0, timeout=10_000)
    qtbot.waitUntil(lambda: not shiboken6.isValid(worker), timeout=10_000)
