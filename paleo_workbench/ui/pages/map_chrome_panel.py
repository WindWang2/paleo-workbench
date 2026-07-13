from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.mapping_helpers import field_value


DEFAULT_CHROME_ELEMENTS = ["图例", "指北针", "比例尺", "标题栏"]


class MapChromePanel(QFrame):
    """Right-hand read-only summary of map chrome and downstream actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapChromePanel")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN)
        layout.setSpacing(tokens.SPACE_3)

        title = QLabel("图面要素")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.title_value = self._add_value(layout, "图名", "未设置")
        self.elements_value = self._add_value(layout, "已启用", "图例 / 指北针 / 比例尺 / 标题栏")

        layout.addStretch()
        self.save_btn = QPushButton("保存编图草稿")
        self.save_btn.setObjectName("SecondaryButton")
        layout.addWidget(self.save_btn)
        self.review_btn = QPushButton("发送成图审核")
        self.review_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.review_btn)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setWordWrap(True)
        value.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
            " border: none; background: transparent;"
        )
        layout.addWidget(value)
        return value

    def update_state(self, document) -> None:
        chrome = field_value(document, "map_chrome", {}) or {}
        fallback_title = field_value(document, "name", "") or "未设置"
        title = chrome.get("title") or fallback_title
        elements = chrome.get("elements") or DEFAULT_CHROME_ELEMENTS

        self.title_value.setText(title)
        self.elements_value.setText(" / ".join(elements))
