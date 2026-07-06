from __future__ import annotations

from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens


class ActionPanel(QFrame):
    """Right-hand action panel for data import and conversion commands."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ActionPanel")
        self.setFixedWidth(180)
        self.setStyleSheet(
            f"QFrame#ActionPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.import_btn = QPushButton("导入资源")
        self.import_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.import_btn)

        self.convert_btn = QPushButton("数据转换")
        self.convert_btn.setObjectName("SecondaryButton")
        layout.addWidget(self.convert_btn)

        layout.addStretch()
