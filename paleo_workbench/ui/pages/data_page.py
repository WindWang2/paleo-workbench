from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui.pages.action_panel import ActionPanel
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
        self.action_panel = ActionPanel()
        self.import_btn = self.action_panel.import_btn
        self.convert_btn = self.action_panel.convert_btn
        bottom.addWidget(self.action_panel, 0)
        layout.addLayout(bottom, 1)

    def update_state(self, state: dict, resources: list) -> None:
        self.summary_bar.update_state(state)
        self.resource_table.update_resources(resources)
