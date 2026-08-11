"""Primary renderer-neutral map canvas with GIS navigation and edit overlays."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPainterPath, QPen, QPolygonF, QWheelEvent
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
    map_position_changed = Signal(tuple)
    tool_operation = Signal()

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
        self._tool_controller = None
        self._overlay_provider: Callable[[], Mapping[str, Any]] | None = None
        self._cursor_map: tuple[float, float] | None = None
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

    def set_map_tool_controller(self, controller) -> None:
        """Attach the one exclusive host map-tool controller.

        The controller intentionally remains framework-neutral; this canvas converts
        pointer coordinates and paints feedback, but does not become edit authority.
        """
        self._tool_controller = controller

    def set_overlay_provider(self, provider: Callable[[], Mapping[str, Any]] | None) -> None:
        """Set a cheap overlay snapshot producer (selection/rubber band/snap mark)."""
        self._overlay_provider = provider
        self.update()

    @property
    def map_units_per_pixel(self) -> float:
        xmin, ymin, xmax, ymax = self._view_extent
        return max((xmax - xmin) / max(1, self.width()), (ymax - ymin) / max(1, self.height()))

    def screen_to_map(self, point: QPointF) -> tuple[float, float]:
        xmin, ymin, xmax, ymax = self._view_extent
        return (
            xmin + point.x() * (xmax - xmin) / max(1, self.width()),
            ymax - point.y() * (ymax - ymin) / max(1, self.height()),
        )

    def map_to_screen(self, point: tuple[float, float]) -> QPointF:
        xmin, ymin, xmax, ymax = self._view_extent
        return QPointF(
            (float(point[0]) - xmin) * self.width() / (xmax - xmin),
            (ymax - float(point[1])) * self.height() / (ymax - ymin),
        )

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
        self._paint_overlay(painter)
        painter.end()

    def _paint_overlay(self, painter: QPainter) -> None:
        provider = self._overlay_provider
        if provider is None:
            return
        state = provider() or {}
        selected = tuple(state.get("selected_features") or ())
        if selected:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor("#ffe066"), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for feature in selected:
                geometry = getattr(feature, "geometry", None)
                if geometry is None and isinstance(feature, Mapping):
                    geometry = feature.get("geometry")
                self._paint_geometry_outline(painter, geometry)
            painter.restore()
        points = list(state.get("capture_points") or ())
        if points:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor("#53d8fb"), 1.5, Qt.PenStyle.DashLine))
            preview = points + ([self._cursor_map] if self._cursor_map is not None else [])
            screen_points = [self.map_to_screen((float(point[0]), float(point[1]))) for point in preview]
            if len(screen_points) >= 2:
                painter.drawPolyline(QPolygonF(screen_points))
            painter.setBrush(QColor("#53d8fb"))
            for point in screen_points[: len(points)]:
                painter.drawEllipse(point, 3.5, 3.5)
            painter.restore()
        snap = state.get("snap_point")
        if snap is not None:
            try:
                center = self.map_to_screen((float(snap[0]), float(snap[1])))
            except (TypeError, ValueError, IndexError):
                return
            painter.save()
            painter.setPen(QPen(QColor("#ff6b6b"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 6.0, 6.0)
            painter.drawLine(center + QPointF(-8, 0), center + QPointF(8, 0))
            painter.drawLine(center + QPointF(0, -8), center + QPointF(0, 8))
            painter.restore()
        self._paint_decorations(painter, state.get("decorations") or {})

    def _paint_decorations(
        self, painter: QPainter, decorations: Mapping[str, Any], *, width: int | None = None,
        height: int | None = None,
    ) -> None:
        canvas_width = self.width() if width is None else int(width)
        canvas_height = self.height() if height is None else int(height)
        elements = {str(item) for item in decorations.get("elements") or ()}
        title = str(decorations.get("title") or "")
        if title and (not elements or "标题栏" in elements or "title" in elements):
            painter.save()
            painter.setPen(QColor("#f8f9fa"))
            font = painter.font()
            font.setPointSize(max(10, font.pointSize() + 3))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(14, 10, canvas_width - 28, canvas_height - 20), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, title)
            painter.restore()
        if not elements or "比例尺" in elements or "scale_bar" in elements:
            width_units = self._view_extent[2] - self._view_extent[0]
            target_units = width_units * 0.2
            if target_units > 0.0:
                pixels = max(35.0, canvas_width * 0.2)
                y = canvas_height - 24.0
                painter.save()
                painter.setPen(QPen(QColor("#ffffff"), 2.0))
                painter.drawLine(QPointF(16, y), QPointF(16 + pixels, y))
                painter.drawLine(QPointF(16, y - 4), QPointF(16, y + 4))
                painter.drawLine(QPointF(16 + pixels, y - 4), QPointF(16 + pixels, y + 4))
                painter.drawText(QPointF(16, y - 7), f"{target_units:.3g} map units")
                painter.restore()
        if not elements or "指北针" in elements or "north_arrow" in elements:
            painter.save()
            center = QPointF(canvas_width - 28, 37)
            painter.setPen(QPen(QColor("#ffffff"), 1.5))
            painter.setBrush(QColor("#343a40"))
            painter.drawPolygon(QPolygonF([center + QPointF(0, -18), center + QPointF(-6, 10), center + QPointF(0, 5), center + QPointF(6, 10)]))
            painter.drawText(center + QPointF(-5, -22), "N")
            painter.restore()
        if (not elements or "图例" in elements or "legend" in elements) and decorations.get("legend_items"):
            items = [str(item) for item in decorations["legend_items"]][:8]
            painter.save()
            painter.setPen(QPen(QColor("#dfe6ee"), 1.0))
            painter.setBrush(QColor(24, 28, 34, 210))
            height = 10 + 18 * len(items)
            rect = QRectF(canvas_width - 180, canvas_height - height - 16, 164, height)
            painter.drawRect(rect)
            for index, item in enumerate(items):
                painter.setBrush(QColor("#6c8ebf"))
                y = rect.top() + 14 + index * 18
                painter.drawRect(rect.left() + 8, y - 8, 9, 9)
                painter.setPen(QColor("#f8f9fa"))
                painter.drawText(QPointF(rect.left() + 23, y), item)
            painter.restore()

    def render_export_image(self, width: int, height: int, *, dpi: float = 300.0) -> QImage:
        """Synchronously render the same backend/composition at export resolution."""
        if width < 1 or height < 1:
            raise ValueError("export size must be positive")
        if self._backend.render_active:
            self._backend.cancel_render()
        previous_size = self._backend._output_size
        previous_dpi = self._backend._dpi
        try:
            self._backend.set_output_size(int(width), int(height))
            self._backend.set_dpi(float(dpi))
            frame = self._backend.render_sync()
            image = QImage(
                frame.rgba, frame.width, frame.height, frame.stride,
                QImage.Format.Format_RGBA8888,
            ).copy()
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            state = self._overlay_provider() if self._overlay_provider is not None else {}
            self._paint_decorations(
                painter, (state or {}).get("decorations") or {}, width=width, height=height
            )
            painter.end()
            return image
        finally:
            self._backend.set_output_size(*previous_size)
            self._backend.set_dpi(previous_dpi)

    def export_png(self, path: str, *, width: int = 2400, height: int = 1600, dpi: float = 300.0) -> None:
        image = self.render_export_image(width, height, dpi=dpi)
        if not image.save(path, "PNG"):
            raise RuntimeError("could not save unified map PNG")

    def _paint_geometry_outline(self, painter: QPainter, geometry: object) -> None:
        if not isinstance(geometry, Mapping):
            return
        geometry_type = str(geometry.get("type") or "")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Point":
            try:
                painter.drawEllipse(self.map_to_screen((float(coordinates[0]), float(coordinates[1]))), 6.0, 6.0)
            except (TypeError, ValueError, IndexError):
                pass
            return
        if geometry_type == "MultiPoint" and isinstance(coordinates, (list, tuple)):
            for point in coordinates:
                self._paint_geometry_outline(painter, {"type": "Point", "coordinates": point})
            return
        if geometry_type in {"LineString", "Polygon"} and isinstance(coordinates, (list, tuple)):
            lines = coordinates if geometry_type == "Polygon" else (coordinates,)
            for line in lines:
                if not isinstance(line, (list, tuple)):
                    continue
                points: list[QPointF] = []
                for point in line:
                    try:
                        points.append(self.map_to_screen((float(point[0]), float(point[1]))))
                    except (TypeError, ValueError, IndexError):
                        continue
                if len(points) >= 2:
                    painter.drawPolyline(QPolygonF(points))
            return
        if geometry_type in {"MultiLineString", "MultiPolygon"} and isinstance(coordinates, (list, tuple)):
            child_type = "LineString" if geometry_type == "MultiLineString" else "Polygon"
            for child in coordinates:
                self._paint_geometry_outline(painter, {"type": child_type, "coordinates": child})

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
        key_name = "escape" if event.key() == Qt.Key.Key_Escape else (event.text() or event.key().name)
        if self._tool_controller is not None and self._tool_controller.key_press(key_name):
            self.tool_operation.emit()
            self.update()
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
        if self._tool_controller is not None and self._tool_controller.active_tool is not None:
            tool = self._tool_controller.active_tool
            if getattr(tool, "tool_id", "") == "pan" and event.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
            point = self.screen_to_map(event.position())
            handled = tool.mouse_press(
                point,
                button=self._button_name(event.button()),
                modifiers=self._modifier_names(event.modifiers()),
            )
            if handled:
                self.tool_operation.emit()
                self.update()
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
        self._cursor_map = self.screen_to_map(event.position())
        self.map_position_changed.emit(self._cursor_map)
        if self._tool_controller is not None and self._tool_controller.active_tool is not None:
            handled = self._tool_controller.active_tool.mouse_move(
                self._cursor_map, modifiers=self._modifier_names(event.modifiers())
            )
            if handled:
                self.tool_operation.emit()
        self.update()
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
        if self._tool_controller is not None and self._tool_controller.active_tool is not None:
            point = self.screen_to_map(event.position())
            handled = self._tool_controller.active_tool.mouse_release(
                point,
                button=self._button_name(event.button()),
                modifiers=self._modifier_names(event.modifiers()),
            )
            if handled:
                self.tool_operation.emit()
                self.update()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._tool_controller is not None and self._tool_controller.active_tool is not None:
            handled = self._tool_controller.active_tool.double_click(
                self.screen_to_map(event.position()),
                modifiers=self._modifier_names(event.modifiers()),
            )
            if handled:
                self.tool_operation.emit()
                self.update()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _button_name(button: Qt.MouseButton) -> str:
        return {
            Qt.MouseButton.LeftButton: "left",
            Qt.MouseButton.RightButton: "right",
            Qt.MouseButton.MiddleButton: "middle",
        }.get(button, "other")

    @staticmethod
    def _modifier_names(modifiers: Qt.KeyboardModifiers) -> set[str]:
        names: set[str] = set()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            names.add("ctrl")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            names.add("shift")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            names.add("alt")
        return names

    def closeEvent(self, event) -> None:  # noqa: N802
        self._poll.stop()
        self._backend.shutdown()
        super().closeEvent(event)
