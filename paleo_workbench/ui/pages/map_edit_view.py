from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QWheelEvent
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
        event.accept()

    def reset_view(self) -> None:
        self.resetTransform()
        if self.scene() is not None:
            self.fitInView(
                self.scene().sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
