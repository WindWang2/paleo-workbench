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
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.ui.workstation.common import workstation_icon


def _title_qss() -> str:
    """主题感知的 dock 标题栏样式（B1：暗色切换时随 palette 重渲染）。"""
    from paleo_workbench.ui import style

    pal = style.palette()
    return f"""
QWidget#WorkstationDockTitleBar {{
    background: {pal['BG_HEADER']};
    border-bottom: 1px solid {pal['BORDER']};
    min-height: 28px;
    max-height: 30px;
}}
QLabel#WorkstationDockTitleLabel {{
    color: {pal['TEXT_PRIMARY']};
    font-size: 12px;
    font-weight: 600;
    padding-left: 8px;
}}
QToolButton#WorkstationDockTitleButton {{
    background: transparent;
    border: none;
    border-radius: 3px;
    color: {pal['TEXT_SECONDARY']};
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    padding: 0;
    margin: 0 1px;
}}
QToolButton#WorkstationDockTitleButton:hover {{
    background: {pal['BG_SEARCH']};
    color: {pal['PRIMARY']};
}}
QToolButton#WorkstationDockTitleButton:pressed {{
    background: {pal['BG_SELECTION']};
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
        self._pending_undock = False

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
        self._float_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._float_btn.setAccessibleName("浮动面板")
        self._float_btn.clicked.connect(self._toggle_float)
        layout.addWidget(self._float_btn)

        self._close_btn = QToolButton(self)
        self._close_btn.setObjectName("WorkstationDockTitleButton")
        self._close_btn.setAutoRaise(True)
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._close_btn.setAccessibleName("关闭面板")
        self._close_btn.setText("×")
        self._close_btn.setToolTip("关闭面板")
        self._close_btn.clicked.connect(self._request_close)
        layout.addWidget(self._close_btn)

        # B1：动态注册 —— 主题切换时 style.repolish_all 重渲染。
        from paleo_workbench.ui import style as _style

        _style.bind(self, _title_qss)
        self._sync_float_affordance()
        self._sync_feature_buttons()

        dock.topLevelChanged.connect(self._on_top_level_changed)
        dock.windowTitleChanged.connect(self._title.setText)
        dock.featuresChanged.connect(self._sync_feature_buttons)
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
            self._float_btn.setToolTip("停靠面板（或双击标题栏）")
            self._float_btn.setAccessibleName("停靠面板")
        else:
            self._float_btn.setIcon(workstation_icon("pane-maximize.svg", tokens.TEXT_SECONDARY))
            self._float_btn.setToolTip("浮动面板（或拖动 / 双击标题栏撕出）")
            self._float_btn.setAccessibleName("浮动面板")
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

    # --- drag: tear off docked panels, move floating windows ----------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # 部件销毁阶段实例字典可能已清空（deleteLater 后仍有事件入队），
        # getattr 防御避免 eventFilter 在 Qt 事件循环里抛异常。
        dock = getattr(self, "_dock", None)
        if dock is not None and watched is dock and event.type() == QEvent.Type.WindowTitleChange:
            self._title.setText(dock.windowTitle())
        return super().eventFilter(watched, event)

    def _floatable(self) -> bool:
        dock = getattr(self, "_dock", None)
        return bool(
            dock is not None
            and dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pending_undock = False
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._floatable()
            and not self._hit_button(event.position().toPoint())
        ):
            # 浮动窗拖动优先交给系统级移动：Wayland 下顶层窗口不允许
            # 自行 move()，必须由合成器接管拖动；X11 上 kwin 等 WM 同样
            # 响应 _NET_WM_MOVERESIZE。返回 False 时回退手动位移。
            # 窗口尚未暴露（新建浮动窗未收到首个 configure）时调用
            # startSystemMove 会触发 xdg_toplevel 协议错误直接崩溃，
            # 必须用 isExposed() 守住。
            if self._dock.isFloating():
                handle = self._dock.windowHandle()
                if (
                    handle is not None
                    and handle.isExposed()
                    and handle.startSystemMove()
                ):
                    self._drag_origin = None
                    self._drag_frame = None
                    event.accept()
                    return
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_frame = self._dock.frameGeometry().topLeft()
            # 停停靠标题栏按下：超过拖拽阈值后撕出为浮动窗（#1122）。
            self._pending_undock = not self._dock.isFloating()
            event.accept()
            return
        self._drag_origin = None
        self._drag_frame = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_origin is not None
            and self._drag_frame is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            if self._pending_undock:
                delta = event.globalPosition().toPoint() - self._drag_origin
                if delta.manhattanLength() < QApplication.startDragDistance():
                    event.accept()
                    return
                self._pending_undock = False
                self._dock.setFloating(True)
                self._dock.raise_()
                self._dock.activateWindow()
                self.float_toggled.emit(True)
                # 注意：这里不能立刻 startSystemMove()——新浮动窗的
                # Wayland surface 尚未 configure，调用会协议错误崩溃。
                # 本次拖动在 Wayland 下原位结束（move 被合成器忽略），
                # 松开后再次按住标题栏即可系统级拖动（isExposed 已就绪）。
                # 重新锚定浮动窗几何，让光标继续「抓着」标题栏（X11 有效）。
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_frame = self._dock.frameGeometry().topLeft()
                event.accept()
                return
            if self._dock.isFloating():
                delta = event.globalPosition().toPoint() - self._drag_origin
                self._dock.move(self._drag_frame + delta)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        self._drag_frame = None
        self._pending_undock = False
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
