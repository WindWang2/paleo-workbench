from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SectionHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_1)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE};"
            f" font-weight: {tokens.FONT_WEIGHT_TITLE};"
        )
        layout.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
        )
        if not subtitle:
            self.subtitle_label.hide()
        layout.addWidget(self.subtitle_label)
