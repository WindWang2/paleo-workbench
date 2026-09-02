"""PROTOTYPE — 综合编修环境布局原型（throwaway，勿并入生产代码）。

问题：综合编修环境（右侧图层管理、中央图件为主体）放进现有工作站后应该长什么样？

子形状 A（嵌入宿主）：三个布局变体挂进 WorkstationFrame 的一个「综合编修·原型」
文档 tab——App bar / 资源管理器 / 检查器 / Process Hub / 状态栏全部保留，变体只
替换文档区。`←`/`→` 或底部浮动切换条循环切换：

- A「右置图层管理」：工具条 + 地图（主体）+ 右侧图层管理 dock。
- B「双栏工作台」：左输入与结果树 + 地图 + 右侧图层管理/检查器堆叠。
- C「全幅浮动停靠」：地图全幅，图层管理为可折叠浮动面板，工具条悬浮。

真实组件：UnifiedMapCanvas + build_workarea_map_snapshot(当前工程)；图层可见性/
不透明度/顺序的变更直接写回渲染快照。面板 mock 仅用于占位判断布局。

门控：仅当 PALEO_PROTOTYPE_COMPOSITE=1 时由 WorkstationFrame 安装本原型 tab。
"""
from __future__ import annotations

import json
import math
import sys
import types
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(__file__).resolve().parents[5]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO))

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSlider,
    QSplitter,
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
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.ui.workstation.common import workstation_icon

PROJECT_JSON = DATA_ROOT / "data" / "project_area" / "project_area.paleo.json"

VARIANTS = (
    ("A", "右置图层管理"),
    ("B", "双栏工作台"),
    ("C", "全幅浮动停靠"),
)

_ENABLED_VALUES = {"1", "true", "yes", "on"}


def prototype_requested() -> bool:
    """门控：仅显式设置 PALEO_PROTOTYPE_COMPOSITE=1 时启用原型 tab。"""
    import os

    return os.environ.get("PALEO_PROTOTYPE_COMPOSITE", "").strip().lower() in _ENABLED_VALUES


# ── mock 面板 ─────────────────────────────────────────────────────────────


class _MockCurves(QWidget):
    """测井轨道 mock：两条曲线 + 深度尺。"""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        w, h = self.width(), self.height()
        painter.setPen(QPen(QColor(tokens.BORDER), 1))
        for i in range(1, 4):
            painter.drawLine(int(w * i / 4), 0, int(w * i / 4), h)
        rng = range(2480, 2540)
        for idx, color in enumerate((QColor("#2f8f4e"), QColor("#c23a3a"))):
            pts = QPolygonF()
            for row, d in enumerate(rng):
                x = int(w * (idx + 1) / 4) + int(
                    30 * math.sin(d / 6.0 + idx * 2) + 18 * math.sin(d / 1.7)
                )
                pts.append(QPointF(x, row * h / max(1, len(rng) - 1)))
            painter.setPen(QPen(color, 1.4))
            painter.drawPolyline(pts)
        painter.setPen(QPen(QColor(tokens.TEXT_SECONDARY), 1))
        font = painter.font()
        font.setPixelSize(9)
        painter.setFont(font)
        for row, d in enumerate(rng):
            if d % 10 == 0:
                painter.drawText(4, int(row * h / (len(rng) - 1)) + 4, str(d))
        painter.end()


def _input_tree(project: ProjectDocument) -> QTreeWidget:
    """左侧「输入与结果」树 mock（B 变体）：真实井名 + 结果分组。"""
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    wells = [str(getattr(w, "name", "")) for w in getattr(project, "wells", None) or []]

    def group(title: str, children: list[str]) -> QTreeWidgetItem:
        node = QTreeWidgetItem([title])
        node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        node.setCheckState(0, Qt.CheckState.Checked)
        for child in children:
            leaf = QTreeWidgetItem([child])
            leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            leaf.setCheckState(0, Qt.CheckState.Checked)
            node.addChild(leaf)
        return node

    tree.addTopLevelItem(
        group(f"井数据 ({len(wells)})", wells[:8] + (["…"] if len(wells) > 8 else []))
    )
    tree.addTopLevelItem(group("地震数据", ["200P_seismic", "振幅属性", "频率属性"]))
    tree.addTopLevelItem(group("结果", ["工区边界", "测线标注", "不确定图"]))
    return tree


