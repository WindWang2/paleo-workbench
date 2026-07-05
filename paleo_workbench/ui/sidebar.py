from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from paleo_workbench.ui import tokens


class TextSidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TextSidebar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        self.context_label = QLabel(tokens.PAGE_NAMES[0])
        self.context_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(self.context_label)
        self._placeholder = QLabel("上下文面板 (待实现)")
        self._placeholder.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        layout.addWidget(self._placeholder)
        layout.addStretch()

    def set_context(self, name: str) -> None:
        self.context_label.setText(name)
