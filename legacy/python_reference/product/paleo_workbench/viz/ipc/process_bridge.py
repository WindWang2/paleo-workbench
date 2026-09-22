"""QProcessFutureBridge -- Bridges ProcessPoolExecutor futures into PySide6 Qt Signals."""
from __future__ import annotations

from typing import Any
from concurrent.futures import Future
from PySide6.QtCore import QObject, Signal, QTimer


class QProcessFutureBridge(QObject):
    """Bridge ProcessPoolExecutor Futures into PySide6 Qt Signals without blocking UI."""

    finished = Signal(int, object, object)  # (request_id, result, meta)
    failed = Signal(int, str)  # (request_id, error_msg)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(16)  # Check once per frame (60 FPS)
        self._poll_timer.timeout.connect(self._check_futures)
        self._pending_futures: dict[Future, tuple[int, Any]] = {}

    def watch(self, future: Future, request_id: int, meta: Any = None) -> None:
        self._pending_futures[future] = (request_id, meta)
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _check_futures(self) -> None:
        completed = [f for f in self._pending_futures if f.done()]
        for f in completed:
            request_id, meta = self._pending_futures.pop(f)
            try:
                result = f.result()
                self.finished.emit(request_id, result, meta)
            except Exception as exc:
                self.failed.emit(request_id, f"Process worker error: {exc}")

        if not self._pending_futures:
            self._poll_timer.stop()
