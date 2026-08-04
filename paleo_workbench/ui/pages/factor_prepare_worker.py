"""Background worker for factor-map batch interpolation (ISS-PREP-01).

Heavy grid math runs off the GUI thread. The worker mutates a dedicated
project reference; the preparation page must not touch that project until
``finished`` / ``failed`` is received.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from geoviz import CancellationToken, JobCancelled
from paleo_workbench.workflow.factor_interpolation import batch_prepare_factor_maps


@dataclass(frozen=True)
class FactorPrepareResult:
    factor_map_tasks: list
    count: int


class FactorPrepareWorker(QObject):
    """Run ``batch_prepare_factor_maps`` and report success or error text."""

    finished = Signal(int)  # number of tasks prepared
    completed = Signal(object)  # FactorPrepareResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        project,
        method: str = "IDW",
        parent=None,
        *,
        cancellation_token: CancellationToken | None = None,
    ):
        super().__init__(parent)
        self._project = project.model_copy(deep=True)
        self._method = method or "IDW"
        self._cancellation_token = cancellation_token or CancellationToken()

    def run(self) -> None:
        try:
            self._cancellation_token.raise_if_cancelled()
            prepared = batch_prepare_factor_maps(
                self._project,
                method=self._method,
                cancellation_token=self._cancellation_token,
            )
            self._cancellation_token.raise_if_cancelled()
            self.completed.emit(
                FactorPrepareResult(
                    factor_map_tasks=list(self._project.factor_map_tasks),
                    count=len(prepared),
                )
            )
            self.finished.emit(len(prepared))
        except JobCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 — surface any prepare failure to UI
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
