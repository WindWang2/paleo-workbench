from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel
from paleo_workbench.ui.pages.navigation_tree import NavigationTree
from paleo_workbench.ui.pages.project_overview_panel import ProjectOverviewPanel


class DataWorkspace(QWidget):
    def __init__(
        self,
        parent=None,
        *,
        well_state_store=None,
        comparison_crs: str = "",
    ):
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

        # Center column: 工区概览 panel stacked over the asset table.  The
        # 工区概览 tree node swaps the stack; every other node shows the table.
        self._center_stack = QStackedWidget()
        self._center_stack.setObjectName("DataCenterStack")
        self.overview_panel = ProjectOverviewPanel()
        self._center_stack.addWidget(self.asset_table)  # index 0 = table
        self._center_stack.addWidget(self.overview_panel)  # index 1 = overview

        # Right column: vertical splitter of reader + inspector
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setChildrenCollapsible(False)
        self.reader_panel = DataReaderPanel(
            well_state_store=well_state_store,
            comparison_crs=comparison_crs,
        )
        self.inspector_panel = InspectorPanel()
        self.right_splitter.addWidget(self.reader_panel)
        self.right_splitter.addWidget(self.inspector_panel)
        self.right_splitter.setStretchFactor(0, 2)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([400, 200])

        self.main_splitter.addWidget(self.navigation_tree)
        center_container = QWidget()
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self._center_stack)
        self.main_splitter.addWidget(center_container)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([220, 600, 480])

        layout.addWidget(self.main_splitter)

    def show_overview(self, visible: bool) -> None:
        """工区概览 node ↔ table swap (center column only)."""
        self._center_stack.setCurrentIndex(1 if visible else 0)

    def overview_visible(self) -> bool:
        return self._center_stack.currentIndex() == 1

    def set_right_visible(self, visible: bool) -> None:
        self.right_splitter.setVisible(visible)
