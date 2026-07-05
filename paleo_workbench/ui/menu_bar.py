from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

_MENU_LABELS = ["工程与文件", "视图", "工具", "帮助"]


class MenuBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MenuBar")
        self.labels: list[QLabel] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(24)
        for text in _MENU_LABELS:
            lbl = QLabel(text)
            self.labels.append(lbl)
            layout.addWidget(lbl)
        layout.addStretch()
