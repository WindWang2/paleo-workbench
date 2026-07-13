from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QWidget

from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel
from paleo_workbench.ui.pages.navigation_tree import NavigationTree


class DataWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataWorkspace")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("DataMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)

        self.navigation_tree = NavigationTree()
        self.asset_table = DataAssetTable()

        # Right column: vertical splitter of reader + inspector
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setChildrenCollapsible(False)
        self.reader_panel = DataReaderPanel()
        self.inspector_panel = InspectorPanel()
        self.right_splitter.addWidget(self.reader_panel)
        self.right_splitter.addWidget(self.inspector_panel)
        self.right_splitter.setStretchFactor(0, 2)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([400, 200])

        self.main_splitter.addWidget(self.navigation_tree)
        self.main_splitter.addWidget(self.asset_table)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([220, 600, 480])

        layout.addWidget(self.main_splitter)

    def set_right_visible(self, visible: bool) -> None:
        self.right_splitter.setVisible(visible)
