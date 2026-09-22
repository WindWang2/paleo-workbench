"""Milestone 1 Empirical Stress Tests: OwnedWorkerJob Concurrency & Lifecycle.

Stress-tests:
1. Rapid job creation, start, and shutdown/rejection churn (100+ sequential/wave jobs).
2. Concurrent dialog / worker rejection, close, and detach cycles with DetachedJobKeeper.
3. Worker exception storms and error propagation under heavy thread churn.
4. Rapid cancellation and late-result suppression under racing conditions.
5. QObject parent destruction races during active worker execution.
"""

from __future__ import annotations

import random
import threading
from threading import Event
import time
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget
import pytest

from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.thread_keeper import detached_job_keeper


class _FastProbeWorker(QObject):
    finished = Signal()
    failed = Signal(str)

    def __init__(self, should_fail: bool = False, delay_ms: float = 0.0, started_evt: Event | None = None) -> None:
        super().__init__()
        self.should_fail = should_fail
        self.delay_ms = delay_ms
        self.started_evt = started_evt
        self.ran_off_gui = False

    @Slot()
    def run(self) -> None:
        app = QApplication.instance()
        assert app is not None
        self.ran_off_gui = QThread.currentThread() is not app.thread()
        if self.started_evt is not None:
            self.started_evt.set()
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        if self.should_fail:
            self.failed.emit("intentional failure")
        else:
            self.finished.emit()


class _ControllableWorker(QObject):
    progress = Signal(int)
    completed = Signal(dict)
    finished = Signal()

    def __init__(self, total_steps: int = 50, step_delay_ms: float = 1.0, started_evt: Event | None = None) -> None:
        super().__init__()
        self.total_steps = total_steps
        self.step_delay_ms = step_delay_ms
        self.started_evt = started_evt
        self.ran_off_gui = False

    @Slot()
    def run(self) -> None:
        app = QApplication.instance()
        assert app is not None
        self.ran_off_gui = QThread.currentThread() is not app.thread()
        if self.started_evt is not None:
            self.started_evt.set()
        thread = QThread.currentThread()
        for i in range(self.total_steps):
            if thread.isInterruptionRequested():
                self.finished.emit()
                return
            if self.step_delay_ms > 0:
                time.sleep(self.step_delay_ms / 1000.0)
            self.progress.emit(i)
        self.completed.emit({"status": "ok", "steps": self.total_steps})
        self.finished.emit()


def test_stress_rapid_job_lifecycle_churn(qtbot):
    """Stress-test 100 rapid sequential and overlapping OwnedWorkerJob runs."""
    for cycle in range(100):
        job = OwnedWorkerJob()
        worker = _FastProbeWorker(delay_ms=random.uniform(0.01, 0.2))
        released: list[bool] = []
        job.released.connect(lambda: released.append(True))
        job.start(
            worker,
            terminal_signals=(worker.finished,),
        )
        qtbot.waitUntil(lambda: len(released) == 1, timeout=3_000)
        assert worker.ran_off_gui is True
        assert job.is_running is False
        assert job.thread is None
        assert job.worker is None


def test_stress_concurrent_dialog_rejections_and_closes(qtbot):
    """Concurrently start and randomly reject/close/detach 30 workers."""
    keeper = detached_job_keeper()
    threads_to_track: list[QThread] = []
    jobs: list[OwnedWorkerJob] = []

    for i in range(30):
        started_event = Event()
        worker = _ControllableWorker(total_steps=100, step_delay_ms=2.0, started_evt=started_event)
        job = OwnedWorkerJob()
        jobs.append(job)
        job.start(
            worker,
            terminal_signals=(worker.finished,),
        )
        assert started_event.wait(timeout=2.0)
        t = job.thread
        assert t is not None
        threads_to_track.append(t)

        # Randomly perform different shutdown actions
        action = i % 4
        if action == 0:
            # Immediate shutdown with 0 timeout -> detaches to keeper
            joined = job.shutdown(wait_ms=0)
            assert joined is False
            assert keeper.owns(t) is True
        elif action == 1:
            # Shutdown with reasonable timeout -> attempts join
            job.shutdown(wait_ms=50)
        elif action == 2:
            # Request cancel first, then shutdown
            job.cancel()
            job.shutdown(wait_ms=10)
        elif action == 3:
            # Let it run briefly, then shutdown
            time.sleep(0.005)
            job.shutdown(wait_ms=20)

    # Wait for all detached and active threads to finish execution cleanly
    qtbot.waitUntil(
        lambda: all(not keeper.owns(t) for t in threads_to_track),
        timeout=10_000,
    )
    qtbot.waitUntil(
        lambda: keeper.job_count() == 0,
        timeout=5_000,
    )


