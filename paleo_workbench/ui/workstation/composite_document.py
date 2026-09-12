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
from collections.abc import Mapping
from dataclasses import replace
import zlib

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen, QPixmap
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
    QSizePolicy,
    QToolButton,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.crs_contract import panel_publish_crs
from paleo_workbench.mapping.capability_model import (
    QgisCapabilitySnapshot as QgisCapabilityManifest,
    probe_qgis_capability,
    snapshot_stable_hash,
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
from paleo_workbench.mapping.tool_availability import evaluate_all
from paleo_workbench.mapping.tool_context import build_tool_context
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
    pick_topmost_visible_layer_id,
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


#: 点击悬浮框每行上限（QGIS maptip 式摘要；全量仍在识别结果面板）。
_IDENTIFY_POPUP_MAX_LINES = 5

#: 悬浮主属性跳过的几何类键（大小写不敏感；后缀匹配 *_geometry/*_geom）。
_IDENTIFY_POPUP_GEOMETRY_KEYS = frozenset({
    "geometry", "geom", "the_geom", "coordinates", "extent", "bbox",
    "wkt", "geo_json", "geojson",
})


def _identify_popup_key_is_geometry(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if lowered in _IDENTIFY_POPUP_GEOMETRY_KEYS:
        return True
    return lowered.endswith(("_geometry", "_geom"))


def _identify_popup_main(result: Mapping) -> str:
    """一条识别结果的悬浮主属性：name → facies → 首个非几何属性 → 要素 id。"""
    attributes = result.get("attributes") if isinstance(result, Mapping) else None
    if isinstance(attributes, Mapping):
        for key in ("name", "facies"):
            value = attributes.get(key)
            if value is not None and str(value) != "":
                return str(value)
        for key, value in attributes.items():
            if _identify_popup_key_is_geometry(key):
                continue
            return "" if value is None else str(value)
    return str(result.get("feature_id") or "") if isinstance(result, Mapping) else ""


def _identify_popup_text(results) -> str:
    """识别结果 → 点击悬浮文本（纯函数，无 Qt）。

    每行「图层名：主属性」，至多 ``_IDENTIFY_POPUP_MAX_LINES`` 行；超出
    追加「共 N 项 · 详见识别结果面板」；无结果返回空串（调用方不弹框）。
    """
    items = list(results or ())
    if not items:
        return ""
    lines = []
    for result in items[:_IDENTIFY_POPUP_MAX_LINES]:
        layer_name = str(result.get("layer_name") or "") if isinstance(result, Mapping) else ""
        main = _identify_popup_main(result)
        if not main:
            main = "（无属性）"
        lines.append(f"{layer_name or '（未知图层）'}：{main}")
    if len(items) > _IDENTIFY_POPUP_MAX_LINES:
        lines.append(f"共 {len(items)} 项 · 详见识别结果面板")
    return "\n".join(lines)


def _pick_base_identify_target_id(base_layers) -> str | None:
    """最上可见基础镜像层 doc_id（纯函数；原生 identify 的 current 备选）。

    ``base_layers`` 为组装顺序（自下而上）的工区快照层；复用
    ``pick_topmost_visible_layer_id``（反向首个可见即最上），缺
    ``visible`` 视为可见（与 ``identify_all`` 的缺省一致）。
    """
    layers = [
        layer for layer in (base_layers or ()) if str(getattr(layer, "id", "") or "")
    ]
    return pick_topmost_visible_layer_id(
        tuple(str(layer.id) for layer in layers),
        frozenset(str(layer.id) for layer in layers if getattr(layer, "visible", True)),
    )


def _base_identify_entry(base_layers, layer_id, feature_id) -> dict | None:
    """基础镜像层原生 identify 回调 → 面板条目（纯函数，未命中返 None）。

    桥 ``fidResolver`` 回写的是文档记录 id（``record["id"]``，如
    ``wells:<well_id>``），故按记录 id 反查、与顺序无关；条目与
    ``identify_all`` 基础分支同形（``editable=False``），悬浮框复用。
    """
    if not layer_id or not feature_id:
        return None
    for snapshot_layer in base_layers or ():
        if str(getattr(snapshot_layer, "id", "")) != str(layer_id):
            continue
        for record in getattr(snapshot_layer, "features", ()) or ():
            if not isinstance(record, Mapping):
                continue
            if str(record.get("id") or "") != str(feature_id):
                continue
            geometry = record.get("geometry")
            geometry = geometry if isinstance(geometry, Mapping) else {}
            return {
                "layer_id": str(getattr(snapshot_layer, "id", "")),
                "layer_name": str(getattr(snapshot_layer, "name", "")),
                "feature_id": str(record.get("id") or ""),
                "geometry_type": str(geometry.get("type") or ""),
                "attributes": dict(record.get("properties") or {}),
                "source": str(
                    getattr(snapshot_layer, "source_version_id", "") or "workarea"
                ),
                "template": "",
                "editable": False,
                "record": dict(record),
            }
    return None


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
        self.type = getattr(layer, "type", None) or getattr(layer, "layer_type", "vector")
        self.crs = layer.crs
        self.opacity = opacity
        self.source_ref = getattr(layer, "source_ref", "") or "managed"
        self.data_revision = getattr(layer, "data_revision", 0)
        self.style_revision = getattr(layer, "style_revision", 0)
        self.metadata = metadata if metadata is not None else dict(getattr(layer, "metadata", {}) or {})
        self.provenance_ref = (
            getattr(layer, "provenance_ref", "")
            or getattr(layer, "source_version_id", "")
        )


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

    def __init__(self, parent: QWidget | None = None, *, repair_probe=None,
                 menu_probe=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        # V8 M2：修复几何可用性探针（CompositeDocument 注入，消费 canonical
        # evaluator——面板不自建第二套 kind/门禁判断；None = 无宿主，禁用）。
        self._repair_probe = repair_probe
        # V10 M5：图层级菜单事实探针（toggle_editing/repair 的 evaluator
        # 结论 + raw_protected 编排事实）。编辑入口此前只看 metadata.
        # editable 旗标——RAW/冻结/组锁/阻塞的禁用原因进不了菜单（F-1）。
        # None = 无宿主（独立用/测试）：回落 metadata 旗标（旧行为）。
        self._menu_probe = menu_probe
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
            # R3 P2-4：文字按钮的完整文本宽是图层列 360px 地板的来源
            #（连带 hub dock 同列）；给紧凑地板，正文交给省略。
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
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
        # R2-1：禁用原因直达菜单（Qt 默认不显示菜单项 tooltip——必须显式开）。
        menu.setToolTipsVisible(True)
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
        # V8 M2：查看/导出类动作（属性表/属性/符号/标注/导出）对任意已注
        # 册图层开放——与 canonical evaluator 同语义（attribute_table 是只
        # 读查看，RAW 层禁查看是 evaluator 明确拒绝的假限制，review R2-P1）。
        # 编辑类动作（开始编辑/重命名/复制/删除/修复）仍要求可编辑图层。
        open_table = menu.addAction(
            workstation_icon("map/tree-attribute-table.svg"), "打开属性表"
        )
        properties = menu.addAction(
            workstation_icon("map/tree-properties.svg"), "图层属性…"
        )
        symbology = menu.addAction("符号系统…")
        labeling = menu.addAction("标注…")
        export = menu.addAction("导出图层…")
        rename = duplicate = remove = repair = draft = toggle_edit = None
        # V10 M5/R2-6：编辑入口的可用性与禁用原因来自 canonical evaluator
        # （宿主探针把目标图层事实投影进 ToolContext 求值）。facts 先取——
        # RAW 工作流入口按 facts.raw_protected 编排，不受 metadata 旗标
        # 限制（无旗标的 RAW 层同样要拿到「复制为草稿」）。
        facts = (
            self._menu_probe(str(layer_id))
            if callable(self._menu_probe) else None
        )
        if editable or (facts is not None and facts.raw_protected):
            menu.addSeparator()
            toggle_verdict = getattr(facts, "toggle_editing", None)
            if layer_id == self._editing_layer_id:
                toggle_edit = menu.addAction("停止编辑（保存编辑）")
            else:
                toggle_edit = menu.addAction("开始编辑")
            if toggle_verdict is not None:
                toggle_edit.setEnabled(bool(toggle_verdict.enabled))
                if not toggle_verdict.enabled:
                    toggle_edit.setToolTip(
                        f"不可用：{toggle_verdict.disabled_reason}")
            menu.addSeparator()
            # RAW 保护图层的正确工作流入口：复制为可编辑草稿（复制图层），
            # 而不是一个注定失败的「开始编辑」。
            if facts is not None and facts.raw_protected:
                draft = menu.addAction(
                    workstation_icon("map/tree-add-layer.svg"), "复制为草稿…")
                draft.setToolTip("复制本图层为可编辑草稿（RAW/模型结果不可直接编辑）")
            rename = menu.addAction(
                workstation_icon("map/tree-properties.svg"), "重命名图层…"
            )
            duplicate = menu.addAction("复制图层")
            remove = menu.addAction(workstation_icon("map/tree-remove.svg"), "删除图层")
            menu.addSeparator()
            repair = menu.addAction("修复无效几何…")
            # V8 M2：可用性与禁用原因来自 canonical evaluator（宿主探针），
            # 面板不再自建 kind/门禁判断。R1-5：facts 探针优先（menu_probe
            # 已求值过 repair——避免每次开菜单三次全量求值），独立用/测试
            # 回落 repair_probe（旧行为）。
            repair_avail = None
            if facts is not None:
                repair_avail = facts.repair_geometry
            if repair_avail is None and callable(self._repair_probe):
                repair_avail = self._repair_probe(str(layer_id))
            repair.setEnabled(bool(repair_avail and repair_avail.enabled))
            if repair_avail is not None and not repair_avail.enabled:
                repair.setToolTip(f"不可用：{repair_avail.disabled_reason}")
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
        elif chosen is draft:
            self.duplicate_layer_requested.emit(layer_id)
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
                project_crs=panel_publish_crs(self._project_crs),
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

    本部件只拥有主图与两条地图工具条（由 WorkstationFrame 托管为宿主顶行）；
    图层管理 / 输入与结果 / 联动视图三个
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
        # V10 §15：拓扑问题 chip 的进入路径（显式校验 + 首问题定位反馈）；
        # 捕捉读数点击 → 捕捉设置（QGIS 状态条磁铁惯例）。
        self.status_bar.topology_activated.connect(
            self._on_topology_issue_activated)
        self.status_bar.snapping_activated.connect(
            self._open_snapping_settings)
        # V10 R5：最近地图坐标缓存（画布右键「复制坐标」与状态条轻路径）。
        self._last_map_point: tuple[float, float] | None = None

        # 矢量图层新建 / 编辑（QGIS 式编辑会话，见 composite_editing.py）
        self.edit_controller = CompositeEditController(parent=self)
        # RAW/锁定门禁单点注入（V6 B-P0-1：所有会话起点与 flush 提交经此）。
        self.edit_controller.set_edit_gate(self._role_allows_editing)
        # V9 W6/W9：角色查询单点注入——快照 metadata.role（镜像 QgsFields 来源）
        # 与捕获 spec 默认值都派生自 stage membership（单一角色权威）。
        self.edit_controller.set_role_lookup(self._layer_role_value)
        # V7 能力快照：桥面（native/fallback）单次探测；会话的 EditDelta
        # 以此摘要记录引擎溯源（native 执行 vs shapely 兜底可审计）。
        self._qgis_capability: QgisCapabilityManifest = probe_qgis_capability()
        self.edit_controller.set_qgis_capability_token(
            snapshot_stable_hash(self._qgis_capability)
            if self._qgis_capability.available
            else "unavailable"
        )
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
        # M2 §3：邻层入集被拒（场景 7）——状态条提示。
        self.edit_controller.native_join_refused.connect(
            self.status_message.emit)
        self.edit_controller.state_changed.connect(self._sync_action_state)
        # V8 M3：复合撤销被拒（冲突/顺序）必须可见——接状态消息通道，
        # 不静默半组回退（review-1 P1 处置的 UI 面）。
        self.edit_controller.topology_conflict.connect(self.status_message.emit)
        self.canvas.tool_operation.connect(self._on_tool_operation)
        # V10 M7：画布右键菜单（§20）——复用 action_controller 的已求值
        # QAction（enabled/visible/禁用原因与工具条同源；执行仍经
        # tool_requested/command_requested 的 execution re-gate）。
        self.canvas.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(
            self._on_canvas_context_menu)
        # 视野（pan/zoom）是高频事件：走轻路径——勾选态 + 状态条；统一
        # 可用性/树装饰与 extent 无关（R3-P2：满载 1000 层时每次 pan 全量
        # 重算 27ms，超 60fps 预算）。
        def _on_extent_changed(*_):
            controller = self.edit_controller
            for action_id in self.action_controller._TOOL_IDS:
                action = self.action_controller.actions[action_id]
                active_tool_id = (
                    getattr(controller.tools.active_tool, "tool_id", "") or "pan"
                )
                action.blockSignals(True)
                action.setChecked(action_id == active_tool_id)
                action.blockSignals(False)
            # V10 R5-2：extent 是逐帧事件——只轻量更新比例尺读数（全量
            # 上下文重建留在状态同步链；R3-P2 的 pan 预算不被回退）。
            self.status_bar.update_scale(self._canvas_scale_denominator())

        self.canvas.extent_changed.connect(_on_extent_changed)
        self.canvas.map_position_changed.connect(self._on_map_position)
        self.canvas.backend_status_changed.connect(lambda *_: self._sync_status_bar())
        # V8/M1：原生 QgsMapTool 激活失败 → 回退 pan + 状态条原因（checked
        # 与画布实际工具不得漂移）。fallback 画布有同名信号但永不发射。
        native_failed = getattr(self.canvas, "native_tool_activation_failed", None)
        if native_failed is not None:
            native_failed.connect(self._on_native_tool_activation_failed)
        # V7：原生测距结果 → 状态栏（fallback 画布无此信号，鸭子类型跳过）。
        measure_updated = getattr(self.canvas, "measure_updated", None)
        if measure_updated is not None:
            measure_updated.connect(self._on_measure_updated)
        # V10（review-5 #20）：捕获过程反馈接到测距栏（数字化与测距互斥，
        # 标签复用零 UI 改动）；snap_feedback 保持纯信号面（消费方按需接线，
        # 状态栏 snapping 标签归 update_state 所有——避免高频闪烁）。
        capture_progress = getattr(self.canvas, "capture_progress", None)
        if capture_progress is not None:
            capture_progress.connect(self._on_capture_progress)
        measure_canceled = getattr(self.canvas, "measure_canceled", None)
        if measure_canceled is not None:
            measure_canceled.connect(lambda: self.status_bar.set_measure(""))
        # V7/P1-3：旧桥视口路由的测距分段/预览 → 状态栏（平面距离，明确
        # 标注；原生测距在位时路由器不挂载，此处无信号可接，自然静默）。
        measure_segment = getattr(self.canvas, "measure_segment", None)
        if measure_segment is not None:
            measure_segment.connect(self._on_measure_segment)
        measure_preview = getattr(self.canvas, "measure_preview", None)
        if measure_preview is not None:
            measure_preview.connect(self._on_measure_preview)
        # V7：原生 identify 结果消费（此前无消费者——原生栈点击识别面板
        # 从不打开）。结果经 Python 数据权威组装后进 Identify Results 面板。
        native_identified = getattr(self.canvas, "native_identified", None)
        if native_identified is not None:
            native_identified.connect(self._on_native_identified)
        # V7/ADV-2：原生提交被拒 → 状态栏明示（采点完成必须有回执）。
        commit_rejected = getattr(self.canvas, "commit_rejected", None)
        if commit_rejected is not None:
            commit_rejected.connect(self.status_message.emit)

        # 面板实例（dock 由宿主 QMainWindow 创建并管理）。图层管理面板跟随
        # 画布形态：原生栈用 QgsLayerTreeView 面板，回退画布用同信号接缝的
        # LayerManagerPanel（QTreeWidget 自绘树）——两套面板 16 个请求信号同构。
        self.layer_manager = self._create_layer_manager()
        # 面板挂为本部件子部件：dock 宿主路径下 setWidget 会再 reparent 进
        # dock（所有权随 dock），无 dock 的孤立构造（单测直接建 document）
        # 则随 document 析构——此前无父，裸 document 每拆一次泄漏 3 个面板。
        self.input_tree = InputTreePanel(project, self)
        self.linked_views = LinkedViewsPanel(self)
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
            self._on_user_active_layer_changed)
        # V11 五目标：树选中节点信息性记录（07-active-edit-state）。
        self.layer_manager.active_layer_changed.connect(
            self.edit_controller.note_tree_selection)
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
        from paleo_workbench.mapping_workspace.artifact_keys import (
            candidate_artifact_keys,
        )

        self.stage_controller = MappingStageController(parent=self)
        self._layer_role_enum = LayerRole
        # V7 §7：组聚合的成熟度回调（键解析唯一源在本类，controller 只数）。
        self.stage_controller.group_controller.set_maturity_provider(
            self._layer_maturity_value
        )
        # V7 R3-P1：新鲜度评估变化 → 树装饰即时刷新（此前 stale 推送后
        # 树要等下一次无关交互才更新——goal §7 的主过期呈现面滞后）。
        try:
            self.stage_controller.stale_summary_changed.connect(
                lambda *_: self._push_layer_decorations()
            )
        except (AttributeError, RuntimeError):
            pass  # 旧 controller 无该信号：保持轮询路径
        # 主题切换 → 状态列颜色重取（R3-P2：装饰色随 palette()，但只在
        # 推送时写入 item，切主题后需重推）。
        from paleo_workbench.ui.theme import theme_manager

        try:
            theme_manager.theme_changed.connect(self._on_theme_changed)
        except (AttributeError, RuntimeError):
            pass
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
        """图层管理面板跟随画布形态（两套面板请求信号同构，见类 docstring）。

        V11 Goal §7（A1）：两套面板消费同一 evaluator 探针——同一图层在
        原生树/回退树的编辑·修复·删除可用性与判词一致。
        """
        if self.uses_native_stack:
            return QgisLayerTreePanel(
                self,
                repair_probe=self._layer_repair_availability,
                menu_probe=self.layer_menu_facts,
            )
        return LayerManagerPanel(
            self,
            repair_probe=self._layer_repair_availability,
            menu_probe=self.layer_menu_facts,
        )

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

    # -- 地图工具条（宿主托管，见 _build_toolbar） ----------------------------------

    # -- 阶段工具面（V6 §4） ------------------------------------------------------

    def apply_stage_tool_profile(self, stage_value: str) -> None:
        """切换阶段并让 canonical evaluator 重新裁决工具面可见性。

        V8 M1：不再直接 ``QAction.setVisible``（消除与 evaluator 并行的
        第二可见性权威）——阶段进入 :class:`ToolContext`，组隐藏/受治理
        编辑动作过滤全部由 ``mapping.tool_availability`` 单点推导。
        未知阶段值保持现状（evaluator 对未知阶段 fail-closed）。
        """
        from paleo_workbench.mapping_workspace.stages import stage_from_value

        stage = stage_from_value(stage_value)
        if stage is None:
            return
        if hasattr(self, "stage_controller"):
            try:
                self.stage_controller.set_stage(stage)
            except Exception:
                pass
        # V10 M-N：阶段切换改变层集成员资格/可见性——捕捉配置投影重建。
        try:
            self.edit_controller.repush_snapping()
        except Exception:
            pass
        self._sync_action_state()

    # -- V7 上下文驱动工具面（V8 M1：canonical contract） ---------------------

    def tool_context(self) -> ToolContext:
        """当前 canonical ``ToolContext``（工具条/palette/状态条共用输入）。

        全部字段来自既有权威：``tool_context_inputs``（V7 kernel 采集器，
        会话/选择/撤销/捕捉/阻塞任务）+ ``action_state`` 的 extent 历史 +
        图层事实（角色/几何/成熟度/门禁结论）+ 阶段 + 运行期画布后端三态。
        构造廉价（纯派生，无 Qt 事件循环依赖）。
        """
        controller = self.edit_controller
        stage_value = None
        stage_controller = getattr(self, "stage_controller", None)
        if stage_controller is not None:
            current = getattr(stage_controller, "current_stage", None)
            stage_value = getattr(current, "value", None)
        backend = self._capability_snapshot()
        layer = self._layer_capability(controller.active_layer_id)
        raw_locked, stage_locked = self._layer_lock_classes(
            str(controller.active_layer_id or ""))
        inputs = dict(
            controller.tool_context_inputs()
            if hasattr(controller, "tool_context_inputs") else {}
        )
        inputs["can_previous_extent"] = bool(self.canvas.can_previous_extent)
        inputs["can_next_extent"] = bool(self.canvas.can_next_extent)
        inputs["raw_locked"] = raw_locked
        inputs["stage_locked"] = stage_locked
        inputs["queryable_layer_count"] = self.queryable_layer_count()
        # V9 W1：画布权威比例尺 + 运行时阻塞任务（文档拥有画布与调度器视野，
        # 控制器不持有——注入而非在采集器里猜）。控制器上显式设置的标签
        # （visual-QA 驱动面/宿主模态操作）优先于调度器派生。
        inputs["scale_denominator"] = self._canvas_scale_denominator()
        # V10 R5-3：调度器快照只取一次（blocking 判定与计数共用——此前
        # 每次上下文构建两次 statuses() 拷贝）。
        scheduler_statuses = self._scheduler_statuses()
        inputs["blocking_task"] = (
            str(getattr(controller, "blocking_task_label", "") or "")
            or self._mapping_blocking_task_label(scheduler_statuses)
        )
        # V10 M3：CRS 呈现事实（画布目标 CRS + 工程/图层 CRS 不一致判定）
        # 与状态计数（失败引用/运行任务/参与捕捉引用）——全部派生自既有
        # 权威（桥 getter、crs_contract、引用状态表、调度器快照），O(1)。
        inputs["canvas_destination_crs"] = self._canvas_destination_crs()
        inputs["crs_mismatch"] = self._project_layer_crs_mismatch(
            inputs.get("project_crs", ""), inputs.get("layer_crs", ""))
        inputs["reference_failed_count"] = self._reference_failed_count()
        inputs["snapping_reference_count"] = self._snapping_reference_count()
        inputs["running_task_count"] = self._running_task_count(scheduler_statuses)
        # V10 M-B/M-O/M-N：地图事实（canvas 权威）+ 捕捉事实（SnappingService
        # 权威）注入。回退画布无对应方法 → 诚实默认（""/0.0）。
        canvas = self.canvas
        inputs["canvas_crs"] = str(
            getattr(canvas, "destination_crs", lambda: "")() or "")
        inputs["map_units"] = str(
            getattr(canvas, "map_units", lambda: "")() or "")
        inputs["output_dpi"] = float(
            getattr(canvas, "output_dpi", lambda: 0.0)() or 0.0)
        snapping_service = getattr(controller, "snapping", None)
        if snapping_service is not None:
            inputs["snapping_tolerance_px"] = float(
                getattr(snapping_service, "pixel_tolerance", 0.0) or 0.0)
            inputs["snapping_modes"] = tuple(
                getattr(snapping_service, "modes", ()) or ())
        # V10 M-H：活动层 provider 能力（桥自省面；无面 = None 不参与门禁）。
        provider_writable = None
        provider_name = ""
        active_id = str(controller.active_layer_id or "")
        if active_id and self.uses_native_stack:
            facts = canvas.mirror_provider_facts(active_id) if hasattr(
                canvas, "mirror_provider_facts") else None
            if facts and facts.get("exists"):
                provider_name = str(facts.get("provider") or "")
                capability = facts.get("capability") or {}
                # V10（#1260）："是否可写"采信桥给的权威结论
                # （QgsVectorLayer::supportsEditing）——此前宿主用三个
                # capability 位自造合取重新推断，会用"只读数据源"这种失实
                # 判词硬拦支持编辑但属性只读的 provider。只有桥未提供该位
                # （旧桥）时才回落到三位合取，并按近似判据记录。
                declared = facts.get("supports_editing")
                if declared is None:
                    provider_writable = bool(
                        capability.get("add_features")
                        and capability.get("change_geometries")
                        and capability.get("change_attribute_values"))
                    provider_writable_approximate = True
                else:
                    provider_writable = bool(declared)
                    provider_writable_approximate = False
        inputs["provider_writable"] = provider_writable
        inputs["provider_name"] = provider_name
        return build_tool_context(
            controller_state=inputs,
            qgis=self._qgis_capability,
            native_canvas_available=bool(self.uses_native_stack),
            project_open=self._project is not None,
            mapping_stage=stage_value,
            layer_facts=layer.layer_facts(),
            backend_mode=backend.mode,
            backend_reason=backend.reason,
        )

    def queryable_layer_count(self) -> int:
        """可查询图层计数（identify 门禁输入）：编修层 + 可见基础层 + 可见就绪引用层。

        引用层以面板写回的 ``visible`` 与运行期状态（``_reference_status``，
        缺键回落模型 ``status``）为准——离线/失败的外部源不是可查询图层。
        """
        controller = self.edit_controller
        try:
            edit_count = len(controller.layer_ids())
        except Exception:  # noqa: BLE001 — 门禁输入缺席按零层处理，不崩工具条
            edit_count = 0
        base_count = sum(
            1 for layer in (self._base_layers or ())
            if getattr(layer, "visible", True)
        )
        reference_count = 0
        for reference in (self._reference_layers or ()):
            if not getattr(reference, "visible", True):
                continue
            status = self._reference_status.get(
                getattr(reference, "id", ""),
                getattr(reference, "status", "ready"),
            )
            if str(status or "") == "ready":
                reference_count += 1
        return edit_count + base_count + reference_count

    # -- V9 W1：画布比例尺与阻塞任务（上下文权威事实） --------------------------

    def _canvas_scale_denominator(self) -> float:
        """画布比例尺分母（0.0 = 诚实未知）。

        原生路径取 QGIS ``QgsMapCanvas::scale()``（桥 getter，探针门控）；
        回退画布仅在 CRS 可证米制轴时由像素几何推导（QGIS 同式
        ``mupp × 39.3701 × logicalDpi``），否则未知——绝不给一个貌似
        精确的错误数字。
        """
        canvas = self.canvas
        if canvas is None:
            return 0.0
        native_scale = getattr(canvas, "map_scale", None)
        if callable(native_scale):
            try:
                value = float(native_scale())
                if value > 0.0:
                    return value
            except Exception:
                pass
        from paleo_workbench.mapping.crs_contract import (
            scale_denominator_from_pixels,
        )

        try:
            mupp = float(canvas.map_units_per_pixel)
            width = int(canvas.width() or 0)
            dpi = float(canvas.logicalDotsPerInch() or 0.0)
        except Exception:
            return 0.0
        if mupp <= 0.0 or width <= 0 or dpi <= 0.0:
            return 0.0
        return scale_denominator_from_pixels(
            mupp, dpi, self.edit_controller.project_crs)

    def _scheduler_statuses(self) -> tuple:
        """调度器状态快照（一次取用，blocking/计数共用；None = 不可用）。"""
        try:
            from paleo_workbench.runtime.task_scheduler import get_scheduler

            return tuple(get_scheduler().statuses())
        except Exception:
            return ()

    def _mapping_blocking_task_label(self, statuses=None) -> str:
        """持有编图工程独占权的运行中任务标签（blocking_task 生产生产者）。

        V9 W1 契约：不是所有后台任务都阻塞编图（渲染/转码不阻塞）——
        只有改写编图工程产物的工作流 DAG 运行（kind=background.compute、
        title=workflow:*）会让 merge/assemble/QA 等读到半成品，须以全局
        阻塞呈现。判定词表集中在此，采集廉价（statuses() 快照）。
        """
        try:
            from paleo_workbench.runtime.task_scheduler import TaskState

            handles = self._scheduler_statuses() if statuses is None else statuses
        except Exception:
            return ""
        for handle in handles:
            if handle.state is not TaskState.RUNNING:
                continue
            kind = str(handle.spec.kind or "")
            title = str(handle.spec.title or "")
            if kind == "background.compute" and title.startswith("workflow:"):
                return title.split("(", 1)[0].strip() or "工作流运行中"
        return ""

    def _canvas_destination_crs(self) -> str:
        """画布目标 CRS auth id（V10 M3；"" = 桥未暴露/画布未创建）。

        原生桥 ≥0.5.0a0 经 ``canvas_destination_crs`` getter 暴露；回退
        画布与旧桥诚实返回 ""。呈现层不猜测（绝不能显示一个伪造的 4326）。
        """
        canvas = self.canvas
        getter = getattr(canvas, "destination_crs", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "")
        except Exception:
            return ""

    @staticmethod
    def _project_layer_crs_mismatch(project_crs: object, layer_crs: object) -> bool | None:
        """工程/图层 CRS 是否可证不一致（None = 不可判定）。

        任一未声明 → None（不猜）；两者都声明 → 归一化后比对（经
        crs_contract.normalize_crs——描述式别名如「EPSG:4490 / CGCS2000」
        与 auth id 等价）。这是呈现警示事实，不是门禁（门禁在
        crs_valid / 捕获 commit 守卫）。
        """
        from paleo_workbench.mapping.crs_contract import normalize_crs

        project = normalize_crs(project_crs)
        layer = normalize_crs(layer_crs)
        if not project or not layer:
            return None
        return project != layer

    def _reference_failed_count(self) -> int:
        """失败/错误的引用图层数（V10 M3 呈现计数）。"""
        count = 0
        for reference in self._reference_layers or ():
            status = str(self._reference_status.get(
                getattr(reference, "id", ""),
                getattr(reference, "status", ""),
            ) or "")
            if status in {"failed", "error"}:
                count += 1
        return count

    def _snapping_reference_count(self) -> int:
        """参与捕捉的引用图层数（V10 M3；metadata.snap == "true"）。"""
        count = 0
        for reference in self._reference_layers or ():
            metadata = getattr(reference, "metadata", None) or {}
            if str(metadata.get("snap", "") or "") == "true":
                count += 1
        return count

    def _running_task_count(self, statuses=None) -> int:
        """运行中+排队任务总数（V10 M3 呈现计数；门禁事实是 blocking_task）。

        ``statuses`` 可传入共享调度器快照（tool_context 一次取用，
        R5-3——避免每次上下文构建两次 statuses() 拷贝）。
        """
        try:
            from paleo_workbench.runtime.task_scheduler import TaskState

            handles = self._scheduler_statuses() if statuses is None else statuses
        except Exception:
            return 0
        return sum(
            1 for handle in handles
            if handle.state in (TaskState.QUEUED, TaskState.RUNNING)
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

    def active_layer_capability(self) -> LayerCapabilitySnapshot:
        """活动图层能力呈现快照（palette/status/inspector 的图层事实源）。"""
        return self._layer_capability(self.edit_controller.active_layer_id)

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
        from paleo_workbench.mapping_workspace.artifact_keys import (
            candidate_artifact_keys,
        )
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole

        state = self.stage_controller.state
        layer_id = str(layer_id)
        if role is None:
            role = state.role_of(layer_id)
        if role.is_raw_protected:
            return "raw"
        record = state.membership(layer_id)
        keys: list[str] = (
            candidate_artifact_keys(layer_id, record) if record is not None else []
        )
        for key in keys:
            found = state.artifact_maturity.get(key)
            if found:
                return str(found)
        return None

    def tool_availability(self) -> dict[str, ToolAvailability]:
        """统一可用性求值（canonical evaluator；供工具条刷新与 palette 复用）。"""
        return evaluate_all(self.tool_context())

    def explain_action(self, tool_id: str):
        """M4：一个动作的完整上下文解释（Inspector/palette/Agent 共用）。

        动态结论（可用性/原因/checked）来自 canonical evaluator，静态事实
        来自 ``action_help`` 登记处——没有第二份手写状态表。
        """
        from paleo_workbench.ui.workstation.action_help import explain

        return explain(tool_id, self.tool_context())

    def _apply_tool_availability(self) -> None:
        """把 canonical evaluator 结论应用到 QAction 面（唯一应用点）。

        V8 M1：host 不再改写 evaluator 输出——snapping 只需活动图层、
        save/rollback 的 dirty 门禁等规则已并入 canonical evaluator。
        V8 M4：tooltip/statusTip 由 ``action_help`` 从同一契约派生。
        V10 M8：preferred 工具的轻微视觉提示（QToolButton[preferred] 下缘
        accent 线）+ 捕获/捕捉/拓扑工具 tooltip 附「当前编辑目标/捕捉配置」
        状态块（呈现事实来自同一 ToolContext，非第二判词）。
        """
        from paleo_workbench.ui.workstation.action_help import (
            explain,
            format_status,
            format_tooltip,
        )

        ctx = self.tool_context()
        availability = dict(evaluate_all(ctx))
        # V10 M12：help 文本按上下文签名差分重建——explain（每工具一次
        # 求值 + 文本拼装）占刷新成本的大头，而它只依赖 ctx + 静态登记处。
        # state_changed 风暴（一次操作 ~30 次发射）在上下文未变时不再重拼。
        # enable/visible/checked 每次照常应用（无漂移风险）。
        signature = repr(ctx.to_dict())
        if signature != getattr(self, "_help_signature", None):
            help_texts = {}
            status_blocks = self._action_status_blocks(ctx)
            for tool_id in availability:
                explanation = explain(tool_id, ctx)
                tooltip, status_tip = (
                    format_tooltip(explanation), format_status(explanation))
                extra = status_blocks.get(tool_id)
                if extra:
                    tooltip = f"{tooltip}\n{extra}"
                help_texts[tool_id] = (tooltip, status_tip)
            self._help_signature = signature
            self._help_texts = help_texts
        else:
            help_texts = self._help_texts
        self._last_availability = availability
        self.action_controller.apply_availability(availability, help_texts=help_texts)
        # preferred 动态属性（QSS 弱提示）——写入工具条按钮并 repolish；
        # 仅 enabled+preferred 才提示（禁用态不叠样式）。
        for bar in self.host_map_toolbars():
            for tool_id, verdict in availability.items():
                action = self.action_controller.actions.get(tool_id)
                if action is None:
                    continue
                button = bar.widgetForAction(action)
                if button is None:
                    continue
                preferred = bool(verdict.enabled and verdict.preferred)
                if bool(button.property("preferred") or False) != preferred:
                    button.setProperty("preferred", preferred)
                    button.style().unpolish(button)
                    button.style().polish(button)
        # 求值器隐藏整组动作后，组间分隔符会变孤儿「|」（Qt 不随动作联动
        # 隐藏）——按可见邻居重算，保持条带干净。
        self._sync_toolbar_separators()

    def _action_status_blocks(self, ctx: ToolContext) -> dict[str, str]:
        """捕获/捕捉/拓扑/编辑会话工具的 tooltip 状态块（V10 §13/§15）。

        呈现事实全部来自 ToolContext（单一事实源）——当前编辑目标（名称/
        几何/角色）、捕捉配置（容差/模式/参与引用/角色推荐态）。这是状态
        块，不是禁用判词（判词永远原样来自 evaluator）。
        """
        blocks: dict[str, str] = {}
        # V11（#1268 收敛）：数字化进行中（tool 目标 ≠ 树选中）时，捕获类
        # 工具的状态块必须显示**工具实际写入层**，绝不把树选中层呈现成
        # 编辑目标（07-active-edit-state 的 divergent 呈现义务）。
        targets = getattr(self.edit_controller, "edit_targets", None)
        snapshot = targets() if callable(targets) else None
        if snapshot is not None and snapshot.divergent:
            tool_layer = self.edit_controller._layers.get(
                snapshot.tool_target_layer or "")
            tool_name = (tool_layer.name if tool_layer is not None
                         else snapshot.tool_target_layer)
            divergent_note = (
                f"数字化目标：{tool_name}"
                f"（树选中 {ctx.layer_name or ctx.active_layer_id}；"
                "手势完成后随目标切换）")
            for tool_id in ("add_point", "add_line", "add_polygon",
                            "move_feature", "vertex", "toggle_editing",
                            "delete_selected", "split", "merge", "reshape"):
                blocks[tool_id] = divergent_note
        elif ctx.has_active_layer:
            from paleo_workbench.mapping.tool_availability import LAYER_CAPTION

            target = f"当前编辑目标：{ctx.layer_name or ctx.active_layer_id}"
            details = [LAYER_CAPTION(ctx.active_layer_kind) + "图层"]
            if ctx.layer_role_label:
                details.append(ctx.layer_role_label)
            if ctx.artifact_maturity:
                details.append(ctx.artifact_maturity)
            target += "（" + " · ".join(details) + "）"
            for tool_id in ("add_point", "add_line", "add_polygon",
                            "move_feature", "vertex", "toggle_editing",
                            "delete_selected", "split", "merge", "reshape"):
                blocks[tool_id] = target
        snap_lines = []
        if ctx.snapping_enabled:
            effective = self._effective_snapping_tolerance()
            if effective > 0.0:
                snap_lines.append(f"有效容差 {effective:g} px（含图层覆盖）")
            if ctx.snapping_modes:
                snap_lines.append("模式：" + "、".join(ctx.snapping_modes))
            if ctx.snapping_reference_count > 0:
                snap_lines.append(f"参与捕捉引用层 {ctx.snapping_reference_count} 个")
            if ctx.snapping_role_recommended is True:
                snap_lines.append("当前配置 = 角色推荐")
            elif ctx.snapping_role_recommended is False:
                snap_lines.append("用户自定义（与角色推荐不同）")
        else:
            snap_lines.append("捕捉关闭")
        blocks["snapping"] = "捕捉设置：" + "；".join(snap_lines)
        topology_lines = []
        if ctx.topology_enabled:
            topology_lines.append("拓扑编辑开启（保存时校验）")
        else:
            topology_lines.append("拓扑编辑关闭")
        if ctx.topology_error_count > 0:
            topology_lines.append(f"当前会话拓扑错误 {ctx.topology_error_count} 处")
        blocks["topology"] = "拓扑状态：" + "；".join(topology_lines)
        return blocks

    def _sync_toolbar_separators(self) -> None:
        """隐藏无动作邻居的分隔符（首/尾/连续可见分隔符一律隐藏）。

        判定只看 ``QAction.isVisible``（``addWidget`` 挂的视图开关按钮以
        关联 action 计入，与工具动作同一规则）。求值器每次应用后调用。

        隐藏分隔符在判定中视为透明，但同一动作间隔内只保留第一个分隔
        符——否则「全显→全藏→全显」逐次震荡（非幂等陷阱），永远不
        收敛。终态：连续隐藏组之间恰好一条 ``|``，首/尾/连续 ``|`` 为零条。
        """
        for bar in self.host_map_toolbars():
            actions = bar.actions()
            # 间隔端点：最近可见动作（跳过隐藏项与分隔符本身）。
            prev_action: list = [None] * len(actions)
            last = None
            for index, action in enumerate(actions):
                prev_action[index] = last
                if action.isVisible() and not action.isSeparator():
                    last = index
            next_action: list = [None] * len(actions)
            coming = None
            for index in range(len(actions) - 1, -1, -1):
                next_action[index] = coming
                action = actions[index]
                if action.isVisible() and not action.isSeparator():
                    coming = index
            # 同一动作间隔（隐藏项延续间隔，不重置）只保留首个分隔符。
            interval_shown = False
            for index, action in enumerate(actions):
                if not action.isSeparator():
                    if action.isVisible():
                        interval_shown = False
                    continue
                show = (
                    prev_action[index] is not None
                    and next_action[index] is not None
                    and not interval_shown
                )
                if show:
                    interval_shown = True
                if action.isVisible() != show:
                    action.setVisible(show)

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
        # 树上仍存在、但编辑注册表已没有的行 → 显式「缺失」（R1-P2：承诺
        # 的 missing 装饰此前从未产生）。
        from PySide6.QtCore import Qt as _Qt

        tree = getattr(self.layer_manager, "tree", None)
        if tree is not None:
            for row in range(tree.topLevelItemCount()):
                layer_id = str(tree.topLevelItem(row).data(
                    0, _Qt.ItemDataRole.UserRole) or "")
                if layer_id and layer_id not in decorations                         and controller.layer(layer_id) is None:
                    decorations[layer_id] = LayerPresentationState(
                        missing=True,
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

    def _on_theme_changed(self, *_args) -> None:
        self._push_layer_decorations()

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
        """地图工具条：QGIS 命令面（MapActionController）+ 视图开关 +「面板」菜单。

        托管模型（两行布局）：本方法只建条——两条原生 ``QToolBar``（上排核心
        编图组 / 下排辅助组 + 视图开关与面板菜单），宿主 ``WorkstationFrame``
        把它们加进 ``_dock_host`` TopToolBarArea 第 2 行（见
        ``host_map_toolbars``）。画布上不再悬浮任何工具条；窄窗口溢出交给
        Qt 原生工具条扩展按钮（``»``）。动作使能求值语义见
        ``_apply_tool_availability``（只改托管父级与布局，逻辑不变）。
        """
        self.action_controller = MapActionController(self)
        # V7 专业分组（goal §6）：Navigation / Selection / Inspection / Edit
        # Session / Capture / Geometry / Snapping·Topology / Layer /
        # Symbology / Factor / QA / Layout·Export——组内动作使能由统一
        # 求值器管理，组级可见性随阶段/图层切换（_apply_tool_availability）。
        from paleo_workbench.ui.workstation.tool_surface import TOOL_GROUPS

        self._toolbar_group_order = (
            "navigate", "selection", "inspection", "edit_session",
            "capture", "geometry", "snapping", "layer",
            "symbology", "factor", "qa", "layout_export",
        )
        self._toolbar_top_groups = (
            "navigate", "selection", "inspection", "edit_session",
            "capture", "geometry",
        )
        self._toolbar_bottom_groups = (
            "snapping", "layer", "symbology", "factor", "qa",
            "layout_export",
        )
        # 建条时暂挂本部件名下；宿主 addToolBar 时 Qt 自动 reparent 进
        # QMainWindow（孤立构造/单测则留在此处，随 document 析构）。
        self._map_toolbar_top = self.action_controller.toolbar(
            "编图常用",
            tuple(tuple(TOOL_GROUPS[group]) for group in self._toolbar_top_groups),
            self,
        )
        self._map_toolbar_top.setObjectName("WorkstationMapToolsToolbarTop")
        self._configure_host_toolbar(self._map_toolbar_top)
        self._map_toolbar_bottom = self.action_controller.toolbar(
            "编图扩展",
            tuple(tuple(TOOL_GROUPS[group]) for group in self._toolbar_bottom_groups),
            self,
        )
        self._map_toolbar_bottom.setObjectName("WorkstationMapToolsToolbarBottom")
        self._configure_host_toolbar(self._map_toolbar_bottom)
        self.action_controller.tool_requested.connect(self._on_tool_requested)
        self.action_controller.command_requested.connect(self._on_command_requested)

        # 视图 dock 开关 + 联动（宿主 WorkstationFrame 接线）。
        self.well_track_button = QToolButton(self._map_toolbar_bottom)
        self.well_track_button.setObjectName("WorkstationWellTrackButton")
        self.well_track_button.setText("测井轨道")
        self.well_track_button.setCheckable(True)
        self.well_track_button.toggled.connect(self.well_track_toggled)
        self.seismic_section_button = QToolButton(self._map_toolbar_bottom)
        self.seismic_section_button.setObjectName("WorkstationSeismicSectionButton")
        self.seismic_section_button.setText("地震剖面")
        self.seismic_section_button.setCheckable(True)
        self.seismic_section_button.toggled.connect(self.seismic_section_toggled)
        self.link_button = QToolButton(self._map_toolbar_bottom)
        self.link_button.setObjectName("WorkstationLinkButton")
        self.link_button.setText("链接")
        self.link_button.setCheckable(True)
        self.link_button.setChecked(True)
        self.link_button.toggled.connect(self.link_toggled)
        self._map_toolbar_bottom.addSeparator()
        self._map_toolbar_bottom.addWidget(self.well_track_button)
        self._map_toolbar_bottom.addWidget(self.seismic_section_button)
        self._map_toolbar_bottom.addWidget(self.link_button)

        # 面板菜单：显隐 / 布局预设 / 全部浮动·停靠 / 恢复默认（由宿主注入）
        self.panels_button = QToolButton(self._map_toolbar_bottom)
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
        self._map_toolbar_bottom.addSeparator()
        self._map_toolbar_bottom.addWidget(self.panels_button)

    @staticmethod
    def _configure_host_toolbar(bar) -> None:
        """宿主行工具条统一样式：不可移动/浮动、屏蔽右键菜单（与全局栏/阶段条对齐）。"""
        from PySide6.QtWidgets import QToolBar

        assert isinstance(bar, QToolBar)
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        bar.layout().setContentsMargins(0, 0, 0, 0)

    def host_map_toolbars(self) -> tuple:
        """宿主行挂载顺序：shell 按此顺序把两条工具条加进第 2 行。"""
        return (self._map_toolbar_top, self._map_toolbar_bottom)

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

    #: 画布交互工具（palette/shortcut 复用工具条同一激活路径）。
    _CANVAS_TOOL_COMMANDS = frozenset({
        "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
        "measure_distance", "add_point", "add_line", "add_polygon",
        "move_feature", "vertex", "reshape", "add_ring", "add_part",
    })

    def _ensure_identify_layer_current(self) -> None:
        """原生 identify 前置：无活动层时把识别目标置为当前。

        有可见编修层 → 最上层经 set_active_layer 置为活动（即传播
        set_current_layer，Task 8 语义）；零可见编修层 → 最上可见基础
        镜像层经画布 set_current_layer 直设（**不**在 edit_controller
        里伪造活动层——这只是原生 identify 的目标图层）。
        fallback 路径不走这里（activate_tool 内绑定可见层即可，
        不替用户切换活动层）。
        """
        controller = self.edit_controller
        if controller.active_layer_id:
            return
        if not self.uses_native_stack:
            return
        topmost = controller.topmost_visible_layer_id()
        if topmost is not None:
            controller.set_active_layer(topmost)
            # V10 M-G（D2 修复）：identify 自动置位也同步树选中——否则
            # QgsLayerTreeView current ≠ 控制器活动层（三方漂移）。
            try:
                self.layer_manager.select_layer(topmost)
            except Exception:
                pass
            return
        base_target = _pick_base_identify_target_id(self._base_layers)
        if base_target is not None:
            try:
                self.canvas.set_current_layer(base_target)
            except Exception:  # noqa: BLE001, S110 — 识别目标置位失败不拦工具激活
                pass

    def _on_tool_requested(self, tool_id: str) -> None:
        """画布工具激活（checkable QAction 路径）——同样经过 re-gate。

        V8 M6：工具条 checkable 动作此前直连 ``activate_tool``（绕过
        统一门禁）。工具条刷新间隙里的过期可用判断（选择/会话刚变）在
        此用新鲜求值拦截；QAction 的 checked 已被点击翻转，须回同步。
        """
        verdict = self.tool_availability().get(tool_id)
        if verdict is not None and not verdict.enabled:
            self.status_message.emit(f"不可用：{verdict.disabled_reason}")
            self._sync_action_state()
            return
        if tool_id == "identify":
            self._ensure_identify_layer_current()
        self.edit_controller.activate_tool(tool_id)

    def _on_command_requested(self, command_id: str) -> None:
        # V8 M6：execution-time re-gate——shortcut/palette/工具条全部经此
        # 单一入口，禁用动作（含原因）不得被任何表面绕过。求值必须新鲜
        # （选择/会话可能在上次工具条刷新后又变了）。
        verdict = self.tool_availability().get(command_id)
        if verdict is not None and not verdict.enabled:
            self.status_message.emit(
                f"不可用：{verdict.disabled_reason}")
            # 拒绝后回同步：checkable 动作的点击翻转不得残留（R1-P2）。
            self._sync_action_state()
            return
        if command_id in self._CANVAS_TOOL_COMMANDS:
            if command_id == "identify":
                self._ensure_identify_layer_current()
            self.edit_controller.activate_tool(command_id)
            self._sync_action_state()
            return
        if command_id == "full_extent":
            self._zoom_home()
        elif command_id == "previous_extent":
            self.canvas.previous_extent()
        elif command_id == "next_extent":
            self.canvas.next_extent()
        elif command_id == "cancel":
            self.edit_controller.cancel_active_tool()
        elif command_id == "snapping":
            # V8 M6：以控制器权威为基准做「取反」分派——palette 路径不经
            # QAction 翻转，读 isChecked() 会把当前态重设一遍（静默空操作）。
            self.edit_controller.set_snapping(
                not self.edit_controller.snapping.enabled)
            self._sync_status_bar()
        elif command_id == "topology":
            enabling = not self.edit_controller.topology_enabled
            self.edit_controller.set_topology(enabling)
            self.status_message.emit(
                "拓扑编辑已开启：保存编辑将执行拓扑校验" if enabling else "拓扑编辑已关闭"
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
                elif self._apply_crs_entry_guidance(
                        self.edit_controller.active_layer_id):
                    # 引导框被取消/未修复时不进入编辑（门内已发状态消息）。
                    self.edit_controller.start_editing()
        elif command_id == "save_edits":
            self._save_edits_with_feedback()
        elif command_id == "vertex_scope":
            # M2 §4 顶点档位取反（当前层 ⇄ 全部层）。
            enabling = not self.edit_controller.vertex_all_layers
            self.edit_controller.set_vertex_scope(enabling)
            self.status_message.emit(
                "顶点工具：全部层档（跨层共享节点，同 CRS）" if enabling
                else "顶点工具：当前层档")
        elif command_id == "avoid_intersections":
            # M2 §4 避免重叠开关取反（默认开；裁切范围 = 当前编辑层）。
            enabling = not self.edit_controller.avoid_intersections_enabled
            self.edit_controller.set_avoid_intersections(enabling)
            self.status_message.emit(
                "避免重叠已开启" if enabling else "避免重叠已关闭")
            self._sync_status_bar()
        elif command_id == "tracing":
            # M2 §4 追踪开关取反（默认关；随编辑会话持久化）。
            enabling = not self.edit_controller.tracing_enabled
            self.edit_controller.set_tracing(enabling)
            self.status_message.emit(
                "追踪已开启（沿现有边数字化）" if enabling else "追踪已关闭")
        elif command_id == "rollback":
            self.edit_controller.rollback_edits()
        elif command_id in {"undo", "redo", "delete_selected", "duplicate_selected"}:
            self.edit_controller.edit_command(command_id)
        elif command_id in {"split", "merge", "explode_multipart", "collect_multipart"}:
            ok, message = self.edit_controller.geometry_command(command_id)
            if not ok:
                self.status_message.emit(message)
            else:
                self.status_message.emit(message)
        elif command_id == "repair_geometry":
            layer_id = self.edit_controller.active_layer_id
            if layer_id:
                self._repair_layer(str(layer_id))
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

    def _managed_style_db_path(self) -> str:
        """受管样式库路径（工程 .artifacts/styles.db；无工程 → 用户目录）。"""
        import pathlib

        root = getattr(getattr(self._project, "meta", None), "project_root", "")
        if root:
            directory = pathlib.Path(root) / ".artifacts"
        else:
            from PySide6.QtCore import QStandardPaths

            base = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            directory = pathlib.Path(base or ".") / "PaleoWorkbench"
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory / "styles.db")

    def _open_style_manager(self) -> None:
        """QGIS 样式库入口（桥能力门禁；失败与 False 返回均如实反馈）。"""
        try:
            from paleo_workbench.ui.map_symbology_bridge import open_style_manager

            opened = open_style_manager(
                self, style_db_path=self._managed_style_db_path()
            )
            if not opened:
                self.status_message.emit("样式库未打开（对话框被取消或未提交）")
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

    def _on_topology_issue_activated(self) -> None:
        """拓扑问题 chip：显式校验 + 首问题定位反馈（V10 §15 / R4-3）。

        R4-3：chip 计数覆盖全部打开的会话——校验也必须覆盖全部（此前
        只校验活动层：多会话时点击永远报「通过」而计数不清零）。
        """
        issues = self.edit_controller.validate_open_session_topology()
        if not issues:
            self.status_message.emit("拓扑校验通过（问题计数已刷新）")
            self._sync_action_state()
            return
        first = issues[0]
        feature_id = str(first.get("feature_id") or "")
        layer_id = str(first.get("layer_id") or "")
        self.status_message.emit(
            f"拓扑问题 {len(issues)} 处；首处：{first.get('message') or '未知问题'}"
            + (f"（图层 {layer_id} 要素 {feature_id}）" if feature_id else "")
        )
        # 首问题要素选中 + 定位（可定位时）——给「进入验证/定位」一条实体路径。
        if feature_id and self.edit_controller.layer(layer_id) is not None:
            try:
                self.edit_controller.set_active_layer(layer_id)
                self._locate_feature(feature_id, layer_id)
            except Exception:
                logging.getLogger(__name__).exception("拓扑问题定位失败")
        self._sync_action_state()

    # -- 画布右键菜单（V10 M7） -------------------------------------------------

    def _on_canvas_context_menu(self, position) -> None:
        # R4-1：捕获进行中（有 pending 采点）右键是「完成捕获」手势——
        # 工具已消费按键，此处不得再弹菜单（双重动作 = 意外提交 + 焦点
        # 被模态菜单劫走）。无 pending 采点时才提供上下文菜单。
        tool = self.edit_controller.tools.active_tool
        if list(getattr(tool, "points", ()) or ()):
            return
        menu = self._build_canvas_menu()
        menu.exec(self.canvas.mapToGlobal(position))
        menu.deleteLater()  # R4-6：exec 后释放（父挂 canvas，否则逐次累积）

    def _copy_canvas_coordinate(self) -> None:
        """复制最近地图坐标（画布右键；无坐标诚实提示，不复制垃圾）。"""
        from PySide6.QtWidgets import QApplication

        point = getattr(self, "_last_map_point", None)
        if point is None:
            self.status_message.emit("尚无地图坐标（移动鼠标后再复制）")
            return
        QApplication.clipboard().setText(f"{point[0]:.6f}, {point[1]:.6f}")
        self.status_message.emit(f"已复制坐标 {point[0]:.6f}, {point[1]:.6f}")

    def _open_snapping_settings_gated(self) -> None:
        """菜单/状态条入口的捕捉设置：阻塞任务期间拒绝（与其它菜单项
        的 blocking 门禁同语义；R4-7）。"""
        if self.tool_context().blocking_task:
            self.status_message.emit(
                f"后台任务进行中，暂不能打开捕捉设置：{self.tool_context().blocking_task}")
            return
        self._open_snapping_settings()

    def _build_canvas_menu(self):
        """画布上下文菜单：视图 / 工具 / 选择 / 编辑会话 / 捕捉·拓扑 / 图层。

        菜单项直接挂 ``action_controller`` 的 QAction（求值器输出已写入
        enabled/visible/tooltip——与工具条零漂移）；菜单组合按当前上下文
        呈现（选择类仅在有活动矢量层时出现等），**不做业务判断**。
        visible=False 的动作（阶段隐藏组）不出现在菜单。
        """
        from PySide6.QtWidgets import QMenu

        actions = self.action_controller.actions

        def _add(menu, *ids: str) -> None:
            for tool_id in ids:
                action = actions.get(tool_id)
                if action is not None and action.isVisible():
                    menu.addAction(action)

        def _group_visible(*ids: str) -> bool:
            return any(
                actions.get(tool_id) is not None
                and actions.get(tool_id).isVisible()
                for tool_id in ids
            )

        menu = QMenu(self.canvas)
        # R2-1：菜单项 tooltip 必须显式开启（Qt 默认不在菜单里显示——
        # 禁用原因直达菜单是 M5 的核心承诺）。
        menu.setToolTipsVisible(True)
        _add(menu, "pan", "zoom_in", "zoom_out", "full_extent",
             "previous_extent", "next_extent", "refresh")
        # R2-8：复制坐标（QGIS 画布右键惯例；地质师粘贴坐标的高频动作）。
        menu.addAction("复制坐标", self._copy_canvas_coordinate)
        menu.addSeparator()
        _add(menu, "identify", "select", "select_rectangle", "measure_distance")
        # 选择命令组：无活动矢量层时整组不出现（组语义而非逐项隐藏）。
        if _group_visible("select_all", "invert_selection", "clear_selection"):
            menu.addSeparator()
            _add(menu, "select_all", "invert_selection", "clear_selection")
        # 编辑会话组。
        if _group_visible("toggle_editing", "save_edits", "rollback",
                          "undo", "redo", "delete_selected"):
            menu.addSeparator()
            _add(menu, "toggle_editing", "save_edits", "rollback")
            _add(menu, "undo", "redo", "delete_selected")
        # 捕捉·拓扑：开关 + 设置入口（设置对话框是配置面，常驻）。
        if _group_visible("snapping", "topology"):
            menu.addSeparator()
            _add(menu, "snapping", "topology")
            settings = menu.addAction(
                workstation_icon("map/snapping.svg"), "捕捉设置…",
                self._open_snapping_settings_gated)
            settings.setToolTip("打开捕捉设置（容差/模式/参与层）")
        # 图层泛用组。
        if _group_visible("attribute_table", "layer_properties", "layer_zoom"):
            menu.addSeparator()
            _add(menu, "attribute_table", "layer_properties", "layer_zoom")
        return menu

    def _on_tool_operation(self, edits_data: bool = True) -> None:
        """工具操作回执：数据编辑重组快照，纯选择 / 指针反馈只刷状态。"""
        if edits_data:
            self._sync_composition()
        else:
            self.canvas.update()
        self._sync_action_state()

    def _on_map_position(self, point) -> None:
        # V10 R5-1：指针事件以最高频率到达——只更新坐标读数（全量事实
        # 重建在状态同步链上；本方法不再触发 tool_context()）。
        self._last_map_point = tuple(point)
        self.status_bar.update_coordinate(
            tuple(point), self.edit_controller.project_crs or "")

    def _on_measure_updated(self, payload: dict) -> None:
        """V7 原生测距显示：椭球测算（米）或平面测算（地图单位）。

        桥 payload 契约（PwbMeasureTool::payloadJson）：``segments`` 数组 =
        已完成分段 + 末尾 live 预览段（鼠标跟随），故完成段数 = len - 1；
        ``total`` 含 live 段。非法数值（NaN/Inf）显示"测距无效"而非 0/nan。
        """
        import math

        try:
            total = float(payload.get("total") or 0.0)
        except (TypeError, ValueError):
            total = math.nan
        segments = payload.get("segments") or ()
        try:
            segment_count = len(segments)
        except TypeError:
            segment_count = 0
        ellipsoidal = bool(payload.get("ellipsoidal"))
        if not math.isfinite(total):
            self.status_bar.set_measure("测距: 无效")
            return
        if ellipsoidal:
            text = f"{total / 1000.0:.3f} km" if total >= 1000 else f"{total:.1f} m"
            text += "（椭球）"
        else:
            text = f"{total:.4g}"
        action = str(payload.get("action") or "")
        suffix = " 完成" if action == "measure_completed" else ""
        self.status_bar.set_measure(f"测距: {text} · {max(segment_count - 1, 0)} 段{suffix}")

    def _on_capture_progress(self, payload: dict) -> None:
        """V10 捕获过程反馈（PwbDigitizeTool "digitizing" 流）：已采点数/段长/总长。

        平面地图单位（与桥 payload 的 planar:true 一致）；有 snapping 命中时
        附层名提示（数字化过程中即可见吸附目标）。
        """
        try:
            points = payload.get("points") or ()
            count = len(points)
            total = float(payload.get("total") or 0.0)
            segment = float(payload.get("segments") or 0.0)
            text = f"数字化: {count} 点 · 段长 {segment:.4g} · 总长 {total:.4g}"
            snap = payload.get("snap") or {}
            if snap.get("matched") and snap.get("layer_doc_id"):
                text += f" · 吸附 {snap['layer_doc_id']}"
            self.status_bar.set_measure(text)
        except Exception:
            pass

    def _measure_segment_label(self, distance: float) -> str:
        """分段距离的诚实标注（V9 W8）：测地(米) / 平面(地图单位)。

        距离来自活动 MeasureDistanceTool 的 last_distance；测地与否由
        工具的 ``last_geodesic`` 决定（地理 CRS + Geod 可用 → 测地米；
        投影/未知 CRS → 平面地图单位）。工具不可达时按平面标注（保守）。
        """
        import math

        try:
            value = float(distance)
        except (TypeError, ValueError):
            value = math.nan
        if not math.isfinite(value):
            return "测距: 无效"
        tool = self.edit_controller.tools.active_tool
        geodesic = bool(getattr(tool, "last_geodesic", False))
        if geodesic:
            text = f"{value / 1000.0:.3f} km" if value >= 1000 else f"{value:.1f} m"
            return f"测距: {text}（测地）"
        return f"测距: {value:.4g}（平面，地图单位）"

    def _on_measure_segment(self, distance: float) -> None:
        """旧桥视口路由的分段完成（标注测地/平面——V9 W8 后地理 CRS 为测地米）。"""
        self.status_bar.set_measure(self._measure_segment_label(distance))

    def _on_measure_preview(self, distance: float) -> None:
        """旧桥视口路由的实时预览（review-2 P2-4：预览经工具同一测距）。

        路由侧给的是平面 mupp 距离；活动工具持有起/终点与同一 Geod——
        有两点时用工具的 ``_measure`` 重算（与完成段同语义），否则退回
        平面值并按平面标注。"""
        tool = self.edit_controller.tools.active_tool
        points = list(getattr(tool, "points", ()) or ())
        if len(points) == 2 and hasattr(tool, "_measure"):
            try:
                distance = float(tool._measure(points[0], points[1]))
            except Exception:
                pass
        label = self._measure_segment_label(distance)
        if "无效" not in label:
            self.status_bar.set_measure(f"{label}…")

    def _show_identify_popup(self, results) -> None:
        """识别结果 → 点击处 QToolTip 悬浮（有结果才弹）。

        调用点恒在点击处理中（fallback 鼠标路径同步调用 / 原生信号直达
        GUI 线程），光标位置即点击处；无结果时只收旧提示，不弹空框。
        """
        text = _identify_popup_text(results)
        if text:
            QToolTip.showText(QCursor.pos(), text, self)
        else:
            QToolTip.hideText()

    def _on_native_identified(self, payload: dict) -> None:
        """原生 identify 结果 → Python 数据权威组装 → Identify Results 面板。

        原生 QgsMapToolIdentifyFeature 只回 (doc_id, feature_id)；面板条目
        从 CompositeEditController 的图层记录（权威）重建，不建第二数据源。
        基础镜像层不在编辑控制器里——此时从工区快照（``_base_layers``）按
        文档记录 id 反查重建（与 identify_all 基础分支同形），同样复用悬浮框。
        多图层命中列举仍由 fallback 路径的 identify_all 提供（点选语义差异
        记录在 03-decisions.md）。
        """
        layer_id = str(payload.get("layer_doc_id") or "")
        feature_id = str(payload.get("feature_id") or "")
        controller = self.edit_controller
        layer = controller.layer(layer_id)
        if layer is None:
            entry = _base_identify_entry(self._base_layers, layer_id, feature_id)
            if entry is not None:
                self.identify_results.set_results([entry])
                self._show_identify_popup([entry])
                return
        # UX-3：未命中（无图层/无要素）时清空面板并提示——不得残留上次结果
        # 误导用户（fallback identify_all 至少会刷新为空）。
        if layer is None or not feature_id:
            self.identify_results.set_results([])
            self._show_identify_popup(())
            return
        session = layer.edit_session
        source = session.features() if session is not None else layer.features()
        feature = next((f for f in source if f.feature_id == feature_id), None)
        if feature is None:
            self.identify_results.set_results([])
            self._show_identify_popup(())
            self.status_message.emit("识别未命中：要素不存在或已被删除")
            return
        results = [
            {
                "layer_id": layer.id,
                "layer_name": layer.name,
                "feature_id": feature.feature_id,
                "geometry_type": str(feature.geometry.get("type") or ""),
                "attributes": dict(feature.attributes),
                "source": "composite",
                "template": controller.layer_template(layer.id),
                "editable": True,
                "record": feature.as_record(),
            }
        ]
        self.identify_results.set_results(results)
        self._show_identify_popup(results)

    def _build_tool_context(self) -> ToolContext:
        """V7 kernel 集成入口（V8 起与 :meth:`tool_context` 同一实现）。"""
        return self.tool_context()

    def _on_native_tool_activation_failed(self, tool_id: str, reason: str) -> None:
        """原生工具激活失败：回退 pan，让 checked 与画布实际工具一致。

        evaluator 的 capability 门禁挡住的是「已知不支持」；这里是运行期
        失败（桥异常等）——按钮亮着但画布没换工具是不允许的。pan 的失败
        不再递归回退。
        """
        if tool_id and tool_id != "pan":
            self.edit_controller.activate_tool("pan")
        self._sync_action_state()
        if tool_id == "pan":
            self.status_message.emit(f"原生平移工具激活失败：{reason}")
        else:
            self.status_message.emit(f"原生工具「{tool_id}」激活失败，已回退平移：{reason}")

    def _sync_action_state(self) -> None:
        self._update_empty_hint()
        controller = self.edit_controller
        self.layer_manager.set_editing_layer(
            controller.active_layer_id if controller.editing else None
        )
        # 工具按钮勾选态由 apply_availability 统一写入（evaluator 的
        # checked ← current_tool，单一写者；review R2-P2：此处此前存在
        # 第二写者且原生探针优先级逻辑会被随后 apply 覆盖——已删）。
        # 原生实际工具的回读（canvas.active_map_tool_id）保留为 QA/检测
        # API，激活失败路径经 _on_native_tool_activation_failed 收敛。
        # 捕捉 / 拓扑的勾选态以控制器为权威（捕捉设置对话框等旁路入口
        # 不得让工具条按钮失步，review #11）。
        actions = self.action_controller.actions
        for action_id, checked in (
            ("toggle_editing", controller.editing),
            ("snapping", controller.snapping.enabled),
            ("topology", controller.topology_enabled),
        ):
            action = actions.get(action_id)
            if action is not None:
                action.blockSignals(True)
                action.setChecked(bool(checked))
                action.blockSignals(False)
        # V7：使能/可见/禁用原因统一由 tool_surface 求值
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
            QTimer.singleShot(0, self, self._sync_hint_geometry)

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

    def _effective_snapping_tolerance(self) -> float:
        """活动图层的有效捕捉容差（per-layer 覆盖优先，R2-5）。"""
        snapping = self.edit_controller.snapping
        active_id = str(self.edit_controller.active_layer_id or "")
        if active_id and active_id in getattr(snapping, "layer_tolerance", {}):
            return float(snapping.layer_tolerance[active_id] or 0.0)
        return float(snapping.pixel_tolerance or 0.0)

    def _sync_status_bar(self, *, point=None) -> None:
        """状态条刷新：全部读数经 canonical ToolContext 投影（V10 §14–§17）。

        坐标指针事件以 ``point`` 增量进入（高频路径不重算上下文）；其余
        事实从一次 ``tool_context()`` 求值派生——状态条与工具条/palette
        消费同一份事实，无第二状态源。
        """
        controller = self.edit_controller
        layer = controller.active_layer
        ctx = self.tool_context()
        self.status_bar.apply_context({
            "point": tuple(point) if point is not None else None,
            # V9 W3：状态条 CRS 呈现经契约——未声明显示「未声明」，
            # 不伪造 4326（review-1 P1-1 存量清理）。
            "crs": controller.project_crs or "未声明",
            "renderer": self.canvas.backend_status,
            "scale_denominator": ctx.scale_denominator,
            "selection_count": len(layer.selection) if layer is not None else 0,
            "snapping_enabled": controller.snapping.enabled,
            "snapping_available": ctx.snapping_available,
            "snapping_tolerance_px": ctx.snapping_tolerance_px,
            "snapping_modes": ctx.snapping_modes,
            "snapping_reference_count": ctx.snapping_reference_count,
            "snapping_role_recommended": ctx.snapping_role_recommended,
            "topology_enabled": controller.topology_enabled,
            "topology_error_count": ctx.topology_error_count,
            "crs_mismatch": ctx.crs_mismatch,
            "layer_crs": ctx.layer_crs,
            "editing": controller.editing,
            "dirty": ctx.dirty,
            "layer_name": layer.name if layer is not None else "",
            "raw_locked": ctx.raw_locked,
            "layer_frozen": ctx.layer_frozen,
            "edit_gate_open": ctx.edit_gate_open,
            # R1-1：gate 关闭的原因直达 chip tooltip（判词来自宿主门禁，
            # 不在此改写）；R2-5：捕捉容差按活动图层有效值（覆盖优先）。
            "edit_gate_reason": ctx.edit_gate_reason,
            "save_blocked": bool(
                controller.editing and ctx.dirty and ctx.topology_error_count > 0),
            "snapping_tolerance_px": self._effective_snapping_tolerance(),
        })

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
        # R1-6：结构性动作（内存副本，不写源数据）不进 evaluator 矩阵，
        # 但保留工程级守卫（无工程无复制）。
        if self._project is None:
            self.status_message.emit("未打开工程")
            return
        copy = self.edit_controller.duplicate_layer(layer_id)
        if copy is None:
            return
        # R2-2：RAW 源的副本 = DERIVED 草稿（本工作流的语义承诺）——登记
        # 阶段成员资格为草稿角色，并覆写控制器角色登记。否则副本落在
        # 角色体系之外：抢主位防护失效、快照仍按 RAW 角色 badge。
        from paleo_workbench.mapping_workspace.layer_roles import LayerRole
        from paleo_workbench.mapping_workspace.stage_state import (
            LayerMembershipRecord,
        )

        source_role = self.stage_controller.state.role_of(str(layer_id))
        if source_role.is_raw_protected:
            draft_role = (
                LayerRole.INITIAL_FACIES_DRAFT
                if source_role == LayerRole.INITIAL_FACIES_SOURCE
                else LayerRole.USER_GENERAL
            )
            self.stage_controller.state.set_membership(
                LayerMembershipRecord(layer_id=str(copy.id), role=draft_role))
            self.edit_controller.set_layer_role(str(copy.id), draft_role.value)
            self.status_message.emit(
                f"已复制为可编辑草稿「{copy.name}」（RAW 源保持不变）")
        else:
            self.status_message.emit(f"已复制图层为「{copy.name}」")

    def stage_action(self, stage_value: str, action_id: str) -> None:
        """阶段面板上下文动作入口（宿主壳经 _dispatch_stage_action 调用）。

        V8 M6：有工具面映射的阶段动作（因子/QA/成果组装）在执行前经
        canonical evaluator re-gate——阶段面板按钮与工具条/palette 同一
        门禁（review R2-P1：此前面板直连 dispatch，blocking/project 门
        禁可被绕过）。
        """
        from paleo_workbench.ui.workstation.stage_actions import STAGE_ACTION_TOOLS

        tool_id = STAGE_ACTION_TOOLS.get(str(action_id))
        if tool_id:
            verdict = self.tool_availability().get(tool_id)
            if verdict is not None and not verdict.enabled:
                self.status_message.emit(f"不可用：{verdict.disabled_reason}")
                return
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

    def _on_user_active_layer_changed(self, layer_id) -> None:
        """树选择：用户切层必须先提交/回滚其他打开会话（#1268）。

        ``bind``/``_publish`` 仍直调 ``set_active_layer``，不受本路径影响。
        """
        target = str(layer_id or "")
        current = str(self.edit_controller.active_layer_id or "")
        if target == current:
            return
        self._commit_other_open_sessions(target)
        self.edit_controller.set_active_layer(target or None)

    def _apply_active_target(self, layer_id) -> None:
        """阶段编辑目标应用（active_target_changed → 编辑权威 + 树选中）。

        None（阶段无编辑目标）也必须生效：清空活动图层，编辑动作落到
        门禁拒绝（P1 修复：绝不让上一阶段目标悄悄存活）。
        """
        if not layer_id:
            if self.edit_controller.active_layer_id is not None:
                self._commit_other_open_sessions("")
                self.edit_controller.set_active_layer(None)
            return
        if self.edit_controller.layer(str(layer_id)) is not None:
            self._on_user_active_layer_changed(str(layer_id))
            self.layer_manager.select_layer(str(layer_id))

    def layer_domain_status(self, layer_id: str) -> dict[str, str]:
        """图层级域状态行（V6 §6：inspector 上下文 seam 数据源）。

        角色/成熟度/可编辑/新鲜度四行，值经 state_language 词汇渲染
        （glyph+文字）；未知项诚实「未知」，不编造。
        V10 M11（§19）：补齐专业 GIS 上下文行——几何类型/CRS/编辑会话/
        选择/推荐动作（推荐动作 = canonical evaluator 的 preferred 捕获
        工具或 toggle_editing 结论，禁用带原因——V8 08 #9 的 Inspector
        action-hint 闭环）。
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
        rows = {
            "角色": f"{role.label}",
            "成熟度": f"{maturity.glyph} {maturity.label}",
            "可编辑": f"{editability.glyph} {editability.label}" + (
                f"（{reason}）" if not allowed and reason else ""),
            "新鲜度": f"{freshness.glyph} {freshness.label}",
        }
        # V10 M11：几何/CRS/会话/选择（图层级事实，O(1)）。
        layer = self.edit_controller.layer(layer_id)
        if layer is not None:
            from paleo_workbench.mapping.tool_availability import LAYER_CAPTION

            rows["几何"] = LAYER_CAPTION(self.edit_controller.kind_of(layer_id))
            rows["CRS"] = str(getattr(layer, "crs", "") or "") or "未声明"
            session = getattr(layer, "edit_session", None)
            if session is not None:
                rows["编辑"] = (
                    "编辑中 · 未保存" if getattr(session, "is_dirty", False)
                    else "编辑中")
            selection = getattr(layer, "selection", None) or ()
            if selection:
                rows["已选"] = f"{len(selection)} 个要素"
        # 推荐动作：活动图层 = preferred 捕获工具；否则 toggle_editing 结论。
        if layer_id == str(self.edit_controller.active_layer_id or ""):
            rows["推荐动作"] = self._recommended_action_text(layer_id)
        return rows

    def _recommended_action_text(self, layer_id: str) -> str:
        """推荐动作行（V10 M11）：preferred 捕获工具 / toggle_editing 结论。

        结论与禁用原因全部来自 canonical evaluator（explain 同源）；本
        方法只拼呈现文本，不改写判词。
        """
        from paleo_workbench.mapping.tool_help import TOOL_LABELS

        verdict = self._layer_tool_availability(layer_id, "toggle_editing")
        if verdict.enabled and not self.edit_controller.editing:
            return "开始编辑（工具条/右键/命令面板同入口）"
        for tool_id in ("add_point", "add_line", "add_polygon"):
            capture = self._layer_tool_availability(layer_id, tool_id)
            if capture.enabled and capture.preferred:
                return f"{TOOL_LABELS.get(tool_id, tool_id)}（推荐捕获工具）"
        if not verdict.enabled:
            return f"开始编辑（不可用：{verdict.disabled_reason}）"
        # 会话已开启但无 preferred 捕获（未知 kind 等）——诚实说明。
        return "编辑会话进行中" if self.edit_controller.editing else "开始编辑"

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

    def _layer_role_value(self, layer_id) -> str:
        """图层角色值（stage membership 单权威；无 = ""）。

        V9 W6/W9 注入给编辑控制器的角色查询——快照 metadata.role 与
        捕获 spec 都从这里派生，控制器不自持角色表。
        """
        role = self.stage_controller.state.role_of(str(layer_id or ""))
        return str(getattr(role, "value", "") or "")

    def _role_allows_editing(self, layer_id) -> tuple[bool, str]:
        """编辑门禁（单点）：RAW 不可变保护（V5 §14）+ 成熟度冻结 + 阶段证据组锁（§41）。

        所有开启编辑会话的路径（树面板/主工具栏命令/修复几何/保存提交）
        都必须经过本检查——「画物源线写进相带边界」与「改写原始相图」
        都是 P0 级业务风险。
        """
        if not layer_id:
            return False, "当前没有活动编辑目标（本阶段的默认编辑对象尚未创建）"
        gate = getattr(self.edit_controller, "_edit_gate", None)
        if gate is not None and gate != self._role_allows_editing:
            allowed, reason = gate(layer_id)
            if not allowed:
                return False, reason
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

    # -- 编辑进前段 CRS 门（拓扑编辑迁移 M0 §6，决议 #1285）---------------------

    def _layer_crs_facts(self):
        """编辑控制器全部层的 CRS 事实（声明 CRS + 数据实际坐标范围）。"""
        from paleo_workbench.mapping.crs_chain import LayerCrsFacts
        from paleo_workbench.mapping.geometry_planar import extent_of_geometries

        facts = []
        for layer_id in self.edit_controller.layer_ids():
            layer = self.edit_controller.layer(str(layer_id))
            if layer is None:
                continue
            try:
                extent = extent_of_geometries(
                    [feature.geometry for feature in layer.features()])
            except ValueError:
                extent = None  # 空层：无数据范围可校验
            facts.append(LayerCrsFacts(
                layer_id=str(layer_id), crs=str(layer.crs or ""),
                extent=extent))
        return facts

    def _crs_entry_gate(self, layer_id) -> tuple[object, list]:
        """进前段 CRS 门：返回 (verdict, 受影响 (layer_id, 显示名) 序列)。

        会话集合候选 = {活动层}（§3 进入编辑 = {活动层}）；域失配的
        「受影响层」全景取工程全部层（引导对话框数据源）。
        """
        from paleo_workbench.mapping import crs_chain

        facts = self._layer_crs_facts()
        candidate = [fact for fact in facts if fact.layer_id == str(layer_id or "")]
        canvas = self.canvas
        destination_crs = getattr(canvas, "destination_crs", None)
        canvas_crs = ""
        if callable(destination_crs):
            try:
                canvas_crs = str(destination_crs() or "")
            except Exception:
                canvas_crs = ""
        project_crs = str(getattr(self.edit_controller, "project_crs", "") or "")
        if not project_crs and self._project is not None:
            project_crs = str(
                getattr(self._project.coordinate, "project_crs", "") or "")
        verdict = crs_chain.evaluate_edit_entry(
            candidate,
            canvas_crs=canvas_crs,
            project_crs=project_crs,
            all_layers=facts,
            runtime_crs_capable=crs_chain.runtime_crs_capable(),
        )
        affected = []
        if verdict.mismatches:
            from paleo_workbench.mapping.crs_contract import (
                coordinate_domain_mismatch,
            )
            for fact in facts:
                effective = fact.effective_crs(verdict.declared_crs)
                if coordinate_domain_mismatch(effective, fact.extent) is not None:
                    layer = self.edit_controller.layer(fact.layer_id)
                    affected.append((
                        fact.layer_id,
                        str(layer.name) if layer is not None else fact.layer_id))
        return verdict, affected

    def _apply_crs_entry_guidance(self, layer_id) -> bool:
        """进前 CRS 门被拒时的一次性引导（§6）。

        一键修复（清除声明 → 画布切本地坐标 → 重试进入编辑）返回
        True；用户取消返回 False。
        """
        verdict, affected = self._crs_entry_gate(layer_id)
        if verdict.allowed:
            return True  # 通过（或无事实可比对）：交回常规进入路径
        from paleo_workbench.ui.crs_guidance import CrsGuidanceDialog

        dialog = CrsGuidanceDialog(verdict, affected_layers=affected, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.cleared:
            self.status_message.emit(f"未进入编辑：{verdict.reason}")
            return False
        self._clear_crs_declaration()
        # 修复即入编辑（§6）：清除声明后画布以本地坐标渲染，重查通过。
        verdict, affected = self._crs_entry_gate(layer_id)
        if not verdict.allowed:
            self.status_message.emit(f"仍无法进入编辑：{verdict.reason}")
            return False
        return True

    def _clear_crs_declaration(self) -> None:
        """一键修复：工程 CRS 声明改为本地（清除）并重推画布。

        层自身声明了**可证明与数据失配** CRS 的一并清除（新建层会把
        工程声明烙进 layer.crs——只清工程声明会让这些层继续拦在门上）；
        声明可验证无误的层不动。
        """
        from paleo_workbench.mapping.crs_contract import (
            coordinate_domain_mismatch,
        )
        from paleo_workbench.mapping.geometry_planar import extent_of_geometries

        for layer_id in self.edit_controller.layer_ids():
            layer = self.edit_controller.layer(str(layer_id))
            if layer is None or not str(layer.crs or ""):
                continue
            try:
                extent = extent_of_geometries(
                    [feature.geometry for feature in layer.features()])
            except ValueError:
                continue
            if coordinate_domain_mismatch(layer.crs, extent) is not None:
                layer.crs = ""
        if self._project is not None:
            from paleo_workbench.project.domain import sync_workarea_with_coordinate

            self._project.coordinate.project_crs = ""
            sync_workarea_with_coordinate(self._project)
        self.edit_controller.project_crs = ""
        self._sync_composition_now()
        self.status_message.emit("工程 CRS 声明已清除——画布按本地坐标渲染")

    def _layer_lock_classes(self, layer_id: str) -> tuple[bool, bool]:
        """(raw_locked, stage_locked) 分类（review-3 UX-5）。

        只在真正的 RAW 保护 / 组证据锁分支置 true；门禁的其他拒绝原因
        （无活动目标等瞬态原因）保持两者皆 false，具体判词走
        ``edit_gate_reason``（evaluator 的 _role_gate 优先用判词）。
        """
        if not layer_id:
            return False, False
        role = self.stage_controller.state.role_of(str(layer_id))
        if bool(getattr(role, "is_raw_protected", False)):
            return True, False
        from paleo_workbench.mapping_workspace.layer_groups import (
            system_group_template,
        )

        group_id = self.stage_controller.group_controller.placement_of(layer_id)
        template = system_group_template(group_id) if group_id else None
        stage = self.stage_controller.current_stage
        try:
            view_state = self.stage_controller.state.view_state(stage)
            locked_override = view_state.group_locked.get(group_id)
            locked = locked_override if locked_override is not None else bool(
                template and template.stage_locked(stage))
        except Exception:
            locked = False
        return False, bool(locked)

    def _toggle_layer_editing(self, layer_id: str) -> None:
        # V10 M6：树面板编辑入口的 execution re-gate 升级为完整 evaluator
        # （此前只复查角色门禁——blocking task 等全局阻断可从树菜单绕过）。
        verdict = self._layer_tool_availability(str(layer_id), "toggle_editing")
        if not verdict.enabled:
            self.status_message.emit(f"不可用：{verdict.disabled_reason}")
            return
        # R4-2：另一图层尚有打开的编辑会话时，先提交它（QGIS 切层即询问
        # 保存的语义）——否则半途会话被静默遗弃，后续 flush 会把没看过
        # 的修改一并落盘。
        self._commit_other_open_sessions(str(layer_id))
        self.edit_controller.set_active_layer(layer_id)
        if self.edit_controller.editing:
            self._save_edits_with_feedback()
        else:
            # M0 §6：树面板入口同样过进前段 CRS 门（一次性引导修复）。
            if not self._apply_crs_entry_guidance(str(layer_id)):
                self._sync_action_state()
                return
            self.edit_controller.start_editing()
        self._sync_action_state()

    def _commit_other_open_sessions(self, exclude_layer_id: str) -> None:
        """提交除目标图层外所有打开的编辑会话（切层保护，R4-2）。

        会话被拒提交（RAW 纵深防御等）时回滚——绝不带着未知状态的会话
        切换编辑目标。
        """
        controller = self.edit_controller
        for other_id in list(controller.layer_ids()):
            if other_id == exclude_layer_id:
                continue
            layer = controller.layer(str(other_id))
            session = getattr(layer, "edit_session", None) if layer else None
            if session is None:
                continue
            original_active = controller.active_layer_id
            controller.set_active_layer(str(other_id))
            allowed, _reason = self._role_allows_editing(str(other_id))
            if allowed:
                error = controller.save_edits()
                if error:
                    self.status_message.emit(f"图层 {layer.name} 会话未提交：{error}")
                    controller.rollback_edits()
            else:
                controller.rollback_edits()
                self.status_message.emit(
                    f"图层 {layer.name} 的会话已回滚（门禁拒绝提交）")
            controller.set_active_layer(
                str(original_active) if original_active else None)

    def _layer_tool_availability(
        self, layer_id: str, tool_id: str, *, base=None,
    ):
        """图层级工具可用性（canonical evaluator，供树面板探针/re-gate）。

        把目标图层的事实投影进 ToolContext 再求值——右键菜单、工具条、
        palette、执行 re-gate 消费同一规则（kind/门禁/阻塞），无第二套
        判断。投影语义与 ``_layer_repair_availability``（V8 M2）一致，
        本方法是它的泛化。``base`` 可传入共享上下文（一次构建多次投影，
        R5-6——菜单探针每开一次菜单省两次全量采集）。
        """
        from dataclasses import replace as _replace

        from paleo_workbench.mapping.tool_availability import evaluate_tool

        layer = self._layer_capability(str(layer_id))
        base = base if base is not None else self.tool_context()
        raw_locked, stage_locked = self._layer_lock_classes(str(layer_id))
        ctx = _replace(
            base,
            active_layer_id=str(layer_id),
            active_layer_kind=layer.kind or "",
            layer_role=layer.role or "",
            layer_role_label=layer.role_label or "",
            edit_gate_open=layer.editable,
            edit_gate_reason=layer.block_reason or "",
            layer_frozen=layer.frozen,
            layer_missing=layer.missing,
            layer_degraded=layer.degraded,
            raw_locked=raw_locked,
            stage_locked=stage_locked,
            vector_writable=self.edit_controller.layer(str(layer_id)) is not None,
        )
        return evaluate_tool(tool_id, ctx)

    def _layer_repair_availability(self, layer_id: str):
        """图层级「修复几何」可用性（V8 M2 契约面；= 通用探针的特化）。"""
        return self._layer_tool_availability(str(layer_id), "repair_geometry")

    def layer_menu_facts(self, layer_id: str):
        """树右键菜单事实（V10 M5）：evaluator 结论 + RAW 编排事实。

        面板据此呈现菜单（禁用+原因、复制为草稿入口），不做业务判断。
        """
        from paleo_workbench.ui.workstation.tool_surface import LayerMenuFacts

        layer_id = str(layer_id or "")
        role = self.stage_controller.state.role_of(layer_id)
        base = self.tool_context()  # R5-6：一次采集，两次投影共用
        return LayerMenuFacts(
            toggle_editing=self._layer_tool_availability(
                layer_id, "toggle_editing", base=base),
            repair_geometry=self._layer_tool_availability(
                layer_id, "repair_geometry", base=base),
            raw_protected=bool(getattr(role, "is_raw_protected", False)),
        )

    def _repair_layer(self, layer_id: str) -> None:
        # V10 M6：修复几何的 execution re-gate 升级为完整 evaluator（此前
        # 只复查角色门禁——kind 门禁（面图层）在原生面板信号路径上缺席）。
        verdict = self._layer_tool_availability(str(layer_id), "repair_geometry")
        if not verdict.enabled:
            self.status_message.emit(f"无法修复：{verdict.disabled_reason}")
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
            snapshot = self.layer_manager.layer_by_id(str(layer_id))
            if snapshot is None:
                return
            self._open_snapshot_properties_dialog(str(layer_id), snapshot, focus=focus)
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

    def _open_snapshot_properties_dialog(
        self, layer_id: str, snapshot, *, focus: str = ""
    ) -> None:
        """回退画布：为基础工区 / 引用快照层打开同一套属性对话框。"""
        features = tuple(
            dict(record)
            for record in (snapshot.features or ())
            if isinstance(record, dict)
        )
        fields: list[str] = []
        for record in features:
            properties = record.get("properties") or {}
            for key in sorted(properties):
                if key not in fields:
                    fields.append(str(key))
        adapter = _LayerPropertiesAdapter(
            snapshot,
            opacity=float(getattr(snapshot, "opacity", 1.0) or 1.0),
            metadata=dict(getattr(snapshot, "metadata", {}) or {}),
        )
        dialog = MapLayerPropertiesDialog(
            adapter,
            style=dict(snapshot.style or {}),
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
            lambda _id, payload: self._apply_native_snapshot_layer_properties(
                layer_id, payload
            )
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
        new_style = dict(snapshot.style or {})
        if isinstance(result.get("style"), dict):
            new_style.update(dict(result["style"]))
        if isinstance(result.get("qgis_style"), dict):
            new_style["qgis_style"] = dict(result["qgis_style"])
        if isinstance(result.get("labels"), dict):
            new_style["labels"] = dict(result["labels"])
        new_crs = str(result.get("crs") or "").strip() or snapshot.crs
        style_changed = new_style != dict(snapshot.style or {})
        # 快照是 frozen dataclass：以 replace 重建后换回面板列表。
        new_snapshot = replace(
            snapshot,
            name=(name or snapshot.name),
            crs=new_crs,
            opacity=(
                min(1.0, max(0.05, float(opacity))) if has_opacity else snapshot.opacity
            ),
            style=new_style,
            style_revision=snapshot.style_revision + (1 if style_changed else 0),
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
                self._base_layers[index] = replace(
                    base,
                    name=(name or base.name),
                    crs=new_crs,
                    opacity=(
                        min(1.0, max(0.05, float(opacity)))
                        if has_opacity
                        else base.opacity
                    ),
                    style=new_style,
                    style_revision=new_snapshot.style_revision,
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
            # V9 W3：CRS 经契约解析——未声明时拒绝导入并说明，不静默按 4326 转换。
            from paleo_workbench.mapping.crs_contract import resolve_crs

            resolution = resolve_crs(
                self.edit_controller.project_crs, purpose="参考图层导入")
            if not resolution.declared:
                self.status_message.emit(
                    resolution.degraded_reason + "——请先在工程设置中声明坐标系")
                continue
            try:
                layer = self._reference_service.import_layer(path, resolution.crs)
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
        """多图层识别：全部可见可查询图层 → Identify Results 面板 + 点击悬浮。"""
        controller = self.edit_controller
        results = controller.identify_all(point, base_layers=self._base_layers)
        self.identify_results.set_results(results)
        self._show_identify_popup(results)
        active_id = controller.active_layer_id
        for result in results:
            if result.get("editable") and result.get("layer_id") == active_id:
                return result.get("feature_id")
        return None

    def _locate_identify_result(self, result) -> None:
        # V7 §8：识别结果同步进入 Inspector（feature 分节；双击仍定位）。
        try:
            self.object_selected.emit({
                "kind": "feature",
                "object": dict(result or {}),
                "layer_id": (result or {}).get("layer_id"),
            })
        except RuntimeError:
            pass
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
            # V11（D2-ws）：factor 组标题随组成同步（此前
            # sync_factor_titles 无生产调用方，factor 组显示裸任务 id）。
            factor_tasks = getattr(self._project, "factor_map_tasks", None) or []
            self.stage_controller.group_controller.sync_factor_titles({
                str(task.id): str(task.name) for task in factor_tasks})
            self.stage_controller.sync_composition()
            expand = getattr(self.layer_manager, "expand_layer_groups", None)
            if callable(expand):
                expand()
        except Exception:
            logging.getLogger(__name__).exception("stage workspace reconcile failed")

    # -- 工程绑定 -------------------------------------------------------------

    def set_project(self, project) -> None:
        self._project = project
        snapshot = build_workarea_map_snapshot(project)
        self._base_layers = list(snapshot.layers)
        self.edit_controller.project_crs = snapshot.project_crs
        # V9 W8（review-2 P2-4）：测距工具不在 rebind 集合（非会话/图层/
        # 几何绑定），CRS 变更后其 Geod 过期——显式重建保持测地语义。
        if getattr(self.edit_controller, "_active_tool_action", "pan") == "measure_distance":
            self.edit_controller.activate_tool("measure_distance")
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
            if self.edit_controller.load_from_project(project) is False:
                # 被阻断的会话保持打开（可回滚/可修复）：拒绝带病切换，
                # 如实告知用户哪些图层未提交，而不是静默 rollback 丢数据。
                self.status_message.emit(
                    "工程切换已取消：有未保存且无法提交的编辑（见状态栏），"
                    "请先回滚或修复后再切换"
                )
                return
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
            if self._home_extent is not None:
                self.canvas.set_extent(self._home_extent)
        finally:
            self._loading = False
        if project is not None:
            self._write_map_project_xml()
            # 工程装载完成后恢复阶段上下文（组显隐 + 编辑目标 + 就绪度评估）。
            self.stage_controller.restore_stage_view()
            expand = getattr(self.layer_manager, "expand_layer_groups", None)
            if callable(expand):
                expand()
        self.input_tree.refresh(project)

    def _write_map_project_xml(self) -> None:
        """把当前 QgsProject 呈现态写入工程信封。loading 期间不调用。"""
        if self._project is None:
            return
        write = getattr(getattr(self.canvas, "stack", None), "write_project_xml", None)
        if not callable(write):
            return
        self._project.map_qgis_project_xml = write()

    # -- 宿主行工具条（画布无悬浮条；定位由 QMainWindow 工具栏区负责） ----------

    def _reposition_toolbar(self) -> None:
        """No-op 兼容垫片（悬浮条已拆除，工具条由宿主 QMainWindow 托管布局）。

        保留方法名：外部调用方（旧测试/脚本）直接调用仍安全。
        """
        return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 画布随窗口/布局变化后，空态提示必须盖满当前画布矩形（否则残留
        # 布局前的小矩形，文字被截断或不可见）。
        self._sync_hint_geometry()

    def showEvent(self, event) -> None:
        super().showEvent(event)

    # -- 生命周期 --------------------------------------------------------------

    def shutdown(self) -> None:
        """释放渲染后端（工程切换 / 退出时由 WorkstationFrame 调用）。"""
        self._composition_timer.stop()
        self._sync_workspace_state_to_project()
        self.canvas.shutdown()
