"""综合编修文档 — 主图居中、其余面板全部为 Qt 可浮动 dock 的编修环境。

架构（2026-09 评审裁决）：中央部件是图件画布；图层管理 / 输入与结果 /
联动视图全部是 ``QDockWidget``，享有 Qt 原生的完整窗口管理——停靠四边、
拖出浮动成独立窗口、面板间叠 tab、关闭后经「面板」菜单重开、
``saveState/restoreState`` 布局持久化（QSettings）。

图层管理是渲染快照的真实控制器：可见性 / 不透明度 / 顺序变更直接写回
:class:`UnifiedMapCanvas` 的快照并触发重渲染。
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSlider,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot
from paleo_workbench.mapping.workarea_map_snapshot import (
    WORKAREA_LEGEND_ITEMS,
    build_workarea_map_snapshot,
    workarea_view_extent,
)
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.ui.workstation.common import workstation_icon


class LayerManagerPanel(QFrame):
    """图层管理面板：可见性 / 不透明度 / 顺序 / 图例，真实写回渲染快照。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._layers: list = []
        self._canvas: UnifiedMapCanvas | None = None
        self._tree_connected = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索图层名称")
        self.search.setClearButtonEnabled(True)
        outer.addWidget(self.search)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        outer.addWidget(self.tree, 1)

        opacity_row = QHBoxLayout()
        opacity_label = QLabel("不透明度", self)
        opacity_label.setObjectName("WorkstationPanelFootnote")
        opacity_row.addWidget(opacity_label)
        self.opacity = QSlider(Qt.Orientation.Horizontal, self)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(100)
        opacity_row.addWidget(self.opacity, 1)
        outer.addLayout(opacity_row)

        order_row = QHBoxLayout()
        for label, icon, callback in (
            ("上移", "map/tree-move-up.svg", self._move_up),
            ("下移", "map/tree-move-down.svg", self._move_down),
        ):
            button = QToolButton(self)
            button.setObjectName("WorkstationContextButton")
            button.setIcon(workstation_icon(icon))
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.clicked.connect(callback)
            order_row.addWidget(button)
        order_row.addStretch(1)
        outer.addLayout(order_row)

        legend_title = QLabel("图例", self)
        legend_title.setObjectName("WorkstationPanelFootnote")
        outer.addWidget(legend_title)
        self.legend = QListWidget(self)
        self.legend.setObjectName("WorkstationTaskTree")
        self.legend.setMaximumHeight(96)
        for label, color in WORKAREA_LEGEND_ITEMS:
            item = QListWidgetItem(f"●  {label}")
            item.setForeground(QColor(color))
            self.legend.addItem(item)
        outer.addWidget(self.legend)

        self.search.textChanged.connect(self._filter)
        self.tree.currentItemChanged.connect(lambda *_: self._sync_opacity())
        self.opacity.valueChanged.connect(self._apply_opacity)

    # -- 绑定 ---------------------------------------------------------------

    def bind(self, canvas: UnifiedMapCanvas, layers: list) -> None:
        self._canvas = canvas
        self._layers = layers
        self._reload()

    # -- 快照变更（渲染自底向上：上移 = 提前 = index-1） ---------------------

    def layer_by_id(self, layer_id: str):
        for layer in self._layers:
            if layer.id == layer_id:
                return layer
        return None

    def set_layer_visible(self, layer_id: str, visible: bool) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        self._layers[self._layers.index(layer)] = replace(layer, visible=visible)
        self._publish()

    def set_layer_opacity(self, layer_id: str, opacity: float) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        self._layers[self._layers.index(layer)] = replace(
            layer, opacity=max(0.05, opacity)
        )
        self._publish()

    def move_layer(self, layer_id: str, direction: int) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        index = self._layers.index(layer)
        target = index - direction
        if not 0 <= target < len(self._layers):
            return
        self._layers[index], self._layers[target] = (
            self._layers[target],
            self._layers[index],
        )
        self._publish()

    def _publish(self) -> None:
        if self._canvas is None:
            return
        self._canvas.set_layer_snapshot(
            MapRenderSnapshot(project_crs="EPSG:4326", layers=tuple(self._layers))
        )
        self._reload()

    # -- 树 ------------------------------------------------------------------

    def _reload(self) -> None:
        if self._tree_connected:
            self.tree.itemChanged.disconnect(self._on_item_changed)
            self._tree_connected = False
        self.tree.clear()
        for layer in self._layers:
            item = QTreeWidgetItem([layer.name])
            item.setData(0, Qt.ItemDataRole.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0, Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
            )
            self.tree.addTopLevelItem(item)
        self.tree.itemChanged.connect(self._on_item_changed)
        self._tree_connected = True

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            item.setHidden(bool(text) and text not in item.text(0).lower())

    def _on_item_changed(self, item: QTreeWidgetItem) -> None:
        self.set_layer_visible(
            item.data(0, Qt.ItemDataRole.UserRole),
            item.checkState(0) == Qt.CheckState.Checked,
        )

    def _sync_opacity(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        layer = self.layer_by_id(item.data(0, Qt.ItemDataRole.UserRole))
        if layer is not None:
            self.opacity.blockSignals(True)
            self.opacity.setValue(int(layer.opacity * 100))
            self.opacity.blockSignals(False)

    def _apply_opacity(self, value: int) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self.set_layer_opacity(
                item.data(0, Qt.ItemDataRole.UserRole), value / 100.0
            )

    def _move_up(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self.move_layer(item.data(0, Qt.ItemDataRole.UserRole), +1)

    def _move_down(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self.move_layer(item.data(0, Qt.ItemDataRole.UserRole), -1)


class InputTreePanel(QFrame):
    """输入与结果树：编修输入（井 / 地震）与成果（图件文档）的真实清单。

    选中仅发布 payload（供后续联动接线），不做虚假交互。
    """

    object_selected = Signal(object)

    def __init__(self, project=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._project = project

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        outer.addWidget(self.tree, 1)
        self.refresh(project)

    def refresh(self, project) -> None:
        self._project = project
        self.tree.clear()
        if project is None:
            return

        wells = [
            str(getattr(w, "name", "") or "")
            for w in getattr(project, "wells", None) or []
            if str(getattr(w, "name", "") or "")
        ]
        seismic = [
            str(getattr(r, "name", "") or "")
            for r in getattr(project, "resources", None) or []
            if str(getattr(r, "type", "") or "") == "seismic"
        ]
        maps = [
            str(getattr(d, "name", "") or "")
            for d in getattr(project, "paleomap_documents", None) or []
            if str(getattr(d, "name", "") or "")
        ]

        for title, kind, names in (
            (f"井数据 ({len(wells)})", "well", wells),
            (f"地震数据 ({len(seismic)})", "seismic", seismic),
            (f"图件成果 ({len(maps)})", "map", maps),
        ):
            group = QTreeWidgetItem([title])
            self.tree.addTopLevelItem(group)
            for name in names:
                leaf = QTreeWidgetItem([name])
                leaf.setData(0, Qt.ItemDataRole.UserRole, {"kind": kind, "name": name})
                group.addChild(leaf)
            group.setExpanded(True)

    def _on_current_changed(self, current, _previous) -> None:
        if current is None:
            return
        payload = current.data(0, Qt.ItemDataRole.UserRole)
        if payload:
            self.object_selected.emit(payload)


class LinkedViewsPanel(QFrame):
    """联动视图面板：与图件选择联动的测井 / 地震视图（诚实空态）。

    真实联动视图（WellLogCanvasPanel / SeismicViewPanel）在后续迭代接入；
    当前显示待接入说明，不伪造内容。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        label = QLabel("联动视图（测井轨道 / 地震剖面）将在选择井位后于此加载。")
        label.setWordWrap(True)
        label.setObjectName("WorkstationPanelFootnote")
        layout.addWidget(label)
        layout.addStretch(1)


class CompositeDocument(QWidget):
    """综合编修文档：图件画布即主窗口内容（永不浮动），面板全部为宿主 dock。

    本部件只拥有主图与悬浮工具条；图层管理 / 输入与结果 / 联动视图三个
    面板实例在此创建、由 ``WorkstationFrame``（QMainWindow）注册为
    dock —— 图件显示区域就是主窗口的中央区域，其余一切皆可浮动。
    """

    object_selected = Signal(object)

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("CompositeDocument")
        self._project = project
        self._home_extent: tuple[float, float, float, float] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.canvas = UnifiedMapCanvas(parent=self)
        layout.addWidget(self.canvas, 1)

        # 面板实例（dock 由宿主 QMainWindow 创建并管理）
        self.layer_manager = LayerManagerPanel()
        self.input_tree = InputTreePanel(project)
        self.linked_views = LinkedViewsPanel()
        self.input_tree.object_selected.connect(self.object_selected.emit)

        self._build_toolbar()
        self.set_project(project)

    # -- 悬浮工具条 -----------------------------------------------------------

    def _build_toolbar(self) -> None:
        """悬浮工具条：仅图标（tooltip 提示），顶部居中，含「面板」菜单。"""
        self.toolbar = QFrame(self)
        self.toolbar.setObjectName("WorkstationContextBar")
        bar_layout = QHBoxLayout(self.toolbar)
        bar_layout.setContentsMargins(6, 3, 6, 3)
        bar_layout.setSpacing(3)

        def add_button(
            label: str, icon: str, tip: str, on_click=None,
            *, checkable: bool = False, enabled: bool = True,
        ) -> QToolButton:
            button = QToolButton(self.toolbar)
            button.setObjectName("WorkstationContextButton")
            button.setIcon(workstation_icon(icon))
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setToolTip(tip if enabled else f"{tip}（待接入）")
            button.setCheckable(checkable)
            button.setEnabled(enabled)
            if on_click is not None:
                button.clicked.connect(on_click)
            bar_layout.addWidget(button)
            return button

        # 平移是画布原生交互；选择/测距/查询等解释工具后续经 MapToolController 接入。
        self.pan_button = add_button("平移", "map/pan.svg", "平移", checkable=True)
        self.pan_button.setChecked(True)
        self.select_button = add_button(
            "选择", "map/select.svg", "选择", checkable=True, enabled=False
        )
        self.zoom_in_button = add_button(
            "缩放+", "map/zoom_in.svg", "放大", lambda: self.canvas.zoom_by(0.8)
        )
        self.zoom_out_button = add_button(
            "缩放-", "map/zoom_out.svg", "缩小", lambda: self.canvas.zoom_by(1.25)
        )
        self.home_button = add_button("全图", "map/full_extent.svg", "全图", self._zoom_home)
        self.previous_button = add_button(
            "上一视图", "map/previous_extent.svg", "上一视图", self.canvas.previous_extent
        )
        self.next_button = add_button(
            "下一视图", "map/next_extent.svg", "下一视图", self.canvas.next_extent
        )
        add_button("测距", "map/measure_distance.svg", "测距", enabled=False)
        add_button("查询", "map/identify.svg", "查询", enabled=False)
        self.canvas.extent_changed.connect(lambda *_: self._sync_history_buttons())

        # 面板菜单：宿主 dock 的显隐动作 + 恢复默认布局（动作由宿主注入）
        self.panels_button = QToolButton(self.toolbar)
        self.panels_button.setObjectName("WorkstationContextButton")
        self.panels_button.setIcon(workstation_icon("map/panel-manager.svg"))
        self.panels_button.setText("面板")
        self.panels_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.panels_button.setToolTip("显示 / 隐藏面板，恢复默认布局")
        self._panels_menu = QMenu(self.panels_button)
        self.panels_button.setMenu(self._panels_menu)
        self.panels_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        bar_layout.addWidget(self.panels_button)

        self.toolbar.adjustSize()

    def register_panel_actions(self, actions: list, reset_callable) -> None:
        """宿主 QMainWindow 注入 dock 显隐动作与恢复默认布局回调。"""
        for action in actions:
            self._panels_menu.addAction(action)
        self._panels_menu.addSeparator()
        self._panels_menu.addAction("恢复默认布局", reset_callable)

    def _sync_history_buttons(self) -> None:
        self.previous_button.setEnabled(self.canvas.can_previous_extent)
        self.next_button.setEnabled(self.canvas.can_next_extent)

    def _zoom_home(self) -> None:
        if self._home_extent is not None:
            self.canvas.set_extent(self._home_extent)

    # -- 工程绑定 -------------------------------------------------------------

    def set_project(self, project) -> None:
        self._project = project
        snapshot = build_workarea_map_snapshot(project)
        self.canvas.set_layer_snapshot(snapshot)
        self._home_extent = workarea_view_extent(snapshot)
        if self._home_extent is not None:
            self.canvas.set_extent(self._home_extent)
        self.layer_manager.bind(self.canvas, list(snapshot.layers))
        self.input_tree.refresh(project)

    # -- 悬浮工具条定位 ----------------------------------------------------------

    def _reposition_toolbar(self) -> None:
        self.toolbar.move((self.width() - self.toolbar.width()) // 2, 8)
        self.toolbar.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_toolbar()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._reposition_toolbar)

    # -- 生命周期 --------------------------------------------------------------

    def shutdown(self) -> None:
        """释放渲染后端（工程切换 / 退出时由 WorkstationFrame 调用）。"""
        self.canvas.shutdown()
