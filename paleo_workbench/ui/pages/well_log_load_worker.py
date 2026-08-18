"""Background worker for single LAS/XML parse off the GUI thread (#842).

The #659 async-LAS fix only covered the correlation page; the visualization
page and the well-log prediction panel still resolved ``well_log`` refs
synchronously on the GUI thread (``VizAdapter.resolve`` →
``load_well_log_from_path``), freezing the event loop for seconds on cold
multi-MB LAS files. This worker mirrors the ``CorrelationLoadWorker`` pattern:
parse on an owned thread, deliver the :class:`VizPayload` back via a queued
signal, and let the page/panel keep the LRU-hit synchronous fast path.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal


class WellLogLoadWorker(QObject):
    """Resolve one ``well_log`` VizRef off the GUI thread."""

    finished = Signal(object)  # VizPayload
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, ref, project, *, adapter=None, parent=None):
        super().__init__(parent)
        self.ref = ref
        self.project = project
        self._adapter = adapter
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        if self._cancel_event.is_set():
            self.cancelled.emit()
            return
        try:
            adapter = self._adapter
            if adapter is None:
                from paleo_workbench.viz.adapter import VizAdapter

                adapter = VizAdapter()
            payload = adapter.resolve(self.ref, self.project)
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            if self._cancel_event.is_set():
                self.cancelled.emit()
                return
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        if self._cancel_event.is_set():
            self.cancelled.emit()
            return
        self.finished.emit(payload)