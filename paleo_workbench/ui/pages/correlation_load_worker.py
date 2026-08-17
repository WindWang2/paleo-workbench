"""Background worker for multi-well LAS load (off the GUI thread).

``load_correlation_wells`` walks up to 8 LAS files through VizAdapter.resolve
(stat + LRU + ``load_las_preview``). On a cold cache without the native LAS
hook that is seconds of parse work; it used to run inside the
「加载连井剖面」click slot (#659).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal


class CorrelationLoadWorker(QObject):
    """Run ``load_correlation_wells`` off the GUI thread.

    Emits ``finished((logs, names, loaded_ids, warnings))``, ``failed(message)``,
    or ``cancelled()``.
    """

    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        project,
        resource_ids: list[str],
        *,
        max_wells: int = 8,
        seq: int = 0,
        loader=None,
        parent=None,
    ):
        super().__init__(parent)
        self.project = project
        self.resource_ids = list(resource_ids)
        self.max_wells = int(max_wells)
        self.seq = int(seq)
        self._loader = loader
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        if self._cancel_event.is_set():
            self.cancelled.emit()
            return
        try:
            loader = self._loader
            if loader is None:
                from paleo_workbench.workflow.stratigraphy_correlation import (
                    load_correlation_wells as loader,
                )

            result = loader(
                self.project,
                resource_ids=self.resource_ids,
                max_wells=self.max_wells,
            )
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            if self._cancel_event.is_set():
                self.cancelled.emit()
                return
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        if self._cancel_event.is_set():
            self.cancelled.emit()
            return
        self.finished.emit(result)
