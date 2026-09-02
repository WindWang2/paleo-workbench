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
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
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
from paleo_workbench.ui.map_action_controller import MapActionController
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.ui.workstation.common import workstation_icon
from paleo_workbench.ui.workstation.composite_editing import (
    GEO_TEMPLATES,
    GEOMETRY_KINDS,
    CompositeEditController,
)

_GEOMETRY_TYPE_KIND = {
    "Point": "point",
    "MultiPoint": "point",
    "LineString": "line",
    "MultiLineString": "line",
    "Polygon": "polygon",
    "MultiPolygon": "polygon",
}


def _snapshot_geometry_kind(layer) -> str:
    """图层几何类型：编辑图层取元数据权威，基础图层嗅探首个要素。"""
    metadata = getattr(layer, "metadata", None) or {}
    kind = str(metadata.get("geometry_kind") or "")
    if kind in GEOMETRY_KINDS:
        return kind
    for feature in getattr(layer, "features", ()) or ():
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if isinstance(geometry, dict):
            return _GEOMETRY_TYPE_KIND.get(str(geometry.get("type") or ""), "")
    return ""


def _layer_kind_icon(kind: str, style: dict) -> QIcon:
    """QGIS 式图层树类型图标：按几何类型绘制 16px 符号。"""
    style = style or {}
    color_name = str(style.get("stroke") or "")
    if not color_name or color_name == "transparent":
        color_name = str(style.get("fill") or "") or "#868e96"
    color = QColor(color_name)
    if not color.isValid():
        color = QColor("#868e96")
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind == "point":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(3, 3, 10, 10)
    elif kind == "polygon":
        fill = QColor(color)
        fill.setAlpha(110)
        painter.setBrush(fill)
        painter.setPen(QPen(color, 1.4))
        painter.drawRect(2, 3, 12, 10)
    else:  # 线（含未知类型的保守回退）
        painter.setPen(QPen(color, 2.0))
        painter.drawLine(1, 13, 7, 8)
        painter.drawLine(7, 8, 15, 3)
    painter.end()
    return QIcon(pixmap)


