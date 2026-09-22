"""Background worker for factor-map batch interpolation (ISS-PREP-01 / Stage-5).

Heavy grid math runs off the GUI thread. The worker never deep-copies the whole
:class:`~paleo_workbench.project.models.ProjectDocument`; it builds a narrow
scientific :class:`FactorPrepareSnapshot` and stages
:class:`FactorPrepareBatchResult` DTOs for host-thread commit.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from geoviz import CancellationToken, JobCancelled
from paleo_workbench.workflow.factor_prepare_scheduler import (
    FactorPrepareBatchResult,
    FactorPrepareProgress,
    FactorPrepareSnapshot,
    build_prepare_snapshot,
    run_factor_prepare_schedule,
)

# Back-compat alias used by older tests / call sites.
FactorPrepareResult = FactorPrepareBatchResult


class FactorPrepareWorker(QObject):
    """Run the Stage-5 prepare schedule and report success or error text."""

    finished = Signal(int)  # number of tasks considered
    completed = Signal(object)  # FactorPrepareBatchResult
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(object)  # FactorPrepareProgress

    def __init__(
        self,
        project,
        method: str = "IDW",
        parent=None,
        *,
        cancellation_token: CancellationToken | None = None,
        generation: int = 0,
        force: bool = False,
        grid_n: int | None = None,
        power: float = 2.0,
        snapshot: FactorPrepareSnapshot | None = None,
    ):
        super().__init__(parent)
        # Prefer a pre-built snapshot (host thread) so fingerprint resolution
        # uses the same resolved scientific inputs as classification.
        if snapshot is not None:
            self._snapshot = snapshot
        else:
            from paleo_workbench.workflow.factor_interpolation import DEFAULT_GRID_N

            self._snapshot = build_prepare_snapshot(
                project,
                generation=generation,
                method=method or "IDW",
                grid_n=grid_n if grid_n is not None else DEFAULT_GRID_N,
                power=power,
                force=force,
            )
        self._method = method or "IDW"
        self._cancellation_token = cancellation_token or CancellationToken()

    def run(self) -> None:
        try:
            self._cancellation_token.raise_if_cancelled()

            def _on_progress(update: FactorPrepareProgress) -> None:
                self.progress.emit(update)

            result = run_factor_prepare_schedule(
                self._snapshot,
                cancellation_token=self._cancellation_token,
                progress=_on_progress,
            )
            self._cancellation_token.raise_if_cancelled()
            if result.cancelled:
                self.cancelled.emit()
                return
            self.completed.emit(result)
            self.finished.emit(result.count)
        except JobCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 — surface any prepare failure to UI
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
