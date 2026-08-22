"""Off-GUI unified-map PNG export (throwaway Fallback backend + OwnedWorkerJob)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPainter

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapRenderSnapshot,
)
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.unified_map_canvas import (
    UnifiedMapCanvas,
    paint_map_decorations,
)


@dataclass(frozen=True, slots=True)
class MapExportSpec:
    snapshot: MapRenderSnapshot
    extent: tuple[float, float, float, float]
    width: int
    height: int
    dpi: float
    decorations: Mapping[str, Any]
    path: str
    # #923: True when the LIVE canvas backend is the QGIS renderer, so the
    # worker must interpret the same renderer payloads instead of the legacy
    # painter vocabulary (which silently drops qgis_style.renderer_xml).
    prefer_native_renderer: bool = False


def unified_map_canvas_from(widget: object) -> UnifiedMapCanvas | None:
    """Return the UnifiedMapCanvas on ``widget`` or a common host wrapper."""
    if isinstance(widget, UnifiedMapCanvas):
        return widget
    for name in ("canvas", "unified_canvas", "widget"):
        inner = getattr(widget, name, None)
        if isinstance(inner, UnifiedMapCanvas):
            return inner
    return None


def snapshot_map_export(
    canvas: UnifiedMapCanvas,
    path: str | Path,
    *,
    width: int = 2400,
    height: int | None = None,
    dpi: float = 300.0,
) -> MapExportSpec:
    """Copy backend inputs on the GUI thread for a throwaway worker render."""
    extent = tuple(float(value) for value in canvas.view_extent)
    if len(extent) != 4:
        raise ValueError("view extent must contain four values")
    if height is None:
        xmin, ymin, xmax, ymax = extent
        if xmax > xmin and ymax > ymin:
            height = max(64, min(16000, round(int(width) * (ymax - ymin) / (xmax - xmin))))
        else:
            height = 1600
    if int(width) < 1 or int(height) < 1:
        raise ValueError("export size must be positive")
    provider = getattr(canvas, "_overlay_provider", None)
    state = provider() if provider is not None else {}
    decorations = dict((state or {}).get("decorations") or {})
    backend = getattr(canvas, "backend", None)
    return MapExportSpec(
        snapshot=canvas.backend._snapshot,
        extent=(extent[0], extent[1], extent[2], extent[3]),
        width=int(width),
        height=int(height),
        dpi=float(dpi),
        decorations=decorations,
        path=str(path),
        prefer_native_renderer=getattr(backend, "backend_name", "") == "qgis",
    )


def _render_frame_native(spec: MapExportSpec):
    """Render the snapshot through a throwaway QGIS backend on this thread.

    The bridge's ``render_sync`` blocks on ``waitForFinished()`` (no caller
    event loop needed), and every native object here is born and torn down on
    the calling worker thread, so there is no cross-thread QObject affinity.
    This keeps export on ONE style interpreter with the screen (#923): the
    legacy painter vocabulary cannot express qgis_style.renderer_xml.
    """
    from paleo_workbench.mapping.map_render_backend import QgisMapRenderBackend

    backend = QgisMapRenderBackend()
    backend.initialize()
    try:
        backend.set_layer_snapshot(spec.snapshot)
        backend.set_extent(spec.extent)
        backend.set_output_size(spec.width, spec.height)
        backend.set_dpi(spec.dpi)
        return backend.render_sync()
    finally:
        try:
            backend.shutdown()
        except Exception:  # noqa: BLE001 — teardown must not mask the export
            pass


def render_and_save_map_export(spec: MapExportSpec) -> None:
    """Render the map body with the same interpreter as the screen (#923).

    When the live canvas is the QGIS renderer the frame comes from a throwaway
    QGIS backend on this worker thread; anything that fails (bridge missing,
    scalar pipeline unready, native error) degrades to the legacy painter
    path exactly as before.
    """
    frame = None
    if spec.prefer_native_renderer:
        try:
            frame = _render_frame_native(spec)
        except Exception as exc:  # noqa: BLE001 — degrade, never lose the export
            import logging

            logging.getLogger(__name__).warning(
                "PNG 导出回退到回退渲染器（QGIS 渲染失败：%s）", exc
            )
    if frame is None:
        backend = FallbackMapRenderBackend()
        backend.initialize()
        backend.set_layer_snapshot(spec.snapshot)
        backend.set_extent(spec.extent)
        backend.set_output_size(spec.width, spec.height)
        backend.set_dpi(spec.dpi)
        frame = backend.render_sync()
    image = QImage(
        frame.rgba,
        frame.width,
        frame.height,
        frame.stride,
        QImage.Format.Format_RGBA8888,
    ).copy()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint_map_decorations(
        painter,
        spec.decorations,
        width=spec.width,
        height=spec.height,
        extent=spec.extent,
        dpi=spec.dpi,
    )
    painter.end()
    if not image.save(spec.path, "PNG"):
        raise RuntimeError("could not save unified map PNG")


class MapExportWorker(QObject):
    """Run ``render_and_save_map_export`` off the GUI thread."""

    finished = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, spec: MapExportSpec, parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        if self._cancel_event.is_set():
            self.cancelled.emit()
            return
        try:
            render_and_save_map_export(self._spec)
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            if self._cancel_event.is_set():
                # A render that raised mid-way may have left partial bytes
                # on disk; a cancelled export must never keep them (#852).
                self._discard_partial()
                self.cancelled.emit()
                return
            # A FAILED (non-cancelled) render may equally have written a
            # partial file before raising — never leave it behind (#937-11,
            # #852 covered cancellation only).
            self._discard_partial()
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        if self._cancel_event.is_set():
            # The render completed and wrote its file while the user was
            # cancelling: drop the stale half-product instead of reporting
            # "cancelled" next to a completed-looking file (#852).
            self._discard_partial()
            self.cancelled.emit()
            return
        self.finished.emit(self._spec.path)

    def _discard_partial(self) -> None:
        """Remove the target file written by a cancelled render (best-effort)."""
        try:
            Path(self._spec.path).unlink(missing_ok=True)
        except OSError:
            pass


def start_map_export_job(
    job: OwnedWorkerJob,
    spec: MapExportSpec,
    *,
    on_finished,
    on_failed,
    on_cancelled=None,
) -> MapExportWorker:
    worker = MapExportWorker(spec)
    connections = [
        (worker.finished, on_finished),
        (worker.failed, on_failed),
    ]
    if on_cancelled is not None:
        connections.append((worker.cancelled, on_cancelled))
    job.start(
        worker,
        terminal_signals=(worker.finished, worker.failed, worker.cancelled),
        result_connections=tuple(connections),
        cancel=worker.cancel,
        target=spec.path,
    )
    return worker