class LayerManagerPanel(QFrame):
    """图层管理面板：可见性 / 不透明度 / 顺序 / 图例，真实写回渲染快照。

    矢量图层的新建与删除不在此直接执行——面板只发请求信号，由
    ``CompositeDocument`` 经 ``CompositeEditController`` 落地后重绑。
    """

    create_layer_requested = Signal()
    remove_layer_requested = Signal(str)
    rename_layer_requested = Signal(str)
    # 当前图层变化（无可编辑图层时携带 None）。
    active_layer_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._layers: list = []
        self._canvas: UnifiedMapCanvas | None = None
        self._tree_connected = False
        self._editing_layer_id: str | None = None
        self._reloading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索图层名称")
        self.search.setClearButtonEnabled(True)
        outer.addWidget(self.search)

        manage_row = QHBoxLayout()
        for label, icon, tip, callback in (
            ("新建矢量图层", "map/tree-add-layer.svg", "新建点 / 线 / 面矢量图层", self._on_create_layer),
            ("删除图层", "map/tree-remove.svg", "删除当前矢量图层（编修图层）", self._on_remove_layer),
        ):
            button = QToolButton(self)
            button.setObjectName("WorkstationContextButton")
            button.setIcon(workstation_icon(icon))
            button.setText(label)
            button.setToolTip(tip)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.clicked.connect(callback)
            manage_row.addWidget(button)
            if label == "删除图层":
                self.remove_button = button
        self.remove_button.setEnabled(False)
        manage_row.addStretch(1)
        outer.addLayout(manage_row)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        # QGIS 图层面板语义：右键 = 图层上下文菜单（缩放到图层 / 重命名 / 删除）。
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
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
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.opacity.valueChanged.connect(self._apply_opacity)

    # -- 矢量图层管理（请求信号，由宿主落地） --------------------------------------

    def _on_create_layer(self) -> None:
        self.create_layer_requested.emit()

    def _on_remove_layer(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        layer_id = item.data(0, Qt.ItemDataRole.UserRole)
        layer = self.layer_by_id(layer_id)
        if layer is not None and self.is_editable_layer(layer):
            self.remove_layer_requested.emit(str(layer_id))

    @staticmethod
    def is_editable_layer(layer) -> bool:
        return bool(getattr(layer, "metadata", {}) and layer.metadata.get("editable") == "true")

    def _on_context_menu(self, position) -> None:
        """图层上下文菜单（QGIS 图层面板的核心动作子集）。"""
        item = self.tree.itemAt(position)
        if item is None:
            return
        layer_id = str(item.data(0, Qt.ItemDataRole.UserRole))
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        editable = self.is_editable_layer(layer)
        menu = QMenu(self.tree)
        zoom = menu.addAction(workstation_icon("map/tree-zoom.svg"), "缩放到图层")
        extent = getattr(layer, "extent", None)
        has_extent = bool(extent) and extent[0] < extent[2] and extent[1] < extent[3]
        zoom.setEnabled(has_extent)
        if editable:
            menu.addSeparator()
            rename = menu.addAction(workstation_icon("map/tree-properties.svg"), "重命名图层…")
            remove = menu.addAction(workstation_icon("map/tree-remove.svg"), "删除图层")
        else:
            rename = remove = None
        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen is zoom and self._canvas is not None:
            self._canvas.set_extent(tuple(float(v) for v in extent))
        elif rename is not None and chosen is rename:
            self.rename_layer_requested.emit(layer_id)
        elif remove is not None and chosen is remove:
            self.remove_layer_requested.emit(layer_id)

    def set_editing_layer(self, layer_id: str | None) -> None:
        """标记正在编辑的图层（树项前缀 ✏，QGIS 的 in-edit 视觉语义）。"""
        if layer_id == getattr(self, "_editing_layer_id", None):
            return
        self._editing_layer_id = layer_id
        self._reload()

    def _on_current_changed(self, current, _previous) -> None:
        self._sync_opacity()
        editable = False
        if current is not None:
            layer = self.layer_by_id(current.data(0, Qt.ItemDataRole.UserRole))
            editable = layer is not None and self.is_editable_layer(layer)
        self.remove_button.setEnabled(editable)
        if not getattr(self, "_reloading", False):
            self.active_layer_changed.emit(
                current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
            )

    # -- 绑定 ---------------------------------------------------------------

    def bind(self, canvas: UnifiedMapCanvas, layers: list) -> None:
        self._canvas = canvas
        self._layers = layers
        self._reload()

    def select_layer(self, layer_id: str) -> None:
        """按 id 置为当前图层（QGIS 语义：新建图层即成为当前图层）。"""
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            if str(item.data(0, Qt.ItemDataRole.UserRole)) == str(layer_id):
                self.tree.setCurrentItem(item)
                return

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
        # 重组快照会触发重载：保持当前图层选中，避免编辑态在每次内容
        # 变更后被树清空信号误重置。
        current = self.tree.currentItem()
        current_id = (
            str(current.data(0, Qt.ItemDataRole.UserRole)) if current is not None else None
        )
        self._reloading = True
        try:
            self.tree.clear()
            restored = None
            for layer in self._layers:
                label = layer.name
                if self.is_editable_layer(layer):
                    label = f"✏ {label}" if layer.id == self._editing_layer_id else f"{label}（矢量）"
                item = QTreeWidgetItem([label])
                item.setData(0, Qt.ItemDataRole.UserRole, layer.id)
                item.setIcon(
                    0,
                    _layer_kind_icon(
                        _snapshot_geometry_kind(layer), getattr(layer, "style", None)
                    ),
                )
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0, Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
                )
                self.tree.addTopLevelItem(item)
                if current_id is not None and layer.id == current_id:
                    restored = item
            if restored is not None:
                self.tree.setCurrentItem(restored)
            # 重载只刷新按钮态（不emit active_layer_changed——活动图层是
            # 编辑控制器的权威状态，树重载不得将其重置）。
            self._on_current_changed(self.tree.currentItem(), None)
        finally:
            self._reloading = False
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
        self._loading = False
        self._home_extent: tuple[float, float, float, float] | None = None
        self._base_layers: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.canvas = UnifiedMapCanvas(parent=self)
        layout.addWidget(self.canvas, 1)

        # 矢量图层新建 / 编辑（QGIS 式编辑会话，见 composite_editing.py）
        self.edit_controller = CompositeEditController(parent=self)
        self.edit_controller.attach_canvas(self.canvas)
        self.edit_controller.layers_changed.connect(self._sync_composition)
        self.edit_controller.content_changed.connect(lambda *_: self._sync_composition())
        self.edit_controller.state_changed.connect(self._sync_action_state)
        self.canvas.tool_operation.connect(self._on_tool_operation)
        self.canvas.extent_changed.connect(lambda *_: self._sync_action_state())

        # 面板实例（dock 由宿主 QMainWindow 创建并管理）
        self.layer_manager = LayerManagerPanel()
        self.input_tree = InputTreePanel(project)
        self.linked_views = LinkedViewsPanel()
        self.input_tree.object_selected.connect(self.object_selected.emit)
        self.layer_manager.create_layer_requested.connect(self._create_vector_layer)
        self.layer_manager.remove_layer_requested.connect(self._remove_vector_layer)
        self.layer_manager.rename_layer_requested.connect(self._rename_vector_layer)
        self.layer_manager.active_layer_changed.connect(
            self.edit_controller.set_active_layer
        )

        self._build_toolbar()
        self.set_project(project)

    # -- 悬浮工具条 -----------------------------------------------------------

    def _build_toolbar(self) -> None:
        """悬浮工具条：QGIS 命令面（MapActionController）+「面板」菜单。"""
        self.toolbar = QFrame(self)
        # Overlay chrome (not the linked-doc context bar): hairline floating strip.
        self.toolbar.setObjectName("WorkstationOverlayToolbar")
        self.toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar_layout = QHBoxLayout(self.toolbar)
        bar_layout.setContentsMargins(5, 2, 5, 2)
        bar_layout.setSpacing(2)

        self.action_controller = MapActionController(self)
        bar_layout.addWidget(
            self.action_controller.toolbar(
                "综合编修",
                (
                    ("pan", "zoom_in", "zoom_out", "full_extent", "previous_extent", "next_extent"),
                    ("identify", "select", "select_rectangle", "measure_distance"),
                    ("toggle_editing", "save_edits", "rollback"),
                    ("add_point", "add_line", "add_polygon", "move_feature", "vertex"),
                    ("undo", "redo", "delete_selected"),
                    ("snapping", "cancel"),
                ),
                self.toolbar,
            )
        )
        self.action_controller.tool_requested.connect(
            self.edit_controller.activate_tool
        )
        self.action_controller.command_requested.connect(self._on_command_requested)

        # 面板菜单：显隐 / 布局预设 / 全部浮动·停靠 / 恢复默认（由宿主注入）
        self.panels_button = QToolButton(self.toolbar)
        self.panels_button.setObjectName("WorkstationContextButton")
        self.panels_button.setIcon(workstation_icon("map/panel-manager.svg"))
        self.panels_button.setText("面板")
        self.panels_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.panels_button.setToolTip("面板显隐、布局预设、全部浮动 / 停靠")
        self._panels_menu = QMenu(self.panels_button)
        self.panels_button.setMenu(self._panels_menu)
        self.panels_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        bar_layout.addWidget(self.panels_button)

        self.toolbar.adjustSize()

    def register_panel_actions(
        self,
        actions: list,
        reset_callable,
        *,
        float_all_callable=None,
        dock_all_callable=None,
        layout_presets: list | None = None,
        apply_preset_callable=None,
    ) -> None:
        """宿主注入 dock 显隐、布局预设与浮动/停靠批量动作。"""
        self._panels_menu.clear()
        visibility = self._panels_menu.addMenu("显示面板")
        for action in actions:
            visibility.addAction(action)
        if layout_presets and apply_preset_callable is not None:
            layouts = self._panels_menu.addMenu("布局预设")
            for preset_id, label in layout_presets:
                layouts.addAction(
                    label,
                    lambda checked=False, pid=preset_id: apply_preset_callable(pid),
                )
        self._panels_menu.addSeparator()
        if float_all_callable is not None:
            self._panels_menu.addAction("全部浮动", float_all_callable)
        if dock_all_callable is not None:
            self._panels_menu.addAction("全部停靠", dock_all_callable)
        self._panels_menu.addSeparator()
        self._panels_menu.addAction("恢复默认布局", reset_callable)

    def _zoom_home(self) -> None:
        if self._home_extent is not None:
            self.canvas.set_extent(self._home_extent)

    # -- 命令与工具回调 ----------------------------------------------------------

    def _on_command_requested(self, command_id: str) -> None:
        if command_id == "full_extent":
            self._zoom_home()
        elif command_id == "previous_extent":
            self.canvas.previous_extent()
        elif command_id == "next_extent":
            self.canvas.next_extent()
        elif command_id == "cancel":
            self.edit_controller.cancel_active_tool()
        elif command_id == "snapping":
            self.edit_controller.set_snapping(
                self.action_controller.actions["snapping"].isChecked()
            )
        elif command_id in {"clear_selection", "select_all", "invert_selection"}:
            self.edit_controller.selection_command(command_id)
        elif command_id == "toggle_editing":
            if self.edit_controller.editing:
                self.edit_controller.save_edits()
            else:
                self.edit_controller.start_editing()
        elif command_id == "save_edits":
            self.edit_controller.save_edits()
        elif command_id == "rollback":
            self.edit_controller.rollback_edits()
        elif command_id in {"undo", "redo", "delete_selected"}:
            self.edit_controller.edit_command(command_id)
        self._sync_action_state()

    def _on_tool_operation(self, edits_data: bool = True) -> None:
        """工具操作回执：数据编辑重组快照，纯选择 / 指针反馈只刷状态。"""
        if edits_data:
            self._sync_composition()
        else:
            self.canvas.update()
        self._sync_action_state()

    def _sync_action_state(self) -> None:
        self.action_controller.update_state(
            self.edit_controller.action_state(
                can_previous_extent=self.canvas.can_previous_extent,
                can_next_extent=self.canvas.can_next_extent,
            )
        )
        controller = self.edit_controller
        self.layer_manager.set_editing_layer(
            controller.active_layer_id if controller.editing else None
        )

    # -- 矢量图层新建 / 删除 / 重命名 ------------------------------------------------

    def _create_vector_layer(self) -> None:
        """新建矢量图层对话框：地质模板按 点 / 线 / 面 分组 + 自定义类型。"""
        dialog = QDialog(self)
        dialog.setObjectName("CompositeNewVectorLayerDialog")
        dialog.setWindowTitle("新建矢量图层")
        layout = QVBoxLayout(dialog)
        template_list = QListWidget(dialog)
        template_list.setObjectName("CompositeTemplateList")

        def add_header(title: str) -> None:
            item = QListWidgetItem(title)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#8a94a6"))
            template_list.addItem(item)

        def add_entry(label: str, kind: str, template: str = "") -> None:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (kind, template, label))
            item.setIcon(_layer_kind_icon(kind, {}))
            template_list.addItem(item)

        add_header("点")
        for template in GEO_TEMPLATES:
            if template.kind == "point":
                add_entry(template.label, template.kind, template.key)
        add_entry("自定义点图层", "point")
        add_header("线")
        for template in GEO_TEMPLATES:
            if template.kind == "line":
                add_entry(template.label, template.kind, template.key)
        add_entry("自定义线图层", "line")
        add_header("面")
        for template in GEO_TEMPLATES:
            if template.kind == "polygon":
                add_entry(template.label, template.kind, template.key)
        add_entry("自定义面图层", "polygon")
        layout.addWidget(template_list, 1)

        form = QFormLayout()
        name_edit = QLineEdit(dialog)
        form.addRow("图层名称", name_edit)
        layout.addLayout(form)

        def on_selection() -> None:
            item = template_list.currentItem()
            data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if data:
                _kind, template_key, label = data
                count = len(self.edit_controller.layer_ids()) + 1
                name_edit.setText(label if template_key else f"{label} {count}")

        template_list.currentItemChanged.connect(lambda *_: on_selection())
        template_list.itemDoubleClicked.connect(lambda *_: dialog.accept())
        first = next(
            (
                template_list.item(row)
                for row in range(template_list.count())
                if template_list.item(row).data(Qt.ItemDataRole.UserRole)
            ),
            None,
        )
        if first is not None:
            template_list.setCurrentItem(first)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            item = template_list.currentItem()
            data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if not data:
                return
            kind, template_key, _label = data
            self.edit_controller.create_layer(
                name_edit.text().strip(), kind, template=template_key
            )

    def _rename_vector_layer(self, layer_id: str) -> None:
        layer = self.edit_controller.layer(layer_id)
        if layer is None:
            return
        name, ok = QInputDialog.getText(
            self, "重命名图层", "图层名称", text=layer.name
        )
        if ok:
            self.edit_controller.rename_layer(layer_id, name)

    def _remove_vector_layer(self, layer_id: str) -> None:
        self.edit_controller.remove_layer(layer_id)

    # -- 快照合成 ------------------------------------------------------------------

    def _sync_composition(self) -> None:
        """基础工区图层 + 用户矢量图层合并发布到画布与图层管理面板。"""
        display = {
            layer.id: layer for layer in self.layer_manager._layers
        }
        layers = list(self._base_layers)
        layers.extend(self.edit_controller.snapshot_layers(display=display))
        if self._project is not None and not self._loading:
            # 人工建数据写回工程文档，纳入数据管理（磁盘保存走工程保存）。
            self.edit_controller.sync_to_project(self._project)
        self.layer_manager.bind(self.canvas, layers)
        active_id = self.edit_controller.active_layer_id
        if active_id is not None:
            self.layer_manager.select_layer(active_id)
        self.layer_manager._publish()

    # -- 工程绑定 -------------------------------------------------------------

    def set_project(self, project) -> None:
        self._project = project
        snapshot = build_workarea_map_snapshot(project)
        self._base_layers = list(snapshot.layers)
        self.edit_controller.project_crs = snapshot.project_crs
        self._home_extent = workarea_view_extent(snapshot)
        if self._home_extent is not None:
            self.canvas.set_extent(self._home_extent)
        self._loading = True
        try:
            self.edit_controller.load_from_project(project)
        finally:
            self._loading = False
        self._sync_composition()
        self.input_tree.refresh(project)

    # -- 悬浮工具条定位 ----------------------------------------------------------

    def _reposition_toolbar(self) -> None:
        """Centre the overlay on the map; keep a hairline margin from edges.

        Floating QDockWidgets are separate top-level windows, so they never
        stack under this toolbar. Within the canvas we always raise the bar
        above map chrome and leave 8px top / ≥12px side inset so it does not
        collide with docked panel edges on narrow widths.
        """
        self.toolbar.adjustSize()
        margin_x = 12
        y = 8
        x = max(margin_x, (self.width() - self.toolbar.width()) // 2)
        max_x = max(margin_x, self.width() - self.toolbar.width() - margin_x)
        self.toolbar.move(min(x, max_x), y)
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
