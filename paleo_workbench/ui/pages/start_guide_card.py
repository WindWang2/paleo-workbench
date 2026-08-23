from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens


class StartGuideCard(QFrame):
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4)
        layout.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("开始使用 Paleogeography Workbench")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("新建工程从数据文件夹自动构建工区，或打开已有工程文件。")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
        )
        layout.addWidget(self.subtitle_label)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(tokens.SPACE_2)

        self.new_project_button = QPushButton("新建工程")
        self.new_project_button.setObjectName("PrimaryButton")
        self.new_project_button.clicked.connect(self.new_project_requested.emit)
        btn_row.addWidget(self.new_project_button)

        self.open_project_button = QPushButton("打开工程")
        self.open_project_button.setObjectName("SecondaryButton")
        self.open_project_button.clicked.connect(self.open_project_requested.emit)
        btn_row.addWidget(self.open_project_button)

        self.open_sample_button = QPushButton("打开样例工程")
        self.open_sample_button.setObjectName("SecondaryButton")
        self.open_sample_button.clicked.connect(self.open_sample_requested.emit)
        btn_row.addWidget(self.open_sample_button)

        btn_row.addStretch()
        layout.addLayout(btn_row)
