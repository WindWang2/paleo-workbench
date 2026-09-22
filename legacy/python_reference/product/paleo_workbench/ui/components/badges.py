"""徽章与行内状态（V5-U2）。

PwbBadge：白字深底徽章（BADGE_* / ERROR_RED，三主题 ≥ 4.5:1），
取代此前 5 处各自实现的 status pill。
PwbInlineStatus：小图标 + 文字的行内状态行，tone 驱动图标与文字色，
取代「裸 QLabel 状态文本」方言（降级态渲染统一入口，D6）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from paleo_workbench import tokens
from paleo_workbench.ui.theme import theme_manager
from paleo_workbench.ui.workstation.common import workstation_icon

BADGE_TONES = ("neutral", "primary", "success", "warning", "error")

#: tone → (默认图标, 图标染色 token 名)
_TONE_ICON: dict[str, tuple[str, str]] = {
    "neutral": ("", "TEXT_SECONDARY"),
    "primary": ("", "PRIMARY"),
    "success": ("circle-check.svg", "SUCCESS"),
    "warning": ("alert-triangle.svg", "WARNING"),
    "process": ("refresh-cw.svg", "ACCENT"),
    "error": ("alert-triangle.svg", "ERROR"),
}


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class PwbBadge(QLabel):
    """语义色调徽章。tone ∈ {neutral, primary, success, warning, error}。"""

    def __init__(
        self,
        text: str = "",
        *,
        tone: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("PwbBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        if tone not in BADGE_TONES:
            tone = "neutral"
        self._tone = tone
        self.setProperty("tone", tone)
        _repolish(self)

    @property
    def tone(self) -> str:
        return self._tone


class PwbInlineStatus(QWidget):
    """「图标 + 一句话」行内状态（含降级/加载/错误语义，D6 渲染端）。

    tone ∈ {neutral, primary, success, warning, process, error}。
    图标可用 ``icon_name`` 显式覆盖；文字走 QSS 按 tone 着色。
    """

    def __init__(
        self,
        text: str = "",
        *,
        tone: str = "neutral",
        icon_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tone = tone
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(16, 16)
        self._icon_label.setVisible(False)
        self._text_label = QLabel(text, self)
        self._text_label.setObjectName("PwbInlineStatusText")
        self._text_label.setWordWrap(True)
        layout.addWidget(self._icon_label)
        layout.addWidget(self._text_label, 1)
        layout.addStretch(0)
        self._explicit_icon: str | None = icon_name
        self._apply(text, tone, icon_name)

    def set_status(self, text: str, tone: str | None = None, icon_name: str | None = None) -> None:
        if tone is None:
            tone = self._tone
        self._apply(text, tone, icon_name if icon_name is not None else self._explicit_icon)

    def _apply(self, text: str, tone: str, icon_name: str | None) -> None:
        self._tone = tone
        self._text_label.setText(text)
        self._text_label.setProperty("tone", tone)
        _repolish(self._text_label)
        palette = tokens.palette_for(theme_manager.current_theme.value)
        resolved = icon_name if icon_name is not None else _TONE_ICON.get(tone, ("", ""))[0]
        if resolved:
            color_token = _TONE_ICON.get(tone, ("", "TEXT_SECONDARY"))[1]
            icon = workstation_icon(resolved, str(palette.get(color_token, "")))
            self._icon_label.setPixmap(icon.pixmap(16, 16))
            self._icon_label.setVisible(True)
        else:
            self._icon_label.setVisible(False)

    def clear(self) -> None:
        self._apply("", "neutral", self._explicit_icon)
