"""#1042 — ``NativeRasterRequestController.shutdown`` must propagate the
worker-join result.

``OwnedWorkerJob.shutdown`` returns ``False`` when the worker thread fails to
join within ``wait_ms`` — the thread is detached while still alive, which is
exactly the signal callers like ``MappingPage.shutdown_workers`` need before
closing the catalog underneath native raster work. The controller used to
discard the value (``-> None``), so the ``res is False`` guard downstream was
dead code.
"""

from __future__ import annotations

import threading
from unittest import mock

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QThread, Signal  # noqa: E402

from paleo_workbench.ui.native_render_worker import (  # noqa: E402
    NativeRasterRequestController,
)


def test_shutdown_returns_join_result_from_owned_job(qtbot, monkeypatch):
    controller = NativeRasterRequestController()
    try:
        for joined in (True, False):
            monkeypatch.setattr(
                controller._job, "shutdown", mock.Mock(return_value=joined)
            )
            assert controller.shutdown(wait_ms=123) is joined
            controller._job.shutdown.assert_called_once_with(123)
            controller._job.shutdown.reset_mock()
    finally:
        controller._job.shutdown = mock.Mock(return_value=True)
        controller.shutdown()


def test_shutdown_result_is_boolean_not_none(qtbot):
    """The old signature returned ``None`` — the ``res is False`` guard in
    ``MappingPage.shutdown_workers`` could never fire."""
    controller = NativeRasterRequestController()
    result = controller.shutdown(wait_ms=10)
    assert isinstance(result, bool)
    assert result is True


class _StuckWorker(QObject):
    """Worker whose ``run`` outlives the shutdown wait window."""

    terminal = Signal()

    def __init__(self, release: threading.Event) -> None:
        super().__init__()
        self._release = release

    def run(self) -> None:
        import time

        deadline = time.monotonic() + 5.0
        while not self._release.is_set() and time.monotonic() < deadline:
            QThread.msleep(20)
        self.terminal.emit()


def test_shutdown_reports_timeout_for_stuck_worker(qtbot):
    """A worker that ignores quit within wait_ms must surface ``False``."""
    controller = NativeRasterRequestController()
    release = threading.Event()
    worker = _StuckWorker(release)
    controller._job.start(worker, terminal_signals=(worker.terminal,))
    qtbot.wait_until(lambda: controller._job.thread is not None, timeout=2_000)
    QThread.msleep(100)  # let run() enter its wait loop

    try:
        result = controller.shutdown(wait_ms=50)
        assert result is False, "stuck worker must be reported as not joined"
    finally:
        release.set()
        QThread.msleep(150)
        qtbot.wait(50)
