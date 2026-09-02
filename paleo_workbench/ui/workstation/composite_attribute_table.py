"""综合编修属性表：QGIS「打开属性表」窗口语义。

行 = 要素，列 = 字段 schema（+ 要素上出现的额外属性键）。编辑一律落为
``VectorEditSession.change_attribute`` 命令——undo/redo/commit/project
版本链与画布数字化完全一致；表选择与图层选集双向同步；多选支持批量
字段修改。不复制旧 MappingPage 的面板实现，编辑权威只在会话。
"""

from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens
from paleo_workbench.ui.workstation.composite_editing import schema_fields


class CompositeAttributeTableDialog(QDialog):
    """One layer's attribute table, editing through the edit session."""

    feature_activated = Signal(str)  # double-clicked feature id (host locates it)

    def __init__(self, controller, layer_id: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompositeAttributeTableDialog")
        self._controller = controller
        self._layer_id = str(layer_id)
        layer = controller.layer(self._layer_id)
        self.setWindowTitle(f"属性表 — {layer.name if layer is not None else ''}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self._info = QLabel("", self)
        self._info.setObjectName("WorkstationPanelFootnote")
        outer.addWidget(self._info)

        self.table = QTableWidget(0, 1, self)
        self.table.setObjectName("CompositeAttributeTableWidget")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        outer.addWidget(self.table, 1)

        batch = QFrame(self)
        batch_layout = QHBoxLayout(batch)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(6)
        batch_layout.addWidget(QLabel("批量修改选中行：", batch))
        self._batch_field = QComboBox(batch)
        self._batch_value = QLineEdit(batch)
        self._batch_value.setPlaceholderText("新值")
        apply_btn = QPushButton("应用到选中", batch)
        apply_btn.clicked.connect(self._apply_batch)
        batch_layout.addWidget(self._batch_field, 1)
        batch_layout.addWidget(self._batch_value, 1)
        batch_layout.addWidget(apply_btn)
        outer.addWidget(batch)

        close = QPushButton("关闭", self)
        close.clicked.connect(self.accept)
        outer.addWidget(close)

        self._suppress_selection_sync = False
        self._suppress_item_changed = False
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self._controller.content_changed.connect(self._on_content_changed)
        self._controller.state_changed.connect(self._on_state_changed)

        self.refresh()
        self.resize(720, 420)

    # -- data ---------------------------------------------------------------

    def _layer(self):
        return self._controller.layer(self._layer_id)

    def _features(self):
        layer = self._layer()
        if layer is None:
            return ()
        session = layer.edit_session
        return session.features() if session is not None else layer.features()

    def _columns(self) -> list[tuple[str, str, str]]:
        """(key, header, kind) — schema 字段优先，额外属性键附加。"""
        columns: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for field in schema_fields(self._controller.layer_schema(self._layer_id)):
            columns.append((field.name, field.label, field.kind))
            seen.add(field.name)
        for feature in self._features():
            for key in sorted(feature.attributes):
                if key not in seen:
                    columns.append((key, key, "text"))
                    seen.add(key)
        return columns or [("id", "ID", "text")]

    def refresh(self) -> None:
        layer = self._layer()
        if layer is None:
            self.reject()
            return
        columns = self._columns()
        features = self._features()
        self._suppress_item_changed = True
        self._suppress_selection_sync = True
        try:
            self.table.setColumnCount(len(columns) + 1)
            self.table.setHorizontalHeaderLabels(
                ["fid"] + [header for _key, header, _kind in columns]
            )
            self.table.setRowCount(len(features))
            selection = layer.selection
            for row, feature in enumerate(features):
                fid_item = QTableWidgetItem(feature.feature_id)
                fid_item.setFlags(
                    fid_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                fid_item.setData(Qt.ItemDataRole.UserRole, feature.feature_id)
                self.table.setItem(row, 0, fid_item)
                if feature.feature_id in selection:
                    fid_item.setSelected(True)
                for column, (key, _header, kind) in enumerate(columns, start=1):
                    value = feature.attributes.get(key, "")
                    item = QTableWidgetItem("" if value is None else str(value))
                    item.setData(Qt.ItemDataRole.UserRole, (feature.feature_id, key, kind))
                    self.table.setItem(row, column, item)
            self._info.setText(
                f"{len(features)} 个要素 · {len(columns)} 个字段 · "
                + ("编辑中（修改即时进入编辑会话）" if layer.edit_session is not None else "只读（编辑单元格将自动开始编辑会话）")
            )
            self._batch_field.clear()
            for key, header, _kind in columns:
                self._batch_field.addItem(header, key)
        finally:
            self._suppress_selection_sync = False
            self._suppress_item_changed = False

    # -- editing ------------------------------------------------------------

    def _edit_session(self):
        layer = self._layer()
        if layer is None:
            return None
        return layer.edit_session or layer.start_editing()

    def _write_attribute(self, feature_id: str, key: str, kind: str, text: str) -> None:
        session = self._edit_session()
        if session is None:
            return
        value: object = text
        if kind == "number":
            try:
                value = float(text)
            except ValueError:
                value = text  # 保留输入；校验在 schema 层标记
        session.change_attribute(feature_id, key, value)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suppress_item_changed:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not payload:
            return
        feature_id, key, kind = payload
        self._write_attribute(feature_id, key, kind, item.text())

    def _apply_batch(self) -> None:
        key = str(self._batch_field.currentData() or "")
        text = self._batch_value.text()
        if not key:
            return
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        feature_ids = []
        for row in rows:
            fid_item = self.table.item(row, 0)
            if fid_item is not None:
                feature_ids.append(str(fid_item.text()))
        kind = next(
            (k for c_key, _h, k in self._columns() if c_key == key), "text"
        )
        session = self._edit_session()
        if session is None:
            return
        for feature_id in feature_ids:
            self._write_attribute(feature_id, key, kind, text)
        self.refresh()

    # -- selection sync -------------------------------------------------------

    def _on_selection_changed(self) -> None:
        if self._suppress_selection_sync:
            return
        layer = self._layer()
        if layer is None:
            return
        feature_ids = set()
        for index in self.table.selectedIndexes():
            if index.column() == 0:
                item = self.table.item(index.row(), 0)
                if item is not None:
                    feature_ids.add(str(item.text()))
        layer.set_selection(feature_ids)
        self._controller.state_changed.emit()

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if column != 0:
            return
        item = self.table.item(row, 0)
        if item is not None:
            self.feature_activated.emit(str(item.text()))

    # -- live refresh ------------------------------------------------------------

    def _on_content_changed(self, layer_id: str) -> None:
        if str(layer_id) == self._layer_id:
            self.refresh()

    def _on_state_changed(self) -> None:
        # 选择变化来自图层侧（画布点选）时同步表选区，避免整表重建。
        layer = self._layer()
        if layer is None:
            return
        selection = layer.selection
        self._suppress_selection_sync = True
        try:
            self.table.clearSelection()
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None and str(item.text()) in selection:
                    item.setSelected(True)
        finally:
            self._suppress_selection_sync = False
