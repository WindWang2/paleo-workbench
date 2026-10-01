"""Regression test for OwnedWorkerJob result-signal cleanup (ISSUE-018).

``_release_identity`` used to clear ``_result_connections`` without
disconnecting them, so the guarded result closures stayed connected to the
worker for as long as the worker object lived — the signal-closure leak
from audit/issues ISSUE-018. Release must actually disconnect, like
``shutdown()`` already did.
"""

from __future__ import annotations

from threading import Event

from PySide6.QtCore import QObject, Signal, Slot
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob


class _QuickWorker(QObject):
    completed = Signal(dict)
    finished = Signal()

    def __init__(self, started_evt: Event | None = None) -> None:
        super().__init__()
        self.started_evt = started_evt

    @Slot()
    def run(self) -> None:
        if self.started_evt is not None:
            self.started_evt.set()
        self.completed.emit({"status": "ok"})
        self.finished.emit()


def test_release_disconnects_result_signal_closures(qtbot):
    started = Event()
    job = OwnedWorkerJob()
    worker = _QuickWorker(started_evt=started)

    disconnected: list[tuple[object, object]] = []
    original = OwnedWorkerJob._disconnect_results

    def spy(self):
        disconnected.extend(self._result_connections)
        original(self)

    OwnedWorkerJob._disconnect_results = spy  # type: ignore[method-assign]
    try:
        released: list[bool] = []
        job.released.connect(lambda: released.append(True))
        got: list[dict] = []

        job.start(
            worker,
            terminal_signals=(worker.finished,),
            result_connections=((worker.completed, got.append),),
        )
        qtbot.waitUntil(lambda: len(released) == 1, timeout=3_000)
    finally:
        OwnedWorkerJob._disconnect_results = original  # type: ignore[method-assign]

    # The release path must have disconnected the real result connection,
    # not merely dropped the list (the leak).
    assert len(disconnected) == 1, (
        f"release path disconnected {len(disconnected)} result connection(s), expected 1"
    )
    signal, _slot = disconnected[0]
    assert signal is worker.completed
    assert job._result_connections == []
