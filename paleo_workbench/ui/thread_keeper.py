"""Application-lifetime ownership for cooperative jobs that outlive a page."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication


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
            app = QApplication.instance()
            if app is not None and worker.thread() is not app.thread():
                worker.moveToThread(app.thread())
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
