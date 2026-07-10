from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class EmptyStateLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("EmptyStateLabel")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
