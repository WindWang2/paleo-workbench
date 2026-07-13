from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsView

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene


class MapEditView(QGraphicsView):
    """Primary map edit surface backed by MapEditScene."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapEditView")
        self.setStyleSheet(
            f"QGraphicsView#MapEditView {{ background: {tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._shared_view_state = {"center": (0.0, 0.0), "scale": 1.0}

        scene = MapEditScene(self)
        self.setScene(scene)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Stub zoom: scale view with mouse wheel (no geometry change)."""
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        self.scale(factor, factor)
        self._shared_view_state = self._read_view_state()
        self.view_state_changed.emit(self.view_state())
        event.accept()

    def _read_view_state(self) -> dict:
        center = self.mapToScene(self.viewport().rect().center())
        return {
            "center": (float(center.x()), float(center.y())),
            "scale": float(self.transform().m11()),
        }

    def view_state(self) -> dict:
        return dict(self._shared_view_state)

    def apply_view_state(self, state: dict, *, emit: bool = False) -> None:
        center = tuple(state.get("center", (0.0, 0.0)))
        scale = float(state.get("scale", 1.0))
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(float(center[0]), float(center[1]))
        self._shared_view_state = {"center": (float(center[0]), float(center[1])), "scale": scale}
        if emit:
            self.view_state_changed.emit(self.view_state())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        scene = self.scene()
        if isinstance(scene, MapEditScene):
            scene.keyPressEvent(event)
            if event.isAccepted():
                return
        super().keyPressEvent(event)

    def reset_view(self) -> None:
        self.resetTransform()
        if self.scene() is not None:
            self.fitInView(
                self.scene().sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
    view_state_changed = Signal(dict)
