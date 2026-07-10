from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton

from paleo_workbench.ui import tokens

_BUTTON_SPECS = [
    ("新建工程", "PrimaryButton"),
    ("打开工程", "SecondaryButton"),
    ("打开样例工程", "SecondaryButton"),
    ("保存工程", "SecondaryButton"),
    ("工程属性", "SecondaryButton"),
]


class HeaderToolbar(QFrame):
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_project_requested = Signal()
    save_project_requested = Signal()
    properties_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeaderToolbar")
        self.buttons: list[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(tokens.SPACE_2)
        for text, obj_name in _BUTTON_SPECS:
            btn = QPushButton(text)
            btn.setObjectName(obj_name)
            if obj_name == "PrimaryButton":
                btn.setMinimumHeight(tokens.CONTROL_HEIGHT_LG)
            else:
                btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
            self.buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch()

        self.new_project_btn = self.buttons[0]
        self.open_project_btn = self.buttons[1]
        self.open_sample_project_btn = self.buttons[2]
        self.save_project_btn = self.buttons[3]
        self.properties_btn = self.buttons[4]

        self.new_project_btn.clicked.connect(self.new_project_requested)
        self.open_project_btn.clicked.connect(self.open_project_requested)
        self.open_sample_project_btn.clicked.connect(self.open_sample_project_requested)
        self.save_project_btn.clicked.connect(self.save_project_requested)
        self.properties_btn.clicked.connect(self.properties_requested)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索井名 / 层位 / 功能…  Ctrl+K")
        self.search_box.setMaximumWidth(280)
        layout.addWidget(self.search_box)
