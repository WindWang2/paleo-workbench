"""只读 QgsMapCanvas：自有 QgsProject，供首页/工区/编图预览。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui.qgis_stack.events import StackEvents
from paleo_workbench.ui.qgis_stack.mirror import mirror_snapshot_to_stack
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost
from paleo_workbench.ui.unified_map_canvas import paint_map_decorations


class _DisplayBackend:
    backend_name = "qgis"
    status = "ready"

    def __init__(self) -> None:
        self._snapshot = None


def create_display_canvas(parent=None) -> QWidget:
    try:
        from qgis_render_bridge.mapstack import QgisMapStack  # noqa: F401
    except ImportError:
        from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
        return UnifiedMapCanvas(parent=parent)
    return QgisDisplayCanvas(parent)


class _ClickFilter(QObject):
    def __init__(self, host: "QgisDisplayCanvas") -> None:
        super().__init__(host)
        self._host = host
        self._press: QPointF | None = None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._press = event.position()
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
                press = self._press
                self._press = None
                if (event.position() - press).manhattanLength() < 6:
                    self._host._emit_map_click(event.position())
        return False


class _Overlay(QWidget):
    def __init__(self, host: "QgisDisplayCanvas") -> None:
        super().__init__(host)
        self._host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, _event) -> None:  # noqa: N802
        host = self._host
        provider = getattr(host, "_overlay_provider", None)
        if provider is None:
            return
        state = provider() or {}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = tuple(state.get("selected_features") or ())
        if selected:
            painter.setPen(QPen(QColor("#ffe066"), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for feature in selected:
                geometry = feature.get("geometry") if isinstance(feature, dict) else getattr(feature, "geometry", None)
                if not isinstance(geometry, dict) or geometry.get("type") != "Point":
                    continue
                coords = geometry.get("coordinates") or ()
                if len(coords) < 2:
                    continue
                screen = host.map_to_screen((float(coords[0]), float(coords[1])))
                painter.drawEllipse(QPointF(screen.x(), screen.y()), 8.0, 8.0)
        decorations = state.get("decorations") or {}
        if decorations:
            paint_map_decorations(
                painter, decorations,
                width=self.width(), height=self.height(),
                extent=host.view_extent, dark_chrome=False,
            )
        painter.end()


class QgisDisplayCanvas(QWidget):
    extent_changed = Signal(tuple)
    map_position_changed = Signal(tuple)
    backend_status_changed = Signal(str)
    map_clicked = Signal(tuple)
    tool_operation = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from qgis_render_bridge.mapstack import QgisMapStack

        self.stack = QgisMapStack()
        self.stack.initialize(display=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._host = QgisCanvasHost(self.stack, self)
        layout.addWidget(self._host)
        self.canvas = self._host.canvas
        self.canvas_address = self._host.canvas_address
        self._overlay_provider = None
        self._shutdown_done = False
        self._snapshot = None
        self._backend = _DisplayBackend()
        self._tool_controller = None
        self._last_frame = None
        self._extent_history = [(0.0, 0.0, 1.0, 1.0)]
        self._extent_history_index = 0
        self._pending_programmatic = False
        self.events = StackEvents(self)
        self.events.attach(self.stack, self.canvas_address)
        self.events.extent_changed.connect(self._on_stack_extent)
        self.events.map_position_changed.connect(self._on_stack_position)
        self._overlay = _Overlay(self)
        self._filter = _ClickFilter(self)
        self.canvas.installEventFilter(self._filter)
        viewport = getattr(self.canvas, "viewport", None)
        if callable(viewport):
            vp = viewport()
            if vp is not None:
                vp.installEventFilter(self._filter)
        self.stack.set_map_tool(self.canvas_address, "pan")
        try:
            self.destroyed.connect(lambda _obj=None: self.shutdown())
        except Exception:
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

    def _emit_map_click(self, pos: QPointF) -> None:
        self.map_clicked.emit(self.screen_to_map((pos.x(), pos.y())))

    def _on_stack_position(self, x, y) -> None:
        self.map_position_changed.emit((float(x), float(y)))

    def _record_extent(self, tup: tuple[float, float, float, float], *, coalesce: bool = False) -> None:
        if self._extent_history_index < len(self._extent_history) - 1:
            self._extent_history = self._extent_history[: self._extent_history_index + 1]
        if coalesce and self._extent_history:
            self._extent_history[-1] = tup
        elif not self._extent_history or self._extent_history[-1] != tup:
            self._extent_history.append(tup)
            if len(self._extent_history) > 100:
                self._extent_history.pop(0)
            self._extent_history_index = len(self._extent_history) - 1

    def _on_stack_extent(self, xmin, ymin, xmax, ymax) -> None:
        tup = (float(xmin), float(ymin), float(xmax), float(ymax))
        if self._pending_programmatic:
            self._pending_programmatic = False
            self.extent_changed.emit(tup)
            self._overlay.update()
            return
        self._record_extent(tup)
        self.extent_changed.emit(tup)
        self.tool_operation.emit(False)
        self._overlay.update()

    @property
    def view_extent(self):
        try:
            return tuple(self.stack.canvas_extent(self.canvas_address))
        except Exception:
            return self._extent_history[self._extent_history_index]

    def set_extent(self, extent, *, record_history: bool = True, coalesce_history: bool = False) -> None:
        tup = tuple(float(v) for v in extent)
        if record_history:
            self._record_extent(tup, coalesce=coalesce_history)
        self._pending_programmatic = True
        self.stack.set_canvas_extent(self.canvas_address, *tup)
        self.extent_changed.emit(tup)
        self._overlay.update()

    def set_layer_snapshot(self, snapshot) -> None:
        if self._shutdown_done:
            return
        self._snapshot = snapshot
        self._backend._snapshot = snapshot
        _, _, failures = mirror_snapshot_to_stack(
            self.stack, self.canvas_address, snapshot)
        self._mirror_failures = list(failures)
        self._overlay.update()
        self.backend_status_changed.emit(self.backend_status)

    def map_to_screen(self, point):
        sx, sy = self.stack.map_to_screen(self.canvas_address, float(point[0]), float(point[1]))
        return QPointF(sx, sy)

    def screen_to_map(self, point):
        return tuple(self.stack.screen_to_map(self.canvas_address, float(point[0]), float(point[1])))

    def set_overlay_provider(self, provider) -> None:
        self._overlay_provider = provider
        self._overlay.update()

    def update(self) -> None:  # noqa: A003
        super().update()
        self._overlay.update()

    @property
    def backend(self):
        return self._backend

    @property
    def last_frame(self):
        return self._last_frame

    @property
    def backend_status(self) -> str:
        return "qgis"

    @property
    def snapshot_source_version_ids(self) -> tuple[str, ...]:
        snapshot = self._snapshot
        if snapshot is None:
            return ()
        return tuple(
            dict.fromkeys(
                str(layer.source_version_id)
                for layer in snapshot.layers
                if getattr(layer, "source_version_id", None)
            )
        )

    @property
    def map_units_per_pixel(self) -> float:
        try:
            xmin, ymin, xmax, ymax = self.view_extent
            w = max(1, int(self.canvas.width() or self.width() or 1))
            h = max(1, int(self.canvas.height() or self.height() or 1))
            return max((xmax - xmin) / w, (ymax - ymin) / h) if w and h else 1.0
        except Exception:
            return 1.0

    def zoom_by(self, factor: float, center: tuple[float, float] | None = None, *, coalesce_history: bool = False) -> None:
        if factor <= 0.0:
            raise ValueError("zoom factor must be positive")
        xmin, ymin, xmax, ymax = self.view_extent
        cx, cy = center if center is not None else ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
        self.set_extent(
            (
                cx + (xmin - cx) * factor,
                cy + (ymin - cy) * factor,
                cx + (xmax - cx) * factor,
                cy + (ymax - cy) * factor,
            ),
            coalesce_history=coalesce_history,
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

    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            self.stack.shutdown()
        except Exception:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)
