from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QWidget,
)

from paleo_workbench.ui import tokens

_MENU_LABELS = ["视图", "工具", "帮助"]


class MenuBar(QFrame):
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_project_requested = Signal()
    save_project_requested = Signal()
    properties_requested = Signal()
    preview_settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MenuBar")
        self.labels: list[QWidget] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, 0)
        layout.setSpacing(tokens.SPACE_4)

        self.project_menu_button = QPushButton("工程与文件")
        self.project_menu_button.setObjectName("ProjectMenuButton")
        self.project_menu = QMenu(self.project_menu_button)
        self.new_project_action = self._add_project_action(
            "新建工程", self.new_project_requested
        )
        self.open_project_action = self._add_project_action(
            "打开工程", self.open_project_requested
        )
        self.open_sample_project_action = self._add_project_action(
            "打开样例工程", self.open_sample_project_requested
        )
        self.save_project_action = self._add_project_action(
            "保存工程", self.save_project_requested
        )
        self.project_menu.addSeparator()
        self.properties_action = self._add_project_action(
            "工程属性", self.properties_requested
        )
        self.project_menu_button.setMenu(self.project_menu)
        layout.addWidget(self.project_menu_button)

        for text in _MENU_LABELS:
            if text == "工具":
                self.tools_menu_button = QPushButton(text)
                self.tools_menu_button.setObjectName("ToolsMenuButton")
                self.tools_menu = QMenu(self.tools_menu_button)
                self.preview_settings_action = self.tools_menu.addAction("预览设置…")
                self.preview_settings_action.triggered.connect(
                    self.preview_settings_requested
                )
                self.tools_menu_button.setMenu(self.tools_menu)
                self.labels.append(self.tools_menu_button)
                layout.addWidget(self.tools_menu_button)
                continue
            lbl = QLabel(text)
            self.labels.append(lbl)
            layout.addWidget(lbl)
        layout.addStretch()

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索井名 / 层位 / 功能…  Ctrl+F")
        self.search_box.setToolTip("搜索井名/层位/功能 (Ctrl+F)")
        self.search_box.setMaximumWidth(280)
        layout.addWidget(self.search_box)

    def _add_project_action(self, text: str, signal: Signal) -> QAction:
        action = self.project_menu.addAction(text)
        action.triggered.connect(signal)
        return action
