"""Reusable ownership for one cooperative QObject worker and its QThread."""

from __future__ import annotations

from collections.abc import Callable
import weakref

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from paleo_workbench.ui.thread_keeper import detached_job_keeper


class OwnedWorkerJob(QObject):
    """Own one worker thread until it has completely stopped."""

    released = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._cancel: Callable[[], None] | None = None
        self._target: object | None = None
        self._result_connections: list[tuple[object, object]] = []
        self._destroyed_conn: object | None = None

    @property
    def thread(self) -> QThread | None:
        return self._thread

    @property
    def worker(self) -> QObject | None:
        return self._worker

    @property
    def target(self) -> object | None:
        return self._target

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(
        self,
        worker: QObject,
        *,
        terminal_signals: tuple[object, ...],
        result_connections: tuple[tuple[object, object], ...] = (),
        cancel: Callable[[], None] | None = None,
        target: object | None = None,
    ) -> None:
        if self._thread is not None:
            raise RuntimeError("worker job already owns a thread")

        thread = QThread()
        self._thread = thread
        self._worker = worker
        self._cancel = cancel
        self._target = target
        self._result_connections = list(result_connections)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)  # type: ignore[attr-defined]
        for signal, slot in self._result_connections:
            signal.connect(slot)
        for signal in terminal_signals:
            signal.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            self._on_thread_stopped,
            Qt.ConnectionType.QueuedConnection,
        )
        thread_ref = weakref.ref(thread)
        worker_ref = weakref.ref(worker)
        self._destroyed_conn = self.destroyed.connect(
            lambda _=None, thread_ref=thread_ref, worker_ref=worker_ref, cancel=cancel:
            _safe_detach_on_destroy(thread_ref, worker_ref, cancel)
        )
        thread.start()

    def shutdown(self, wait_ms: int = 3_000) -> bool:
        """Cancel and release this job, detaching it when the wait expires."""
        thread = self._thread
        worker = self._worker
        if thread is None or worker is None:
            return True

        self._disconnect_results()
        # Disconnect our own slot so no queued thread.finished signal can
        # arrive after identity is released (C-2 race-condition guard).
        try:
            thread.finished.disconnect(self._on_thread_stopped)
        except (RuntimeError, TypeError):
            pass
        cancel = self._cancel
        if cancel is not None:
            try:
                cancel()
            except Exception:
                pass

        joined = True
        try:
            thread.requestInterruption()
            if thread.isRunning():
                thread.quit()
                joined = thread.wait(max(0, int(wait_ms)))
        except RuntimeError:
            joined = True

        if not joined:
            try:
                thread.requestInterruption()
                thread.quit()
                detached_job_keeper().adopt(thread, worker)
            except RuntimeError:
                pass
        self._release_identity(thread, worker, delete_thread=joined)
        return joined

    def _disconnect_results(self) -> None:
        connections = self._result_connections
        self._result_connections = []
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _release_identity(
        self,
        thread: QThread,
        worker: QObject,
        *,
        delete_thread: bool,
    ) -> None:
        if self._thread is not thread or self._worker is not worker:
            return
        self._thread = None
        self._worker = None
        self._cancel = None
        self._target = None
        self._result_connections = []
        if self._destroyed_conn is not None:
            try:
                self.destroyed.disconnect(self._destroyed_conn)
            except (RuntimeError, TypeError):
                pass
            self._destroyed_conn = None
        if delete_thread:
            try:
                thread.deleteLater()
            except RuntimeError:
                pass
        self.released.emit()

    @Slot()
    def _on_thread_stopped(self) -> None:
        thread = self.sender()
        worker = self._worker
        if not isinstance(thread, QThread) or worker is None:
            return
        self._release_identity(thread, worker, delete_thread=True)


def _safe_detach_on_destroy(
    thread_ref: weakref.ref[QThread],
    worker_ref: weakref.ref[QObject],
    cancel: Callable[[], None] | None,
) -> None:
    thread = thread_ref()
    worker = worker_ref()
    if thread is not None and worker is not None:
        try:
            if thread.isRunning():
                if cancel is not None:
                    try:
                        cancel()
                    except Exception:
                        pass
                thread.requestInterruption()
                thread.quit()
                detached_job_keeper().adopt(thread, worker)
        except Exception:
            pass
