"""QgisLayerTreePanel：QgsLayerTreeView 承载的图层管理面板。

LayerManagerPanel（QTreeWidget 自绘树）的 drop-in 替换——同名 16 个信号与
bind/select_layer/layer_by_id/set_layer_visible/set_layer_opacity/move_layer/
set_editing_layer/set_project_crs/_publish 接缝，``self._layers`` 保持可读。

树的用户操作（勾选/拖拽/重命名/右键菜单）直接落在 QgsProject（运行时权威），
经 C++ 回调回写 ``_layers`` 后由 ``notify_display_changed`` 落持久化权威；
程序化 reconcile 走 suppress 计数器，不回声。
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from paleo_workbench.ui.qgis_stack.tree_sync import parse_tree_change
from paleo_workbench.ui.qgis_stack.widgets import QgisLayerTreeHost


def _icon(name: str):
    """延迟导入：workstation/__init__ → composite_document → 本模块存在环。"""
    from paleo_workbench.ui.workstation.common import workstation_icon

    return workstation_icon(name)

# 菜单动作键 → 面板请求信号名（C++ menu provider 的自定义键）
_MENU_SIGNALS = {
    "create_layer": "create_layer_requested",
    "import_reference": "import_reference_requested",
    "remove_layer": "remove_layer_requested",
    "remove_reference": "remove_reference_requested",
    "refresh_reference": "refresh_reference_requested",
    "toggle_reference_snap": "toggle_reference_snap_requested",
    "attribute_table": "attribute_table_requested",
    "toggle_editing": "toggle_editing_requested",
    "properties": "properties_requested",
    "symbology": "symbology_requested",
    "labeling": "labeling_requested",
    "duplicate": "duplicate_layer_requested",
    "export": "export_layer_requested",
    "repair": "repair_layer_requested",
}


class QgisLayerTreePanel(QWidget):
    """QgsLayerTreeView 图层管理面板（QGIS 图层面板语义）。"""

    create_layer_requested = Signal()
    remove_layer_requested = Signal(str)
    # 无 rename_layer_requested：树上改名直接生效并经 _on_tree_change 回写
    # （QGIS 语义，rename 不经请求信号绕行）。
    import_reference_requested = Signal()
    remove_reference_requested = Signal(str)
    refresh_reference_requested = Signal(str)
    toggle_reference_snap_requested = Signal(str)
    attribute_table_requested = Signal(str)
    toggle_editing_requested = Signal(str)
    properties_requested = Signal(str)
    symbology_requested = Signal(str)
    labeling_requested = Signal(str)
    duplicate_layer_requested = Signal(str)
    export_layer_requested = Signal(str)
    repair_layer_requested = Signal(str)
    # 当前图层变化（无可编辑图层时携带 None）。
    active_layer_changed = Signal(object)
    # 树回写/显示增量后的持久化通知（CompositeDocument 接 notify_display_changed）。
    display_state_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._layers: list = []
        self._canvas = None
        self._project_crs = ""
        self._editing_layer_id: str | None = None
        self._selected_doc_id: str | None = None
        self.tree_host: QgisLayerTreeHost | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self._outer = outer

        manage_row = QHBoxLayout()
        for label, icon, tip, callback in (
            ("新建矢量图层", "map/tree-add-layer.svg", "新建点 / 线 / 面矢量图层",
             self.create_layer_requested.emit),
            ("导入参考图层", "map/tree-add-layer.svg",
             "导入外部矢量文件作为只读参考（GDAL）", self.import_reference_requested.emit),
            ("删除图层", "map/tree-remove.svg", "删除当前矢量图层（编修图层）",
             self._on_remove_layer),
        ):
            button = QToolButton(self)
            button.setObjectName("WorkstationContextButton")
            button.setIcon(_icon(icon))
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

        opacity_row = QHBoxLayout()
        opacity_label = QLabel("不透明度", self)
        opacity_label.setObjectName("WorkstationPanelFootnote")
        opacity_row.addWidget(opacity_label)
        self.opacity = QSlider(Qt.Orientation.Horizontal, self)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(100)
        opacity_row.addWidget(self.opacity, 1)
        outer.addLayout(opacity_row)
        self.opacity.valueChanged.connect(self._apply_opacity)

    # -- 静态判定（与旧面板同语义） ---------------------------------------------

    @staticmethod
    def is_editable_layer(layer) -> bool:
        return bool(getattr(layer, "metadata", {}) and layer.metadata.get("editable") == "true")

    @staticmethod
    def is_reference_layer(layer) -> bool:
        return bool(getattr(layer, "metadata", {}) and layer.metadata.get("reference") == "true")

    # -- 绑定 ---------------------------------------------------------------

    def bind(self, canvas, layers: list) -> None:
        self._canvas = canvas
        self._layers = list(layers)
        if self.tree_host is None and canvas is not None:
            self.tree_host = QgisLayerTreeHost(canvas.stack, canvas.canvas_address, self)
            self._outer.insertWidget(1, self.tree_host, 1)
            tree = self.tree_host.tree_view_address
            canvas.stack.set_tree_selection_callback(tree, self._on_tree_selection)
            canvas.stack.set_tree_change_callback(tree, self._on_tree_change)
            canvas.stack.set_tree_menu_callback(tree, self._on_tree_menu)
        self._publish()

    def set_project_crs(self, crs: str) -> None:
        """注入项目 CRS 权威（ProjectDocument.coordinate → 渲染快照）。"""
        crs = str(crs or "")
        if crs and crs != self._project_crs:
            self._project_crs = crs

    def _make_snapshot(self):
        from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot

        return MapRenderSnapshot(
            project_crs=self._project_crs or "EPSG:4326",
            layers=tuple(self._layers),
        )

    def _publish(self, *, reload_tree: bool = True) -> None:
        """推快照到画布；树由 reconcile 自动跟随（reload_tree 仅保签名兼容）。"""
        if self._canvas is None:
            return
        self._canvas.set_layer_snapshot(self._make_snapshot())

    # -- 查询/选择 ------------------------------------------------------------

    def layer_by_id(self, layer_id: str):
        for layer in self._layers:
            if layer.id == layer_id:
                return layer
        return None

    def tree_row_count(self) -> int:
        """树顶层行数（测试/状态检查用；未绑定时为 0）。"""
        if self.tree_host is None or self._canvas is None:
            return 0
        return self._canvas.stack.tree_view_row_count(self.tree_host.tree_view_address)

    def select_layer(self, layer_id: str) -> None:
        """按 id 置为当前图层（QGIS 语义：新建图层即成为当前图层）。"""
        if self.tree_host is None or self._canvas is None:
            return
        self._canvas.stack.tree_view_select_doc(
            self.tree_host.tree_view_address, str(layer_id))

    def set_editing_layer(self, layer_id: str | None) -> None:
        """标记正在编辑的图层。

        M3（M2 移交项）：QgsLayerTreeView 以图层指示器呈现 ✏ 编辑态
        （QGIS 桌面同款视觉机制，不改节点名避免写回权威污染）。
        """
        previous = getattr(self, "_editing_layer_id", None)
        if layer_id == previous:
            return
        self._editing_layer_id = layer_id
        if self.tree_host is None or self._canvas is None:
            return
        tree = self.tree_host.tree_view_address
        for doc_id, on in ((previous, False), (layer_id, True)):
            if not doc_id:
                continue
            try:
                self._canvas.stack.set_edit_indicator(tree, str(doc_id), on)
            except Exception:
                pass

    # -- 外部显示增量（CompositeDocument 属性应用路径） ---------------------------

    def set_layer_visible(self, layer_id: str, visible: bool) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        self._layers[self._layers.index(layer)] = replace(layer, visible=visible)
        if self._canvas is not None and self.tree_host is not None:
            try:
                self._canvas.stack.set_mirror_layer_visibility(str(layer_id), bool(visible))
            except Exception:
                pass
        self._notify_display_changed()

    def set_layer_opacity(self, layer_id: str, opacity: float) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        opacity = max(0.05, float(opacity))
        self._layers[self._layers.index(layer)] = replace(layer, opacity=opacity)
        if self._canvas is not None and self.tree_host is not None:
            try:
                self._canvas.stack.set_mirror_layer_opacity(str(layer_id), opacity)
            except Exception:
                pass
        self._notify_display_changed()

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
        self._push_mirror_order()
        self._notify_display_changed()

    def _push_mirror_order(self) -> None:
        """把 _layers 的顶层顺序（top-first）推到镜像树（程序化，不 echo）。"""
        if self._canvas is None or self.tree_host is None:
            return
        try:
            self._canvas.stack.set_mirror_layer_order(
                [str(layer.id) for layer in self._layers])
        except Exception:
            pass

    # -- 树回调 ---------------------------------------------------------------

    def _on_tree_selection(self, doc_id: str) -> None:
        self._selected_doc_id = doc_id or None
        self._sync_opacity(self._selected_doc_id)
        layer = self.layer_by_id(doc_id) if doc_id else None
        self.remove_button.setEnabled(
            layer is not None and self.is_editable_layer(layer))
        self.active_layer_changed.emit(doc_id or None)

    def _on_tree_menu(self, key: str, doc_id: str) -> None:
        signal_name = _MENU_SIGNALS.get(str(key))
        if signal_name is None:
            return
        signal = getattr(self, signal_name)
        if signal_name in ("create_layer_requested", "import_reference_requested"):
            signal.emit()
        elif doc_id:
            signal.emit(str(doc_id))

    def _on_tree_change(self, payload: str) -> None:
        """树用户操作回写 _layers（不回推画布，防回环）+ 落持久化权威。"""
        changes = parse_tree_change(payload)
        if changes.empty:
            return
        for doc_id, visible in changes.visibility.items():
            layer = self.layer_by_id(doc_id)
            if layer is not None and layer.visible != visible:
                self._layers[self._layers.index(layer)] = replace(layer, visible=visible)
        for doc_id, name in changes.renames.items():
            layer = self.layer_by_id(doc_id)
            if layer is not None and layer.name != name:
                self._layers[self._layers.index(layer)] = replace(layer, name=name)
        if changes.order:
            listed = [self.layer_by_id(doc) for doc in changes.order]
            listed = [layer for layer in listed if layer is not None]
            listed_ids = {layer.id for layer in listed}
            unlisted = [layer for layer in self._layers if layer.id not in listed_ids]
            self._layers = listed + unlisted
        self._notify_display_changed()

    def _notify_display_changed(self) -> None:
        """通知宿主把显示增量写回编辑权威与工程文档（不重组快照）。"""
        self.display_state_changed.emit()

    # -- 工具行 ---------------------------------------------------------------

    def _on_remove_layer(self) -> None:
        if not self._layers:
            return
        layer_id = self._current_doc_id()
        if layer_id is None:
            return
        layer = self.layer_by_id(layer_id)
        if layer is not None and self.is_editable_layer(layer):
            self.remove_layer_requested.emit(str(layer_id))

    def _current_doc_id(self) -> str | None:
        """树当前图层的 doc_id（选择回调同步缓存，随 currentLayerChanged 更新）。"""
        return getattr(self, "_selected_doc_id", None)

    def _sync_opacity(self, doc_id: str | None) -> None:
        layer = self.layer_by_id(doc_id) if doc_id else None
        if layer is not None:
            self.opacity.blockSignals(True)
            self.opacity.setValue(int(layer.opacity * 100))
            self.opacity.blockSignals(False)

    def _apply_opacity(self, value: int) -> None:
        layer_id = self._current_doc_id()
        if layer_id is not None:
            self.set_layer_opacity(layer_id, value / 100.0)
