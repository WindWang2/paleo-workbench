from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.viz.mapping_helpers import field_value


DEFAULT_CHROME_ELEMENTS = ["图例", "指北针", "比例尺", "标题栏"]


class MapChromePanel(QFrame):
    """Right-hand read-only summary of map chrome and downstream actions."""

    chrome_changed = Signal(dict)

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
        self.title_edit = QLineEdit(self)
        self.title_edit.setPlaceholderText("地图标题")
        layout.addWidget(self.title_edit)
        self.element_checks: dict[str, QCheckBox] = {}
        for element in DEFAULT_CHROME_ELEMENTS:
            check = QCheckBox(element, self)
            check.setChecked(True)
            self.element_checks[element] = check
            layout.addWidget(check)
            check.toggled.connect(self._emit_changed)
        self.title_edit.editingFinished.connect(self._emit_changed)

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
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 500;"
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
        self.title_edit.blockSignals(True)
        self.title_edit.setText(title)
        self.title_edit.blockSignals(False)
        enabled = {str(element) for element in elements}
        for element, check in self.element_checks.items():
            check.blockSignals(True)
            check.setChecked(element in enabled)
            check.blockSignals(False)

    def _emit_changed(self) -> None:
        elements = [element for element, check in self.element_checks.items() if check.isChecked()]
        self.chrome_changed.emit({"title": self.title_edit.text().strip(), "elements": elements})
