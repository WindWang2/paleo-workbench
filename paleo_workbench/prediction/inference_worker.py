"""Background worker for ModelRegistry-backed inference runs.

Runs :func:`paleo_workbench.prediction.inference_service.execute_run` off the
GUI thread following the codebase's OwnedWorkerJob convention (see
``ui/pages/factor_prepare_worker.py``). The service mutates the shared
catalog; the page must only read it until ``completed`` / ``failed`` arrives.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from paleo_workbench.prediction.inference_service import execute_run


class InferenceWorker(QObject):
    """Execute one inference run and report its outcome payload."""

    completed = Signal(object)  # {"run", "result", "model", "model_version", ...}
    failed = Signal(str)
    terminal = Signal()

    def __init__(self, service, run_id: str, parent=None):
        super().__init__(parent)
        self._service = service
        self._run_id = run_id

    def run(self) -> None:
        try:
            payload = execute_run(self._service, self._run_id)
            self.completed.emit(payload)
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
        finally:
            self.terminal.emit()


__all__ = ["InferenceWorker"]
