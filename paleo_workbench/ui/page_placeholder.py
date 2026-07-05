from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens


class PagePlaceholder(QWidget):
    def __init__(self, page_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PagePlaceholder")
        self.name_label = QLabel(f"{page_name}\n(占位页, 待实现)")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 16px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(self.name_label)
        layout.addStretch()
