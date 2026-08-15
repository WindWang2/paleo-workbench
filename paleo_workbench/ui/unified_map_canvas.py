"""Primary renderer-neutral map canvas with GIS navigation and edit overlays."""

from __future__ import annotations

from collections.abc import Callable
import math
from typing import Any, Mapping

from PySide6.QtCore import QMarginsF, QPointF, QRect, QRectF, QSize, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
    QPolygonF,
    QTransform,
    QWheelEvent,
)
from PySide6.QtSvg import QSvgGenerator
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
        self._last_snapshot_signature: tuple | None = None
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
        signature = self._snapshot_signature(snapshot)
        if signature == self._last_snapshot_signature:
            # Host refreshes can fire many times per interaction; identical
            # revisions/visibility must not enqueue another render pass.
            return
        self._last_snapshot_signature = signature
        self._navigation_render.stop()
        self._backend.set_layer_snapshot(snapshot)
        self._request_render()

    @staticmethod
    def _snapshot_signature(snapshot: MapRenderSnapshot) -> tuple:
        return (
            str(snapshot.project_crs),
            tuple(
                (
                    layer.id,
                    layer.layer_type,
                    int(layer.data_revision),
                    int(layer.style_revision),
                    bool(layer.visible),
                    round(float(layer.opacity), 6),
                    layer.scale_range,
                    str(layer.source_version_id),
                )
                for layer in snapshot.layers
            ),
        )

    @property
    def snapshot_source_version_ids(self) -> tuple[str, ...]:
        """Catalog DataVersion ids referenced by the current composition."""
        backend_snapshot = getattr(self._backend, "_snapshot", None)
        if backend_snapshot is None:
            return ()
        return tuple(
            dict.fromkeys(
                str(layer.source_version_id)
                for layer in backend_snapshot.layers
                if layer.source_version_id
            )
        )

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

    def _request_render(self) -> None:
        self._backend.set_output_size(max(1, self.width()), max(1, self.height()))
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
        height: int | None = None, scale: float = 1.0,
        extent: tuple[float, float, float, float] | None = None,
    ) -> None:
        """Paint chrome (title/scale bar/north arrow/legend) in device pixels.

        ``scale`` is ``dpi / 96`` for exports: every fixed-size element —
        including text, which is set in pixel sizes — scales with it.
        ``extent`` is the extent actually rendered into this target (exports
        letterbox the view extent); the scale bar reads it so its label always
        matches the drawn bar length.
        """
        canvas_width = self.width() if width is None else int(width)
        canvas_height = self.height() if height is None else int(height)
        drawn_extent = self._view_extent if extent is None else extent
        elements = {str(item) for item in decorations.get("elements") or ()}
        title = str(decorations.get("title") or "")
        title_font = QFont(painter.font())
        title_font.setPixelSize(max(10, round(16 * scale)))
        title_font.setBold(True)
        if title and (not elements or "标题栏" in elements or "title" in elements):
            painter.save()
            painter.setPen(QColor("#f8f9fa"))
            painter.setFont(title_font)
            painter.drawText(
                QRectF(14 * scale, 10 * scale, canvas_width - 28 * scale, canvas_height - 20 * scale),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, title,
            )
            painter.restore()
        if not elements or "比例尺" in elements or "scale_bar" in elements:
            self._paint_scale_bar(painter, drawn_extent, canvas_width, canvas_height, scale)
        if not elements or "指北针" in elements or "north_arrow" in elements:
            painter.save()
            center = QPointF(canvas_width - 28 * scale, 37 * scale)
            painter.setPen(QPen(QColor("#ffffff"), 1.5 * scale))
            painter.setBrush(QColor("#343a40"))
            painter.drawPolygon(QPolygonF([
                center + QPointF(0, -18 * scale),
                center + QPointF(-6 * scale, 10 * scale),
                center + QPointF(0, 5 * scale),
                center + QPointF(6 * scale, 10 * scale),
            ]))
            font = QFont(painter.font())
            font.setPixelSize(max(8, round(10 * scale)))
            painter.setFont(font)
            painter.drawText(center + QPointF(-5 * scale, -22 * scale), "N")
            painter.restore()
        if (not elements or "图例" in elements or "legend" in elements) and decorations.get("legend_items"):
            items = [str(item) for item in decorations["legend_items"]][:8]
            painter.save()
            legend_width = 164 * scale
            row_height = 18 * scale
            swatch = 9 * scale
            legend_height = 10 * scale + row_height * len(items)
            painter.setPen(QPen(QColor("#dfe6ee"), 1.0 * scale))
            painter.setBrush(QColor(24, 28, 34, 210))
            rect = QRectF(
                canvas_width - legend_width - 16 * scale,
                canvas_height - legend_height - 16 * scale,
                legend_width,
                legend_height,
            )
            painter.drawRect(rect)
            font = QFont(painter.font())
            font.setPixelSize(max(8, round(11 * scale)))
            for index, item in enumerate(items):
                painter.setBrush(QColor("#6c8ebf"))
                y = rect.top() + 14 * scale + index * row_height
                painter.drawRect(QRectF(rect.left() + 8 * scale, y - swatch, swatch, swatch))
                painter.setPen(QColor("#f8f9fa"))
                painter.setFont(font)
                painter.drawText(QPointF(rect.left() + 23 * scale, y), item)
            painter.restore()

    @staticmethod
    def _nice_scale_units(value: float) -> float:
        """Round a map-unit length down onto the 1/2/5 × 10ⁿ ladder."""
        if value <= 0.0 or not math.isfinite(value):
            return value
        exponent = math.floor(math.log10(value))
        fraction = value / (10.0**exponent)
        for nice in (5.0, 2.0, 1.0):
            if fraction >= nice:
                return nice * (10.0**exponent)
        return 10.0**exponent

    @classmethod
    def _scale_bar_spec(
        cls, extent: tuple[float, float, float, float], canvas_width: int, scale: float = 1.0,
    ) -> tuple[float, float] | None:
        """Return (nice unit length, matching pixel length) for a scale bar.

        Bar length matches the printed label exactly (units → pixels via the
        target's own extent), so the bar is a true measurement reference.
        """
        xmin, _, xmax, _ = extent
        span = xmax - xmin
        if span <= 0.0:
            return None
        target_units = cls._nice_scale_units(span * 0.2)
        if target_units <= 0.0:
            return None
        pixels = target_units / span * canvas_width
        if pixels < 16 * scale:
            return None
        return target_units, pixels

    def _paint_scale_bar(
        self,
        painter: QPainter,
        extent: tuple[float, float, float, float],
        canvas_width: int,
        canvas_height: int,
        scale: float,
    ) -> None:
        spec = self._scale_bar_spec(extent, canvas_width, scale)
        if spec is None:
            return
        target_units, pixels = spec
        y = canvas_height - 24.0 * scale
        painter.save()
        painter.setPen(QPen(QColor("#ffffff"), 2.0 * scale))
        painter.drawLine(QPointF(16 * scale, y), QPointF(16 * scale + pixels, y))
        painter.drawLine(QPointF(16 * scale, y - 4 * scale), QPointF(16 * scale, y + 4 * scale))
        painter.drawLine(QPointF(16 * scale + pixels, y - 4 * scale), QPointF(16 * scale + pixels, y + 4 * scale))
        font = QFont(painter.font())
        font.setPixelSize(max(8, round(10 * scale)))
        painter.setFont(font)
        label = f"{target_units:g} map units"
        painter.drawText(QPointF(16 * scale, y - 7 * scale), label)
        painter.restore()

    def _letterboxed_extent(self, width: int, height: int) -> tuple[float, float, float, float]:
        """Expand the view extent so geometry keeps its aspect at any export size."""
        xmin, ymin, xmax, ymax = self._view_extent
        span_x, span_y = xmax - xmin, ymax - ymin
        if width < 1 or height < 1 or span_x <= 0 or span_y <= 0:
            return self._view_extent
        target_aspect = width / height
        view_aspect = span_x / span_y
        if math.isclose(target_aspect, view_aspect, rel_tol=1e-3):
            return self._view_extent
        if target_aspect > view_aspect:
            padded = span_y * target_aspect
            return (xmin - (padded - span_x) / 2.0, ymin, xmax + (padded - span_x) / 2.0, ymax)
        padded = span_x / target_aspect
        return (xmin, ymin - (padded - span_y) / 2.0, xmax, ymax + (padded - span_y) / 2.0)

    def render_export_image(
        self, width: int, height: int, *, dpi: float = 300.0, preserve_aspect: bool = True,
    ) -> QImage:
        """Synchronously render the same backend/composition at export resolution."""
        if width < 1 or height < 1:
            raise ValueError("export size must be positive")
        if self._backend.render_active:
            self._backend.cancel_render()
        previous_size = self._backend._output_size
        previous_dpi = self._backend._dpi
        previous_extent = self._backend._extent
        try:
            self._backend.set_output_size(int(width), int(height))
            self._backend.set_dpi(float(dpi))
            if preserve_aspect:
                self._backend.set_extent(self._letterboxed_extent(int(width), int(height)))
            frame = self._backend.render_sync()
            image = QImage(
                frame.rgba, frame.width, frame.height, frame.stride,
                QImage.Format.Format_RGBA8888,
            ).copy()
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            state = self._overlay_provider() if self._overlay_provider is not None else {}
            self._paint_decorations(
                painter, (state or {}).get("decorations") or {}, width=width, height=height,
                scale=float(dpi) / 96.0,
                extent=self._letterboxed_extent(int(width), int(height)) if preserve_aspect else self._view_extent,
            )
            painter.end()
            return image
        finally:
            self._backend.set_output_size(*previous_size)
            self._backend.set_dpi(previous_dpi)
            self._backend.set_extent(previous_extent)

    def export_png(self, path: str, *, width: int = 2400, height: int = 1600, dpi: float = 300.0) -> None:
        image = self.render_export_image(width, height, dpi=dpi)
        # Persist the physical resolution so printed sizes match the export DPI.
        dots_per_meter = round(float(dpi) / 0.0254)
        image.setDotsPerMeterX(dots_per_meter)
        image.setDotsPerMeterY(dots_per_meter)
        if not image.save(path, "PNG"):
            raise RuntimeError("could not save unified map PNG")

    def export_svg(
        self, path: str, *, width: int = 2400, height: int = 1600, dpi: float = 300.0
    ) -> None:
        """Vector SVG export through the same composition pipeline as the screen."""
        generator = QSvgGenerator()
        generator.setFileName(str(path))
        generator.setSize(QSize(int(width), int(height)))
        generator.setViewBox(QRect(0, 0, int(width), int(height)))
        generator.setResolution(int(round(float(dpi))))
        generator.setTitle(self._export_title())
        painter = QPainter()
        if not painter.begin(generator):
            raise RuntimeError("could not begin unified map SVG export")
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._paint_export_vector(painter, int(width), int(height), dpi)
        finally:
            painter.end()

    def export_pdf(
        self, path: str, *, width: int = 2400, height: int = 1600, dpi: float = 300.0
    ) -> None:
        """Vector PDF export through the same composition pipeline as the screen."""
        writer = QPdfWriter(str(path))
        writer.setResolution(int(round(float(dpi))))
        page_mm = QSizeF(width / dpi * 25.4, height / dpi * 25.4)
        writer.setPageSize(QPageSize(page_mm, QPageSize.Unit.Millimeter))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        painter = QPainter()
        if not painter.begin(writer):
            raise RuntimeError("could not begin unified map PDF export")
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            page_rect = writer.pageLayout().paintRectPixels(writer.resolution())
            self._paint_export_vector(
                painter, int(page_rect.width()), int(page_rect.height()), dpi
            )
        finally:
            painter.end()

    def _paint_export_vector(self, painter: QPainter, width: int, height: int, dpi: float) -> None:
        """Run the backend's vector pipeline plus chrome at export resolution."""
        from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend

        if self._backend.render_active:
            # An in-flight screen render must not complete against the mutated
            # export viewport and later surface on screen.
            self._backend.cancel_render()
        previous_size = self._backend._output_size
        previous_dpi = self._backend._dpi
        previous_extent = self._backend._extent
        export_extent = self._letterboxed_extent(int(width), int(height))
        try:
            self._backend.set_output_size(int(width), int(height))
            self._backend.set_dpi(float(dpi))
            self._backend.set_extent(export_extent)
            if isinstance(self._backend, FallbackMapRenderBackend):
                self._backend.render_to_painter(painter, int(width), int(height), dpi=float(dpi))
            else:
                frame = self._backend.render_sync()
                image = QImage(
                    frame.rgba, frame.width, frame.height, frame.stride,
                    QImage.Format.Format_RGBA8888,
                )
                painter.drawImage(QRectF(0, 0, width, height), image)
            state = self._overlay_provider() if self._overlay_provider is not None else {}
            self._paint_decorations(
                painter, (state or {}).get("decorations") or {}, width=width, height=height,
                scale=float(dpi) / 96.0, extent=export_extent,
            )
        finally:
            self._backend.set_output_size(*previous_size)
            self._backend.set_dpi(previous_dpi)
            self._backend.set_extent(previous_extent)

    def _export_title(self) -> str:
        state = self._overlay_provider() if self._overlay_provider is not None else {}
        return str((state or {}).get("decorations", {}).get("title") or "Paleogeographic map")

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
            self.zoom_by(0.8 if delta > 0 else 1.25, coalesce_history=True)
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
            # Only tools paint cursor-relative feedback; a bare hover over the
            # canvas must not schedule full repaints per mouse-move event.
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
        self._navigation_render.stop()
        self._image = QImage()
        self._image_buffer = None
        self._backend.shutdown()
        super().closeEvent(event)
