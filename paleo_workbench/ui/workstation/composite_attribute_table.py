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
        self._suppress_content_refresh = False
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self._controller.content_changed.connect(self._on_content_changed)
        self._controller.state_changed.connect(self._on_state_changed)

        # 差量刷新基线（C-P0-3）：(session, packed revision, columns, {fid: row})。
        # None = 无基线，首个 content_changed 走全量 refresh。
        self._refresh_state: tuple | None = None

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
        # 角色门禁（V6）：RAW/锁定图层整表只读并明示原因，单元格不可编辑。
        editable, gate_reason = self._controller.can_edit_layer(self._layer_id)
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
                    if not editable:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, column, item)
            if not editable:
                self._info.setText(
                    f"{len(features)} 个要素 · {len(columns)} 个字段 · 只读 — {gate_reason}")
            else:
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
        session = layer.edit_session
        self._refresh_state = (
            session,
            (layer.data_revision << 32) + (session.revision if session is not None else 0),
            tuple(columns),
            {feature.feature_id: row for row, feature in enumerate(features)},
        )

    # -- editing ------------------------------------------------------------

    def _edit_session(self):
        """门禁下的会话获取（V6 B-P0-1：RAW 图层绝不开启会话）。"""
        layer = self._layer()
        if layer is None:
            return None
        session, _reason = self._controller.ensure_layer_session(self._layer_id)
        return session

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
        # 属性变化驱动画布（标注渲染）与工程同步（review #17）；
        # 本表自身的重建被抑制——不能打断正在编辑的单元格。
        self._suppress_content_refresh = True
        try:
            self._controller.content_changed.emit(self._layer_id)
        finally:
            self._suppress_content_refresh = False

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
        if str(layer_id) == self._layer_id and not self._suppress_content_refresh:
            if not self._refresh_changed_features():
                self.refresh()

    def _refresh_changed_features(self) -> bool:
        """差量刷新（C-P0-3）：会话内属性变更只 setText 受影响单元格。

        会话日志（``changes_since``）定位受影响要素；行/列结构不变时
        原地更新，不重建任何 QTableWidgetItem。要素增删、新字段、会话
        更替（提交/回滚后 session 对象换新）或日志跨度不可恢复时返回
        False，由调用方走全量 ``refresh``。单元格可编辑标志保持上次
        refresh 的门禁判定——本路径不触碰编辑门禁语义。
        """
        layer = self._layer()
        if layer is None:
            return False
        session = layer.edit_session
        state = self._refresh_state
        if session is None or state is None or state[0] is not session:
            return False
        revision = (layer.data_revision << 32) + session.revision
        if revision == state[1]:
            return True  # 重复通知，内容未变
        entries = session.changes_since(state[1] & 0xFFFFFFFF)
        if entries is None:
            return False
        row_by_id = state[3]
        columns = state[2]
        known_keys = {key for key, _header, _kind in columns}
        touched: set[str] = set()
        for ids in entries:
            touched.update(ids)
        changed: dict[str, object] = {}
        for feature_id in touched:
            if feature_id not in row_by_id:
                return False  # 新增要素 → 行结构变化 → 全量
            try:
                feature = session.feature(feature_id)
            except KeyError:
                return False  # 要素已删除 → 全量
            if any(key not in known_keys for key in feature.attributes):
                return False  # 出现新字段 → 列结构变化 → 全量
            changed[feature_id] = feature
        self._suppress_item_changed = True
        try:
            for feature_id, feature in changed.items():
                row = row_by_id[feature_id]
                for column, (key, _header, _kind) in enumerate(columns, start=1):
                    item = self.table.item(row, column)
                    if item is None:
                        continue  # 行尾列守卫（正常 refresh 不会出现）
                    value = feature.attributes.get(key, "")
                    item.setText("" if value is None else str(value))
        finally:
            self._suppress_item_changed = False
        self._refresh_state = (session, revision, columns, row_by_id)
        return True

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
