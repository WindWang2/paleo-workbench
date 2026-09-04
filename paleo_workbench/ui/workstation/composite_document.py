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

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._layers: list = []
        self._canvas: QgisCanvasShim | None = None
        self._tree_connected = False
        self._editing_layer_id: str | None = None
        self._reloading = False
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

        # 识别结果（多图层 Identify）与运行状态栏：图件主视图的诚实附属层。
        self.identify_results = IdentifyResultsPanel(self)
        self.identify_results.setMaximumHeight(200)
        self.identify_results.result_activated.connect(self._locate_identify_result)
        layout.addWidget(self.identify_results)
        self.status_bar = MapStatusBar(self)
        layout.addWidget(self.status_bar)

        # 矢量图层新建 / 编辑（QGIS 式编辑会话，见 composite_editing.py）
        self.edit_controller = CompositeEditController(parent=self)
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
            self.edit_controller.set_active_layer
        )
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
        except RuntimeError:
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
                "编图",
                (
                    ("pan", "zoom_in", "zoom_out", "full_extent", "previous_extent", "next_extent"),
                    ("identify", "select", "select_rectangle", "measure_distance"),
                    ("toggle_editing", "save_edits", "rollback"),
                    ("add_point", "add_line", "add_polygon", "move_feature", "vertex"),
                    ("undo", "redo", "delete_selected", "split", "merge"),
                    ("snapping", "topology", "cancel"),
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
        self._sync_action_state()

    def _save_edits_with_feedback(self) -> None:
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
        # split 需要「编辑中的多边形选集 + 选中切割线」；通用使能规则之外
        # 的综合编修特定条件在此收敛（不显示点了没反应的假按钮）。
        self.action_controller.actions["split"].setEnabled(
            controller._split_inputs() is not None
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
        self._sync_status_bar()

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
        self.edit_controller.remove_layer(layer_id)

    def _duplicate_vector_layer(self, layer_id: str) -> None:
        copy = self.edit_controller.duplicate_layer(layer_id)
        if copy is not None:
            self.status_message.emit(f"已复制图层为「{copy.name}」")

    def _toggle_layer_editing(self, layer_id: str) -> None:
        self.edit_controller.set_active_layer(layer_id)
        if self.edit_controller.editing:
            self._save_edits_with_feedback()
        else:
            self.edit_controller.start_editing()
        self._sync_action_state()

    def _repair_layer(self, layer_id: str) -> None:
        repaired = self.edit_controller.repair_layer_geometries(layer_id)
        if repaired:
            self.status_message.emit(f"已修复 {repaired} 个无效几何（可撤销）")
        else:
            self.status_message.emit("未发现需要修复的无效几何")

    # -- 图层属性 / 符号系统 / 标注（复用 MapLayerPropertiesDialog） ----------

    def _open_layer_properties(self, layer_id: str, *, focus: str = "") -> None:
        """图层属性对话框：QGIS 桥可用走原生符号编辑器，否则 legacy 快速字段。

        不建立第二套符号模型——renderer XML（``qgis_style``）与 legacy
        ``VectorStyle`` 字段同存于图层 style dict，由
        :class:`MapLayerPropertiesDialog` / ``map_symbology_bridge`` 权威解释。
        """
        controller = self.edit_controller
        layer = controller.layer(layer_id)
        if layer is None:
            return
        if isinstance(self.canvas, QgisCanvasShim):
            # QGIS 地图栈：直接 exec 原生 QgsVectorLayerProperties（与 QGIS
            # Desktop 完全一致的属性页），结果经 _apply_native_layer_properties
            # 写回文档模型（不建立第二套符号模型）。
            result = self.canvas.stack.exec_layer_properties(
                self.canvas.canvas_address, str(layer_id))
            if result.get("ok"):
                self._apply_native_layer_properties(str(layer_id), result)
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

    def notify_display_changed(self) -> None:
        """图层树回写（可见性/顺序/重命名）后的轻量持久化：不重组快照。"""
        self.edit_controller.apply_display_state(
            self.layer_manager._layers, include_names=True)
        self._apply_reference_display_state(self.layer_manager._layers)
        if self._project is not None and not self._loading:
            self.edit_controller.sync_to_project(self._project)
            self._sync_reference_layers_to_project()

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
            self._sync_composition_now()
            xml = str(getattr(project, "map_qgis_project_xml", "") or "")
            apply = getattr(getattr(self.canvas, "stack", None), "apply_project_xml", None)
            if xml and callable(apply):
                apply(xml)
        finally:
            self._loading = False
        if project is not None:
            self._write_map_project_xml()
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
        self._composition_timer.stop()
        self.canvas.shutdown()
