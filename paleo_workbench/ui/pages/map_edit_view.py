from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsView

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene

# Idle delay before full-detail rendering is restored after navigation.
_NAV_LOD_IDLE_MS = 120


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
        self.setMouseTracking(True)
        self._shared_view_state = {"center": (0.0, 0.0), "scale": 1.0}
        # Navigation display LOD state (display-only; restored after idle).
        self._nav_lod_active = False
        self._nav_lod_timer = QTimer(self)
        self._nav_lod_timer.setSingleShot(True)
        self._nav_lod_timer.setInterval(_NAV_LOD_IDLE_MS)
        self._nav_lod_timer.timeout.connect(self._end_navigation_lod)

        scene = MapEditScene(self)
        self.setScene(scene)

    # --- navigation display LOD ---------------------------------------------

    def navigation_lod_active(self) -> bool:
        return self._nav_lod_active

    def _begin_navigation_lod(self) -> None:
        """Enter low-detail mode for wheel/pan; an idle timer restores detail."""
        if not self._nav_lod_active:
            self._nav_lod_active = True
            self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            self.setOptimizationFlags(
                QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing
                | QGraphicsView.OptimizationFlag.DontSavePainterState
            )
            scene = self.scene()
            if isinstance(scene, MapEditScene):
                scene.set_navigation_lod(True)
        self._nav_lod_timer.start()  # restart the idle countdown

    def _end_navigation_lod(self) -> None:
        if not self._nav_lod_active:
            return
        self._nav_lod_active = False
        self._nav_lod_timer.stop()
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setOptimizationFlags(QGraphicsView.OptimizationFlag(0))
        scene = self.scene()
        if isinstance(scene, MapEditScene):
            scene.set_navigation_lod(False)
        self.viewport().update()

    # --- events ---------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom with mouse wheel (no geometry change); low-detail while scrolling."""
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        self._begin_navigation_lod()
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        self.scale(factor, factor)
        self._shared_view_state = self._read_view_state()
        self.view_state_changed.emit(self.view_state())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Publish the cursor in scene coordinates (project CRS)."""
        pos = self.mapToScene(event.position().toPoint())
        self.cursor_position_changed.emit((float(pos.x()), float(pos.y())))
        super().mouseMoveEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        # Any pan (scrollbars, keyboard, centerOn) engages navigation LOD.
        if dx or dy:
            self._begin_navigation_lod()
        super().scrollContentsBy(dx, dy)

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
    cursor_position_changed = Signal(tuple)
