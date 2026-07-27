from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from geoviz import GeoVizEngine, PreparedPreview, PreviewKind

from paleo_workbench.viz.hosts.well_location_preview import (
    WellLocationPreview,
    WellLocationPreviewStateStore,
)


class _EnginePreviewLifecycle:
    def __init__(self, engine) -> None:
        self.engine = engine

    def create(self, kind: PreviewKind, parent: QWidget) -> QWidget:
        return self.engine.create_widget(kind, parent)

    def render(
        self,
        widget: QWidget,
        preview: PreparedPreview,
    ) -> None:
        self.engine.render(widget, preview)

    def release(self, widget: QWidget) -> None:
        self.engine.release(widget)


class _WellLocationLifecycle:
    def __init__(
        self,
        engine,
        state_store: WellLocationPreviewStateStore,
    ) -> None:
        self.engine = engine
        self.state_store = state_store

    def create(self, _kind: PreviewKind, parent: QWidget) -> QWidget:
        return WellLocationPreview(
            self.engine,
            parent,
            state_store=self.state_store,
        )

    def render(
        self,
        widget: QWidget,
        preview: PreparedPreview,
    ) -> None:
        if not isinstance(widget, WellLocationPreview):
            raise TypeError("XY preview host widget type mismatch")
        widget.render(preview)

    def release(self, widget: QWidget) -> None:
        if not isinstance(widget, WellLocationPreview):
            raise TypeError("XY preview host widget type mismatch")
        widget.release()


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
        self._well_state_store = WellLocationPreviewStateStore()
        self._default_lifecycle = _EnginePreviewLifecycle(self.engine)
        self._lifecycles = {
            PreviewKind.XY_SCATTER: _WellLocationLifecycle(
                self.engine,
                self._well_state_store,
            )
        }

    def render(self, preview: PreparedPreview) -> QWidget:
        self._require_ui_thread()
        if self._active_kind is not None and self._active_kind is not preview.kind:
            self._release_kind(self._active_kind)

        widget = self.widgets.get(preview.kind)
        if widget is None:
            widget = self._create_widget(preview)
            self.widgets[preview.kind] = widget
            self.stack.addWidget(widget)

        try:
            self._render_widget(widget, preview)
        except Exception:
            try:
                self._dispose_widget(preview.kind, widget)
            except Exception:
                pass
            raise
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
        first_error: Exception | None = None
        for kind in tuple(self.widgets):
            try:
                self._release_kind(kind)
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def clear_session_state(self) -> None:
        """Forget per-asset preview state, for example when closing a project."""
        self._well_state_store.clear()

    def _release_kind(self, kind: PreviewKind) -> None:
        widget = self.widgets.get(kind)
        if widget is None:
            if self._active_kind is kind:
                self._active_kind = None
            return
        self._dispose_widget(kind, widget)

    def _dispose_widget(self, kind: PreviewKind, widget: QWidget) -> None:
        try:
            self._lifecycle(kind).release(widget)
        finally:
            widget.hide()
            self.stack.removeWidget(widget)
            if self.widgets.get(kind) is widget:
                self.widgets.pop(kind)
            if self._active_kind is kind:
                self._active_kind = None
            widget.deleteLater()

    def _create_widget(self, preview: PreparedPreview) -> QWidget:
        return self._lifecycle(preview.kind).create(
            preview.kind,
            self.stack,
        )

    def _render_widget(
        self,
        widget: QWidget,
        preview: PreparedPreview,
    ) -> None:
        self._lifecycle(preview.kind).render(widget, preview)

    def _lifecycle(self, kind: PreviewKind):
        return self._lifecycles.get(kind, self._default_lifecycle)

    @staticmethod
    def _require_ui_thread() -> None:
        application = QCoreApplication.instance()
        if application is None or QThread.currentThread() is not application.thread():
            raise RuntimeError("GeoVizPreviewHost methods require the UI thread")
