"""编图文档 — 主图居中、其余面板全部为 Qt 可浮动 dock 的编修环境。

架构（2026-09 评审裁决）：中央部件是图件画布；图层管理 / 输入与结果 /
联动视图全部是 ``QDockWidget``，享有 Qt 原生的完整窗口管理——停靠四边、
拖出浮动成独立窗口、面板间叠 tab、关闭后经「面板」菜单重开、
``saveState/restoreState`` 布局持久化（QSettings）。

图层管理是渲染快照的真实控制器：可见性 / 不透明度 / 顺序变更直接写回
鸭子类型画布（UnifiedMapCanvas / QgisCanvasShim）的快照并触发重渲染。QGIS 收敛（2026-09 第二轮）：
图层属性 / 符号系统 / 标注复用 :class:`MapLayerPropertiesDialog` 与
``map_symbology_bridge``（桥未构建时走 legacy 快速字段，renderer XML 仍是
QGIS 权威）；属性表 / 识别结果 / 捕捉设置 / split·merge·topology 全部
落在 ``VectorEditSession`` 编辑权威上。
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
import zlib

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
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

from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot
from paleo_workbench.mapping.map_styles import LinePattern, MarkerSymbol, VectorStyle
from paleo_workbench.mapping.reference_layers import (
    ReferenceLayerError,
    ReferenceLayerService,
)
from paleo_workbench.mapping.workarea_map_snapshot import (
    WORKAREA_LEGEND_ITEMS,
    build_workarea_map_snapshot,
    workarea_view_extent,
)
from paleo_workbench.project.domain import crs_equivalent
from paleo_workbench.project.models import MapReferenceLayer
from paleo_workbench.ui.map_action_controller import MapActionController
from paleo_workbench.ui.map_layer_properties import MapLayerPropertiesDialog
from paleo_workbench.ui.map_status_bar import MapStatusBar
from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.ui.workstation.common import workstation_icon
from paleo_workbench.ui.workstation.tool_surface import (
    LayerCapabilitySnapshot,
    QgisCapabilitySnapshot,
    ToolAvailability,
    ToolContext,
    availability_for_context,
)
from paleo_workbench.ui.workstation.composite_attribute_table import (
    CompositeAttributeTableDialog,
)
from paleo_workbench.ui.workstation.composite_editing import (
    GEOMETRY_KINDS,
    GEO_TEMPLATES,
    CompositeEditController,
    _feature_extent,
    schema_fields,
)
from paleo_workbench.ui.workstation.composite_panels import (
    IdentifyResultsPanel,
    SnappingSettingsDialog,
)

_GEOMETRY_TYPE_KIND = {
    "Point": "point",
    "MultiPoint": "point",
    "LineString": "line",
    "MultiLineString": "line",
    "Polygon": "polygon",
    "MultiPolygon": "polygon",
}

# 引用矢量图层的默认符号：刻意区别于编修图层（ muted 蓝灰 + 虚线），
# 视觉上一眼可分「外部参考」与「本工程数字化」。
_REFERENCE_STYLES: dict[str, dict] = {
    "point": VectorStyle(
        fill="#8fa3b8",
        stroke="#3d4a5c",
        stroke_width=1.0,
        marker=MarkerSymbol.CIRCLE,
        marker_size=5.0,
    ).to_dict(),
    "line": VectorStyle(
        fill="transparent",
        stroke="#7c8fa6",
        stroke_width=1.2,
        line_pattern=LinePattern.DASH,
    ).to_dict(),
    "polygon": VectorStyle(
        fill="#1e64748b",
        stroke="#64748b",
        stroke_width=1.0,
    ).to_dict(),
}

# QFileDialog 的 GDAL 矢量过滤（未列出的 GDAL 格式仍可经「所有文件」导入）。
_REFERENCE_IMPORT_FILTER = (
    "矢量参考图层 (*.shp *.geojson *.json *.gpkg *.kml *.gml *.gmt *.csv *.vrt);;"
    "所有文件 (*)"
)


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


#: 状态 tone → tokens palette 键（V7 §7 状态列前景色；随主题重取）。
_TONE_PALETTE_KEYS = {
    "ok": "SUCCESS",
    "warn": "WARNING",
    "error": "ERROR_RED",
    "info": "PRIMARY",
    "muted": "TEXT_SECONDARY",
    "locked": "TEXT_SECONDARY",
}


def _decoration_color(tone: str):
    """状态列前景色（theme-aware；每次调用重取，勿缓存）。"""
    from paleo_workbench.ui import style

    palette = style.palette()
    key = _TONE_PALETTE_KEYS.get(str(tone))
    value = palette.get(key) if key else None
    if not value:
        return None
    color = QColor(str(value))
    return color if color.isValid() else None


class _LayerPropertiesAdapter:
    """``MapLayerPropertiesDialog`` 的图层视图（VectorLayer + 显示态合成）。

    对话框只读这些展示字段；编辑结果经 ``properties_applied`` 回到
    ``CompositeEditController`` 的图层权威，不产生平行图层状态。
    """

    def __init__(self, layer, *, opacity: float = 1.0, metadata: dict | None = None):
        self.id = layer.id
        self.name = layer.name
        self.type = "vector"
        self.crs = layer.crs
        self.opacity = opacity
        self.source_ref = "composite-digitizing"
        self.data_revision = layer.data_revision
        self.style_revision = layer.style_revision
        self.metadata = metadata or {}
        self.provenance_ref = ""


class LayerManagerPanel(QFrame):
    """图层管理面板：可见性 / 不透明度 / 顺序 / 图例，真实写回渲染快照。

    矢量图层的新建与删除不在此直接执行——面板只发请求信号，由
    ``CompositeDocument`` 经 ``CompositeEditController`` 落地后重绑。
    """

    create_layer_requested = Signal()
    remove_layer_requested = Signal(str)
    rename_layer_requested = Signal(str)
    # 引用矢量图层（外部 GDAL 源，只读参考）的导入与上下文动作。
    import_reference_requested = Signal()
    remove_reference_requested = Signal(str)
    refresh_reference_requested = Signal(str)
    toggle_reference_snap_requested = Signal(str)
    # QGIS 图层面板语义的上下文动作（由 CompositeDocument 落地）。
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
    # V7 §7：双击定位（zoom to layer；由 CompositeDocument 落地）。
    zoom_to_layer_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._layers: list = []
        self._canvas: QgisCanvasShim | None = None
        self._tree_connected = False
        self._editing_layer_id: str | None = None
        self._reloading = False
        # V7 §7 呈现态（id → LayerPresentationState；空 = 无装饰）。
        self._decorations: dict = {}
        # 项目 CRS 权威来自 ProjectDocument.coordinate（经 CompositeDocument
        # 注入）；面板只提交显示增量，绝不自行猜测 CRS。
        self._project_crs = ""

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
            ("导入参考图层", "map/tree-add-layer.svg", "导入外部矢量文件作为只读参考（GDAL）", self._on_import_reference),
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
        # V7 §7：第 2 列 = 状态装饰（glyph+label；hover 摘要看 tooltip）。
        self.tree.setColumnCount(2)
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnWidth(1, 96)
        # QGIS 图层面板语义：右键 = 图层上下文菜单（缩放到图层 / 重命名 / 删除）。
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        # 双击 = 定位问题图层（选中 + 缩放；goal §7「定位问题 feature/layer」）。
        self.tree.itemDoubleClicked.connect(
            lambda item, _col: self.zoom_to_layer_requested.emit(
                str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            )
        )
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

    def _on_import_reference(self) -> None:
        self.import_reference_requested.emit()

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

    @staticmethod
    def is_reference_layer(layer) -> bool:
        return bool(getattr(layer, "metadata", {}) and layer.metadata.get("reference") == "true")

    def _on_context_menu(self, position) -> None:
        """图层上下文菜单（QGIS 图层面板的核心动作集）。"""
        item = self.tree.itemAt(position)
        if item is None:
            return
        layer_id = str(item.data(0, Qt.ItemDataRole.UserRole))
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        editable = self.is_editable_layer(layer)
        is_reference = self.is_reference_layer(layer)
        menu = QMenu(self.tree)
        zoom = menu.addAction(workstation_icon("map/tree-zoom.svg"), "缩放到图层")
        extent = getattr(layer, "extent", None)
        has_extent = (
            bool(extent)
            and extent[0] < extent[2]
            and extent[1] < extent[3]
            # 空图层会拿到 (0,0,1,1) 的占位范围（review #16），无缩放语义。
            and bool(tuple(getattr(layer, "features", ()) or ()))
        )
        zoom.setEnabled(has_extent)
        refresh = toggle_snap = remove_reference = None
        if is_reference:
            menu.addSeparator()
            refresh = menu.addAction("刷新引用（重读源文件）")
            metadata = getattr(layer, "metadata", None) or {}
            toggle_snap = menu.addAction("参与捕捉")
            toggle_snap.setCheckable(True)
            toggle_snap.setChecked(metadata.get("snap") == "true")
            remove_reference = menu.addAction(workstation_icon("map/tree-remove.svg"), "移除引用…")
        if editable:
            menu.addSeparator()
            open_table = menu.addAction(
                workstation_icon("map/tree-attribute-table.svg"), "打开属性表"
            )
            if layer_id == self._editing_layer_id:
                toggle_edit = menu.addAction("停止编辑（保存编辑）")
            else:
                toggle_edit = menu.addAction("开始编辑")
            menu.addSeparator()
            properties = menu.addAction(
                workstation_icon("map/tree-properties.svg"), "图层属性…"
            )
            symbology = menu.addAction("符号系统…")
            labeling = menu.addAction("标注…")
            menu.addSeparator()
            rename = menu.addAction(
                workstation_icon("map/tree-properties.svg"), "重命名图层…"
            )
            duplicate = menu.addAction("复制图层")
            remove = menu.addAction(workstation_icon("map/tree-remove.svg"), "删除图层")
            menu.addSeparator()
            repair = menu.addAction("修复无效几何…")
            repair.setEnabled(self._repair_available(layer_id))
            export = menu.addAction("导出图层…")
        else:
            open_table = toggle_edit = properties = symbology = labeling = None
            rename = duplicate = remove = repair = export = None
        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen is None:
            return
        if chosen is zoom and self._canvas is not None and has_extent:
            self._canvas.set_extent(tuple(float(v) for v in extent))
        elif chosen is refresh:
            self.refresh_reference_requested.emit(layer_id)
        elif chosen is toggle_snap:
            self.toggle_reference_snap_requested.emit(layer_id)
        elif chosen is remove_reference:
            self.remove_reference_requested.emit(layer_id)
        elif chosen is open_table:
            self.attribute_table_requested.emit(layer_id)
        elif chosen is toggle_edit:
            self.toggle_editing_requested.emit(layer_id)
        elif chosen is properties:
            self.properties_requested.emit(layer_id)
        elif chosen is symbology:
            self.symbology_requested.emit(layer_id)
        elif chosen is labeling:
            self.labeling_requested.emit(layer_id)
        elif chosen is rename:
            self.rename_layer_requested.emit(layer_id)
        elif chosen is duplicate:
            self.duplicate_layer_requested.emit(layer_id)
        elif chosen is remove:
            self.remove_layer_requested.emit(layer_id)
        elif chosen is repair:
            self.repair_layer_requested.emit(layer_id)
        elif chosen is export:
            self.export_layer_requested.emit(layer_id)

    def _repair_available(self, layer_id: str) -> bool:
        """只有面图层存在 make-valid 修复语义。"""
        kind = str((getattr(self.layer_by_id(layer_id), "metadata", None) or {}).get("geometry_kind") or "")
        return kind == "polygon"

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

    def tree_row_count(self) -> int:
        return self.tree.topLevelItemCount()

    def bind(self, canvas: QgisCanvasShim, layers: list) -> None:
        self._canvas = canvas
        self._layers = layers
        self._reload()

    def set_project_crs(self, crs: str) -> None:
        """注入项目 CRS 权威（ProjectDocument.coordinate → 渲染快照）。"""
        crs = str(crs or "")
        if crs and crs != self._project_crs:
            self._project_crs = crs

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

    def set_layer_visible(
        self, layer_id: str, visible: bool, *, reload_tree: bool = True
    ) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        self._layers[self._layers.index(layer)] = replace(layer, visible=visible)
        self._publish(reload_tree=reload_tree)

    def set_layer_opacity(self, layer_id: str, opacity: float) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        self._layers[self._layers.index(layer)] = replace(
            layer, opacity=max(0.05, opacity)
        )
        # 不透明度不影响树呈现；滑杆拖动的每个 tick 都整树重建是 GUI
        # 热点（review #5），只重发渲染快照。
        self._publish(reload_tree=False)

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

    def _publish(self, *, reload_tree: bool = True) -> None:
        if self._canvas is None:
            return
        self._canvas.set_layer_snapshot(
            MapRenderSnapshot(
                project_crs=self._project_crs or "EPSG:4326",
                layers=tuple(self._layers),
            )
        )
        if reload_tree:
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
        # V7 §12：差分重载——结构（id 顺序）未变时只更新单元格，不清树
        # （全清重建是 GUI 热点，且破坏滚动位置）。
        existing_ids = [
            str(self.tree.topLevelItem(row).data(0, Qt.ItemDataRole.UserRole))
            for row in range(self.tree.topLevelItemCount())
        ]
        desired_ids = [str(layer.id) for layer in self._layers]
        differential = existing_ids == desired_ids and desired_ids
        scroll = self.tree.verticalScrollBar().value()
        self._reloading = True
        try:
            if differential:
                for row, layer in enumerate(self._layers):
                    self._update_tree_item(self.tree.topLevelItem(row), layer)
                restored = current
            else:
                self.tree.clear()
                restored = None
                for layer in self._layers:
                    item = QTreeWidgetItem(["", ""])
                    self._update_tree_item(item, layer)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
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
        if differential:
            self.tree.verticalScrollBar().setValue(scroll)
        self.tree.itemChanged.connect(self._on_item_changed)
        self._tree_connected = True

    def _update_tree_item(self, item: QTreeWidgetItem, layer) -> None:
        """（差分）刷新一行：名称 / 图标 / 勾选 / 状态装饰。"""
        label = layer.name
        if self.is_editable_layer(layer):
            label = f"{label}（矢量）"
        item.setText(0, label)
        item.setData(0, Qt.ItemDataRole.UserRole, layer.id)
        item.setIcon(
            0,
            _layer_kind_icon(
                _snapshot_geometry_kind(layer), getattr(layer, "style", None)
            ),
        )
        item.setCheckState(
            0, Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
        )
        self._apply_item_decoration(item, str(layer.id), label)

    def _apply_item_decoration(self, item: QTreeWidgetItem, layer_id: str, label: str) -> None:
        """状态列 + hover 摘要（V7 §7；词汇来自 state_language）。"""
        from paleo_workbench.ui.workstation.layer_decorations import (
            decoration_summary_text,
            decoration_token,
        )

        state = self._decorations.get(str(layer_id))
        token = decoration_token(state) if state is not None else None
        if token is None:
            item.setText(1, "")
            item.setToolTip(0, label)
            item.setToolTip(1, "")
            item.setData(1, Qt.ItemDataRole.ForegroundRole, None)
            return
        item.setText(1, f"{token.glyph} {token.label}")
        summary = decoration_summary_text(state) if state is not None else ""
        tooltip = label if not summary else f"{label}\n{summary}"
        item.setToolTip(0, tooltip)
        item.setToolTip(1, tooltip)
        color = _decoration_color(token.tone)
        if color is not None:
            item.setData(1, Qt.ItemDataRole.ForegroundRole, color)

    def set_layer_decorations(self, decorations: dict) -> None:
        """V7 §7：推送图层级呈现态（差分更新状态列，不重建树）。"""
        self._decorations = dict(decorations or {})
        if self._reloading:
            return
        if self._tree_connected:
            self.tree.itemChanged.disconnect(self._on_item_changed)
            self._tree_connected = False
        try:
            for row in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(row)
                layer_id = str(item.data(0, Qt.ItemDataRole.UserRole))
                self._apply_item_decoration(item, layer_id, item.text(0))
        finally:
            self.tree.itemChanged.connect(self._on_item_changed)
            self._tree_connected = True

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            item.setHidden(bool(text) and text not in item.text(0).lower())

    def _on_item_changed(self, item: QTreeWidgetItem) -> None:
        # 复选框勾选在鼠标释放事件的 delegate 处理栈内触发本回调；此时
        # 绝不能同步重建树（tree.clear() 销毁 delegate 仍持有的 item →
        # libQt6Widgets 内 use-after-free SIGSEGV）。勾选态本就是树自己
        # 写的，跳过重载只重发渲染快照即可（同 set_layer_opacity 的
        # reload_tree=False 先例）。
        self.set_layer_visible(
            item.data(0, Qt.ItemDataRole.UserRole),
            item.checkState(0) == Qt.CheckState.Checked,
            reload_tree=False,
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
    """编图文档：图件画布即主窗口内容（永不浮动），面板全部为宿主 dock。

    本部件只拥有主图与悬浮工具条；图层管理 / 输入与结果 / 联动视图三个
    面板实例在此创建、由 ``WorkstationFrame``（QMainWindow）注册为
    dock —— 图件显示区域就是主窗口的中央区域，其余一切皆可浮动。
    """

    object_selected = Signal(object)
    status_message = Signal(str)
    well_track_toggled = Signal(bool)
    seismic_section_toggled = Signal(bool)
    link_toggled = Signal(bool)
    # V5：阶段动作请求导航到既有 hub 页（如单因素制备），由宿主壳执行。
    hub_page_requested = Signal(str)

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("CompositeDocument")
        self._project = project
        self._loading = False
        self._home_extent: tuple[float, float, float, float] | None = None
        self._base_layers: list = []
        self._attribute_dialog: CompositeAttributeTableDialog | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.canvas, self.uses_native_stack = self._create_canvas()
        layout.addWidget(self.canvas, 1)
        # 空态提示（视觉 QA 11）：无任何编修/参考图层时中央画布给明确引导，
        # 而不是一片纯白；有内容即隐藏，不影响正常渲染。
        self._empty_hint = QLabel("空工程 — 从左侧 Explorer 导入数据，"
                                  "或用工具条「新建图层」开始编图", self.canvas)
        self._empty_hint.setObjectName("CompositeEmptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_hint.hide()

        # 识别结果（多图层 Identify）与运行状态栏：图件主视图的诚实附属层。
        self.identify_results = IdentifyResultsPanel(self)
        self.identify_results.setMaximumHeight(200)
        self.identify_results.result_activated.connect(self._locate_identify_result)
        layout.addWidget(self.identify_results)
        self.status_bar = MapStatusBar(self)
        layout.addWidget(self.status_bar)

        # 矢量图层新建 / 编辑（QGIS 式编辑会话，见 composite_editing.py）
        self.edit_controller = CompositeEditController(parent=self)
        # RAW/锁定门禁单点注入（V6 B-P0-1：所有会话起点与 flush 提交经此）。
        self.edit_controller.set_edit_gate(self._role_allows_editing)
        self.edit_controller.attach_canvas(self.canvas)
        self.edit_controller.identify_delegate = self._identify_with_results
        # 引用矢量图层：外部 GDAL 源的只读参考（渲染要素经源修订缓存，
        # 源文件永不修改；工程只保存引用描述）。合成顺序固定为
        # 基础工区 → 引用参考 → 编修图层（参考永远垫底）。
        self._reference_service = ReferenceLayerService()
        self._reference_layers: list[MapReferenceLayer] = []
        self._reference_status: dict[str, str] = {}
        # 内容变化（数字化 / 属性编辑）经 120ms debounce 重组快照：连续
        # 采点不重复触发全图层重序列化；overlay（采点预览/捕捉）不经过
        # 快照，交互反馈不受影响。结构变化（图层增删改名）立即重组。
        self._composition_timer = QTimer(self)
        self._composition_timer.setSingleShot(True)
        self._composition_timer.setInterval(120)
        self._composition_timer.timeout.connect(self._sync_composition_now)
        self.edit_controller.layers_changed.connect(
            lambda *_: self._sync_composition(immediate=True)
        )
        self.edit_controller.content_changed.connect(
            lambda *_: self._sync_composition(immediate=False)
        )
        # 提交 / 回滚点是数据边界：立即重组并写回工程文档（内存态不得
        # 滞后于「保存编辑」语义）；immediate 同时取消 pending debounce，
        # 避免 120ms 后的一次冗余全量重组。
        self.edit_controller.sessions_committed.connect(
            lambda *_: self._sync_composition(immediate=True)
        )
        self.edit_controller.state_changed.connect(self._sync_action_state)
        self.canvas.tool_operation.connect(self._on_tool_operation)
        self.canvas.extent_changed.connect(lambda *_: self._sync_action_state())
        self.canvas.map_position_changed.connect(self._on_map_position)
        self.canvas.backend_status_changed.connect(lambda *_: self._sync_status_bar())

        # 面板实例（dock 由宿主 QMainWindow 创建并管理）。图层管理面板跟随
        # 画布形态：原生栈用 QgsLayerTreeView 面板，回退画布用同信号接缝的
        # LayerManagerPanel（QTreeWidget 自绘树）——两套面板 16 个请求信号同构。
        self.layer_manager = self._create_layer_manager()
        self.input_tree = InputTreePanel(project)
        self.linked_views = LinkedViewsPanel()
        self.input_tree.object_selected.connect(self.object_selected.emit)
        self.layer_manager.create_layer_requested.connect(self._create_vector_layer)
        self.layer_manager.remove_layer_requested.connect(self._remove_vector_layer)
        # V7 §7：双击定位（两套面板同构信号；无桥环境同样生效）。
        if hasattr(self.layer_manager, "zoom_to_layer_requested"):
            self.layer_manager.zoom_to_layer_requested.connect(
                self._zoom_to_layer_by_id
            )
        if not self.uses_native_stack:
            # 树内改名在回退面板走请求信号（原生 QgsLayerTreeView 直接改名回写）。
            self.layer_manager.rename_layer_requested.connect(
                self._rename_layer_prompt
            )
        self.layer_manager.import_reference_requested.connect(self._import_reference_layer)
        self.layer_manager.remove_reference_requested.connect(self._remove_reference_layer)
        self.layer_manager.refresh_reference_requested.connect(self._refresh_reference_layer)
        self.layer_manager.toggle_reference_snap_requested.connect(
            self._toggle_reference_snap
        )
        self.layer_manager.active_layer_changed.connect(
            self.edit_controller.set_active_layer)
        self.layer_manager.attribute_table_requested.connect(
            self._open_attribute_table
        )
        self.layer_manager.toggle_editing_requested.connect(self._toggle_layer_editing)
        self.layer_manager.properties_requested.connect(
            lambda layer_id: self._open_layer_properties(layer_id)
        )
        self.layer_manager.symbology_requested.connect(
            lambda layer_id: self._open_layer_properties(layer_id, focus="symbology")
        )
        self.layer_manager.labeling_requested.connect(
            lambda layer_id: self._open_layer_properties(layer_id, focus="labels")
        )
        self.layer_manager.duplicate_layer_requested.connect(self._duplicate_vector_layer)
        self.layer_manager.export_layer_requested.connect(self._export_layer)
        self.layer_manager.repair_layer_requested.connect(self._repair_layer)
        if self.uses_native_stack:
            # 显示态回写只有原生树面板产生（回退面板的显示态经自身信号即时生效）。
            self.layer_manager.display_state_changed.connect(self.notify_display_changed)

        # V5 分层编图工作区：阶段状态机 + 图层组编排（同一画布/同一工程权威）。
        from paleo_workbench.mapping_workspace.controller import MappingStageController
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole

        self.stage_controller = MappingStageController(parent=self)
        self._layer_role_enum = LayerRole
        # V7 §7：组聚合的成熟度回调（键解析唯一源在本类，controller 只数）。
        self.stage_controller.group_controller.set_maturity_provider(
            self._layer_maturity_value
        )
        if self.uses_native_stack:
            self.stage_controller.group_controller.attach_canvas(self.canvas)
            if isinstance(self.layer_manager, QgisLayerTreePanel):
                self.layer_manager.set_group_controller(
                    self.stage_controller.group_controller)
        else:
            # 完全降级（无原生栈）：诚实标记（宿主提示分组/阶段显隐不可用）。
            self.stage_controller.group_controller.mark_fallback()
        self.stage_controller.set_snapshot_provider(
            lambda: list(self.layer_manager._layers))
        self.stage_controller.set_target_resolver(self._resolve_editing_target)
        # 编辑目标信号 → 编辑权威 active layer（阶段切换重指派；用户点选经
        # set_active_target 记录，无回环）。
        self.stage_controller.active_target_changed.connect(self._apply_active_target)
        # 用户树选层同步回流阶段控制器（编辑目标单一权威；set_active_target
        # 仅在变化时发信号，无回环）。
        self.layer_manager.active_layer_changed.connect(
            self.stage_controller.set_active_target)
        if isinstance(self.layer_manager, QgisLayerTreePanel):
            self.layer_manager.group_state_changed.connect(
                self._on_tree_structure_changed)
            self.layer_manager.create_group_requested.connect(self._create_user_group)
            self.layer_manager.remove_group_requested.connect(self._remove_user_group)
        self.stage_controller.group_controller.on_invalid_move = (
            lambda layer_id, group_id: self.status_message.emit(
                "该图层不能移入此系统组（科学角色与组语义不相容）——已保持原位"))
        # V5 阶段动作分派（面板动作 → 工作流；见 stage_actions.py）。
        from paleo_workbench.ui.workstation.stage_actions import StageActionDispatcher
        self.stage_actions = StageActionDispatcher(self)

        self._build_toolbar()
        self.set_project(project)

    # -- 画布 / 面板形态 -------------------------------------------------------

    def _create_canvas(self) -> tuple[QWidget, bool]:
        """优先原生 QGIS 地图栈；桥缺失/初始化失败时诚实降级回退画布。

        回退不伪装原生能力：UnifiedMapCanvas 的 backend_status 会如实报告
        fallback 渲染器；原生专属分支（QgsVectorLayerProperties 等）以
        ``uses_native_stack`` 显式判断。桥构建指引见 canvas_shim 的报错文案。
        """
        try:
            return QgisCanvasShim(parent=self), True
        except Exception:
            # RuntimeError（桥未装）之外的异常也可能从 shim 构造链冒出
            # （QgisCanvasHost / 事件attach 等）；降级必须兜住整个链路，
            # 否则一台环境有问题的机器直接打不开工作站。
            logging.getLogger(__name__).exception(
                "QGIS 画布栈初始化失败，回退 fallback 画布"
            )
            return UnifiedMapCanvas(parent=self), False

    def _create_layer_manager(self) -> QWidget:
        """图层管理面板跟随画布形态（两套面板请求信号同构，见类 docstring）。"""
        if self.uses_native_stack:
            return QgisLayerTreePanel()
        return LayerManagerPanel()

    def _rename_layer_prompt(self, layer_id: str) -> None:
        """回退树面板的改名请求：QInputDialog → edit_controller.rename_layer。"""
        layer = self.edit_controller.layer(str(layer_id))
        if layer is None:
            return
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, "重命名图层", "图层名称", text=str(layer.name or "")
        )
        if ok and str(name).strip():
            self.edit_controller.rename_layer(str(layer_id), str(name).strip())

    # -- 悬浮工具条 -----------------------------------------------------------

    # -- 阶段工具面（V6 §4） ------------------------------------------------------

    def apply_stage_tool_profile(self, stage_value: str) -> None:
        """按 ``StageToolProfile`` 过滤工具条的数字化/编辑动作可见性。

        只隐藏受治理全集（``governed_edit_actions``）内的动作；基础导航/
        识别/选择永不因阶段隐藏。未知阶段值保持现状（宽容：阶段条已校验）。
        """
        from paleo_workbench.mapping_workspace.stage_profiles import (
            governed_edit_actions,
            stage_profile,
        )
        from paleo_workbench.mapping_workspace.stages import stage_from_value

        stage = stage_from_value(stage_value)
        if stage is None:
            return
        tools = stage_profile(stage).tools
        for action_id in governed_edit_actions():
            action = self.action_controller.actions.get(action_id)
            if action is not None:
                action.setVisible(tools.allows_edit_action(action_id))

    # -- V7 上下文驱动工具面 ----------------------------------------------------

    def tool_context(self) -> ToolContext:
        """当前 ``ToolContext``（palette/状态条/工具条共用的求值输入）。

        全部字段来自既有权威（edit_controller.action_state /
        stage_controller / 画布 backend_status / 角色门禁结论），构造廉价。
        """
        controller = self.edit_controller
        state = controller.action_state(
            can_previous_extent=self.canvas.can_previous_extent,
            can_next_extent=self.canvas.can_next_extent,
        )
        stage_value = None
        stage_controller = getattr(self, "stage_controller", None)
        if stage_controller is not None:
            current = getattr(stage_controller, "current_stage", None)
            stage_value = getattr(current, "value", None)
        split_inputs = getattr(controller, "_split_inputs", None)
        return ToolContext(
            project_open=self._project is not None,
            stage=stage_value,
            layer=self._layer_capability(controller.active_layer_id),
            has_active_vector_layer=state.has_active_vector_layer,
            vector_layer_writable=state.vector_layer_writable,
            editing=state.editing,
            selected_count=state.selected_count,
            compatible_polygon_count=state.compatible_polygon_count,
            can_undo=state.can_undo,
            can_redo=state.can_redo,
            can_previous_extent=state.can_previous_extent,
            can_next_extent=state.can_next_extent,
            split_inputs_ready=(split_inputs() is not None) if split_inputs else None,
            capability=self._capability_snapshot(),
        )

    def _capability_snapshot(self) -> QgisCapabilitySnapshot:
        """画布后端能力三态（native / degraded / unavailable）。"""
        try:
            status = str(self.canvas.backend_status or "")
        except Exception:
            status = ""
        if not self.uses_native_stack:
            return QgisCapabilitySnapshot(
                mode="unavailable", reason="QGIS 桥不可用（回退画布）"
            )
        if "degraded" in status:
            return QgisCapabilitySnapshot(mode="degraded", reason=status)
        return QgisCapabilitySnapshot(mode="native")

    def _layer_capability(self, layer_id) -> LayerCapabilitySnapshot:
        """活动图层能力快照（角色/几何/成熟度/门禁结论——全部派生）。"""
        if not layer_id:
            return LayerCapabilitySnapshot()
        layer_id = str(layer_id)
        state = self.stage_controller.state
        role = state.role_of(layer_id)
        layer = self.edit_controller.layer(layer_id)
        if layer is None:
            return LayerCapabilitySnapshot(
                layer_id=layer_id,
                role=role.value,
                role_label=role.label,
                missing=True,
                editable=False,
                block_reason="图层不在当前编辑注册表（可能已被移除）",
            )
        allowed, reason = self._role_allows_editing(layer_id)
        maturity = self._layer_maturity_value(layer_id, role)
        return LayerCapabilitySnapshot(
            layer_id=layer_id,
            name=str(layer.name or ""),
            role=role.value,
            role_label=role.label,
            kind=self.edit_controller.kind_of(layer_id) or None,
            maturity=maturity,
            editable=allowed,
            block_reason=reason or None,
            frozen=maturity in ("frozen", "published"),
        )

    def _layer_maturity_value(self, layer_id, role=None) -> str | None:
        """图层级成熟度原始值（None = 未知；raw 角色直接 raw）。"""
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole

        state = self.stage_controller.state
        layer_id = str(layer_id)
        if role is None:
            role = state.role_of(layer_id)
        if role.is_raw_protected:
            return "raw"
        record = state.membership(layer_id)
        keys: list[str] = []
        if record is not None:
            if record.factor_task_id:
                keys.append(f"factor:{record.factor_task_id}")
            if record.role == LayerRole.INITIAL_FACIES_DRAFT:
                keys.append(f"phase1_draft:{layer_id}")
            if record.role in (LayerRole.INTEGRATED_FACIES, LayerRole.INTEGRATED_BOUNDARY):
                keys.append(f"integrated:{layer_id}")
        for key in keys:
            found = state.artifact_maturity.get(key)
            if found:
                return str(found)
        return None

    def tool_availability(self) -> dict[str, ToolAvailability]:
        """统一可用性求值（供工具条刷新与 palette applicability 复用）。"""
        return availability_for_context(self.tool_context())

    def _apply_tool_availability(self) -> None:
        self.action_controller.apply_availability(self.tool_availability())

    # -- V7 §7 图层树呈现态 ----------------------------------------------------

    def _layer_decorations(self) -> dict:
        """图层级呈现态（编辑/未保存/新鲜度/成熟度/参考降级）。"""
        from paleo_workbench.ui.workstation.layer_decorations import (
            LayerPresentationState,
            presentation_state,
        )

        controller = self.edit_controller
        group_controller = self.stage_controller.group_controller
        decorations: dict[str, LayerPresentationState] = {}
        for layer_id in controller.layer_ids():
            layer = controller.layer(str(layer_id))
            session = getattr(layer, "edit_session", None) if layer else None
            freshness = group_controller.layer_freshness(str(layer_id))
            decorations[str(layer_id)] = presentation_state(
                editing=session is not None,
                session_undo_depth=len(getattr(session, "undo_stack", ()) or ()),
                freshness_status=(
                    freshness.status.value if freshness is not None else None
                ),
                maturity=self._layer_maturity_value(str(layer_id)),
            )
        for reference in self._reference_layers:
            status = str(self._reference_status.get(str(reference.id), "") or "")
            decorations[str(reference.id)] = LayerPresentationState(
                degraded=status in {"failed", "error"},
            )
        return decorations

    def _group_summaries(self) -> list:
        """组级聚合（group_summary + 因子任务运行/排队计数）。"""
        from paleo_workbench.mapping_workspace.layer_groups import (
            system_group_template,
        )
        from paleo_workbench.ui.workstation.layer_decorations import (
            GroupPresentationSummary,
        )

        group_controller = self.stage_controller.group_controller
        running = pending = 0
        for task in getattr(self._project, "factor_map_tasks", None) or []:
            status = str(getattr(task, "status", ""))
            if status == "running":
                running += 1
            elif status == "pending":
                pending += 1
        summaries = []
        for group_id in group_controller.group_ids():
            counts = group_controller.group_summary(group_id)
            template = system_group_template(group_id)
            summaries.append(GroupPresentationSummary(
                group_id=group_id,
                title=template.title if template else group_id,
                layers=int(counts.get("layers", 0)),
                stale=int(counts.get("stale", 0)),
                errors=int(counts.get("errors", 0)),
                running=running if group_id == "phase2.factors" else 0,
                pending=pending if group_id == "phase2.factors" else 0,
                frozen=int(counts.get("frozen", 0)),
                published=int(counts.get("published", 0)),
            ))
        return summaries

    def _push_layer_decorations(self) -> None:
        """把呈现态/组聚合推给图层管理面板（面板差分渲染）。"""
        setters = (
            getattr(self.layer_manager, "set_layer_decorations", None),
            getattr(self.layer_manager, "set_group_summaries", None),
        )
        try:
            if callable(setters[0]):
                setters[0](self._layer_decorations())
            if callable(setters[1]):
                setters[1](self._group_summaries())
        except RuntimeError:
            pass  # 拆壳期 C++ 对象已销毁

    def _zoom_to_layer_by_id(self, layer_id) -> None:
        """按 id 缩放到图层（树双击定位；与树菜单同一有效性判据）。"""
        layer = self.edit_controller.layer(str(layer_id)) if layer_id else None
        extent = getattr(layer, "extent", None) if layer is not None else None
        if not (extent and extent[0] < extent[2] and extent[1] < extent[3]):
            self.status_message.emit("该图层没有可缩放的有效范围")
            return
        try:
            self.canvas.set_extent(tuple(float(v) for v in extent))
        except Exception:
            logging.getLogger(__name__).exception("缩放到图层失败")
            self.status_message.emit("缩放到图层失败（范围无效）")

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
        # V7 专业分组（goal §6）：Navigation / Selection / Inspection / Edit
        # Session / Capture / Geometry / Snapping·Topology / Layer /
        # Symbology / Factor / QA / Layout·Export——组内动作使能由统一
        # 求值器管理，组级可见性随阶段/图层切换（_apply_tool_availability）。
        from paleo_workbench.ui.workstation.tool_surface import TOOL_GROUPS

        bar_layout.addWidget(
            self.action_controller.toolbar(
                "编图",
                tuple(
                    tuple(TOOL_GROUPS[group])
                    for group in (
                        "navigate", "selection", "inspection", "edit_session",
                        "capture", "geometry", "snapping", "layer",
                        "symbology", "factor", "qa", "layout_export",
                    )
                ),
                self.toolbar,
            )
        )
        self.action_controller.tool_requested.connect(
            self.edit_controller.activate_tool
        )
        self.action_controller.command_requested.connect(self._on_command_requested)

        # 视图 dock 开关 + 联动（宿主 WorkstationFrame 接线）。
        self.well_track_button = QToolButton(self.toolbar)
        self.well_track_button.setObjectName("WorkstationWellTrackButton")
        self.well_track_button.setText("测井轨道")
        self.well_track_button.setCheckable(True)
        self.well_track_button.toggled.connect(self.well_track_toggled)
        bar_layout.addWidget(self.well_track_button)
        self.seismic_section_button = QToolButton(self.toolbar)
        self.seismic_section_button.setObjectName("WorkstationSeismicSectionButton")
        self.seismic_section_button.setText("地震剖面")
        self.seismic_section_button.setCheckable(True)
        self.seismic_section_button.toggled.connect(self.seismic_section_toggled)
        bar_layout.addWidget(self.seismic_section_button)
        self.link_button = QToolButton(self.toolbar)
        self.link_button.setObjectName("WorkstationLinkButton")
        self.link_button.setText("链接")
        self.link_button.setCheckable(True)
        self.link_button.setChecked(True)
        self.link_button.toggled.connect(self.link_toggled)
        bar_layout.addWidget(self.link_button)

        # 面板菜单：显隐 / 布局预设 / 全部浮动·停靠 / 恢复默认（由宿主注入）
        self.panels_button = QToolButton(self.toolbar)
        self.panels_button.setObjectName("WorkstationContextButton")
        self.panels_button.setIcon(workstation_icon("map/panel-manager.svg"))
        self.panels_button.setText("面板")
        self.panels_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.panels_button.setToolTip("面板显隐、布局预设、全部浮动 / 停靠")
        # IconOnly 样式隐藏了 text，屏幕阅读器需要显式名（V6 audit G-P1-3）。
        self.panels_button.setAccessibleName("面板")
        self.panels_button.setAccessibleDescription(
            "面板显隐、布局预设、全部浮动 / 停靠"
        )
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
        self._panels_menu.addAction("捕捉设置…", self._open_snapping_settings)
        self._panels_menu.addAction("恢复默认布局", reset_callable)

    def _zoom_home(self) -> None:
        if self._home_extent is not None:
            self.canvas.set_extent(self._home_extent)

    def zoom_to_full_extent(self) -> None:
        """回到 home extent（全部工区井位），与工具条全幅按钮同一路径。"""
        self._zoom_home()

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
            self._sync_status_bar()
        elif command_id == "topology":
            enabled = self.action_controller.actions["topology"].isChecked()
            self.edit_controller.set_topology(enabled)
            self.status_message.emit(
                "拓扑编辑已开启：保存编辑将执行拓扑校验" if enabled else "拓扑编辑已关闭"
            )
        elif command_id in {"clear_selection", "select_all", "invert_selection"}:
            self.edit_controller.selection_command(command_id)
        elif command_id == "toggle_editing":
            if self.edit_controller.editing:
                self._save_edits_with_feedback()
            else:
                allowed, reason = self._role_allows_editing(
                    self.edit_controller.active_layer_id)
                if not allowed:
                    self.status_message.emit(reason)
                else:
                    self.edit_controller.start_editing()
        elif command_id == "save_edits":
            self._save_edits_with_feedback()
        elif command_id == "rollback":
            self.edit_controller.rollback_edits()
        elif command_id in {"undo", "redo", "delete_selected"}:
            self.edit_controller.edit_command(command_id)
        elif command_id in {"split", "merge"}:
            ok, message = self.edit_controller.geometry_command(command_id)
            if not ok:
                self.status_message.emit(message)
        elif command_id == "refresh":
            self.canvas.update()
        elif command_id == "layer_new":
            self._create_vector_layer()
        elif command_id == "reference_import":
            self._import_reference_layer()
        elif command_id == "layer_properties":
            layer_id = self.edit_controller.active_layer_id
            if layer_id:
                self.open_layer_properties(str(layer_id))
        elif command_id == "symbology":
            layer_id = self.edit_controller.active_layer_id
            if layer_id:
                self.open_layer_properties(str(layer_id), focus="symbology")
        elif command_id == "style_manager":
            self._open_style_manager()
        elif command_id == "attribute_table":
            layer_id = self.edit_controller.active_layer_id
            if layer_id:
                self._open_attribute_table(str(layer_id))
        elif command_id == "layer_zoom":
            self._zoom_to_active_layer()
        elif command_id == "layer_export":
            layer_id = self.edit_controller.active_layer_id
            if layer_id:
                self._export_layer(str(layer_id))
        elif command_id == "factor_workbench":
            self.stage_actions.dispatch(
                str(self.stage_controller.current_stage.value
                    if self.stage_controller.current_stage else ""),
                "open_factor_workbench",
            )
        elif command_id == "factor_overlay":
            self.stage_actions.overlay_factor_results()
        elif command_id == "qa_run":
            self.stage_actions.dispatch(
                str(self.stage_controller.current_stage.value
                    if self.stage_controller.current_stage else ""),
                "run_qa",
            )
        elif command_id == "map_product_assemble":
            self.stage_actions.assemble_map_product()
        elif command_id == "map_export":
            self.hub_page_requested.emit("review")
        self._sync_action_state()

    def _open_style_manager(self) -> None:
        """QGIS 样式库入口（桥能力门禁；失败如实反馈，不静默）。"""
        try:
            from paleo_workbench.ui.map_symbology_bridge import open_style_manager

            open_style_manager(self)
        except Exception as exc:  # 桥缺失/构造失败均必须可见
            logging.getLogger(__name__).exception("样式库打开失败")
            self.status_message.emit(f"样式库不可用：{exc}")

    def _zoom_to_active_layer(self) -> None:
        """缩放到活动图层（与图层树「缩放到图层」同一有效性判据）。"""
        layer_id = self.edit_controller.active_layer_id
        layer = self.edit_controller.layer(str(layer_id)) if layer_id else None
        extent = getattr(layer, "extent", None) if layer is not None else None
        has_extent = bool(extent) and extent[0] < extent[2] and extent[1] < extent[3]
        if not has_extent:
            self.status_message.emit("活动图层没有可缩放的有效范围")
            return
        try:
            self.canvas.set_extent(tuple(float(v) for v in extent))
        except Exception:
            logging.getLogger(__name__).exception("缩放到图层失败")
            self.status_message.emit("缩放到图层失败（范围无效）")

    def _save_edits_with_feedback(self) -> None:
        # 纵深防御：RAW 保护角色的会话即使被未知路径打开，也不得提交——
        # 回滚并告知（防原始相图/模型结果被改写后持久化）。
        active_id = self.edit_controller.active_layer_id
        allowed, reason = self._role_allows_editing(active_id)
        if not allowed:
            self.edit_controller.rollback_edits()
            self.status_message.emit(f"已回滚：{reason}")
            return
        error = self.edit_controller.save_edits()
        if error:
            self.status_message.emit(error)

    def _on_tool_operation(self, edits_data: bool = True) -> None:
        """工具操作回执：数据编辑重组快照，纯选择 / 指针反馈只刷状态。"""
        if edits_data:
            self._sync_composition()
        else:
            self.canvas.update()
        self._sync_action_state()

    def _on_map_position(self, point) -> None:
        self._sync_status_bar(point=tuple(point))

    def _sync_action_state(self) -> None:
        self._update_empty_hint()
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
        # 工具按钮勾选态跟随真实活动工具（会话回落 pan 后按钮不得停留在
        # 已失效的工具上）。
        active_tool_id = (
            getattr(controller.tools.active_tool, "tool_id", "") or "pan"
        )
        for action_id in self.action_controller._TOOL_IDS:
            action = self.action_controller.actions[action_id]
            action.blockSignals(True)
            action.setChecked(action_id == active_tool_id)
            action.blockSignals(False)
        # 捕捉 / 拓扑的勾选态以控制器为权威（捕捉设置对话框等旁路入口
        # 不得让工具条按钮失步，review #11）。
        actions = self.action_controller.actions
        for action_id, checked in (
            ("snapping", controller.snapping.enabled),
            ("topology", controller.topology_enabled),
        ):
            action = actions[action_id]
            action.blockSignals(True)
            action.setChecked(bool(checked))
            action.blockSignals(False)
        # V7：使能/可见/禁用原因统一由 tool_surface 求值（在 update_state
        # 之后调用——勾选态归前者，其余归单一真源；split 的「多边形选集 +
        # 切割线」条件经 split_inputs_ready 收敛，不再二次改 enable）。
        self._apply_tool_availability()
        # V7 §7：树呈现态（编辑/新鲜度/成熟度）差分推送。
        self._push_layer_decorations()
        self._sync_status_bar()

    def _update_empty_hint(self) -> None:
        """空画布引导：编修/参考/工程基础内容全都没有时才显示。

        视觉 QA（07/12）矛盾修复：工程已有井/地震/层位（基础工区图层由
        set_project 组装）时画布并非空态，不得再挂「空工程」文案。
        """
        try:
            project = self._project
            has_base = bool(
                project is not None
                and (project.wells or project.resources or project.paleomap_documents)
            )
            empty = (
                not self.edit_controller.layer_ids()
                and not self._reference_layers
                and not has_base
            )
        except RuntimeError:
            return
        self._empty_hint.setVisible(bool(empty))
        if empty:
            self._empty_hint.setGeometry(self.canvas.rect())
            self._empty_hint.raise_()
            # 构造期isVisible 尚为 False（窗口未显示），布局后的真实画布
            # 矩形要等显示完成才拿得到；延迟一拍再对齐一次。
            QTimer.singleShot(0, self._sync_hint_geometry)

    def _sync_hint_geometry(self) -> None:
        hint = getattr(self, "_empty_hint", None)
        if hint is None or not hint.isVisible():
            return
        target = self.canvas.rect()
        # 等值守卫：setGeometry/raise_ 会触发画布布局回流并再次进入
        # resizeEvent → 本函数，无差别重设会无限递归（实测 maximum
        # recursion depth）；收敛后必须成为 no-op。
        if hint.geometry() != target:
            hint.setGeometry(target)
            hint.raise_()

    def _sync_status_bar(self, *, point=None) -> None:
        controller = self.edit_controller
        layer = controller.active_layer
        self.status_bar.update_state(
            point=point,
            extent=self.canvas.view_extent,
            crs=controller.project_crs or "EPSG:4326",
            renderer=self.canvas.backend_status,
            selection_count=len(layer.selection) if layer is not None else 0,
            editing=controller.editing,
            editing_label=layer.name if layer is not None else "",
            snapping=controller.snapping.enabled,
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

    def _remove_vector_layer(self, layer_id: str) -> None:
        self.stage_controller.group_controller.unregister_layer(str(layer_id))
        self.edit_controller.remove_layer(layer_id)

    def _duplicate_vector_layer(self, layer_id: str) -> None:
        copy = self.edit_controller.duplicate_layer(layer_id)
        if copy is not None:
            self.status_message.emit(f"已复制图层为「{copy.name}」")

    def stage_action(self, stage_value: str, action_id: str) -> None:
        """阶段面板上下文动作入口（宿主壳经 _dispatch_stage_action 调用）。"""
        self.stage_actions.dispatch(stage_value, action_id)

    def create_stage_constraint(self, kind_value: str) -> None:
        """typed 地质约束创建（阶段面板约束按钮）。"""
        self.stage_actions.create_constraint(kind_value)

    def _resolve_editing_target(self, role):
        """role → 该角色现存图层 id（阶段编辑目标解析；无则 None）。"""
        if role is None:
            return None
        for layer_id in self.stage_controller.state.layers_with_role(role):
            if self.edit_controller.layer(str(layer_id)) is not None:
                return str(layer_id)
        return None

    def _apply_active_target(self, layer_id) -> None:
        """阶段编辑目标应用（active_target_changed → 编辑权威 + 树选中）。

        None（阶段无编辑目标）也必须生效：清空活动图层，编辑动作落到
        门禁拒绝（P1 修复：绝不让上一阶段目标悄悄存活）。
        """
        if not layer_id:
            if self.edit_controller.active_layer_id is not None:
                self.edit_controller.set_active_layer(None)
            return
        if self.edit_controller.layer(str(layer_id)) is not None:
            self.edit_controller.set_active_layer(str(layer_id))
            self.layer_manager.select_layer(str(layer_id))

    def layer_domain_status(self, layer_id: str) -> dict[str, str]:
        """图层级域状态行（V6 §6：inspector 上下文 seam 数据源）。

        角色/成熟度/可编辑/新鲜度四行，值经 state_language 词汇渲染
        （glyph+文字）；未知项诚实「未知」，不编造。
        """
        from paleo_workbench.ui.workstation.state_language import state_token

        layer_id = str(layer_id)
        state = self.stage_controller.state
        role = state.role_of(layer_id)
        allowed, reason = self._role_allows_editing(layer_id)
        # RAW 角色永远显示 raw 词汇（不可达的 "raw" token 是死词表——
        # review round 1 P2）；其余按门禁 editable/locked。
        if role.is_raw_protected:
            editability = state_token("editability", "raw")
        elif allowed:
            editability = state_token("editability", "editable")
        else:
            editability = state_token("editability", "locked")
        # 成熟度：优先工作区权威（artifact_maturity），RAW 角色直接 raw。
        maturity_value = self._layer_maturity_value(layer_id, role)
        maturity = state_token("maturity", maturity_value)
        freshness_artifact = self.stage_controller.group_controller.layer_freshness(layer_id)
        freshness = (
            state_token("freshness", freshness_artifact.status.value)
            if freshness_artifact is not None
            else state_token("freshness", None)
        )
        return {
            "角色": f"{role.label}",
            "成熟度": f"{maturity.glyph} {maturity.label}",
            "可编辑": f"{editability.glyph} {editability.label}" + (
                f"（{reason}）" if not allowed and reason else ""),
            "新鲜度": f"{freshness.glyph} {freshness.label}",
        }

    def active_editing_target_status(self) -> dict:
        """活动编辑目标摘要（V6 §5：UIContext/状态条/检查器共用 seam）。

        返回 ``active_layer_id / role_label / editable / block_reason /
        editing_active``。无目标时 editable=False 且必须给出原因——
        「我在编辑什么」永远有答案。
        """
        target = self.stage_controller.active_target_layer_id
        if not target:
            return {
                "active_layer_id": None,
                "role_label": None,
                "editable": False,
                "block_reason": "当前阶段没有活动编辑目标（用阶段动作创建编辑对象）",
                "editing_active": False,
            }
        allowed, reason = self._role_allows_editing(str(target))
        role = self.stage_controller.state.role_of(str(target))
        return {
            "active_layer_id": str(target),
            "role_label": role.label,
            "editable": allowed,
            "block_reason": reason,
            "editing_active": self.edit_controller.editing,
        }

    def _role_allows_editing(self, layer_id) -> tuple[bool, str]:
        """编辑门禁（单点）：RAW 不可变保护（V5 §14）+ 成熟度冻结 + 阶段证据组锁（§41）。

        所有开启编辑会话的路径（树面板/主工具栏命令/修复几何/保存提交）
        都必须经过本检查——「画物源线写进相带边界」与「改写原始相图」
        都是 P0 级业务风险。
        """
        if not layer_id:
            return False, "当前没有活动编辑目标（本阶段的默认编辑对象尚未创建）"
        role = self.stage_controller.state.role_of(str(layer_id))
        if role.is_raw_protected:
            return False, (
                f"图层角色为「{role.label}」（RAW/模型结果）——不可直接编辑；"
                "请创建 DERIVED 草稿后编辑")
        # 成熟度冻结/发布：FROZEN/PUBLISHED 工件不可变（goal §5「当前结果
        # 已冻结」禁用原因的真源——UI 不在门禁之外另判）。
        maturity = self._layer_maturity_value(str(layer_id), role)
        if maturity in ("frozen", "published"):
            label = "已发布" if maturity == "published" else "已冻结"
            return False, (
                f"当前结果{label}（{role.label}）——不可编辑；"
                "如需修改请另存草稿或解除冻结")
        # 阶段证据组锁：图层所在组在本阶段锁定 → 拒绝（用户可在阶段视图
        # 状态中显式解锁）。
        from paleo_workbench.mapping_workspace.layer_groups import (
            system_group_template,
        )
        group_id = self.stage_controller.group_controller.placement_of(layer_id)
        template = system_group_template(group_id) if group_id else None
        stage = self.stage_controller.current_stage
        view_state = self.stage_controller.state.view_state(stage)
        locked_override = view_state.group_locked.get(group_id)
        locked = locked_override if locked_override is not None else bool(
            template and template.stage_locked(stage))
        if locked:
            title = template.title if template else group_id
            return False, f"图层所在组「{title}」在本阶段为证据锁定——不可编辑"
        return True, ""

    def _toggle_layer_editing(self, layer_id: str) -> None:
        allowed, reason = self._role_allows_editing(str(layer_id))
        if not allowed:
            self.status_message.emit(reason)
            return
        self.edit_controller.set_active_layer(layer_id)
        if self.edit_controller.editing:
            self._save_edits_with_feedback()
        else:
            self.edit_controller.start_editing()
        self._sync_action_state()

    def _repair_layer(self, layer_id: str) -> None:
        allowed, reason = self._role_allows_editing(str(layer_id))
        if not allowed:
            self.status_message.emit(f"无法修复：{reason}")
            return
        repaired = self.edit_controller.repair_layer_geometries(layer_id)
        if repaired:
            self.status_message.emit(f"已修复 {repaired} 个无效几何（可撤销）")
        else:
            self.status_message.emit("未发现需要修复的无效几何")

    # -- 图层属性 / 符号系统 / 标注（复用 MapLayerPropertiesDialog） ----------

    def open_layer_properties(self, layer_id: str, *, focus: str = "symbology") -> None:
        """公开入口：检查器/资源树把用户送去图层属性（同一套符号系统）。"""
        self._open_layer_properties(layer_id, focus=focus)

    def _open_layer_properties(self, layer_id: str, *, focus: str = "") -> None:
        """图层属性对话框：QGIS 桥可用走原生符号编辑器，否则 legacy 快速字段。

        不建立第二套符号模型——renderer XML（``qgis_style``）与 legacy
        ``VectorStyle`` 字段同存于图层 style dict，由
        :class:`MapLayerPropertiesDialog` / ``map_symbology_bridge`` 权威解释。
        """
        controller = self.edit_controller
        layer = controller.layer(layer_id)
        if layer is None and self.layer_manager.layer_by_id(layer_id) is None:
            return
        if isinstance(self.canvas, QgisCanvasShim):
            # QGIS 地图栈：直接 exec 原生 QgsVectorLayerProperties（与 QGIS
            # Desktop 完全一致的属性页）。可编辑图层与基础工区 / 引用图层
            # （井位、地震工区等快照层）都可打开；结果经
            # _apply_native_layer_properties 写回文档模型（不建立第二套
            # 符号模型）。
            result = self.canvas.stack.exec_layer_properties(
                self.canvas.canvas_address, str(layer_id))
            if result.get("ok"):
                self._apply_native_layer_properties(str(layer_id), result)
            return
        if layer is None:
            # 回退画布的 legacy 属性对话框绑定编辑控制器图层模型；基础
            # 工区 / 引用图层只在原生栈上提供属性（诚实告知，不静默）。
            self.status_message.emit(
                "基础图层属性对话框需要 QGIS 原生地图栈（当前为回退画布）")
            return
        session = layer.edit_session
        features = tuple(
            feature.as_record()
            for feature in (session.features() if session is not None else layer.features())
        )
        fields = [field.name for field in schema_fields(controller.layer_schema(layer_id))]
        for record in features:
            properties = record.get("properties") or {}
            for key in sorted(properties):
                if key not in fields:
                    fields.append(key)
        display = next(
            (snap for snap in self.layer_manager._layers if snap.id == layer_id), None
        )
        adapter = _LayerPropertiesAdapter(
            layer,
            opacity=float(getattr(display, "opacity", 1.0) or 1.0),
            metadata={
                "editable": "true",
                "geometry_kind": controller.kind_of(layer_id),
                "template": controller.layer_template(layer_id),
            },
        )
        dialog = MapLayerPropertiesDialog(
            adapter,
            style=dict(layer.style),
            parent=self,
            features=features,
            fields=tuple(fields),
        )
        if focus:
            titles = {"symbology": "Symbology", "labels": "Labels", "general": "General"}
            target = titles.get(focus)
            if target is not None:
                for index in range(dialog.tabs.count()):
                    if dialog.tabs.tabText(index) == target:
                        dialog.tabs.setCurrentIndex(index)
                        break
        dialog.properties_applied.connect(
            lambda _layer_id, payload: self._apply_layer_properties(layer_id, payload)
        )
        dialog.exec()
        self._sync_composition()

    def _apply_layer_properties(self, layer_id: str, payload) -> None:
        controller = self.edit_controller
        layer = controller.layer(layer_id)
        if layer is None or not isinstance(payload, dict):
            return
        name = str(payload.get("name") or "").strip()
        if name and name != layer.name:
            controller.rename_layer(layer_id, name)
        crs = str(payload.get("crs") or "").strip()
        if crs and crs != layer.crs:
            layer.crs = crs
        opacity = payload.get("opacity")
        if isinstance(opacity, (int, float)) and 0.0 <= float(opacity) <= 1.0:
            self.layer_manager.set_layer_opacity(layer_id, float(opacity))
        style = dict(layer.style)
        if isinstance(payload.get("style"), dict):
            style.update(dict(payload["style"]))
        if isinstance(payload.get("qgis_style"), dict):
            style["qgis_style"] = dict(payload["qgis_style"])
        controller.set_layer_style(layer_id, style)
        self._sync_composition()
        self.status_message.emit(f"图层「{name or layer.name}」属性已更新")

    def _apply_native_layer_properties(self, layer_id: str, result: dict) -> None:
        """原生 QgsVectorLayerProperties 的 Accept 结果写回文档模型。

        与 _apply_layer_properties 同一写回语义（name/opacity/qgis_style →
        set_layer_style → _sync_composition 持久化）；qgis_style payload 沿用
        既有结构并递增 revision（沿用旧 payload 的 tags/name 元数据）。
        """
        from paleo_workbench.mapping.qgis_style import QgisStylePayload

        controller = self.edit_controller
        layer = controller.layer(layer_id)
        if layer is None:
            self._apply_native_snapshot_layer_properties(str(layer_id), result)
            return
        name = str(result.get("name") or "").strip()
        if name and name != layer.name:
            controller.rename_layer(layer_id, name)
        opacity = result.get("opacity")
        if isinstance(opacity, (int, float)) and 0.0 <= float(opacity) <= 1.0:
            self.layer_manager.set_layer_opacity(layer_id, float(opacity))
        renderer_xml = str(result.get("renderer_xml") or "")
        style = dict(layer.style)
        if renderer_xml.strip():
            old_payload = QgisStylePayload.from_dict(style.get("qgis_style"))
            payload = QgisStylePayload(
                renderer_xml=renderer_xml,
                labeling_xml=str(result.get("labeling_xml") or ""),
                name=old_payload.name if old_payload is not None else "",
                tags=old_payload.tags if old_payload is not None else (),
                revision=old_payload.revision + 1 if old_payload is not None else 1,
            )
            style["qgis_style"] = payload.to_dict()
        controller.set_layer_style(layer_id, style)
        self._sync_composition()
        self.status_message.emit(f"图层「{name or layer.name}」属性已更新")

    def _apply_native_snapshot_layer_properties(self, layer_id: str, result: dict) -> None:
        """原生属性对话框结果写回基础工区 / 引用图层（快照层）。

        这些图层不在编辑控制器里；权威是工区快照源（``_base_layers``）与
        引用描述符（工程文档 pydantic 模型）。符号 / 标注已由对话框直接
        落在镜像层上（upsert 的样式签名未变即不重置），经
        ``_sync_composition`` 的呈现态信封（map_qgis_project_xml）持久化；
        名称 / 不透明度写回快照与源，避免重组回滚。
        """
        snapshot = self.layer_manager.layer_by_id(layer_id)
        if snapshot is None:
            return
        name = str(result.get("name") or "").strip()
        opacity = result.get("opacity")
        has_opacity = isinstance(opacity, (int, float)) and 0.0 <= float(opacity) <= 1.0
        # 快照是 frozen dataclass：以 replace 重建后换回面板列表。
        from dataclasses import replace as _dc_replace

        new_snapshot = _dc_replace(
            snapshot,
            name=(name or snapshot.name),
            opacity=(
                min(1.0, max(0.05, float(opacity))) if has_opacity else snapshot.opacity
            ),
        )
        panel_layers = self.layer_manager._layers
        for index, existing in enumerate(panel_layers):
            if existing.id == layer_id:
                panel_layers[index] = new_snapshot
                break
        else:
            panel_layers.append(new_snapshot)
        # 源头同步：工区快照源同样是 frozen dataclass，按 id 换列表条目
        # （重组 list(self._base_layers) 直接复用这里的对象，不回滚）。
        for index, base in enumerate(self._base_layers):
            if base.id == layer_id:
                self._base_layers[index] = _dc_replace(
                    base,
                    name=(name or base.name),
                    opacity=(
                        min(1.0, max(0.05, float(opacity)))
                        if has_opacity
                        else base.opacity
                    ),
                )
                break
        # 引用描述符（工程文档权威，_sync_reference_layers_to_project 持久化）。
        for reference in self._reference_layers:
            if reference.id == layer_id:
                if name and name != reference.name:
                    try:
                        reference.name = name
                    except Exception:
                        pass
                if has_opacity:
                    try:
                        reference.opacity = new_snapshot.opacity
                    except Exception:
                        pass
                break
        # 面板重发快照：名称 / 不透明度即刻上镜像层与原生树。
        self.layer_manager._publish()
        self._sync_composition()
        self.status_message.emit(f"图层「{name or new_snapshot.name}」属性已更新")

    # -- 属性表 ---------------------------------------------------------------

    def _open_attribute_table(self, layer_id: str) -> None:
        if self._attribute_dialog is not None:
            self._attribute_dialog.reject()
            self._attribute_dialog = None
        self._attribute_dialog = CompositeAttributeTableDialog(
            self.edit_controller, layer_id, parent=self
        )
        self._attribute_dialog.feature_activated.connect(
            lambda feature_id, lid=layer_id: self._locate_feature(feature_id, lid)
        )
        self._attribute_dialog.show()

    def _locate_feature(self, feature_id: str, layer_id: str | None = None) -> None:
        layer = self.edit_controller.layer(
            layer_id or self.edit_controller.active_layer_id or ""
        )
        if layer is None:
            return
        layer.set_selection((feature_id,))
        source = (
            layer.edit_session.features()
            if layer.edit_session is not None
            else layer.features()
        )
        feature = next((f for f in source if f.feature_id == feature_id), None)
        if feature is not None:
            extent = _feature_extent([feature.as_record()])
            if extent[0] < extent[2] and extent[1] < extent[3]:
                self.canvas.set_extent(extent)
        self._sync_action_state()

    # -- 引用矢量图层 -----------------------------------------------------------

    def _import_reference_layer(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "导入矢量参考图层", "", _REFERENCE_IMPORT_FILTER
        )
        if not paths:
            return
        self.import_reference_layers(paths)

    def import_reference_layers(self, paths) -> int:
        """把外部矢量文件导入为只读参考图层并重组快照；逐文件回报失败原因。

        返回成功导入数。CRS 无法归一到项目坐标系的源会被拒绝并经
        ``status_message`` 告知（§20：不可叠加的坐标系绝不静默出图）。
        """
        imported = 0
        for path in paths:
            try:
                layer = self._reference_service.import_layer(
                    path, self.edit_controller.project_crs or "EPSG:4326"
                )
            except ReferenceLayerError as exc:
                self.status_message.emit(str(exc))
                continue
            self._reference_layers.append(layer)
            imported += 1
        if imported:
            self.status_message.emit(f"已导入 {imported} 个矢量参考图层")
            self._sync_composition_now()
        return imported

    def _remove_reference_layer(self, layer_id: str) -> None:
        before = len(self._reference_layers)
        self._reference_layers = [
            layer for layer in self._reference_layers if layer.id != layer_id
        ]
        if len(self._reference_layers) != before:
            self._reference_status.pop(layer_id, None)
            self._sync_composition_now()

    def _refresh_reference_layer(self, layer_id: str) -> None:
        for index, layer in enumerate(self._reference_layers):
            if layer.id != layer_id:
                continue
            try:
                refreshed = self._reference_service.import_layer(
                    layer.source_path,
                    self.edit_controller.project_crs or layer.project_crs,
                )
            except ReferenceLayerError as exc:
                self.status_message.emit(f"刷新引用失败：{exc}")
                ReferenceLayerService.refresh_status(layer)
                break
            # 保留显示态与身份，只更新归一化描述与缓存键。
            refreshed.id = layer.id
            refreshed.name = layer.name
            refreshed.visible = layer.visible
            refreshed.opacity = layer.opacity
            refreshed.participates_in_snap = layer.participates_in_snap
            self._reference_layers[index] = refreshed
            self.status_message.emit(f"已刷新参考图层「{layer.name}」")
            break
        self._sync_composition_now()

    def _toggle_reference_snap(self, layer_id: str) -> None:
        for layer in self._reference_layers:
            if layer.id == layer_id:
                layer.participates_in_snap = not layer.participates_in_snap
                break
        self._sync_composition_now()

    def _reference_layer_snap_points(self) -> list[tuple[float, float]]:
        """参与捕捉的引用图层的顶点（井位参考点同一通道）。"""
        points: list[tuple[float, float]] = []
        for layer in self._reference_layers:
            if not layer.participates_in_snap:
                continue
            try:
                points.extend(self._reference_service.vector_snap_points(layer))
            except ReferenceLayerError:
                continue
        return points

    def _reference_snapshot_layers(self) -> list:
        """引用图层的渲染快照（要素按源修订缓存；不可用即诚实降级）。"""
        snapshots: list[MapLayerSnapshot] = []
        project_crs = self.edit_controller.project_crs
        for layer in self._reference_layers:
            features: tuple = ()
            extent = (0.0, 0.0, 1.0, 1.0)
            error = ""
            if layer.source_kind != "vector":
                # 栅格源误入矢量通道：不渲染矢量镜像，状态栏提示走导入校验。
                error = "非矢量参考图层"
            elif (
                project_crs
                and layer.project_crs
                and not crs_equivalent(layer.project_crs, project_crs)
            ):
                # 工程 CRS 在导入后被改过：归一坐标过期，宁可扣发也不错位
                # 叠加（§20；刷新引用可按新 CRS 重读源文件）。
                error = f"坐标系 {layer.project_crs} 与工程 {project_crs} 不一致，未叠加"
            else:
                try:
                    features, extent = self._reference_service.vector_render_payload(layer)
                except ReferenceLayerError as exc:
                    error = str(exc)
            kind = ""
            for record in features:
                geometry = record.get("geometry") if isinstance(record, dict) else None
                if isinstance(geometry, dict):
                    kind = _GEOMETRY_TYPE_KIND.get(str(geometry.get("type") or ""), "")
                    if kind:
                        break
            status = layer.status if not error else "failed"
            previous = self._reference_status.get(layer.id)
            if previous is not None and previous != status:
                self.status_message.emit(f"参考图层「{layer.name}」状态：{status}")
            self._reference_status[layer.id] = status
            revision = zlib.crc32(
                f"{layer.id}|{layer.cache_key}|{status}".encode("utf-8")
            ) & 0x7FFFFFFF
            # 扣发原因上名（短后缀），完整原因进 metadata 供悬停/诊断。
            if error.startswith("坐标系"):
                suffix = "（坐标系不一致，未叠加）"
            elif error:
                suffix = "（不可用）"
            else:
                suffix = ""
            snapshots.append(
                MapLayerSnapshot(
                    id=layer.id,
                    name=f"{layer.name}{suffix}",
                    layer_type="vector",
                    extent=extent,
                    crs=layer.project_crs or self.edit_controller.project_crs,
                    data_revision=revision or 1,
                    style_revision=1,
                    features=features,
                    style=_REFERENCE_STYLES.get(kind) or _REFERENCE_STYLES["line"],
                    visible=layer.visible,
                    opacity=float(layer.opacity),
                    metadata={
                        "reference": "true",
                        "geometry_kind": kind,
                        "status": status,
                        "snap": "true" if layer.participates_in_snap else "false",
                        **({"error": error} if error else {}),
                    },
                )
            )
        return snapshots

    def _apply_reference_display_state(self, display_layers) -> None:
        """把面板显示态（可见性 / 不透明度 / 引用块内顺序）写回引用权威。"""
        by_id = {layer.id: layer for layer in self._reference_layers}
        order: list[str] = []
        for snapshot in display_layers:
            layer_id = str(getattr(snapshot, "id", ""))
            if layer_id not in by_id or layer_id in order:
                continue
            order.append(layer_id)
            reference = by_id[layer_id]
            reference.visible = bool(getattr(snapshot, "visible", True))
            reference.opacity = min(
                1.0, max(0.05, float(getattr(snapshot, "opacity", 1.0) or 1.0))
            )
        if order:
            seen = set(order)
            remaining = [layer.id for layer in self._reference_layers if layer.id not in seen]
            self._reference_layers = [by_id[lid] for lid in order + remaining]

    def _sync_reference_layers_to_project(self) -> None:
        if self._project is not None:
            self._project.workstation_reference_layers = list(self._reference_layers)

    def _on_tree_structure_changed(self) -> None:
        """用户树结构调整（拖拽/建组/删组/组勾选）→ reconcile 落盘。

        1) observe 已更新领域放置表 → reconcile 把期望树（含用户组织）
           增量应用到 QGIS 并写入 state.tree（修复：纯拖拽不落盘，重开
           即回退）；
        2) observe 拒绝的非法放置 → force reconcile 把 QGIS 树拉回领域
           权威位置（修复：非法拖放永不自愈）。
        """
        controller = self.stage_controller.group_controller
        try:
            if getattr(controller, "last_observe_rejected", False):
                # 非法放置：force reconcile 把 QGIS 树拉回领域权威位置。
                controller.reconcile(
                    list(self.layer_manager._layers), force=True)
            else:
                # 合法组织：增量 reconcile 落 state.tree（持久化用户结构）。
                self.stage_controller.sync_composition()
        except Exception:
            logging.getLogger(__name__).exception(
                "tree structure reconcile failed")
        self._sync_workspace_state_to_project()

    def _sync_workspace_state_to_project(self) -> None:
        """阶段工作区科学状态 → ProjectDocument.mapping_workspace；
        组展开态（纯 UI 偏好）→ QSettings。"""
        if self._project is None:
            return
        try:
            self._project.mapping_workspace = self.stage_controller.save_state()
            self.stage_controller.save_expand_prefs(
                str(getattr(getattr(self._project, "meta", None), "name", "") or ""))
        except Exception:
            logging.getLogger(__name__).exception(
                "persist mapping workspace state failed")

    def _create_user_group(self) -> None:
        controller = self.stage_controller.group_controller
        group_id = controller.create_user_group("新建组")
        self._sync_composition_now()
        self.status_message.emit(f"已创建用户组（{group_id}）")

    def _remove_user_group(self, group_id: str) -> None:
        controller = self.stage_controller.group_controller
        controller.remove_user_group(str(group_id), keep_layers=True)
        self._sync_composition_now()
        self.status_message.emit("已删除用户组（图层已保留并上提）")

    def notify_display_changed(self) -> None:
        """图层树回写（可见性/顺序/重命名）后的轻量持久化：不重组快照。"""
        self.edit_controller.apply_display_state(
            self.layer_manager._layers, include_names=True)
        self._apply_reference_display_state(self.layer_manager._layers)
        if self._project is not None and not self._loading:
            self.edit_controller.sync_to_project(self._project)
            self._sync_reference_layers_to_project()
            self._sync_workspace_state_to_project()

    # -- 捕捉设置 -------------------------------------------------------------

    def _open_snapping_settings(self) -> None:
        dialog = SnappingSettingsDialog(
            self.edit_controller,
            well_points=self._well_reference_points()
            + self._reference_layer_snap_points(),
            parent=self,
        )
        dialog.exec()
        self._sync_action_state()

    def _well_reference_points(self) -> list[tuple[float, float]]:
        """基础工区井点（作为捕捉参考点的候选）。"""
        points: list[tuple[float, float]] = []
        for snapshot_layer in self._base_layers:
            if "well" not in str(getattr(snapshot_layer, "id", "")):
                continue
            for record in getattr(snapshot_layer, "features", ()) or ():
                geometry = record.get("geometry") if isinstance(record, dict) else None
                if not isinstance(geometry, dict) or geometry.get("type") != "Point":
                    continue
                coordinates = geometry.get("coordinates")
                if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
                    try:
                        points.append((float(coordinates[0]), float(coordinates[1])))
                    except (TypeError, ValueError):
                        continue
        return points

    # -- 导出 -----------------------------------------------------------------

    def _export_layer(self, layer_id: str) -> None:
        layer = self.edit_controller.layer(layer_id)
        if layer is None:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "导出图层",
            f"{layer.name}.geojson",
            "GeoJSON (*.geojson);;所有文件 (*)",
        )
        if not path:
            return
        features = [
            feature.as_record() for feature in layer.features()
        ]
        payload = {
            "type": "FeatureCollection",
            "name": layer.name,
            "crs": layer.crs or self.edit_controller.project_crs or "",
            "features": features,
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=1)
        except OSError as exc:
            self.status_message.emit(f"导出失败：{exc}")
            return
        self.status_message.emit(f"已导出 {len(features)} 个要素到 {path}")

    # -- 识别结果 -------------------------------------------------------------

    def _identify_with_results(self, point):
        """多图层识别：全部可见可查询图层 → Identify Results 面板。"""
        controller = self.edit_controller
        results = controller.identify_all(point, base_layers=self._base_layers)
        self.identify_results.set_results(results)
        active_id = controller.active_layer_id
        for result in results:
            if result.get("editable") and result.get("layer_id") == active_id:
                return result.get("feature_id")
        return None

    def _locate_identify_result(self, result) -> None:
        if self.edit_controller.locate_identify_result(result):
            record = result.get("record") or {}
            extent = _feature_extent([record])
            if extent[0] < extent[2] and extent[1] < extent[3]:
                self.canvas.set_extent(extent)
            self._sync_composition()
        else:
            geometry = (result.get("record") or {}).get("geometry") or {}
            extent = _feature_extent([{"geometry": dict(geometry)}])
            if extent[0] < extent[2] and extent[1] < extent[3]:
                self.canvas.set_extent(extent)
        self._sync_action_state()

    def flush_edit_sessions(self) -> int:
        """提交全部进行中的矢量编辑会话并写回工程文档（保存前 flush，#1126）。

        显示态（可见性 / 不透明度 / 顺序）一并落盘——保存路径不能只覆盖
        有编辑会话的图层（review #4）。拓扑校验失败的会话保持打开并经
        status_message 告知（review #3）。
        """
        self._composition_timer.stop()
        self.edit_controller.apply_display_state(self.layer_manager._layers)
        self._apply_reference_display_state(self.layer_manager._layers)
        committed, blocked = self.edit_controller.flush_edit_sessions()
        # sessions_committed 已触发过 immediate 重组；无会话提交（纯显示态
        # 变化 / 全部被拓扑阻断）时在此补一次写回。
        if self._project is not None and not committed:
            self.edit_controller.sync_to_project(self._project)
            self._sync_reference_layers_to_project()
        self._sync_workspace_state_to_project()
        for message in blocked:
            self.status_message.emit(message)
        return committed

    # -- 快照合成 ------------------------------------------------------------------

    def _sync_composition(self, *, immediate: bool = True) -> None:
        """重组发布（默认立即；内容变化经 ``immediate=False`` 走 debounce）。"""
        if immediate:
            self._composition_timer.stop()
            self._sync_composition_now()
        else:
            self._composition_timer.start()

    def _sync_composition_now(self) -> None:
        """基础工区图层 + 引用参考图层 + 用户矢量图层合并发布到画布与图层管理面板。"""
        # CRS 权威链：ProjectDocument.coordinate → 编辑控制器 → 面板发布。
        self.layer_manager.set_project_crs(self.edit_controller.project_crs)
        display = {
            layer.id: layer for layer in self.layer_manager._layers
        }
        # 面板显示增量（顺序 / 可见性 / 不透明度）先写回编辑权威，再由
        # 权威重建快照——identify 可见性与工程持久化读到同一份状态（review #4）。
        self.edit_controller.apply_display_state(display.values())
        self._apply_reference_display_state(display.values())
        layers = list(self._base_layers)
        layers.extend(self._reference_snapshot_layers())
        layers.extend(self.edit_controller.snapshot_layers(display=display))
        if self._project is not None and not self._loading:
            # 人工建数据与引用描述写回工程文档（磁盘保存走工程保存）。
            self.edit_controller.sync_to_project(self._project)
            self._sync_reference_layers_to_project()
            self._write_map_project_xml()
        self.layer_manager.bind(self.canvas, layers)
        active_id = self.edit_controller.active_layer_id
        if active_id is not None:
            self.layer_manager.select_layer(active_id)
        self.layer_manager._publish()
        # V5：镜像 upsert 完成后做组结构/放置/阶段显隐的增量 reconcile
        #（组模式下 mirror 不推 root 平铺顺序，组树由 controller 权威驱动）。
        try:
            # 首次发布时绑定树视图地址（展开态回调；幂等）。
            tree_host = getattr(self.layer_manager, "tree_host", None)
            if tree_host is not None and self.uses_native_stack:
                self.stage_controller.group_controller.attach_tree_view(
                    tree_host.tree_view_address)
            self.stage_controller.sync_composition()
        except Exception:
            logging.getLogger(__name__).exception("stage workspace reconcile failed")

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
            self._reference_layers = [
                layer
                for layer in (
                    getattr(project, "workstation_reference_layers", None) or []
                )
                if getattr(layer, "source_kind", "") == "vector"
            ]
            self._reference_status = {}
            self.edit_controller.load_from_project(project)
            # V5：恢复阶段工作区科学状态（当前阶段/成员资格/组结构/视图覆盖）
            # + UI 展开偏好（QSettings，按工程名分域）。
            self.stage_controller.load_state(
                dict(getattr(project, "mapping_workspace", None) or {}))
            self.stage_controller.load_expand_prefs(
                str(getattr(getattr(project, "meta", None), "name", "") or ""))
            catalog = None
            try:
                from paleo_workbench.catalog.runtime import get_catalog
                catalog = get_catalog()
            except Exception:
                catalog = None
            self.stage_controller.attach_document(project, catalog)
            # 先应用呈现态信封（样式/可见性；legacy 信封可能带平铺顺序），
            # 再组合同步——reconcile 以领域树权威重建组结构，覆盖信封的
            # 平铺顺序（否则 legacy 信封会把刚迁移好的分组拆散）。
            xml = str(getattr(project, "map_qgis_project_xml", "") or "")
            apply = getattr(getattr(self.canvas, "stack", None), "apply_project_xml", None)
            if xml and callable(apply):
                apply(xml)
            self._sync_composition_now()
        finally:
            self._loading = False
        if project is not None:
            self._write_map_project_xml()
            # 工程装载完成后恢复阶段上下文（组显隐 + 编辑目标 + 就绪度评估）。
            self.stage_controller.restore_stage_view()
        self.input_tree.refresh(project)

    def _write_map_project_xml(self) -> None:
        """把当前 QgsProject 呈现态写入工程信封。loading 期间不调用。"""
        if self._project is None:
            return
        write = getattr(getattr(self.canvas, "stack", None), "write_project_xml", None)
        if not callable(write):
            return
        self._project.map_qgis_project_xml = write()

    # -- 悬浮工具条定位 ----------------------------------------------------------

    def _reposition_toolbar(self) -> None:
        """Centre the overlay on the map; keep a hairline margin from edges.

        Floating QDockWidgets are separate top-level windows, so they never
        stack under this toolbar. Within the canvas we always raise the bar
        above map chrome and leave 8px top / ≥12px side inset so it does not
        collide with docked panel edges on narrow widths.
        """
        try:
            self._reposition_toolbar_impl()
        except RuntimeError:
            pass  # 死壳迟到的 resize/定时信号：C++ 已销毁，忽略

    def _reposition_toolbar_impl(self) -> None:
        # 窄画布：先收起纯文本的 dock 切换钮（面板菜单保留同功能入口），
        # 否则工具条溢出画布右缘、按钮文字被截断（B17 视觉审查）。
        margin_x = 12
        budget = self.width() - 2 * margin_x
        toggles = (
            self.well_track_button,
            self.seismic_section_button,
            self.link_button,
        )
        self.toolbar.adjustSize()
        overflow = self.toolbar.width() > budget
        for button in toggles:
            button.setVisible(not overflow)
        if overflow:
            self.toolbar.adjustSize()
        y = 8
        x = max(margin_x, (self.width() - self.toolbar.width()) // 2)
        max_x = max(margin_x, self.width() - self.toolbar.width() - margin_x)
        self.toolbar.move(min(x, max_x), y)
        self.toolbar.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_toolbar()
        # 画布随窗口/布局变化后，空态提示必须盖满当前画布矩形（否则残留
        # 布局前的小矩形，文字被截断或不可见）。
        self._sync_hint_geometry()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._reposition_toolbar)

    # -- 生命周期 --------------------------------------------------------------

    def shutdown(self) -> None:
        """释放渲染后端（工程切换 / 退出时由 WorkstationFrame 调用）。"""
        self._composition_timer.stop()
        self._sync_workspace_state_to_project()
        self.canvas.shutdown()
