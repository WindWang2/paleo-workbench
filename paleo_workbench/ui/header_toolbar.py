from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton

_BUTTON_SPECS = [
    ("新建工程", "PrimaryButton"),
    ("打开工程", "SecondaryButton"),
    ("保存工程", "SecondaryButton"),
    ("工程属性", "SecondaryButton"),
]


class HeaderToolbar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeaderToolbar")
        self.buttons: list[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        for text, obj_name in _BUTTON_SPECS:
            btn = QPushButton(text)
            btn.setObjectName(obj_name)
            self.buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch()
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索井名 / 层位 / 功能…  Ctrl+K")
        self.search_box.setMaximumWidth(280)
        layout.addWidget(self.search_box)
