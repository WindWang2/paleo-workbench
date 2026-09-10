"""综合编修属性表：QGIS「打开属性表」窗口语义。

行 = 要素，列 = 字段 schema（+ 要素上出现的额外属性键）。编辑一律落为
``VectorEditSession.change_attribute`` 命令——undo/redo/commit/project
版本链与画布数字化完全一致；表选择与图层选集双向同步；多选支持批量
字段修改。不复制旧 MappingPage 的面板实现，编辑权威只在会话。

V9 W5（QGIS provider schema 消费）：

* 列元数据经 :mod:`attribute_schema` 单一派生——图层有角色时与镜像
  ``fields_json`` 同权威（``GeologicalLayerSpec``），ValueMap/Range/
  CheckBox 控件词表与 QGIS provider 一致；
* 表头点击数值列按数值排序（文本列按本地化文本）；
* 单元格编辑器按控件词表生成（ValueMap → 下拉，CheckBox → 勾选，
  Range → 带上下界的数值输入），约束（必填/范围）在写入路径反馈；
* 状态行呈现与 QGIS provider schema 的一致性标注（synced/drift/
  unavailable——数据权威仍在 Python 会话，drift 只呈现不阻塞）。
"""

from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator
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
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens
from paleo_workbench.ui.workstation.attribute_schema import (
    AttributeFieldMeta,
    field_descriptors_for_layer,
    qgis_schema_parity,
)
from paleo_workbench.ui.workstation.composite_editing import schema_fields


