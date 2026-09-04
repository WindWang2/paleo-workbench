"""只读 QgsMapCanvas：自有 QgsProject，供首页/工区/编图预览。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui.qgis_stack.events import StackEvents
from paleo_workbench.ui.qgis_stack.mirror import mirror_snapshot_to_stack
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost
from paleo_workbench.ui.unified_map_canvas import paint_map_decorations


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
                    host = self._host
                    pos = event.position()
                    host.map_clicked.emit(host.screen_to_map((pos.x(), pos.y())))
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
        self._extent_history = [(0.0, 0.0, 1.0, 1.0)]
        self._extent_history_index = 0
        self.events = StackEvents(self)
        self.events.attach(self.stack, self.canvas_address)
        self.events.extent_changed.connect(self._on_stack_extent)
        self._overlay = _Overlay(self)
        self._filter = _ClickFilter(self)
        self.canvas.installEventFilter(self._filter)
        viewport = getattr(self.canvas, "viewport", None)
        if callable(viewport):
            vp = viewport()
            if vp is not None:
                vp.installEventFilter(self._filter)
        self.stack.set_map_tool(self.canvas_address, "pan")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._overlay.setGeometry(self.rect())
        self._overlay.raise_()

    def _on_stack_extent(self, xmin, ymin, xmax, ymax) -> None:
        tup = (float(xmin), float(ymin), float(xmax), float(ymax))
        self.extent_changed.emit(tup)
        self._overlay.update()

    @property
    def view_extent(self):
        try:
            return tuple(self.stack.canvas_extent(self.canvas_address))
        except Exception:
            return self._extent_history[self._extent_history_index]

    def set_extent(self, extent, *, record_history: bool = True, coalesce_history: bool = False) -> None:
        tup = tuple(float(v) for v in extent)
        self.stack.set_canvas_extent(self.canvas_address, *tup)

    def set_layer_snapshot(self, snapshot) -> None:
        if self._shutdown_done:
            return
        mirror_snapshot_to_stack(self.stack, self.canvas_address, snapshot)
        self._overlay.update()

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
    def backend_status(self) -> str:
        return "qgis"

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
