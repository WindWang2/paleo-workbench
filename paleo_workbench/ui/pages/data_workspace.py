from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui.dock_manager import dock_manager
from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.panel_float_controller import FloatController
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel
from paleo_workbench.ui.pages.navigation_tree import NavigationTree
from paleo_workbench.ui.pages.project_overview_panel import ProjectOverviewPanel
from paleo_workbench.ui.pages.well_map_panel import WellMapPanel

#: Delay before a splitter drag is persisted (avoid a QSettings sync per tick).
_DOCKED_SIZES_DELAY_MS = 400


class PanelFloatButton(QToolButton):
    """Corner button floating one side panel via a FloatController.

    Docked side of the FloatingPanel ⇲ dock-back chrome: pinned to the
    panel's top-right corner through an event filter and hidden while the
    panel is afloat (the floating window carries its own dock-back button).
    Pass ``pin=False`` to place the button into an existing header strip
    (the well-map fold header) instead of overlaying the panel corner.
    """

    def __init__(
        self,
        key: str,
        panel: QWidget,
        controller: FloatController,
        *,
        pin: bool = True,
    ):
        super().__init__(panel if pin else None)
        self._key = key
        self._panel = panel
        self._controller = controller
        self._pinned = pin
        self.setObjectName("PanelFloatButton")
        self.setText("⇱")
        self.setToolTip("浮动面板 (Float panel)")
        self.setFixedSize(18, 18)
        self.clicked.connect(lambda: self._controller.toggle(self._key))
        if pin:
            panel.installEventFilter(self)
        controller.float_changed.connect(self._on_float_changed)
        if pin:
            self._reposition()

    def _reposition(self) -> None:
        self.move(self._panel.width() - self.width() - 4, 2)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if obj is self._panel and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def _on_float_changed(self, key: str, floating: bool) -> None:
        if key == self._key:
            self.setVisible(not floating)


class DataWorkspace(QWidget):
    def __init__(
        self,
        parent=None,
        *,
        well_state_store=None,
        comparison_crs: str = "",
        persistence: LayoutPersistence | None = None,
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
        self._map_center_host = center_container
        self._center_layout = QVBoxLayout(center_container)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.addWidget(self._center_stack, 1)
        # 井位地图 collapsible panel under the table (§18: absorbed page).
        # While the 工区概览 node is active it moves into the overview page
        # as the main content (see show_overview).
        self.well_map_panel = WellMapPanel()
        self._center_layout.addWidget(self.well_map_panel, 0)
        self._map_collapsed_before_overview = True
        self.main_splitter.addWidget(center_container)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([220, 600, 480])

        layout.addWidget(self.main_splitter)

        # M6: the side panels float through the shared FloatController; the
        # center table/overview stack stays docked.
        self._float_persistence = (
            persistence if persistence is not None else LayoutPersistence()
        )
        self._floatable: dict[str, QWidget] = {}
        self.float_controller = FloatController(
            resolver=self._floatable.get,
            persistence=self._float_persistence,
            parent=self,
        )
        self._make_floatable("data:navigation", self.navigation_tree, "数据导航树")
        self._make_floatable("data:reader", self.reader_panel, "数据预览")
        self._make_floatable("data:inspector", self.inspector_panel, "数据资产检查器")
        self._make_floatable("data:well_map", self.well_map_panel, "井位地图")
        # 井位地图 has its own fold header; its float toggle lives there
        # instead of the corner overlay.
        self.well_map_panel.add_header_button(
            PanelFloatButton(
                "data:well_map", self.well_map_panel, self.float_controller, pin=False
            )
        )
        self.float_controller.float_changed.connect(self._on_map_float_changed)
        self._map_collapsed_before_float = True
        self._float_sizes_timer = QTimer(self)
        self._float_sizes_timer.setSingleShot(True)
        self._float_sizes_timer.setInterval(_DOCKED_SIZES_DELAY_MS)
        self._float_sizes_timer.timeout.connect(self._persist_docked_sizes)
        self.main_splitter.splitterMoved.connect(self._on_splitter_moved)
        self.right_splitter.splitterMoved.connect(self._on_splitter_moved)
        for key in self._floatable:
            self.float_controller.restore_saved(key)

    def _make_floatable(self, key: str, panel: QWidget, title: str) -> None:
        """Register a side panel for float/dock and give it a float button."""
        dock_manager.register_panel(key, title)
        self._floatable[key] = panel
        PanelFloatButton(key, panel, self.float_controller)

    def _on_splitter_moved(self, *_pos: int) -> None:
        self._float_sizes_timer.start()

    def _on_map_float_changed(self, key: str, floating: bool) -> None:
        """Expand the afloat map and rebuild its fold slot after docking.

        FloatController re-parents to the recorded dock context, but a
        layout-parented widget needs an explicit layout re-insert to take
        part in the layout again (its splitter restore can also drop it into
        an ancestor splitter slot); a collapsed map would surface as an empty
        floating window, so floating expands and docking restores the fold.
        """
        if key != "data:well_map":
            return
        if floating:
            self._map_collapsed_before_float = self.well_map_panel.is_collapsed()
            self.well_map_panel.set_collapsed(False)
            return
        lost_from_fold = (
            self.well_map_panel.parentWidget() is not self._map_center_host
            or self._center_layout.indexOf(self.well_map_panel) == -1
        )
        if lost_from_fold:
            self._center_layout.addWidget(self.well_map_panel, 0)
        self.well_map_panel.set_collapsed(self._map_collapsed_before_float)

    def _persist_docked_sizes(self) -> None:
        """Persist the splitter distribution for every docked side panel."""
        for key, panel in self._floatable.items():
            splitter = panel.parentWidget()
            if isinstance(splitter, QSplitter):
                self._float_persistence.save_docked_sizes(key, list(splitter.sizes()))

    def show_overview(self, visible: bool) -> None:
        """工区概览 node ↔ table swap (center column only).

        Overview mode reparents the shared well-map panel into the overview
        page — 工区概况下面直接显示工区图，展开占满主区域；切回数据表时
        地图回到表格下方的折叠面板并恢复之前的折叠状态。
        While the map panel is floating the swap is skipped entirely: the
        controller owns the afloat widget until it is docked back.
        """
        map_afloat = self.float_controller.is_floating("data:well_map")
        self._center_stack.setCurrentIndex(1 if visible else 0)
        if visible:
            self._map_collapsed_before_overview = self.well_map_panel.is_collapsed()
            if map_afloat:
                return
            self.overview_panel.set_map_widget(self.well_map_panel)
            self.well_map_panel.set_header_visible(False)
            self.well_map_panel.set_collapsed(False)
        else:
            if map_afloat:
                return
            self._center_layout.addWidget(self.well_map_panel, 0)
            self.well_map_panel.set_header_visible(True)
            self.well_map_panel.set_collapsed(self._map_collapsed_before_overview)

    def overview_visible(self) -> bool:
        return self._center_stack.currentIndex() == 1

    def set_right_visible(self, visible: bool) -> None:
        self.right_splitter.setVisible(visible)