class _FieldEditorDelegate(QStyledItemDelegate):
    """按字段元数据生成编辑器（QGIS 编辑控件词表的表内对应物）。"""

    def __init__(self, columns_provider, parent=None) -> None:
        super().__init__(parent)
        self._columns_provider = columns_provider

    def createEditor(self, parent, option, index):  # noqa: N802
        columns = self._columns_provider()
        column = index.column() - 1
        if column < 0 or column >= len(columns):
            return super().createEditor(parent, option, index)
        field: AttributeFieldMeta = columns[column]
        if field.choices:
            combo = QComboBox(parent)
            combo.setEditable(True)
            combo.addItems(list(field.choices))
            return combo
        if field.kind == "bool":
            combo = QComboBox(parent)
            combo.addItems(["true", "false"])
            return combo
        if field.numeric:
            editor = QLineEdit(parent)
            validator = QDoubleValidator(editor)
            validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            if field.value_range is not None:
                low, high = field.value_range
                validator.setRange(float(low), float(high))
            editor.setValidator(validator)
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index) -> None:  # noqa: N802
        if isinstance(editor, QComboBox) and not editor.isEditable():
            editor.setCurrentIndex(0)
            return
        if isinstance(editor, QComboBox):
            text = index.data() or ""
            position = editor.findText(str(text))
            editor.setCurrentIndex(position if position >= 0 else -1)
            editor.lineEdit().setText(str(text))
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index) -> None:  # noqa: N802
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText())
            return
        super().setModelData(editor, model, index)


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
        # V9 W5：表头点击排序（数值列按数值——item 以 typed DisplayRole
        # 携带数值）。排序移动行后行映射经 _rebuild_row_map 重建。
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.setItemDelegate(_FieldEditorDelegate(self._columns, self.table))
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
        self.table.horizontalHeader().sortIndicatorChanged.connect(
            self._on_sort_changed)

        self._controller.content_changed.connect(self._on_content_changed)
        self._controller.state_changed.connect(self._on_state_changed)

        # 差量刷新基线（C-P0-3）：(session, packed revision, columns, {fid: row})。
        # None = 无基线，首个 content_changed 走全量 refresh。
        self._refresh_state: tuple | None = None
        self._parity_state: tuple[str, str] = ("unavailable", "")

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

    def _columns(self) -> tuple[AttributeFieldMeta, ...]:
        """列元数据（V9 W5：spec/template/extra 单一派生，带缓存）。"""
        cached = getattr(self, "_columns_cache", None)
        if cached is not None:
            return cached
        columns = field_descriptors_for_layer(self._controller, self._layer_id)
        self._columns_cache = columns
        return columns

    def _invalidate_columns(self) -> None:
        self._columns_cache = None

    def refresh(self) -> None:
        layer = self._layer()
        if layer is None:
            self.reject()
            return
        self._invalidate_columns()
        columns = self._columns()
        features = self._features()
        # 角色门禁（V6）：RAW/锁定图层整表只读并明示原因，单元格不可编辑。
        editable, gate_reason = self._controller.can_edit_layer(self._layer_id)
        parity_state, parity_detail = self._qgis_parity(columns)
        self._suppress_item_changed = True
        self._suppress_selection_sync = True
        self.table.setSortingEnabled(False)
        try:
            self.table.setColumnCount(len(columns) + 1)
            self.table.setHorizontalHeaderLabels(
                ["fid"] + [self._header_for(field) for field in columns]
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
                for column, field in enumerate(columns, start=1):
                    value = feature.attributes.get(field.key, "")
                    item = QTableWidgetItem()
                    self._apply_display(item, field, value)
                    item.setData(
                        Qt.ItemDataRole.UserRole, (feature.feature_id, field.key, field.kind))
                    if not editable:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, column, item)
            self._info.setText(
                self._status_text(len(features), len(columns), layer, editable,
                                  gate_reason, parity_state, parity_detail))
            self._batch_field.clear()
            for field in columns:
                self._batch_field.addItem(field.label, field.key)
        finally:
            self.table.setSortingEnabled(True)
            self._suppress_selection_sync = False
            self._suppress_item_changed = False
        session = layer.edit_session
        self._refresh_state = (
            session,
            (layer.data_revision << 32) + (session.revision if session is not None else 0),
            columns,
            self._row_map(),
        )

    def _qgis_parity(self, columns) -> tuple[str, str]:
        """与 QGIS provider schema 的一致性（缓存到列结构变化）。"""
        canvas = getattr(self._controller, "_canvas", None)
        state, detail = qgis_schema_parity(canvas, self._layer_id, columns)
        self._parity_state = (state, detail)
        return state, detail

    @staticmethod
    def _header_for(field: AttributeFieldMeta) -> str:
        mark = "*" if field.required else ""
        return f"{field.label}{mark}"

    @staticmethod
    def _apply_display(item: QTableWidgetItem, field: AttributeFieldMeta, value) -> None:
        """typed DisplayRole——数值列排序按数值，其余按文本。"""
        if value is None:
            item.setData(Qt.ItemDataRole.DisplayRole, "")
            return
        if field.numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
            item.setData(Qt.ItemDataRole.DisplayRole, float(value))
        elif field.numeric:
            text = str(value).strip()
            try:
                item.setData(Qt.ItemDataRole.DisplayRole, float(text))
            except ValueError:
                item.setData(Qt.ItemDataRole.DisplayRole, text)
        else:
            item.setData(Qt.ItemDataRole.DisplayRole, str(value))

    @staticmethod
    def _status_text(feature_count, column_count, layer, editable, gate_reason,
                     parity_state, parity_detail) -> str:
        parity_mark = {
            "synced": " · QGIS provider schema 一致",
            "drift": f" · ⚠ {parity_detail}",
            "unavailable": "",
        }.get(parity_state, "")
        base = (
            f"{feature_count} 个要素 · {column_count} 个字段{parity_mark} · "
        )
        if not editable:
            return base + f"只读 — {gate_reason}"
        return base + (
            "编辑中（修改即时进入编辑会话）"
            if layer.edit_session is not None
            else "只读（编辑单元格将自动开始编辑会话）"
        )

    def _row_map(self) -> dict[str, int]:
        """fid → 当前行（排序后重建的映射）。"""
        mapping: dict[str, int] = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                mapping[str(item.text())] = row
        return mapping

    def _on_sort_changed(self, _column: int, _order) -> None:
        """排序移动行后重建差量刷新基线的行映射。"""
        state = self._refresh_state
        if state is None:
            return
        self._refresh_state = (state[0], state[1], state[2], self._row_map())

    # -- editing ------------------------------------------------------------

    def _edit_session(self):
        """门禁下的会话获取（V6 B-P0-1：RAW 图层绝不开启会话）。"""
        layer = self._layer()
        if layer is None:
            return None
        session, _reason = self._controller.ensure_layer_session(self._layer_id)
        return session

    def _write_attribute(self, feature_id: str, key: str, kind: str, text: str) -> bool | None:
        """写入单元格；返回 False=被门禁/约束拒绝（调用方须恢复渲染）。

        V9 W5：spec 约束（必填/数值范围）在写入路径反馈——空值写入必填
        字段、越界数值写入 Range 字段时拒绝并明示，与 QGIS provider
        constraint 的 not_null/expression 语义同向（QGIS 侧在镜像层由
        ``fields_json`` 约束兜底，两侧同源 spec，不漂移）。
        """
        session = self._edit_session()
        if session is None:
            # 门禁拒绝（含门禁在对话框打开期间翻转的情形——review round 1
            # P2）：明示原因，绝不静默吞掉用户输入。
            _layer = self._layer()
            _allowed, reason = self._controller.can_edit_layer(self._layer_id)
            self._info.setText(
                f"只读 — {reason or '当前图层不可编辑'}（输入未写入）"
                if _layer is not None else "只读")
            return False
        field = next(
            (entry for entry in self._columns() if entry.key == key), None
        )
        value: object = text
        if field is not None and field.numeric:
            try:
                value = float(text)
            except ValueError:
                value = text  # 保留输入；校验在 schema 层标记
            else:
                if field.value_range is not None:
                    low, high = field.value_range
                    if not (float(low) <= float(value) <= float(high)):
                        self._info.setText(
                            f"字段「{field.label}」超出范围 [{low:g}, {high:g}]"
                            "——输入未写入（QGIS Range 约束同源）")
                        return False
        if field is not None and field.required and not str(text).strip():
            self._info.setText(
                f"字段「{field.label}」为必填（not-null）——输入未写入")
            return False
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
        written = self._write_attribute(feature_id, key, kind, item.text())
        if written is False:
            # 门禁拒绝（review round 3 P2）：把单元格恢复为已提交值，
            # 不留「看起来写进去了」的假成功渲染。
            self._suppress_item_changed = True
            try:
                if not self._refresh_changed_features():
                    self.refresh()
            finally:
                self._suppress_item_changed = False

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
            (entry.kind for entry in self._columns() if entry.key == key), "text"
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
        known_keys = {field.key for field in columns}
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
                self._invalidate_columns()  # 出现新字段 → 列结构变化
                return False  # → 全量
            changed[feature_id] = feature
        self._suppress_item_changed = True
        try:
            for feature_id, feature in changed.items():
                row = row_by_id[feature_id]
                for column, field in enumerate(columns, start=1):
                    item = self.table.item(row, column)
                    if item is None:
                        continue  # 行尾列守卫（正常 refresh 不会出现）
                    value = feature.attributes.get(field.key, "")
                    self._apply_display(item, field, value)
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
