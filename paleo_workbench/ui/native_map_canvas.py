"""Qt host canvas that composes native scalar rasters with contours and sample points."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from paleo_workbench.ui import tokens

__all__ = ["NativeMapCanvas"]


class NativeMapCanvas(QWidget):
    """Native Qt map canvas with cached scalar images and pointer pan/zoom."""

    def __init__(self, scene: Any | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("NativeMapCanvas")
        self.setMinimumSize(240, 180)
        self.setMouseTracking(True)
        self._scene = None
        self._view_extent = (0.0, 0.0, 1.0, 1.0)
        self._image_cache: dict[str, tuple[tuple[int, int], QImage]] = {}
        self._last_drag_pos: QPointF | None = None
        self._scene_change_listener = self.update
        if scene is not None:
            self.set_scene(scene)

    @property
    def scene(self):
        return self._scene

    @property
    def view_extent(self) -> tuple[float, float, float, float]:
        return self._view_extent

    def set_scene(self, scene) -> None:
        if self._scene is not None:
            self._scene.remove_change_listener(self._scene_change_listener)
        self._scene = scene
        self._scene.add_change_listener(self._scene_change_listener)
        self._image_cache.clear()
        self.fit_to_scene()
        self.update()

    def fit_to_scene(self) -> None:
        if self._scene is None:
            self._view_extent = (0.0, 0.0, 1.0, 1.0)
            return
        xmin, ymin, xmax, ymax = self._scene.extent()
        dx = xmax - xmin
        dy = ymax - ymin
        if dx <= 0.0 or dy <= 0.0:
            self._view_extent = (0.0, 0.0, 1.0, 1.0)
            return
        margin = 0.04
        self._view_extent = (
            xmin - dx * margin,
            ymin - dy * margin,
            xmax + dx * margin,
            ymax + dy * margin,
        )

    def set_view_extent(self, extent: tuple[float, float, float, float]) -> None:
        xmin, ymin, xmax, ymax = (float(value) for value in extent)
        if not (xmax > xmin and ymax > ymin):
            raise ValueError("view extent must have positive width and height")
        self._view_extent = (xmin, ymin, xmax, ymax)
        self.update()

    def zoom_to_extent(self, extent: tuple[float, float, float, float]) -> None:
        self.set_view_extent(extent)

    def zoom_by(self, factor: float, center: tuple[float, float] | None = None) -> None:
        if factor <= 0.0:
            raise ValueError("zoom factor must be positive")
        xmin, ymin, xmax, ymax = self._view_extent
        cx, cy = center or ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
        self.set_view_extent(
            (
                cx + (xmin - cx) * factor,
                cy + (ymin - cy) * factor,
                cx + (xmax - cx) * factor,
                cy + (ymax - cy) * factor,
            )
        )

    def pan_by_pixels(self, dx: float, dy: float) -> None:
        xmin, ymin, xmax, ymax = self._view_extent
        width = max(1, self.width())
        height = max(1, self.height())
        world_dx = -float(dx) * (xmax - xmin) / width
        world_dy = float(dy) * (ymax - ymin) / height
        self.set_view_extent((xmin + world_dx, ymin + world_dy, xmax + world_dx, ymax + world_dy))

    def _world_to_screen(self, x: float, y: float) -> QPointF:
        xmin, ymin, xmax, ymax = self._view_extent
        return QPointF(
            (x - xmin) * self.width() / (xmax - xmin),
            self.height() - (y - ymin) * self.height() / (ymax - ymin),
        )

    def _screen_to_world(self, point: QPointF) -> tuple[float, float]:
        xmin, ymin, xmax, ymax = self._view_extent
        return (
            xmin + point.x() * (xmax - xmin) / max(1, self.width()),
            ymin + (self.height() - point.y()) * (ymax - ymin) / max(1, self.height()),
        )

    def _image_for(self, layer_id: str) -> QImage:
        assert self._scene is not None
        key = self._scene.scalar_raster_key(layer_id)
        cached = self._image_cache.get(layer_id)
        if cached is not None and cached[0] == key:
            return cached[1]
        rgba = self._scene.raster_rgba(layer_id)
        image = QImage(
            rgba.data,
            rgba.shape[1],
            rgba.shape[0],
            rgba.shape[1] * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        self._image_cache[layer_id] = (key, image)
        return image

    @staticmethod
    def _color(values: tuple[int, int, int, int]) -> QColor:
        return QColor(*values)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens.BG_SEARCH))
        if self._scene is None:
            painter.end()
            return
        for layer in self._scene.registry.layers():
            if not self._scene.registry.is_effectively_visible(layer.id, 1.0):
                continue
            scalar = self._scene.scalar_layer(layer.id)
            painter.save()
            painter.setOpacity(layer.opacity)
            if scalar is not None:
                xmin, ymin, xmax, ymax = layer.extent
                lower_left = self._world_to_screen(xmin, ymin)
                upper_right = self._world_to_screen(xmax, ymax)
                target = QRectF(upper_right, lower_left).normalized()
                painter.drawImage(target, self._image_for(layer.id))
            contour = self._scene.contour_geometry(layer.id)
            if contour is not None:
                painter.setPen(QPen(self._color(contour.color), contour.width))
                for path in contour.paths:
                    if len(path) < 2:
                        continue
                    for start, end in zip(path, path[1:]):
                        painter.drawLine(
                            self._world_to_screen(*start), self._world_to_screen(*end)
                        )
            points = self._scene.point_geometry(layer.id)
            if points is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._color(points.color))
                for x, y in points.points:
                    center = self._world_to_screen(x, y)
                    painter.drawEllipse(center, points.radius, points.radius)
            painter.restore()
        painter.end()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.zoom_by(0.8 if delta > 0 else 1.25, self._screen_to_world(event.position()))
            event.accept()
            return
        event.ignore()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_drag_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._last_drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position() - self._last_drag_pos
            self.pan_by_pixels(delta.x(), delta.y())
            self._last_drag_pos = event.position()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._last_drag_pos is not None:
            self._last_drag_pos = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
