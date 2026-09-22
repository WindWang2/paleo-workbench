from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import style, tokens


def _title_qss() -> str:
    return (
        f"color: {style.palette()['TEXT_PRIMARY']};"
        f" font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 600;"
    )


def _subtitle_qss() -> str:
    return f"color: {style.palette()['TEXT_SECONDARY']}; font-size: {tokens.FONT_SIZE_MINOR};"


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
        style.bind(self.title_label, _title_qss)  # E1: theme-switch re-render
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("新建工程从数据文件夹自动构建工区，或打开已有工程文件。")
        self.subtitle_label.setWordWrap(True)
        style.bind(self.subtitle_label, _subtitle_qss)
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