def _map_toolbar() -> QFrame:
    bar = QFrame()
    bar.setObjectName("WorkstationContextBar")
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(6, 3, 6, 3)
    layout.setSpacing(3)
    checked_seen = False
    for label, icon, tip, checkable in (
        ("选择", "map/select.svg", "选择要素", True),
        ("平移", "map/pan.svg", "平移", True),
        ("缩放+", "map/zoom_in.svg", "放大", False),
        ("缩放-", "map/zoom_out.svg", "缩小", False),
        ("全图", "map/full_extent.svg", "全图", False),
        ("测距", "map/measure_distance.svg", "测距", False),
        ("查询", "map/identify.svg", "查询", False),
        ("清除", "map/clear_selection.svg", "清除选择", False),
    ):
        button = QToolButton(bar)
        button.setObjectName("WorkstationContextButton")
        button.setIcon(workstation_icon(icon))
        button.setText(label)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setToolTip(tip)
        button.setCheckable(checkable)
        if checkable and not checked_seen:
            button.setChecked(True)
            checked_seen = True
        layout.addWidget(button)
    layout.addStretch(1)
    return bar


# ── 图层管理（真实变更：作用于渲染快照） ──────────────────────────────────


class LayerManagerPanel(QFrame):
    """图层管理 mock：树 + 不透明度 + 顺序 + 图例，变更直接写回快照。"""

    def __init__(self, owner: CompositeVariants, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setObjectName("PanelCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        title = QLabel("图层管理")
        title.setObjectName("WorkstationPanelTitle")
        outer.addWidget(title)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索图层名称")
        self.search.setClearButtonEnabled(True)
        outer.addWidget(self.search)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        outer.addWidget(self.tree, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("不透明度"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(100)
        row.addWidget(self.opacity, 1)
        outer.addLayout(row)

        order = QHBoxLayout()
        for label, icon, cb in (
            ("上移", "map/tree-move-up.svg", self._move_up),
            ("下移", "map/tree-move-down.svg", self._move_down),
        ):
            button = QToolButton(self)
            button.setObjectName("WorkstationContextButton")
            button.setIcon(workstation_icon(icon))
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.clicked.connect(cb)
            order.addWidget(button)
        order.addStretch(1)
        outer.addLayout(order)

        legend_title = QLabel("图例")
        legend_title.setObjectName("WorkstationPanelFootnote")
        outer.addWidget(legend_title)
        self.legend = QListWidget(self)
        self.legend.setMaximumHeight(96)
        for label, color in WORKAREA_LEGEND_ITEMS:
            item = QListWidgetItem(f"●  {label}")
            item.setForeground(QColor(color))
            self.legend.addItem(item)
        outer.addWidget(self.legend)

        self.search.textChanged.connect(self._filter)
        self.tree.currentItemChanged.connect(lambda *_: self._sync_opacity())
        self.opacity.valueChanged.connect(self._apply_opacity)
        self._reload()

    def _reload(self) -> None:
        self.tree.clear()
        for layer in self._owner.layers:
            item = QTreeWidgetItem([layer.name])
            item.setData(0, Qt.ItemDataRole.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0, Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
            )
            self.tree.addTopLevelItem(item)
        self.tree.itemChanged.connect(self._on_item_changed)

    def refresh_tree(self) -> None:
        self.tree.itemChanged.disconnect(self._on_item_changed)
        self._reload()

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            item.setHidden(bool(text) and text not in item.text(0).lower())

    def _on_item_changed(self, item: QTreeWidgetItem) -> None:
        self._owner.set_layer_visible(item.data(0, Qt.ItemDataRole.UserRole),
                                      item.checkState(0) == Qt.CheckState.Checked)

    def _sync_opacity(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        layer = self._owner.layer_by_id(item.data(0, Qt.ItemDataRole.UserRole))
        if layer is not None:
            self.opacity.blockSignals(True)
            self.opacity.setValue(int(layer.opacity * 100))
            self.opacity.blockSignals(False)

    def _apply_opacity(self, value: int) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self._owner.set_layer_opacity(
                item.data(0, Qt.ItemDataRole.UserRole), value / 100.0
            )

    def _move_up(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self._owner.move_layer(item.data(0, Qt.ItemDataRole.UserRole), +1)

    def _move_down(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self._owner.move_layer(item.data(0, Qt.ItemDataRole.UserRole), -1)


# ── 变体宿主（可嵌入 WorkstationFrame，也可独立运行） ─────────────────────


class CompositeVariants(QWidget):
    """三个综合编修布局变体的宿主：真实地图 + 图层管理 + 浮动切换条。"""

    variant_changed = Signal()

    def __init__(self, project: ProjectDocument, parent=None):
        super().__init__(parent)
        self.project = project
        self.canvas = UnifiedMapCanvas()
        snapshot = build_workarea_map_snapshot(project)
        self.layers = list(snapshot.layers)
        self.canvas.set_layer_snapshot(snapshot)
        extent = workarea_view_extent(snapshot)
        if extent is not None:
            self.canvas.set_extent(extent)
        self.layer_manager = LayerManagerPanel(self)

        self._variant_index = 0
        self._switcher: QFrame | None = None
        self.apply_variant(0)

    # -- snapshot mutations（真实作用于渲染） --------------------------------

    def _publish(self) -> None:
        self.canvas.set_layer_snapshot(
            MapRenderSnapshot(project_crs="EPSG:4326", layers=tuple(self.layers))
        )
        self.layer_manager.refresh_tree()

    def layer_by_id(self, layer_id: str):
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        return None

    def set_layer_visible(self, layer_id: str, visible: bool) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is not None:
            self.layers[self.layers.index(layer)] = replace(layer, visible=visible)
            self._publish()

    def set_layer_opacity(self, layer_id: str, opacity: float) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is not None:
            self.layers[self.layers.index(layer)] = replace(
                layer, opacity=max(0.05, opacity)
            )
            self._publish()

    def move_layer(self, layer_id: str, direction: int) -> None:
        layer = self.layer_by_id(layer_id)
        if layer is None:
            return
        index = self.layers.index(layer)
        target = index - direction  # 渲染自底向上；上移 = 提前
        if not 0 <= target < len(self.layers):
            return
        self.layers[index], self.layers[target] = self.layers[target], self.layers[index]
        self._publish()

    # -- variants ------------------------------------------------------------

    @property
    def variant_key(self) -> str:
        return VARIANTS[self._variant_index][0]

    @property
    def variant_name(self) -> str:
        return VARIANTS[self._variant_index][1]

    def apply_variant(self, index: int) -> None:
        self._variant_index = index % len(VARIANTS)
        # 跨变体存活的组件先摘出，避免随旧布局树一起销毁
        self.canvas.setParent(None)
        self.layer_manager.setParent(None)
        old = self.layout()
        if old is not None:
            QWidget().setLayout(old)
        builders = {0: self._build_a, 1: self._build_b, 2: self._build_c}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(builders[self._variant_index](), 1)
        self._mount_switcher()
        self.variant_changed.emit()

    def next_variant(self) -> None:
        self.apply_variant(self._variant_index + 1)

    def previous_variant(self) -> None:
        self.apply_variant(self._variant_index - 1)

    def keyPressEvent(self, event) -> None:
        from PySide6.QtWidgets import QLineEdit as _QLineEdit

        focus = self.focusWidget()
        if isinstance(focus, _QLineEdit):
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Left:
            self.previous_variant()
        elif event.key() == Qt.Key.Key_Right:
            self.next_variant()
        else:
            super().keyPressEvent(event)

    def _mount_switcher(self) -> None:
        if self._switcher is not None:
            self._switcher.deleteLater()
        bar = QFrame(self)
        bar.setObjectName("PrototypeSwitcher")
        bar.setStyleSheet(
            "QFrame#PrototypeSwitcher { background: #18232d; border-radius: 16px; }"
            "QFrame#PrototypeSwitcher QLabel { color: #ffffff; font-size: 12px; }"
            "QFrame#PrototypeSwitcher QToolButton { color: #ffffff; border: none;"
            "  background: transparent; padding: 4px 10px; font-size: 14px; }"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)
        prev_button = QToolButton(bar)
        prev_button.setText("◀")
        next_button = QToolButton(bar)
        next_button.setText("▶")
        label = QLabel(f"{self.variant_key} — {self.variant_name}")
        prev_button.clicked.connect(self.previous_variant)
        next_button.clicked.connect(self.next_variant)
        layout.addWidget(prev_button)
        layout.addWidget(label)
        layout.addWidget(next_button)
        bar.adjustSize()
        self._switcher = bar
        self._reposition_switcher()

    def _reposition_switcher(self) -> None:
        if self._switcher is None:
            return
        bar = self._switcher
        bar.move(
            (self.width() - bar.width()) // 2,
            self.height() - bar.height() - 10,
        )
        bar.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_switcher()

    # -- variant builders -----------------------------------------------------

    def _build_a(self) -> QWidget:
        """A「右置图层管理」：工具条 + 地图主体 + 右侧图层管理。"""
        page = QWidget()
        split = QSplitter(Qt.Orientation.Horizontal)
        map_column = QWidget()
        map_layout = QVBoxLayout(map_column)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.setSpacing(0)
        map_layout.addWidget(_map_toolbar())
        map_layout.addWidget(self.canvas, 1)
        split.addWidget(map_column)
        split.addWidget(self.layer_manager)
        split.setSizes([1050, 300])
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(split)
        return page

    def _build_b(self) -> QWidget:
        """B「双栏工作台」：左输入树 + 地图 + 右侧图层管理/检查器。"""
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(_map_toolbar())

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QFrame()
        left.setObjectName("PanelCard")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("输入与结果")
        title.setObjectName("WorkstationPanelTitle")
        left_layout.addWidget(title)
        left_layout.addWidget(_input_tree(self.project), 1)

        map_column = QWidget()
        map_layout = QVBoxLayout(map_column)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.addWidget(self.canvas, 1)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.layer_manager)
        inspector = QFrame()
        inspector.setObjectName("PanelCard")
        inspector_layout = QVBoxLayout(inspector)
        inspector_title = QLabel("检查器")
        inspector_title.setObjectName("WorkstationPanelTitle")
        inspector_layout.addWidget(inspector_title)
        inspector_layout.addWidget(QLabel("选中图层/要素的属性将在这里显示（mock）"))
        inspector_layout.addStretch(1)
        right.addWidget(inspector)
        right.setSizes([320, 220])

        split.addWidget(left)
        split.addWidget(map_column)
        split.addWidget(right)
        split.setSizes([240, 860, 300])
        page_layout.addWidget(split, 1)
        return page

    def _build_c(self) -> QWidget:
        """C「全幅浮动停靠」：地图全幅 + 浮动图层管理 + 悬浮工具条。"""
        page = QWidget()
        page.setStyleSheet("background: #101418;")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self.canvas, 1)

        toolbar = _map_toolbar()
        toolbar.setParent(page)
        toolbar.adjustSize()

        panel = self.layer_manager
        panel.setParent(page)
        panel.adjustSize()
        toggle = QToolButton(page)
        toggle.setText("◀ 图层")
        toggle.setStyleSheet(
            "QToolButton { background: rgba(24,35,45,0.85); color: white;"
            " border-radius: 4px; padding: 4px 8px; }"
        )

        def _relayout(*_args) -> None:
            w = page.width()
            toolbar.move((w - toolbar.width()) // 2, 8)
            panel.move(w - panel.width() - 10, 48)
            toggle.move(w - panel.width() - 10, 12)

        def _toggle() -> None:
            hidden = panel.isHidden()
            panel.setVisible(hidden)
            toggle.setText("◀ 图层" if not hidden else "▶ 图层")

        toggle.clicked.connect(_toggle)
        page.resizeEvent = _relayout  # type: ignore[method-assign]
        QTimer.singleShot(0, _relayout)
        return page


# ── 独立运行（备用）+ 宿主安装 ────────────────────────────────────────────


def install_composite_prototype(workstation):
    """把变体宿主挂进 WorkstationFrame：新增「综合编修·原型」文档 tab。

    返回 handle（host / tab_index），由宿主在 tab 切换时显示对应页。
    """
    project = getattr(workstation, "_project", None)
    variants = CompositeVariants(project)
    tab_index = workstation.document_tabs.addTab("综合编修·原型")
    workstation.document_stack.addWidget(variants)
    variants.keyPressEvent  # noqa: B018 — 保留引用说明方向键在该页生效
    return types.SimpleNamespace(host=variants, tab_index=tab_index)


def main() -> None:
    """独立运行（备用）：无工作站外壳的裸变体宿主。"""
    if PROJECT_JSON.exists():
        project = ProjectDocument.model_validate(json.loads(PROJECT_JSON.read_text("utf-8")))
    else:
        project = ProjectDocument.new("原型工程")
    app = QApplication(sys.argv)
    from paleo_workbench import tokens

    app.setStyleSheet(tokens.build_qss())
    window = QWidget()
    window.setWindowTitle("综合编修环境 · 原型（throwaway）")
    window.resize(1440, 900)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(CompositeVariants(project), 1)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
