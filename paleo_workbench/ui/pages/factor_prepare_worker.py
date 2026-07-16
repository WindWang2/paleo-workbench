"""Background worker for factor-map batch interpolation (ISS-PREP-01).

Heavy grid math runs off the GUI thread. The worker mutates a dedicated
project reference; the preparation page must not touch that project until
``finished`` / ``failed`` is received.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class FactorPrepareWorker(QObject):
    """Run ``batch_prepare_factor_maps`` and report success or error text."""

    finished = Signal(int)  # number of tasks prepared
    failed = Signal(str)

    def __init__(self, project, method: str = "IDW", parent=None):
        super().__init__(parent)
        self._project = project
        self._method = method or "IDW"

    def run(self) -> None:
        try:
            from paleo_workbench.workflow.factor_interpolation import (
                batch_prepare_factor_maps,
            )

            prepared = batch_prepare_factor_maps(self._project, method=self._method)
            self.finished.emit(len(prepared))
        except Exception as exc:  # noqa: BLE001 — surface any prepare failure to UI
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
