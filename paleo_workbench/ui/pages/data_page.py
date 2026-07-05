from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.resource_summary import ResourceSummaryBar
from paleo_workbench.ui.pages.resource_table import ResourceTable


class DataPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.summary_bar = ResourceSummaryBar()
        layout.addWidget(self.summary_bar)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        self.resource_table = ResourceTable()
        bottom.addWidget(self.resource_table, 1)
        self.action_panel = self._build_action_panel()
        bottom.addWidget(self.action_panel, 0)
        layout.addLayout(bottom, 1)

    def _build_action_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("ActionPanel")
        panel.setFixedWidth(180)
        panel.setStyleSheet(
            f"QFrame#ActionPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(8)
        self.import_btn = QPushButton("导入资源")
        self.import_btn.setObjectName("PrimaryButton")
        self.convert_btn = QPushButton("数据转换")
        self.convert_btn.setObjectName("SecondaryButton")
        panel_layout.addWidget(self.import_btn)
        panel_layout.addWidget(self.convert_btn)
        panel_layout.addStretch()
        return panel

    def update_state(self, state: dict, resources: list) -> None:
        self.summary_bar.update_state(state)
        self.resource_table.update_resources(resources)
