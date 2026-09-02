"""Custom QDockWidget title bar for Workstation V3 Light.

Replaces the OS-native dock title chrome with a dense light-shell bar so
floating and docked panels share the same visual language (white surface,
hairline border, teal hover). Qt may still draw an outer window frame when
floating; this bar is the in-content chrome.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.ui.workstation.common import workstation_icon


_TITLE_QSS = f"""
QWidget#WorkstationDockTitleBar {{
    background: {tokens.BG_HEADER};
    border-bottom: 1px solid {tokens.BORDER};
    min-height: 28px;
    max-height: 30px;
}}
QLabel#WorkstationDockTitleLabel {{
    color: {tokens.TEXT_PRIMARY};
    font-size: 12px;
    font-weight: 600;
    padding-left: 8px;
}}
QToolButton#WorkstationDockTitleButton {{
    background: transparent;
    border: none;
    border-radius: 3px;
    color: {tokens.TEXT_SECONDARY};
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    padding: 0;
    margin: 0 1px;
}}
QToolButton#WorkstationDockTitleButton:hover {{
    background: {tokens.BG_SEARCH};
    color: {tokens.PRIMARY};
}}
QToolButton#WorkstationDockTitleButton:pressed {{
    background: {tokens.BG_SELECTION};
}}
"""


class DockTitleBar(QWidget):
    """Dense custom title bar attached via ``QDockWidget.setTitleBarWidget``."""

    float_toggled = Signal(bool)
    close_requested = Signal()

    def __init__(self, dock: QDockWidget, title: str = "", parent: QWidget | None = None):
        super().__init__(parent if parent is not None else dock)
        self.setObjectName("WorkstationDockTitleBar")
        self._dock = dock
        self._drag_origin: QPoint | None = None
        self._drag_frame: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 4, 2)
        layout.setSpacing(0)

        self._title = QLabel(title or dock.windowTitle(), self)
        self._title.setObjectName("WorkstationDockTitleLabel")
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._title, 1)

        self._float_btn = QToolButton(self)
        self._float_btn.setObjectName("WorkstationDockTitleButton")
        self._float_btn.setAutoRaise(True)
        self._float_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._float_btn.clicked.connect(self._toggle_float)
        layout.addWidget(self._float_btn)

        self._close_btn = QToolButton(self)
        self._close_btn.setObjectName("WorkstationDockTitleButton")
        self._close_btn.setAutoRaise(True)
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close_btn.setText("×")
        self._close_btn.setToolTip("关闭面板")
        self._close_btn.clicked.connect(self._request_close)
        layout.addWidget(self._close_btn)

        self.setStyleSheet(_TITLE_QSS)
        self._sync_float_affordance()
        self._sync_feature_buttons()

        dock.topLevelChanged.connect(self._on_top_level_changed)
        dock.windowTitleChanged.connect(self._title.setText)
        dock.installEventFilter(self)

    # --- public API -----------------------------------------------------

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def title(self) -> str:
        return self._title.text()

    # --- wiring ---------------------------------------------------------

    def _sync_feature_buttons(self) -> None:
        features = self._dock.features()
        floatable = bool(
            features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        closable = bool(
            features & QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self._float_btn.setVisible(floatable)
        self._close_btn.setVisible(closable)

    def _sync_float_affordance(self) -> None:
        floating = self._dock.isFloating()
        if floating:
            self._float_btn.setIcon(workstation_icon("pane-restore.svg", tokens.TEXT_SECONDARY))
            self._float_btn.setToolTip("停靠面板")
        else:
            self._float_btn.setIcon(workstation_icon("pane-maximize.svg", tokens.TEXT_SECONDARY))
            self._float_btn.setToolTip("浮动面板")
        # Prefer icons; fall back to glyphs if assets missing.
        if self._float_btn.icon().isNull():
            self._float_btn.setText("⧉" if not floating else "⊟")

    def _toggle_float(self) -> None:
        if not (
            self._dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        ):
            return
        floating = not self._dock.isFloating()
        self._dock.setFloating(floating)
        if floating:
            self._dock.raise_()
            self._dock.activateWindow()
        self.float_toggled.emit(floating)

    def _request_close(self) -> None:
        self.close_requested.emit()
        self._dock.close()

    def _on_top_level_changed(self, _floating: bool) -> None:
        self._sync_float_affordance()

    # --- drag floating window from title bar ----------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._dock and event.type() == QEvent.Type.WindowTitleChange:
            self._title.setText(self._dock.windowTitle())
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._dock.isFloating()
            and not self._hit_button(event.position().toPoint())
        ):
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_frame = self._dock.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_origin is not None
            and self._drag_frame is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and self._dock.isFloating()
        ):
            delta = event.globalPosition().toPoint() - self._drag_origin
            self._dock.move(self._drag_frame + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        self._drag_frame = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._hit_button(event.position().toPoint())
            and (
                self._dock.features()
                & QDockWidget.DockWidgetFeature.DockWidgetFloatable
            )
        ):
            self._toggle_float()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _hit_button(self, pos) -> bool:
        for btn in (self._float_btn, self._close_btn):
            if btn.isVisible() and btn.geometry().contains(pos):
                return True
        return False


def install_dock_title_bar(dock: QDockWidget, title: str | None = None) -> DockTitleBar:
    """Attach a :class:`DockTitleBar` to ``dock`` and return it."""
    bar = DockTitleBar(dock, title=title or dock.windowTitle())
    dock.setTitleBarWidget(bar)
    return bar