def test_stress_worker_exception_storm(qtbot):
    """50 workers failing with error signals must shut down cleanly without deadlocks."""
    for i in range(50):
        worker = _FastProbeWorker(should_fail=True, delay_ms=0.1)
        job = OwnedWorkerJob()
        failed_msgs: list[str] = []
        job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=((worker.failed, failed_msgs.append),),
        )
        qtbot.waitUntil(lambda: len(failed_msgs) == 1, timeout=3_000)
        assert failed_msgs == ["intentional failure"]
        qtbot.waitUntil(lambda: not job.is_running, timeout=3_000)


def test_stress_rapid_cancellation_and_late_result_suppression(qtbot):
    """Late result emissions during shutdown must be strictly suppressed by the guarded slot."""
    received_results: list[dict] = []
    
    for i in range(25):
        started_event = Event()
        worker = _ControllableWorker(total_steps=20, step_delay_ms=1.0, started_evt=started_event)
        job = OwnedWorkerJob()
        job.start(
            worker,
            terminal_signals=(worker.finished,),
            result_connections=((worker.completed, received_results.append),),
        )
        assert started_event.wait(timeout=2.0)
        # Abruptly shutdown while worker is running
        job.shutdown(wait_ms=0)
        # Verify job is released
        assert not job.is_running

    # Process events to allow any queued signals to flush
    QApplication.processEvents()
    time.sleep(0.05)
    QApplication.processEvents()
    
    # None of the aborted jobs should have delivered results to received_results
    assert received_results == []


def test_stress_qobject_destruction_under_active_execution(qtbot):
    """Parent QObject deletion during heavy worker execution safely adopts threads into keeper."""
    import shiboken6

    keeper = detached_job_keeper()
    baseline_jobs = keeper.job_count()
    threads: list[QThread] = []

    # Long-lived on purpose (~10 min of stepped work): the destroy below must
    # happen while the worker is PROVABLY still executing. With the old
    # 200ms budget a loaded CI runner occasionally let the worker finish
    # before the destroy, taking the normal-completion path instead of
    # keeper adoption (#1023).
    for i in range(20):
        parent_widget = QWidget()
        started_event = Event()
        worker = _ControllableWorker(total_steps=300_000, step_delay_ms=2.0, started_evt=started_event)
        job = OwnedWorkerJob(parent_widget)
        job.start(
            worker,
            terminal_signals=(worker.finished,),
        )
        assert started_event.wait(timeout=2.0)
        t = job.thread
        assert t is not None
        threads.append(t)

        # Abruptly destroy the parent widget
        parent_widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()

        # Thread must end up tracked by the keeper. Adoption plus its
        # cooperative interruption can run the FULL lifecycle (finish ->
        # release -> untrack) inside one event pump on a loaded runner, so
        # "owns() right now" is racy: accept either still-tracked or already
        # finished through the keeper. What must never happen is a live,
        # untracked, unfinished thread — with a 300k-step worker there is no
        # natural-completion path, so neither branch means the job was lost.
        def _adopted_or_released():
            if keeper.owns(t):
                return True
            try:
                return t.isFinished()
            except RuntimeError:
                # Wrapper already deleted == tracked, then released.
                return True

        qtbot.waitUntil(_adopted_or_released, timeout=5_000)
        if not (_adopted_or_released()):
            thread_valid = bool(shiboken6.isValid(t))
            raise AssertionError(
                "thread neither adopted nor finished after parent destruction "
                f"(iteration={i}, thread_valid={thread_valid}, "
                f"thread_isRunning={t.isRunning() if thread_valid else 'n/a'}, "
                f"job_released={job._state.get('released')}, "
                f"keeper_jobs={keeper.job_count()}, baseline={baseline_jobs})"
            )

    # Wait for every adopted worker to finish and be released from the
    # keeper. Count the REGISTRY, not the wrappers: released threads are
    # deleteLater'd, so touching them here races shiboken deletion.
    qtbot.waitUntil(
        lambda: keeper.job_count() <= baseline_jobs,
        timeout=15_000,
    )
    # Flush the queued DeferredDelete for the released threads before the
    # conftest fence tears anything down.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
