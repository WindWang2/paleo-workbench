"""Latest-revision asynchronous raster delivery for native scalar-map layers.

The native ``ScalarGridLayer`` remains the only pixel cache.  This coordinator only
owns in-flight work: each completed NumPy snapshot is handed to the Qt canvas, which
accepts it only when the scalar revision and canvas scene epoch still match.  It never
stores a second scientific grid or invokes interpolation.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

__all__ = ["NativeRasterRequestController", "NativeRasterWorker"]


class _RenderCancellation:
    """Tiny thread-safe cancellation token for a non-interruptible native render."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class _Request:
    scene_epoch: int
    layer_id: str
    raster_key: tuple[int, int]
    scalar: Any


class NativeRasterWorker(QObject):
    """Rasterize one native scalar layer away from the GUI thread."""

    finished = Signal(object, object)
    failed = Signal(object, str)
    cancelled = Signal(object)
    terminal = Signal()

    def __init__(self, request: _Request, token: _RenderCancellation, parent=None):
        super().__init__(parent)
        self._request = request
        self._token = token

    @Slot()
    def run(self) -> None:
        try:
            if self._token.cancelled:
                self.cancelled.emit(self._request)
                return
            # The pybind method releases the GIL while C++ owns raster/cache work.
            rgba = self._request.scalar.rasterize()
            if self._token.cancelled:
                self.cancelled.emit(self._request)
                return
            self.finished.emit(self._request, rgba)
        except Exception as exc:  # noqa: BLE001 - relay native errors to the host
            self.failed.emit(self._request, f"{exc.__class__.__name__}: {exc}")
        finally:
            self.terminal.emit()


class NativeRasterRequestController(QObject):
    """Queue one worker at a time while retaining the latest revision per layer.

    Several scalar layers may be visible simultaneously, so a new request for one
    layer does not discard another layer's useful in-flight render.  A changed revision
    for the *same* layer cooperatively cancels delivery and replaces the queued request.
    """

    raster_ready = Signal(object, object)
    raster_failed = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._job = OwnedWorkerJob(self)
        self._job.released.connect(self._on_released)
        self._active: _Request | None = None
        self._pending: OrderedDict[str, _Request] = OrderedDict()
        self._desired: dict[str, _Request] = {}
        self._shutdown = False

    @property
    def is_running(self) -> bool:
        return self._job.is_running

    @staticmethod
    def _same_request(left: _Request | None, right: _Request) -> bool:
        return (
            left is not None
            and left.scene_epoch == right.scene_epoch
            and left.layer_id == right.layer_id
            and left.raster_key == right.raster_key
            and left.scalar is right.scalar
        )

    def request(
        self,
        *,
        scene_epoch: int,
        layer_id: str,
        raster_key: tuple[int, int],
        scalar: Any,
    ) -> None:
        if self._shutdown:
            return
        request = _Request(
            int(scene_epoch), str(layer_id), tuple(int(v) for v in raster_key), scalar
        )
        previous = self._desired.get(request.layer_id)
        if self._same_request(previous, request):
            return
        self._desired[request.layer_id] = request
        if self._active is None:
            self._start(request)
            return
        if self._active.layer_id == request.layer_id:
            # Native rasterization cannot be safely force-stopped. Cancellation means
            # suppressing delivery after its bounded current call returns.
            self._job.cancel()
        self._pending[request.layer_id] = request

    def invalidate(self) -> None:
        """Discard all queued/deliverable work after a canvas scene replacement."""
        self._desired.clear()
        self._pending.clear()
        if self._active is not None:
            self._job.cancel()

    def shutdown(self, wait_ms: int = 3_000) -> None:
        self._shutdown = True
        self.invalidate()
        self._job.shutdown(wait_ms)

    def _start(self, request: _Request) -> None:
        self._active = request
        token = _RenderCancellation()
        worker = NativeRasterWorker(request, token)
        self._job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.finished, self._on_finished),
                (worker.failed, self._on_failed),
            ),
            cancel=token.cancel,
            target=request,
        )

    @Slot(object, object)
    def _on_finished(self, request: _Request, rgba) -> None:
        if not self._shutdown and self._same_request(
            self._desired.get(request.layer_id), request
        ):
            self.raster_ready.emit(request, rgba)

    @Slot(object, str)
    def _on_failed(self, request: _Request, message: str) -> None:
        if not self._shutdown and self._same_request(
            self._desired.get(request.layer_id), request
        ):
            self.raster_failed.emit(request, message)

    @Slot()
    def _on_released(self) -> None:
        self._active = None
        if self._shutdown or not self._pending:
            return
        _layer_id, request = self._pending.popitem(last=False)
        if self._same_request(self._desired.get(request.layer_id), request):
            self._start(request)
        elif self._pending:
            self._on_released()
