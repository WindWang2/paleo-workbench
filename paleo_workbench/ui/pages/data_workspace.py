from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QSplitter, QWidget

from paleo_workbench.ui.pages.action_panel import ActionPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_catalog_panel import DataCatalogPanel
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.floating_panel import FloatingPanel


class DataWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataWorkspace")

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("DataContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)

        self.asset_table = DataAssetTable()
        self.reader_panel = DataReaderPanel()
        self.content_splitter.addWidget(self.asset_table)
        self.content_splitter.addWidget(self.reader_panel)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([720, 520])
        layout.addWidget(self.content_splitter, 0, 0)

        self.catalog_panel = DataCatalogPanel()
        self.catalog_floating_panel = FloatingPanel(
            title="目录 / 筛选",
            tab_text="目录",
            content=self.catalog_panel,
        )
        layout.addWidget(
            self.catalog_floating_panel,
            0,
            0,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )

        self.action_panel = ActionPanel()
        self.actions_floating_panel = FloatingPanel(
            title="导入 / 操作",
            tab_text="操作",
            content=self.action_panel,
        )
        self.actions_floating_panel.set_expanded(True)
        layout.addWidget(
            self.actions_floating_panel,
            0,
            0,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )

    def toggle_catalog_panel(self) -> None:
        self.catalog_floating_panel.set_expanded(
            not self.catalog_floating_panel.is_expanded()
        )

    def toggle_actions_panel(self) -> None:
        self.actions_floating_panel.set_expanded(
            not self.actions_floating_panel.is_expanded()
        )

    def set_reader_visible(self, visible: bool) -> None:
        self.reader_panel.setVisible(visible)
