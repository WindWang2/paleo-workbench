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

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
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
    QTableView,
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


class _CellProxy:
    """Test-facing cell handle: ``item(row, col).text()`` without QTableWidgetItem."""

    def __init__(self, model, row: int, column: int) -> None:
        self._model = model
        self._row = row
        self._column = column

    def text(self) -> str:
        value = self._model.data(self._model.index(self._row, self._column))
        return "" if value is None else str(value)

    def data(self, role=Qt.ItemDataRole.UserRole):
        return self._model.data(self._model.index(self._row, self._column), role)


class _AttributeTableView(QTableView):
    """QTableView with the QTableWidget accessors the differential tests use."""

    def rowCount(self) -> int:  # noqa: N802
        model = self.model()
        return 0 if model is None else model.rowCount()

    def columnCount(self) -> int:  # noqa: N802
        model = self.model()
        return 0 if model is None else model.columnCount()

    def item(self, row: int, column: int):
        model = self.model()
        if model is None:
            return None
        if row < 0 or column < 0 or row >= model.rowCount() or column >= model.columnCount():
            return None
        return _CellProxy(model, row, column)

    def horizontalHeaderItem(self, column: int):  # noqa: N802
        model = self.model()
        if model is None:
            return None

        class _Header:
            def __init__(self, text: str) -> None:
                self._text = text

            def text(self) -> str:
                return self._text

        return _Header(str(model.headerData(column, Qt.Orientation.Horizontal) or ""))


