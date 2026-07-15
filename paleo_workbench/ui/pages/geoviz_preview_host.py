from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from geoviz import GeoVizEngine, PreparedPreview, PreviewKind


class GeoVizPreviewHost(QWidget):
    def __init__(self, engine: GeoVizEngine | None = None, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine or GeoVizEngine.default()
        self.stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.widgets: dict[PreviewKind, QWidget] = {}
        self._active_kind: PreviewKind | None = None

    def render(self, preview: PreparedPreview) -> QWidget:
        self._require_ui_thread()
        if self._active_kind is not None and self._active_kind is not preview.kind:
            self._release_kind(self._active_kind)

        widget = self.widgets.get(preview.kind)
        if widget is None:
            widget = self.engine.create_widget(preview.kind, self.stack)
            self.widgets[preview.kind] = widget
            self.stack.addWidget(widget)

        self.engine.render(widget, preview)
        self._active_kind = preview.kind
        self.stack.setCurrentWidget(widget)
        widget.show()
        return widget

    def clear(self) -> None:
        self._require_ui_thread()
        if self._active_kind is not None:
            self._release_kind(self._active_kind)

    def release_all(self) -> None:
        self._require_ui_thread()
        for kind in tuple(self.widgets):
            self._release_kind(kind)

    def _release_kind(self, kind: PreviewKind) -> None:
        widget = self.widgets.pop(kind, None)
        if widget is None:
            if self._active_kind is kind:
                self._active_kind = None
            return
        self.engine.release(widget)
        widget.hide()
        self.stack.removeWidget(widget)
        widget.deleteLater()
        if self._active_kind is kind:
            self._active_kind = None

    @staticmethod
    def _require_ui_thread() -> None:
        application = QCoreApplication.instance()
        if application is None or QThread.currentThread() is not application.thread():
            raise RuntimeError("GeoVizPreviewHost methods require the UI thread")
