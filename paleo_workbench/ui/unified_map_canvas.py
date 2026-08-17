"""Primary renderer-neutral map canvas with GIS navigation and edit overlays."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPainterPath, QPen, QPolygonF, QTransform, QWheelEvent
from PySide6.QtWidgets import QWidget

from paleo_workbench.mapping.map_render_backend import (
    fit_extent_to_aspect,
    MapRenderBackend,
    MapRenderSnapshot,
    RenderFrame,
    create_map_render_backend,
)
from paleo_workbench.ui import tokens

__all__ = ["UnifiedMapCanvas", "paint_map_decorations"]


def paint_map_decorations(
    painter: QPainter,
    decorations: Mapping[str, Any],
    *,
    width: int,
    height: int,
    extent: tuple[float, float, float, float],
    dpi: float | None = None,
) -> None:
    """Draw title / scale / north arrow / legend. ``dpi`` None keeps screen cosmetics."""
    canvas_width = int(width)
    canvas_height = int(height)
    # Export overlays scale cosmetic sizes (fonts, pen widths, glyphs) with
    # dpi/96 so a 300-dpi export matches the physical screen look; the
    # screen path (dpi=None) stays unchanged.
    dpi_scale = (float(dpi) / 96.0) if dpi else 1.0
    elements = {str(item) for item in decorations.get("elements") or ()}
    title = str(decorations.get("title") or "")
    if title and (not elements or "标题栏" in elements or "title" in elements):
        painter.save()
        painter.setPen(QColor("#f8f9fa"))
        font = painter.font()
        font.setPointSizeF(max(10, font.pointSize() + 3) * dpi_scale)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(14, 10, canvas_width - 28, canvas_height - 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            title,
        )
        painter.restore()
    if not elements or "比例尺" in elements or "scale_bar" in elements:
        width_units = extent[2] - extent[0]
        target_units = width_units * 0.2
        if target_units > 0.0:
            pixels = max(35.0, canvas_width * 0.2)
            y = canvas_height - 24.0
            painter.save()
            painter.setPen(QPen(QColor("#ffffff"), 2.0 * dpi_scale))
            painter.drawLine(QPointF(16, y), QPointF(16 + pixels, y))
            painter.drawLine(QPointF(16, y - 4 * dpi_scale), QPointF(16, y + 4 * dpi_scale))
            painter.drawLine(QPointF(16 + pixels, y - 4 * dpi_scale), QPointF(16 + pixels, y + 4 * dpi_scale))
            painter.drawText(QPointF(16, y - 7 * dpi_scale), f"{target_units:.3g} map units")
            painter.restore()
    if not elements or "指北针" in elements or "north_arrow" in elements:
        painter.save()
        center = QPointF(canvas_width - 28, 37)
        painter.setPen(QPen(QColor("#ffffff"), 1.5 * dpi_scale))
        painter.setBrush(QColor("#343a40"))
        painter.drawPolygon(QPolygonF([
            center + QPointF(0, -18 * dpi_scale),
            center + QPointF(-6 * dpi_scale, 10 * dpi_scale),
            center + QPointF(0, 5 * dpi_scale),
            center + QPointF(6 * dpi_scale, 10 * dpi_scale),
        ]))
        painter.drawText(center + QPointF(-5 * dpi_scale, -22 * dpi_scale), "N")
        painter.restore()
    if (not elements or "图例" in elements or "legend" in elements) and decorations.get("legend_items"):
        items = [str(item) for item in decorations["legend_items"]][:8]
        painter.save()
        painter.setPen(QPen(QColor("#dfe6ee"), 1.0 * dpi_scale))
        painter.setBrush(QColor(24, 28, 34, 210))
        box_height = 10 + 18 * len(items)
        rect = QRectF(canvas_width - 180, canvas_height - box_height - 16, 164, box_height)
        painter.drawRect(rect)
        for index, item in enumerate(items):
            painter.setBrush(QColor("#6c8ebf"))
            y = rect.top() + 14 + index * 18
            painter.drawRect(rect.left() + 8, y - 8, 9, 9)
            painter.setPen(QColor("#f8f9fa"))
            painter.drawText(QPointF(rect.left() + 23, y), item)
        painter.restore()


class UnifiedMapCanvas(QWidget):
    """One host canvas consuming frames from a ``MapRenderBackend``.

    Feature editing overlays are intentionally added above this widget in later slices;
    mouse navigation only changes viewport state and never rebuilds layer data.
    """

    backend_status_changed = Signal(str)
    frame_ready = Signal(object)
    extent_changed = Signal(tuple)
    map_position_changed = Signal(tuple)
    # Emitted when a tool operation is handled.  The boolean argument is True
    # only when the operation mutated document data (composition must resync);
    # pointer/selection feedback (measure hover, select clicks, zoom) emits
    # False so hosts repaint overlays without recomposing the whole document.
    tool_operation = Signal(bool)

    def __init__(self, *, backend: MapRenderBackend | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("UnifiedMapCanvas")
        self.setMinimumSize(240, 180)
        self.setMouseTracking(True)
        self._backend = backend or create_map_render_backend()
        self._backend.initialize()
        self._view_extent = (0.0, 0.0, 1.0, 1.0)
        self._extent_history: list[tuple[float, float, float, float]] = [self._view_extent]
        self._extent_history_index = 0
        self._last_frame: RenderFrame | None = None
        self._image = QImage()
        # QImage below borrows this immutable payload; retaining it in the GUI
        # object keeps the native pixels valid until the next delivered frame.
        self._image_buffer: bytes | None = None
        self._navigation_transform = QTransform()
        self._drag_pos: QPointF | None = None
        self._space_pan = False
        self._tool_controller = None
        self._overlay_provider: Callable[[], Mapping[str, Any]] | None = None
        self._cursor_map: tuple[float, float] | None = None
        self._poll = QTimer(self)
        self._poll.setSingleShot(True)
        self._poll.timeout.connect(self._take_completed_frame)
        self._poll_interval_ms = 0
        self._poll_count = 0
        self._empty_poll_count = 0
        self._navigation_render = QTimer(self)
        self._navigation_render.setSingleShot(True)
        self._navigation_render.setInterval(24)
        self._navigation_render.timeout.connect(self._request_render)
        self._render_request_count = 0
        self._frame_delivery_count = 0
        self._frame_bytes_delivered = 0
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

    @property
    def navigation_preview_active(self) -> bool:
        """Whether the previous frame is being transformed pending a fresh render."""
        return not self._navigation_transform.isIdentity()

    def frame_delivery_diagnostics(self) -> dict[str, int]:
        """Return local counters used to keep navigation delivery observable."""
        return {
            "render_requests": self._render_request_count,
            "frames_delivered": self._frame_delivery_count,
            "frame_bytes_delivered": self._frame_bytes_delivered,
            "polls": self._poll_count,
            "empty_polls": self._empty_poll_count,
        }

    def set_layer_snapshot(self, snapshot: MapRenderSnapshot) -> None:
        self._navigation_render.stop()
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

    def _active_tool_edits_data(self) -> bool:
        tool = self._tool_controller.active_tool if self._tool_controller is not None else None
        return bool(getattr(tool, "edits_data", False))

    def _fitted_extent(self) -> tuple[float, float, float, float]:
        """View extent letterboxed to the widget aspect (#522): uniform
        units-per-pixel so shapes keep their proportions at any size."""
        return fit_extent_to_aspect(
            self._view_extent, self.width(), self.height()
        )

    @property
    def map_units_per_pixel(self) -> float:
        xmin, ymin, xmax, ymax = self._fitted_extent()
        # Uniform after letterboxing; keep max() as a degenerate guard.
        return max((xmax - xmin) / max(1, self.width()), (ymax - ymin) / max(1, self.height()))

    def screen_to_map(self, point: QPointF) -> tuple[float, float]:
        xmin, ymin, xmax, ymax = self._fitted_extent()
        return (
            xmin + point.x() * (xmax - xmin) / max(1, self.width()),
            ymax - point.y() * (ymax - ymin) / max(1, self.height()),
        )

    def map_to_screen(self, point: tuple[float, float]) -> QPointF:
        xmin, ymin, xmax, ymax = self._fitted_extent()
        return QPointF(
            (float(point[0]) - xmin) * self.width() / (xmax - xmin),
            (ymax - float(point[1])) * self.height() / (ymax - ymin),
        )

    def set_extent(
        self, extent: tuple[float, float, float, float], *, record_history: bool = True,
        coalesce_history: bool = False,
    ) -> None:
        self._backend.set_extent(extent)
        self._view_extent = tuple(float(value) for value in extent)
        if record_history:
            if self._extent_history_index < len(self._extent_history) - 1:
                self._extent_history = self._extent_history[: self._extent_history_index + 1]
            if coalesce_history and self._extent_history:
                self._extent_history[-1] = self._view_extent
            elif self._extent_history[-1] != self._view_extent:
                self._extent_history.append(self._view_extent)
                if len(self._extent_history) > 100:
                    self._extent_history.pop(0)
                self._extent_history_index = len(self._extent_history) - 1
        self.extent_changed.emit(self._view_extent)
        if coalesce_history:
            self._request_navigation_render()
        else:
            self._navigation_render.stop()
            self._request_render()

    def zoom_by(
        self, factor: float, center: tuple[float, float] | None = None, *,
        coalesce_history: bool = False,
    ) -> None:
        if factor <= 0.0:
            raise ValueError("zoom factor must be positive")
        xmin, ymin, xmax, ymax = self._view_extent
        cx, cy = center or ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
        if not self._image.isNull():
            screen = self.map_to_screen((cx, cy))
            self._navigation_transform.translate(screen.x(), screen.y())
            self._navigation_transform.scale(1.0 / factor, 1.0 / factor)
            self._navigation_transform.translate(-screen.x(), -screen.y())
            self.update()
        self.set_extent(
            (
                cx + (xmin - cx) * factor,
                cy + (ymin - cy) * factor,
                cx + (xmax - cx) * factor,
                cy + (ymax - cy) * factor,
            ),
            coalesce_history=coalesce_history,
        )

    def pan_by_pixels(self, dx: float, dy: float) -> None:
        xmin, ymin, xmax, ymax = self._view_extent
        width, height = max(1, self.width()), max(1, self.height())
        world_dx = -float(dx) * (xmax - xmin) / width
        world_dy = float(dy) * (ymax - ymin) / height
        if not self._image.isNull():
            self._navigation_transform.translate(float(dx), float(dy))
            self.update()
        self.set_extent(
            (xmin + world_dx, ymin + world_dy, xmax + world_dx, ymax + world_dy),
            coalesce_history=True,
        )

    @property
    def can_previous_extent(self) -> bool:
        return self._extent_history_index > 0

    @property
    def can_next_extent(self) -> bool:
        return self._extent_history_index + 1 < len(self._extent_history)

    def previous_extent(self) -> bool:
        if not self.can_previous_extent:
            return False
        self._extent_history_index -= 1
        self.set_extent(self._extent_history[self._extent_history_index], record_history=False)
        return True

    def next_extent(self) -> bool:
        if not self.can_next_extent:
            return False
        self._extent_history_index += 1
        self.set_extent(self._extent_history[self._extent_history_index], record_history=False)
        return True

    def _screen_pixel_ratio(self) -> float:
        try:
            ratio = float(self.devicePixelRatioF())
        except Exception:
            ratio = 1.0
        return ratio if ratio > 0.0 else 1.0

    def _request_render(self) -> None:
        ratio = self._screen_pixel_ratio()
        width = max(1, int(round(self.width() * ratio)))
        height = max(1, int(round(self.height() * ratio)))
        self._backend.set_output_size(width, height)
        self._backend.set_dpi(96.0 * ratio)
        self._backend.request_render()
        self._render_request_count += 1
        self._schedule_frame_poll(0)

    def _request_navigation_render(self) -> None:
        """Coalesce motion events while the previous frame remains responsive."""
        self._navigation_render.start()

    def _schedule_frame_poll(self, interval_ms: int) -> None:
        self._poll_interval_ms = max(0, int(interval_ms))
        self._poll.start(self._poll_interval_ms)

    def _take_completed_frame(self) -> None:
        self._poll_count += 1
        frame = self._backend.take_completed_frame()
        if frame is None:
            if self._backend.render_active:
                self._empty_poll_count += 1
                interval = 8 if self._poll_interval_ms <= 0 else min(self._poll_interval_ms * 2, 32)
                self._schedule_frame_poll(interval)
            return
        self._last_frame = frame
        self._image_buffer = frame.rgba
        self._image = QImage(
            self._image_buffer,
            frame.width,
            frame.height,
            frame.stride,
            QImage.Format.Format_RGBA8888,
        )
        self._image.setDevicePixelRatio(self._screen_pixel_ratio())
        self._navigation_transform = QTransform()
        self._frame_delivery_count += 1
        self._frame_bytes_delivered += len(frame.rgba)
        self.frame_ready.emit(frame)
        self.update()

    def _publish_backend_status(self) -> None:
        self.backend_status_changed.emit(self.backend_status)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.width() > 0 and self.height() > 0:
            self._navigation_render.stop()
            self._request_render()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens.BG_SEARCH))
        if not self._image.isNull():
            painter.save()
            painter.setTransform(self._navigation_transform)
            painter.drawImage(self.rect(), self._image)
            painter.restore()
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
        height: int | None = None, dpi: float | None = None,
    ) -> None:
        paint_map_decorations(
            painter,
            decorations,
            width=self.width() if width is None else int(width),
            height=self.height() if height is None else int(height),
            extent=self._view_extent,
            dpi=dpi,
        )

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
                painter, (state or {}).get("decorations") or {},
                width=width, height=height, dpi=dpi,
            )
            painter.end()
            return image
        finally:
            self._backend.set_output_size(*previous_size)
            self._backend.set_dpi(previous_dpi)

    def export_png(
        self,
        path: str,
        *,
        width: int = 2400,
        height: int | None = None,
        dpi: float = 300.0,
    ) -> None:
        if height is None:
            # Match the current view's aspect (#522): a fixed 2400x1600
            # canvas letterboxed a non-3:2 view, and pre-letterboxing it
            # stretched the export by up to ~25% relative to the screen.
            xmin, ymin, xmax, ymax = self._view_extent
            if xmax > xmin and ymax > ymin:
                height = max(
                    64, min(16000, round(width * (ymax - ymin) / (xmax - xmin)))
                )
            else:
                height = 1600
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
            # Anchor the zoom at the world point under the cursor (matching
            # NativeMapCanvas and MapEditView); extent-center anchoring made
            # the point under the cursor drift by ~5% of the viewport per
            # wheel notch.
            self.zoom_by(
                0.8 if delta > 0 else 1.25,
                self.screen_to_map(event.position()),
                coalesce_history=True,
            )
            event.accept()
            return
        event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_pan = True
            event.accept()
            return
        key = event.key()
        # PySide6's QKeyEvent.key() returns an int; calling ``.name`` on it
        # raised AttributeError for no-text non-Escape keys (arrows, Delete,
        # F-keys) and aborted the handler before the tool controller or the
        # parent keyPressEvent ran.
        if key == Qt.Key.Key_Escape:
            key_name = "escape"
        else:
            text = event.text()
            key_name = text if text else Qt.Key(key).name.lower()
        if self._tool_controller is not None and self._tool_controller.key_press(key_name):
            self.tool_operation.emit(self._active_tool_edits_data())
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
                self.tool_operation.emit(self._active_tool_edits_data())
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
            self._tool_controller.active_tool.mouse_move(
                self._cursor_map, modifiers=self._modifier_names(event.modifiers())
            )
        # Pointer feedback (measure hover, rubber band, snap mark) only repaints
        # the overlay; document data never changes on a move, so no tool_operation.
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
                self.tool_operation.emit(self._active_tool_edits_data())
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
                self.tool_operation.emit(self._active_tool_edits_data())
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
        self._navigation_render.stop()
        self._image = QImage()
        self._image_buffer = None
        self._backend.shutdown()
        super().closeEvent(event)
