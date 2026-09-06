"""空 / 错误 / 加载状态与进度（V5-U2）。

统一此前 6 处 ad-hoc 空态与各页面自绘的加载/错误面。
所有状态面走 PwbStateSurface / PwbStateTitle / PwbStateHint 全局 QSS 词汇；
PwbProgress 消费任务进度同款 state-chunk 词汇。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.ui.components.buttons import PwbButton
from paleo_workbench.ui.theme import theme_manager
from paleo_workbench.ui.workstation.common import workstation_icon


def _tinted_pixmap(icon_name: str, color_token: str, size: int) -> object:

    palette = tokens.palette_for(theme_manager.current_theme.value)
    icon = workstation_icon(icon_name, str(palette.get(color_token, "")))
    pm = icon.pixmap(size, size)
    pm.setDevicePixelRatio(1.0)
    return pm


class PwbEmptyState(QFrame):
    """虚线框居中状态面：图标 + 标题 + 提示 + 可选动作。"""

    def __init__(
        self,
        title: str,
        hint: str = "",
        *,
        icon_name: str = "inbox.svg",
        action: QPushButton | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PwbStateSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon = QLabel(self)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_name = icon_name
        layout.addWidget(self._icon)

        self._title = QLabel(title, self)
        self._title.setObjectName("PwbStateTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._hint = QLabel(hint, self)
        self._hint.setObjectName("PwbStateHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setVisible(bool(hint))
        layout.addWidget(self._hint)

        self._action = action
        if action is not None:
            wrap = QWidget(self)
            row = QVBoxLayout(wrap)
            row.setContentsMargins(0, 6, 0, 0)
            row.addWidget(action)
            wrap.setStyleSheet("background: transparent;")
            layout.addWidget(wrap)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        pm = _tinted_pixmap(self._icon_name, "TEXT_SECONDARY", 24)
        self._icon.setPixmap(pm)
        self._icon.setVisible(pm is not None)

    def set_state(self, title: str, hint: str = "") -> None:
        self._title.setText(title)
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))

    def set_action(self, action: QPushButton | None) -> None:
        if self._action is not None:
            self._action.setParent(None)
        self._action = action
        if action is not None:
            self.layout().addWidget(action)


class PwbErrorState(PwbEmptyState):
    """错误态：警示图标 + 可选「重试」动作（retry_callback）。"""

    def __init__(
        self,
        title: str = "加载失败",
        hint: str = "",
        *,
        retry_callback=None,
        parent: QWidget | None = None,
    ) -> None:
        self._retry_button = PwbButton("重试", variant="tertiary", icon_name="rotate-cw.svg")
        if retry_callback is not None:
            self._retry_button.clicked.connect(retry_callback)
        super().__init__(
            title,
            hint,
            icon_name="alert-triangle.svg",
            action=self._retry_button,
            parent=parent,
        )

    def set_retry_callback(self, callback) -> None:
        if callback is None:
            self._retry_button.setVisible(False)
            return
        self._retry_button.clicked.connect(callback)
        self._retry_button.setVisible(True)


class PwbLoadingState(QFrame):
    """加载态：busy 进度条 + 说明文字（indeterminate）。"""

    def __init__(
        self,
        text: str = "正在加载…",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PwbStateSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bar = QProgressBar(self)
        self._bar.setObjectName("PwbProgress")
        self._bar.setRange(0, 0)  # indeterminate
        self._bar.setTextVisible(False)
        self._text = QLabel(text, self)
        self._text.setObjectName("PwbStateHint")
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text.setWordWrap(True)
        layout.addWidget(self._bar)
        layout.addWidget(self._text)

    def set_text(self, text: str) -> None:
        self._text.setText(text)


class PwbProgress(QProgressBar):
    """状态着色 slim 进度条（词汇与任务中心一致）。

    state ∈ {normal, running, queued, done, failed}；running 用过程 amber。
    """

    STATES = ("normal", "running", "queued", "done", "failed")

    def __init__(self, *, state: str = "normal", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PwbProgress")
        self.setTextVisible(False)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        if state not in self.STATES:
            state = "normal"
        self._state = state
        self.setProperty("progressState", state)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    @property
    def state(self) -> str:
        return self._state
