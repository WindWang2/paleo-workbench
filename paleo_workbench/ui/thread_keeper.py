"""Application-lifetime ownership for cooperative jobs that outlive a page."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication


def _move_worker_to_app_thread(worker: QObject) -> None:
    """Push a finished worker back to the app thread from its own thread.

    Must execute on the thread the worker currently belongs to (Qt only
    permits pushing out of the *current* thread), i.e. from a
    DirectConnection on ``QThread.finished`` while the worker thread is
    still winding down — never from the GUI thread (#1057).
    """
    app = QApplication.instance()
    if app is None or worker.thread() is app.thread():
        return
    try:
        worker.moveToThread(app.thread())
    except RuntimeError:
        pass


class DetachedJobKeeper(QObject):
    """Keep QThread/worker wrappers alive until their thread actually finishes."""

    release_requested = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: dict[int, tuple[QThread, QObject]] = {}
        self.release_requested.connect(
            self._release,
            Qt.ConnectionType.QueuedConnection,
        )

    def adopt(self, thread: QThread, worker: QObject) -> None:
        key = id(thread)
        if key in self._jobs:
            return
        try:
            thread.setParent(self)
        except RuntimeError:
            pass
        self._jobs[key] = (thread, worker)
        # #1057: Qt only allows pushing a QObject out of the thread it
        # currently belongs to.  Wire the worker's move back to the app
        # thread NOW, as a DirectConnection on finished — it then executes
        # on the still-valid worker thread, which is the legal push
        # direction.  A pull from _release (running on the GUI thread after
        # the thread died) fails with "Cannot move objects that belong to
        # another thread" and leaves any deleteLater posted to a finished
        # thread's event queue forever undelivered (leaked QObject).
        thread.finished.connect(
            lambda: _move_worker_to_app_thread(worker),
            Qt.ConnectionType.DirectConnection,
        )
        # QThread.finished may be emitted from the managed thread.  Emit a
        # relay signal so registry mutation and deleteLater happen on the
        # keeper/QApplication thread.
        thread.finished.connect(lambda key=key: self.release_requested.emit(key))
        if thread.isFinished():
            # The thread finished between the shutdown wait() timeout and
            # this connection (TOCTOU): QThread.finished is emitted exactly
            # once and never replays, so the relay would never fire and the
            # (thread, worker) entry would leak forever.  The finished flag
            # is set before the signal is emitted, so observing it here means
            # the emission is already past — release manually.  Racing the
            # flag itself is safe: a duplicate release_requested emission is
            # a no-op in _release.
            self.release_requested.emit(key)

    def owns(self, thread: QThread) -> bool:
        return id(thread) in self._jobs

    def job_count(self) -> int:
        return len(self._jobs)

    @Slot(object)
    def _release(self, key: int) -> None:
        job = self._jobs.pop(key, None)
        if job is None:
            return
        thread, worker = job
        try:
            # The worker was already pushed back to the app thread by the
            # DirectConnection finished hook installed in adopt(); moving it
            # here would be an invalid cross-thread pull (#1057).
            worker.deleteLater()
            thread.deleteLater()
        except Exception:
            try:
                worker.deleteLater()
                thread.deleteLater()
            except Exception:
                pass


_KEEPER: DetachedJobKeeper | None = None


def detached_job_keeper() -> DetachedJobKeeper:
    global _KEEPER
    if _KEEPER is None:
        _KEEPER = DetachedJobKeeper(QApplication.instance())
    return _KEEPER
