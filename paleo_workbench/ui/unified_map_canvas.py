"""Primary renderer-neutral map canvas with lightweight navigation behavior."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QWidget

from paleo_workbench.mapping.map_render_backend import (
    MapRenderBackend,
    MapRenderSnapshot,
    RenderFrame,
    create_map_render_backend,
)
from paleo_workbench.ui import tokens

__all__ = ["UnifiedMapCanvas"]


class UnifiedMapCanvas(QWidget):
    """One host canvas consuming frames from a ``MapRenderBackend``.

    Feature editing overlays are intentionally added above this widget in later slices;
    mouse navigation only changes viewport state and never rebuilds layer data.
    """

    backend_status_changed = Signal(str)
    frame_ready = Signal(object)
    extent_changed = Signal(tuple)

    def __init__(self, *, backend: MapRenderBackend | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("UnifiedMapCanvas")
        self.setMinimumSize(240, 180)
        self.setMouseTracking(True)
        self._backend = backend or create_map_render_backend()
        self._backend.initialize()
        self._view_extent = (0.0, 0.0, 1.0, 1.0)
        self._last_frame: RenderFrame | None = None
        self._image = QImage()
        self._drag_pos: QPointF | None = None
        self._space_pan = False
        self._poll = QTimer(self)
        self._poll.setInterval(15)
        self._poll.timeout.connect(self._take_completed_frame)
        self._publish_backend_status()

    @property
    def backend(self) -> MapRenderBackend:
        return self._backend

    @property
    def backend_status(self) -> str:
        return f"{self._backend.backend_name}: {self._backend.status}"

    @property
    def last_frame(self) -> RenderFrame | None:
        return self._last_frame

    @property
    def view_extent(self) -> tuple[float, float, float, float]:
        return self._view_extent

    def set_layer_snapshot(self, snapshot: MapRenderSnapshot) -> None:
        self._backend.set_layer_snapshot(snapshot)
        self._request_render()

    def set_extent(self, extent: tuple[float, float, float, float]) -> None:
        self._backend.set_extent(extent)
        self._view_extent = tuple(float(value) for value in extent)
        self.extent_changed.emit(self._view_extent)
        self._request_render()

    def zoom_by(self, factor: float, center: tuple[float, float] | None = None) -> None:
        if factor <= 0.0:
            raise ValueError("zoom factor must be positive")
        xmin, ymin, xmax, ymax = self._view_extent
        cx, cy = center or ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
        self.set_extent(
            (
                cx + (xmin - cx) * factor,
                cy + (ymin - cy) * factor,
                cx + (xmax - cx) * factor,
                cy + (ymax - cy) * factor,
            )
        )

    def pan_by_pixels(self, dx: float, dy: float) -> None:
        xmin, ymin, xmax, ymax = self._view_extent
        width, height = max(1, self.width()), max(1, self.height())
        world_dx = -float(dx) * (xmax - xmin) / width
        world_dy = float(dy) * (ymax - ymin) / height
        self.set_extent((xmin + world_dx, ymin + world_dy, xmax + world_dx, ymax + world_dy))

    def _request_render(self) -> None:
        self._backend.set_output_size(max(1, self.width()), max(1, self.height()))
        self._backend.request_render()
        self._poll.start()

    def _take_completed_frame(self) -> None:
        frame = self._backend.take_completed_frame()
        if frame is None:
            if not self._backend.render_active:
                self._poll.stop()
            return
        self._last_frame = frame
        self._image = QImage(
            frame.rgba,
            frame.width,
            frame.height,
            frame.stride,
            QImage.Format.Format_RGBA8888,
        ).copy()
        self.frame_ready.emit(frame)
        self.update()
        self._poll.stop()

    def _publish_backend_status(self) -> None:
        self.backend_status_changed.emit(self.backend_status)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.width() > 0 and self.height() > 0:
            self._request_render()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens.BG_SEARCH))
        if not self._image.isNull():
            painter.drawImage(self.rect(), self._image)
        painter.end()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.zoom_by(0.8 if delta > 0 else 1.25)
            event.accept()
            return
        event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_pan = True
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_pan = False
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton or (
            self._space_pan and event.button() == Qt.MouseButton.LeftButton
        ):
            self._drag_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None:
            delta = event.position() - self._drag_pos
            self.pan_by_pixels(delta.x(), delta.y())
            self._drag_pos = event.position()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and event.button() in {
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.LeftButton,
        }:
            self._drag_pos = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._poll.stop()
        self._backend.shutdown()
        super().closeEvent(event)
