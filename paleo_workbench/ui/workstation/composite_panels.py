"""综合编修辅助面板：识别结果 + 捕捉设置。

识别结果面板承载多图层 Identify（QGIS Identify Results 语义）；捕捉设置
对话框是 per-layer 配置模型（enabled / vertex / segment / tolerance /
priority + 全局开关与容差）。两者都只是视图——权威状态在
``CompositeEditController`` 与 ``SnappingService``。
"""

from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens

_GEOMETRY_TYPE_LABELS = {
    "Point": "点",
    "MultiPoint": "点（多）",
    "LineString": "线",
    "MultiLineString": "线（多）",
    "Polygon": "面",
    "MultiPolygon": "面（多）",
}


class IdentifyResultsPanel(QFrame):
    """多图层识别结果（点击结果 → 宿主定位 / 选中 / 缩放）。"""

    result_activated = Signal(object)  # result dict

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompositeIdentifyResults")
        self.setVisible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        header = QHBoxLayout()
        title = QLabel("识别结果", self)
        title.setObjectName("WorkstationPanelFootnote")
        header.addWidget(title)
        header.addStretch(1)
        clear_button = QLabel("✕", self)
        clear_button.setToolTip("关闭识别结果")
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.mousePressEvent = lambda _event: self.set_results(())
        header.addWidget(clear_button)
        outer.addLayout(header)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("CompositeIdentifyTree")
        self.tree.setHeaderLabels(["图层", "要素", "几何"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        outer.addWidget(self.tree, 1)

    def set_results(self, results) -> None:
        self.tree.clear()
        for result in results or ():
            geometry_kind = _GEOMETRY_TYPE_LABELS.get(
                str(result.get("geometry_type") or ""), ""
            )
            item = QTreeWidgetItem(
                [
                    str(result.get("layer_name") or ""),
                    str(result.get("feature_id") or ""),
                    geometry_kind,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, dict(result))
            attributes: Mapping[str, object] = result.get("attributes") or {}
            template = str(result.get("template") or "")
            meta: list[tuple[str, str]] = [("来源", str(result.get("source") or ""))]
            if template:
                meta.append(("模板角色", template))
            meta.append(("可编辑", "是" if result.get("editable") else "否"))
            for key, value in meta + sorted(attributes.items()):
                child = QTreeWidgetItem([key, "" if value is None else str(value)])
                child.setFirstColumnSpanned(False)
                item.addChild(child)
            self.tree.addTopLevelItem(item)
        self.setVisible(bool(self.tree.topLevelItemCount()))

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload:
            self.result_activated.emit(payload)


class SnappingSettingsDialog(QDialog):
    """捕捉设置：全局开关/容差/模式 + 每图层 enable·vertex·segment·容差·优先级。

    容差语义为像素（乘以当前视图比例换算为地图单位）；井位参考点捕捉
    把基础工区井点作为 reference 候选（只在勾选时生效）。
    """

    def __init__(self, controller, parent=None, *, well_points: list | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompositeSnappingSettingsDialog")
        self.setWindowTitle("捕捉设置")
        self._controller = controller
        self._snapping = controller.snapping
        self._well_points = [tuple(point) for point in (well_points or ())]
        self._layer_rows: dict[str, dict[str, object]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        global_form = QFormLayout()
        self._global_enable = QCheckBox("启用捕捉", self)
        self._global_enable.setChecked(bool(self._snapping.enabled))
        self._global_tolerance = QDoubleSpinBox(self)
        self._global_tolerance.setRange(1.0, 100.0)
        self._global_tolerance.setDecimals(1)
        self._global_tolerance.setSuffix(" px")
        self._global_tolerance.setValue(float(self._snapping.pixel_tolerance))
        global_form.addRow(self._global_enable)
        global_form.addRow("默认容差（像素）", self._global_tolerance)
        modes_row = QHBoxLayout()
        self._mode_boxes: dict[str, QCheckBox] = {}
        for mode, label in (
            ("vertex", "顶点"),
            ("segment", "线段"),
            ("midpoint", "中点"),
            ("endpoint", "端点"),
            ("intersection", "交点"),
        ):
            box = QCheckBox(label, self)
            box.setChecked(mode in self._snapping.modes)
            self._mode_boxes[mode] = box
            modes_row.addWidget(box)
        modes_container = QWidget(self)
        modes_container.setLayout(modes_row)
        global_form.addRow("捕捉类型", modes_container)
        outer.addLayout(global_form)

        outer.addWidget(QLabel("每图层覆盖（矢量图层；容差留空使用全局值）", self))

        self._table = QTableWidget(0, 6, self)
        self._table.setObjectName("CompositeSnappingTable")
        self._table.setHorizontalHeaderLabels(
            ["图层", "启用", "顶点", "线段", "容差(px)", "优先级"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self._table, 1)

        self._well_snap = QCheckBox(
            f"参考点捕捉（井位 / 参与捕捉的引用图层，{len(self._well_points)} 个）"
            if self._well_points
            else "参考点捕捉（当前无井点 / 引用参考点）",
            self,
        )
        self._well_snap.setEnabled(bool(self._well_points))
        self._well_snap.setChecked("reference" in self._snapping.modes)
        outer.addWidget(self._well_snap)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._populate_layers()

    def _populate_layers(self) -> None:
        snapping = self._snapping
        rows: list[tuple[str, str]] = []
        for layer_id in self._controller.layer_ids():
            layer = self._controller.layer(layer_id)
            if layer is None:
                continue
            kind = self._controller.kind_of(layer_id)
            rows.append((layer_id, f"{layer.name}（{kind}）"))
        self._table.setRowCount(len(rows))
        for row, (layer_id, label) in enumerate(rows):
            enabled = snapping.layer_enabled.get(layer_id, True)
            modes = snapping.layer_modes.get(layer_id, snapping.modes)
            tolerance_override = snapping.layer_tolerance.get(layer_id)
            priority = snapping.layer_priority.get(layer_id, 0)

            name_item = QTableWidgetItem(label)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, name_item)

            entries: dict[str, object] = {}
            for column, (key, checked) in enumerate(
                (
                    ("enabled", enabled),
                    ("vertex", "vertex" in modes),
                    ("segment", "segment" in modes),
                ),
                start=1,
            ):
                box = QCheckBox(self._table)
                box.setChecked(bool(checked))
                self._table.setCellWidget(row, column, box)
                entries[key] = box

            tolerance = QDoubleSpinBox(self._table)
            tolerance.setRange(0.0, 100.0)
            tolerance.setDecimals(1)
            tolerance.setSpecialValueText("全局")
            tolerance.setValue(float(tolerance_override or 0.0))
            self._table.setCellWidget(row, 4, tolerance)
            entries["tolerance"] = tolerance

            priority_spin = QSpinBox(self._table)
            priority_spin.setRange(0, 99)
            priority_spin.setValue(int(priority))
            self._table.setCellWidget(row, 5, priority_spin)
            entries["priority"] = priority_spin

            self._layer_rows[layer_id] = entries

    def accept(self) -> None:
        snapping = self._snapping
        snapping.enabled = self._global_enable.isChecked()
        snapping.pixel_tolerance = float(self._global_tolerance.value())
        snapping.modes = {
            mode for mode, box in self._mode_boxes.items() if box.isChecked()
        }
        for layer_id, entries in self._layer_rows.items():
            snapping.layer_enabled[layer_id] = bool(entries["enabled"].isChecked())
            modes = set(snapping.modes)
            if entries["vertex"].isChecked():
                modes.add("vertex")
            else:
                modes.discard("vertex")
            if entries["segment"].isChecked():
                modes.add("segment")
            else:
                modes.discard("segment")
            if modes:
                snapping.layer_modes[layer_id] = modes
            else:
                snapping.layer_modes.pop(layer_id, None)
            tolerance = float(entries["tolerance"].value())
            if tolerance > 0.0:
                snapping.layer_tolerance[layer_id] = tolerance
            else:
                snapping.layer_tolerance.pop(layer_id, None)
            snapping.layer_priority[layer_id] = int(entries["priority"].value())
        # 井位参考点：勾选时进入 reference 捕捉候选（SnappingService 原生机制）。
        if self._well_snap.isEnabled() and self._well_snap.isChecked():
            snapping.modes.add("reference")
            snapping.set_reference_points(self._well_points)
        else:
            snapping.modes.discard("reference")
            snapping.set_reference_points(())
        self._controller.set_snapping(snapping.enabled)
        self._controller.state_changed.emit()
        super().accept()
