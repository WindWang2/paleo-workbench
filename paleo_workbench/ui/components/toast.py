"""非阻塞通知（V5-U2 / U6）。

PwbToast.show_on(parent, ...) 在窗口顶部中央叠放自动消退的通知条；
不夺焦点、不入数据权威，队列内自上而下堆叠，点击任意处立即关闭。
offscreen 下行为确定性（无动画依赖）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QWidget

from paleo_workbench.ui.components.badges import PwbInlineStatus

#: 每个宿主窗口当前挂着的 toasts（widget → [toast, ...]）
_ACTIVE: dict[QWidget, list[PwbToast]] = {}

_TOP_INSET = 52      # app bar 之下
_SIDE_MARGIN = 24
_GAP = 8
_WIDTH = 460


class PwbToast(QFrame):
    """单条通知。常规调用入口是 :meth:`show_on`。"""

    def __init__(
        self,
        parent: QWidget,
        text: str,
        *,
        tone: str = "neutral",
        title: str = "",
        timeout_ms: int = 4000,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PwbToast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)
        status = PwbInlineStatus(text, tone=tone, parent=self)
        if title:
            title_label = QLabel(title, self)
            title_label.setObjectName("PwbToastTitle")
            layout.addWidget(title_label, 0)
        layout.addWidget(status, 1)
        if timeout_ms > 0:
            # 子 QTimer：toast 随宿主销毁时定时器一并销毁（避免向死对象投递）
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.dismiss)
            timer.start(timeout_ms)
        self.setMaximumWidth(_WIDTH)

    def dismiss(self) -> None:
        host = self.parentWidget()
        if host is not None:
            stack = _ACTIVE.get(host, [])
            if self in stack:
                stack.remove(self)
        self.hide()
        self.deleteLater()
        _relayout(host) if host is not None else None

    def mousePressEvent(self, event) -> None:
        self.dismiss()

    @staticmethod
    def show_on(
        parent: QWidget,
        text: str,
        *,
        tone: str = "neutral",
        title: str = "",
        timeout_ms: int = 4000,
    ) -> PwbToast:
        """在 *parent*（窗口/中央件）顶部堆一条通知并返回实例。"""
        host = parent.window() if not isinstance(parent, QMainWindow) else parent
        toast = PwbToast(host, text, tone=tone, title=title, timeout_ms=timeout_ms)
        stack = _ACTIVE.setdefault(host, [])
        stack.append(toast)
        toast.setParent(host)
        toast.show()
        toast.raise_()
        _relayout(host)
        return toast


def _relayout(host: QWidget) -> None:
    """自上而下重排宿主的所有 toasts（顶部中央）。"""
    stack = _ACTIVE.get(host)
    if not stack:
        return
    y = _TOP_INSET
    x = max(_SIDE_MARGIN, (host.width() - _WIDTH) // 2)
    for toast in list(stack):
        width = min(_WIDTH, max(240, host.width() - 2 * _SIDE_MARGIN))
        toast.setFixedWidth(width)
        x = max(_SIDE_MARGIN, (host.width() - width) // 2)
        toast.move(x, y)
        toast.adjustSize()
        y += toast.height() + _GAP


def notify(text: str, *, tone: str = "neutral", title: str = "", timeout_ms: int = 4000) -> None:
    """进程级便捷入口：挂到 ``QApplication.topLevelWidgets()`` 里的主窗口。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        if isinstance(w, QMainWindow) and w.isVisible():
            PwbToast.show_on(w, text, tone=tone, title=title, timeout_ms=timeout_ms)
            return