class _AttributeTableModel(QAbstractTableModel):
    def __init__(self, dialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._fids: list[str] = []
        self._columns: tuple = ()
        self._editable = False

    def reset_from_layer(self, fids, columns, editable: bool) -> None:
        self.beginResetModel()
        self._fids = list(fids)
        self._columns = tuple(columns)
        self._editable = bool(editable)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._fids)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._columns) + 1

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        if section == 0:
            return "fid"
        if 0 < section <= len(self._columns):
            return CompositeAttributeTableDialog._header_for(self._columns[section - 1])
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() > 0 and self._editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._fids):
            return None
        fid = self._fids[index.row()]
        if index.column() == 0:
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole,
                        Qt.ItemDataRole.UserRole):
                return fid
            return None
        field = self._columns[index.column() - 1]
        feature = self._dialog._feature(fid)
        value = "" if feature is None else feature.attributes.get(field.key, "")
        if role == Qt.ItemDataRole.UserRole:
            return (fid, field.key, field.kind)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if value is None:
                return ""
            if field.numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            if field.numeric:
                try:
                    return float(str(value).strip())
                except ValueError:
                    return str(value)
            return str(value)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() == 0:
            return False
        field = self._columns[index.column() - 1]
        fid = self._fids[index.row()]
        written = self._dialog._write_attribute(fid, field.key, field.kind, str(value))
        if written is False:
            return False
        self.dataChanged.emit(index, index)
        return True

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:  # noqa: N802
        if column < 0 or column >= self.columnCount():
            return
        reverse = order == Qt.SortOrder.DescendingOrder
        keyed: list[tuple[str, object]] = []
        for row, fid in enumerate(self._fids):
            keyed.append((
                fid,
                self.data(self.index(row, column), Qt.ItemDataRole.DisplayRole),
            ))

        def sort_key(item: tuple[str, object]):
            value = item[1]
            if value is None or value == "":
                return (1, 0.0, "")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return (0, float(value), "")
            return (0, 0.0, str(value))

        self.layoutAboutToBeChanged.emit()
        keyed.sort(key=sort_key, reverse=reverse)
        self._fids = [fid for fid, _ in keyed]
        self.layoutChanged.emit()

    def emit_rows(self, fids, row_by_id=None) -> None:
        lookup = row_by_id if row_by_id is not None else {
            fid: index for index, fid in enumerate(self._fids)
        }
        for fid in fids:
            row = lookup.get(fid)
            if row is None:
                continue
            left = self.index(row, 0)
            right = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(left, right)


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
            # review-1 P0-1：编辑器必须落在当前值上——此前硬编码 index 0，
            # 打开 "false" 单元格按 Enter 会把值翻转成 "true"（数据损坏）。
            position = editor.findText(str(index.data() or ""))
            editor.setCurrentIndex(position if position >= 0 else 0)
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

        self._model = _AttributeTableModel(self)
        self.table = _AttributeTableView(self)
        self.table.setObjectName("CompositeAttributeTableWidget")
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
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
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_cell_double_clicked)
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

    def _feature(self, feature_id: str):
        layer = self._layer()
        if layer is None:
            return None
        session = layer.edit_session
        try:
            if session is not None:
                return session.feature(feature_id)
            return layer.feature(feature_id)
        except KeyError:
            return None

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
        editable, gate_reason = self._controller.can_edit_layer(self._layer_id)
        parity_state, parity_detail = self._qgis_parity(columns)
        self._suppress_item_changed = True
        self._suppress_selection_sync = True
        self.table.setSortingEnabled(False)
        try:
            fids = [feature.feature_id for feature in features]
            self._model.reset_from_layer(fids, columns, editable)
            self._info.setText(
                self._status_text(len(features), len(columns), layer, editable,
                                  gate_reason, parity_state, parity_detail))
            self._batch_field.clear()
            for field in columns:
                self._batch_field.addItem(field.label, field.key)
            self._sync_selection_from_layer(layer)
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
        """与 QGIS provider schema 的一致性（每次全量 refresh 各一次桥调用）。

        差量刷新（_refresh_changed_features）不触发本方法——列结构不变时
        parity 结论不变；桥调用本身为 O(字段) 小自省，不在帧级链上。"""
        canvas = getattr(self._controller, "_canvas", None)
        state, detail = qgis_schema_parity(canvas, self._layer_id, columns)
        self._parity_state = (state, detail)
        return state, detail

    @staticmethod
    def _header_for(field: AttributeFieldMeta) -> str:
        mark = "*" if field.required else ""
        return f"{field.label}{mark}"

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
        """fid → 当前行。"""
        return {fid: row for row, fid in enumerate(self._model._fids)}

    def _sync_selection_from_layer(self, layer) -> None:
        selection = layer.selection
        model = self.table.selectionModel()
        if model is None:
            return
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        sel = QItemSelection()
        for row, fid in enumerate(self._model._fids):
            if fid in selection:
                index = self._model.index(row, 0)
                sel.select(index, index)
        model.select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)

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
        V10 M-I：unique 约束同路径反馈——同层其他要素已持有该值时拒绝。
        表达式约束（expression）不在此实现——provider 侧职责，会话保持
        schema 无关。
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
                if field.value_range is not None:
                    # review-2 P2-2：带 Range 域的字段必须可解析为数值——
                    # 非数值文本此前静默绕过范围门（含批量路径）。
                    self._info.setText(
                        f"字段「{field.label}」需要数值（Range 约束）"
                        "——输入未写入")
                    return False
                value = text  # 无域约束：保留输入；校验在 schema 层标记
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
        if field is not None and field.unique and self._unique_value_taken(
                field, feature_id, value):
            self._info.setText(
                f"字段「{field.label}」的值已被其他要素占用"
                "（unique 约束）——输入未写入")
            return False
        session.change_attribute(feature_id, key, value)
        # 属性变化驱动画布（标注渲染）与工程同步（review #17）；
        # 本表自身的重建被抑制——不能打断正在编辑的单元格。
        self._suppress_content_refresh = True
        try:
            self._controller.content_changed.emit(self._layer_id)
        finally:
            self._suppress_content_refresh = False
        return True

    def _unique_value_taken(
        self, field: AttributeFieldMeta, feature_id: str, value: object,
    ) -> bool:
        """unique 字段占位检查：同层其他要素已持有该值时返回 True。

        仅在描述符带 ``unique`` 标志时被调用，单次写入 O(n) 扫描本层
        要素。空值不占用唯一域（与 QGIS unique 约束的 NULL 语义同向：
        清空/未填互不撞车，空值由必填约束另行把关）；数值字段按 float
        归一比较（``"12"`` 与 ``12.0`` 视为同值），其余按去空白文本比较。
        """
        text = str(value).strip()
        if not text:
            return False
        for feature in self._features():
            if feature.feature_id == feature_id:
                continue  # 自身当前值不构成冲突（原地重写/清空合法）
            other = feature.attributes.get(field.key)
            if other is None or not str(other).strip():
                continue
            if field.numeric:
                try:
                    if float(other) == float(value):
                        return True
                except (TypeError, ValueError):
                    continue
            elif str(other).strip() == text:
                return True
        return False

    def _apply_batch(self) -> None:
        key = str(self._batch_field.currentData() or "")
        text = self._batch_value.text()
        if not key:
            return
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        feature_ids = []
        for row in rows:
            if 0 <= row < len(self._model._fids):
                feature_ids.append(self._model._fids[row])
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

    def _on_selection_changed(self, *_args) -> None:
        if self._suppress_selection_sync:
            return
        layer = self._layer()
        if layer is None:
            return
        feature_ids = set()
        for index in self.table.selectedIndexes():
            if index.column() == 0 and 0 <= index.row() < len(self._model._fids):
                feature_ids.add(self._model._fids[index.row()])
        layer.set_selection(feature_ids)
        self._controller.state_changed.emit()

    def _on_cell_double_clicked(self, index) -> None:
        if not index.isValid() or index.column() != 0:
            return
        if 0 <= index.row() < len(self._model._fids):
            self.feature_activated.emit(self._model._fids[index.row()])

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
        self.table.setSortingEnabled(False)
        try:
            self._model.emit_rows(changed, row_by_id)
        finally:
            self.table.setSortingEnabled(True)
            self._suppress_item_changed = False
        self._refresh_state = (session, revision, columns, self._row_map())
        return True

    def _on_state_changed(self) -> None:
        # 选择变化来自图层侧（画布点选）时同步表选区，避免整表重建。
        layer = self._layer()
        if layer is None:
            return
        self._suppress_selection_sync = True
        try:
            self._sync_selection_from_layer(layer)
        finally:
            self._suppress_selection_sync = False
