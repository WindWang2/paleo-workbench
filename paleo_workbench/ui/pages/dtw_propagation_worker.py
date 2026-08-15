"""Background worker for CrossWell DTW pick propagation (off the GUI thread).

The engine's ``propagate_pick_via_dtw`` runs banded DTW per target well on
full-resolution curves with a default band of ``max(20, n // 4)`` — a 50k-
sample LAS would need a ~10 GB cost matrix and froze the UI thread for
seconds per well (C10). This worker runs the propagation on an
:class:`~paleo_workbench.ui.owned_worker_job.OwnedWorkerJob` thread,
cap-passes a bounded ``band_radius`` so the cost matrix stays within a cell
budget, reports per-well progress, and supports cooperative cancellation
(the progress callback raises ``JobCancelled`` when the cancel flag is set).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

# Upper bound on the engine's banded-DTW cost matrix cells
# (n x (2*band+1) float64 = 8 bytes/cell). The engine default band
# (max(20, n//4)) allocates 0.4/10/40 GB at 10k/50k/100k samples; capping
# the band keeps the peak under ~33 MB while preserving the original band
# for typical wells (<= 2k samples). Mirrors the tighter 1e6-cell budget
# used by DTWLogMatcher for the workbench's own matcher.
_MAX_DTW_CELLS = 4_000_000


def bounded_dtw_band(n_samples: int, band_radius: int | None = None) -> int:
    """Cap the DTW band so the cost matrix stays within ``_MAX_DTW_CELLS``.

    ``n_samples`` should be the largest curve length involved in the
    propagation (an over-estimate only makes the band more conservative).
    """
    n = max(1, int(n_samples))
    if band_radius is None:
        band_radius = max(20, n // 4)
    cap = max(20, (_MAX_DTW_CELLS // n - 1) // 2)
    return min(max(1, int(band_radius)), cap)


class DtwPropagationWorker(QObject):
    """Run ``canvas.propagate_pick_via_dtw`` off the GUI thread.

    Emits per-well ``progress(done, total)``, ``finished(created_ids)`` with
    the list of new ghost-pick ids, ``failed(message)``, or ``cancelled()``.
    """

    progress = Signal(int, int)
    finished = Signal(object)  # list[str] created pick ids
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        canvas,
        *,
        ref_well: str,
        ref_depth: float,
        formation: str,
        n_samples: int,
        band_radius: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._canvas = canvas
        self._ref_well = ref_well
        self._ref_depth = float(ref_depth)
        self._formation = formation
        self._n_samples = int(n_samples)
        self._band_radius = band_radius
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request cooperative cancellation (checked at each well boundary)."""
        self._cancel_event.set()

    def run(self) -> None:
        try:
            if self._cancel_event.is_set():
                self.cancelled.emit()
                return
            band = bounded_dtw_band(self._n_samples, self._band_radius)

            def _on_progress(done: int, total: int) -> None:
                if self._cancel_event.is_set():
                    from geoviz import JobCancelled

                    raise JobCancelled("DTW propagation cancelled")
                self.progress.emit(done, total)

            created = self._canvas.propagate_pick_via_dtw(
                self._ref_well,
                self._ref_depth,
                self._formation,
                band_radius=band,
                progress_callback=_on_progress,
            )
            self.finished.emit(created)
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            try:
                from geoviz import JobCancelled
            except Exception:  # pragma: no cover - geoviz always present here
                JobCancelled = None
            if JobCancelled is not None and isinstance(exc, JobCancelled):
                self.cancelled.emit()
            else:
                self.failed.emit(f"{exc.__class__.__name__}: {exc}")
