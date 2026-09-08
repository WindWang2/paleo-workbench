"""Background worker for single LAS/XML parse off the GUI thread (#842, #1224).

The #659 async-LAS fix only covered the correlation page; the visualization
page and the well-log prediction panel still resolved ``well_log`` refs
synchronously on the GUI thread (``VizAdapter.resolve`` →
``load_well_log_from_path``), freezing the event loop for seconds on cold
multi-MB LAS files. This worker mirrors the ``CorrelationLoadWorker`` pattern:
parse on an owned thread, deliver the :class:`VizPayload` back via a queued
signal, and let the page/panel keep the LRU-hit synchronous fast path.

V8 M8 (#1224) honest cancellation semantics:

* the load pipeline takes a cooperative token with checkpoints BEFORE the
  parse and BETWEEN the parse and the unit-inspect phases
  (:class:`paleo_workbench.viz.well_log_load.WellLogLoadCancelled`);
* the engine's single-call LAS/XML parse itself is NON-INTERRUPTIBLE — the
  worker never pretends otherwise: cancelling during that phase emits
  ``cancelling()`` (the honest "正在结束" hint) so the UI tells the truth
  instead of showing a fake "已取消" while the thread keeps burning;
* a late result (cancel fired during the parse) is DISCARDED —
  ``cancelled`` is emitted, ``finished`` never fires for it;
* the slot is released exactly when ``run()`` returns — before-parse
  cancellations release it without running the parse at all.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal


class WellLogLoadWorker(QObject):
    """Resolve one ``well_log`` VizRef off the GUI thread."""

    finished = Signal(object)  # VizPayload
    failed = Signal(str)
    cancelled = Signal()
    #: Emitted ONCE when cancel() lands while the non-interruptible parse is
    #: still running — the honest "正在结束" hint (#1224).
    cancelling = Signal()

    def __init__(self, ref, project, *, adapter=None, parent=None):
        super().__init__(parent)
        self.ref = ref
        self.project = project
        self._adapter = adapter
        self._cancel_event = threading.Event()
        self._parse_started = False

    def cancel(self) -> None:
        was_set = self._cancel_event.is_set()
        self._cancel_event.set()
        if not was_set and self._parse_started:
            # Cancel landed mid-parse: the parse cannot stop — tell the UI
            # the request is ending while the thread still occupies the slot.
            self.cancelling.emit()

    def run(self) -> None:
        if self._cancel_event.is_set():
            self.cancelled.emit()
            return
        self._parse_started = True
        try:
            adapter = self._adapter
            if adapter is None:
                from paleo_workbench.viz.adapter import VizAdapter

                adapter = VizAdapter()
            payload = adapter.resolve(
                self.ref, self.project, cancel=self._cancel_event.is_set
            )
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            from paleo_workbench.viz.well_log_load import WellLogLoadCancelled

            if isinstance(exc, WellLogLoadCancelled) or self._cancel_event.is_set():
                self.cancelled.emit()
                return
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        finally:
            # terminal on EVERY path — a post-run cancel() (e.g. teardown)
            # must not emit a spurious `cancelling` for a finished worker
            # (review R1-P2).
            self._parse_started = False
        if self._cancel_event.is_set():
            # Late result discarded — the request was cancelled while the
            # parse ran; the payload never reaches the UI (#1224 contract:
            # old results are never committed).
            self.cancelled.emit()
            return
        self.finished.emit(payload)