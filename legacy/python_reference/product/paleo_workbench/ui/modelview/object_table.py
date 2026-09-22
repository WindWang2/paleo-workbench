"""对象行虚拟表模型 + 稳定键选择适配（goal §8 Model/View Foundation）。

结构契约（01-ui-audit D2 / 11-performance）：

* 行数 = ``len(rows)``，``data()`` 按需取值 —— **永不**创建
  N×C QTableWidgetItem/QStandardItem；
* ``set_rows`` 是整表差分重置（同一键集合保持行身份，尽量小范围
  dataChanged，减少选择/滚动抖动）；
* 排序在模型侧（索引重排，不搬对象）；
* 选择适配器按**稳定键**（业务 id）跨 reset 存取，重建后同一对象
  仍被选中（paged_asset_model.row_for_key 的推广）。

列规格 :class:`ColumnSpec` 只声明取值函数与展示属性，不放业务判断。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelectionModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QTableView, QWidget

from paleo_workbench.ui import style

UserRole = Qt.ItemDataRole.UserRole

_ROW_KEY_ROLE = UserRole + 1
_ROW_OBJECT_ROLE = UserRole + 2


@dataclass(frozen=True)
class ColumnSpec:
    """一列的声明式规格：标题 + 取值 + 排序键 + 展示。"""

    key: str
    title: str
    value: Callable[[Any], Any]
    sort_value: Callable[[Any], Any] | None = None
    alignment: Qt.Alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    tooltip: Callable[[Any], str | None] | None = None
    # 返回 token 名（如 "TEXT_SECONDARY"）或 None；模型经 palette_for 取色，
    # 主题切换后经 dataChanged 刷新（配合 style.repolish_all 之后调用
    # :meth:`ObjectTableModel.refresh_display`）。
    foreground_role: Callable[[Any], str | None] | None = None
    font_role: Callable[[Any], QFont | None] | None = None
    width_hint: int | None = None

    def display(self, row: Any) -> str:
        v = self.value(row)
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:g}"
        return str(v)


class ObjectTableModel(QAbstractTableModel):
    """行为对象的虚拟表模型（零 item-per-cell）。

    ``rows`` 是任意领域对象列表；``key_of(row) -> str`` 提供稳定业务键。
    典型用法::

        model = ObjectTableModel(
            columns=[ColumnSpec("name", "名称", lambda w: w.name), ...],
            key_of=lambda w: w.id,
            parent=view,
        )
        model.set_rows(wells)          # 差分重置
    """

    def __init__(
        self,
        columns: Sequence[ColumnSpec],
        key_of: Callable[[Any], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns: list[ColumnSpec] = list(columns)
        self._key_of = key_of
        self._rows: list[Any] = []
        self._row_by_key: dict[str, int] = {}
        self._sort_column: int = -1
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

    # -- Qt 必需接口 -----------------------------------------------------------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._columns):
            if role == Qt.ItemDataRole.DisplayRole:
                return self._columns[section].title
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row_idx = index.row()
        if not 0 <= row_idx < len(self._rows):
            return None
        row = self._rows[row_idx]
        col = self._columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return col.display(row)
        if role == Qt.ItemDataRole.ToolTipRole and col.tooltip is not None:
            return col.tooltip(row)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(col.alignment)
        if role == Qt.ItemDataRole.ForegroundRole and col.foreground_role is not None:
            token_name = col.foreground_role(row)
            if token_name:
                color = style.palette().get(token_name)
                if color is not None:
                    return QColor(color)
            return None
        if role == Qt.ItemDataRole.FontRole and col.font_role is not None:
            return col.font_role(row)
        if role == _ROW_OBJECT_ROLE:
            return row
        if role == _ROW_KEY_ROLE:
            return self._key_of(row)
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        if column < -1 or column >= len(self._columns):
            return
        self._sort_column = column
        self._sort_order = order
        if column < 0:
            return
        col = self._columns[column]
        sort_value = col.sort_value or col.value

        def sort_key(row: Any):
            # 统一键形状：(类型档, 值)——数值档 < 文本档，None 档最后；
            # 混合类型列（数值+「—」占位）不再抛 TypeError（评审 P1-2）。
            v = sort_value(row)
            if v is None:
                return (2, 0)
            if isinstance(v, bool):
                return (0, float(v))
            if isinstance(v, (int, float)):
                return (0, float(v))
            return (1, str(v))

        # 行身份 → 排序后行号的映射，用于重映射持久索引（Qt 不会在
        # layoutChanged 时自动重映射——评审 P1-1：选择/当前行错乱）。
        old_rows = list(self._rows)
        persistent = self.persistentIndexList()
        old_positions = [index.row() for index in persistent]

        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=sort_key, reverse=order == Qt.SortOrder.DescendingOrder)
        self._reindex()
        position_by_identity = {id(row): i for i, row in enumerate(self._rows)}
        for index, old_pos in zip(persistent, old_positions):
            if not 0 <= old_pos < len(old_rows):
                continue
            new_pos = position_by_identity.get(id(old_rows[old_pos]))
            if new_pos is None:
                continue
            self.changePersistentIndex(
                index, self.index(new_pos, index.column())
            )
        self.layoutChanged.emit()

    # -- 行管理 -----------------------------------------------------------------

    def set_rows(self, rows: Iterable[Any]) -> None:
        """差分重置：键集合与顺序一致时仅发 dataChanged（保选择/滚动）。"""
        new_rows = list(rows)
        old_keys = [self._key_of(r) for r in self._rows]
        new_keys = [self._key_of(r) for r in new_rows]
        if old_keys == new_keys:
            if not new_keys:
                return
            top = self.index(0, 0)
            bottom = self.index(len(new_rows) - 1, len(self._columns) - 1)
            self._rows = new_rows
            self._reindex()
            self.dataChanged.emit(top, bottom)
            return
        self.beginResetModel()
        self._rows = new_rows
        self._reindex()
        self.endResetModel()

    def append_rows(self, rows: Iterable[Any]) -> None:
        add = [r for r in rows if self._key_of(r) not in self._row_by_key]
        if not add:
            return
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(add) - 1)
        self._rows.extend(add)
        self._reindex()
        self.endInsertRows()

    def remove_keys(self, keys: Iterable[str]) -> None:
        key_set = set(keys)
        if not key_set:
            return
        # 简化实现：按整表重置处理（保持行序）。
        self.set_rows([r for r in self._rows if self._key_of(r) not in key_set])

    def clear_rows(self) -> None:
        self.set_rows([])

    # -- 查询 -------------------------------------------------------------------

    def row_at(self, index: int) -> Any | None:
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def row_for_key(self, key: str) -> Any | None:
        idx = self._row_by_key.get(key)
        return self._rows[idx] if idx is not None and idx < len(self._rows) else None

    def index_for_key(self, key: str) -> QModelIndex:
        idx = self._row_by_key.get(key)
        if idx is None or idx >= len(self._rows):
            return QModelIndex()
        return self.index(idx, 0)

    def key_for_index(self, index: QModelIndex) -> str | None:
        if not index.isValid():
            return None
        row = self.row_at(index.row())
        return self._key_of(row) if row is not None else None

    def all_keys(self) -> list[str]:
        return [self._key_of(r) for r in self._rows]

    def __len__(self) -> int:
        return len(self._rows)

    def refresh_display(self) -> None:
        """主题切换后重取前景/字体 token（配合 style.repolish_all 之后调用）。"""
        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 0), self.index(len(self._rows) - 1, len(self._columns) - 1)
        )

    def _reindex(self) -> None:
        self._row_by_key = {self._key_of(r): i for i, r in enumerate(self._rows)}


class StableSelection:
    """跨模型重置保持选择：按稳定键存取（view 选择由调用方应用）。

    用法::

        sel = StableSelection(table_view)
        keys = sel.capture()          # refresh 前
        model.set_rows(new_rows)
        sel.restore(keys)             # 键仍存在的行恢复选中
    """

    def __init__(self, view: QAbstractItemView) -> None:
        self._view = view

    def capture(self) -> list[str]:
        model = self._view.model()
        if model is None:
            return []
        keys: list[str] = []
        for index in self._view.selectionModel().selectedRows() if isinstance(
            self._view, QTableView
        ) else self._view.selectionModel().selectedIndexes():
            key = _model_key(model, index)
            if key is not None and key not in keys:
                keys.append(key)
        return keys

    def restore(self, keys: Sequence[str], *, current_key: str | None = None) -> None:
        model = self._view.model()
        if model is None:
            return
        selection_model = self._view.selectionModel()
        selection_model.clearSelection()
        first_index: QModelIndex | None = None
        for key in keys:
            index = _model_index_for_key(model, key)
            if index.isValid():
                selection_model.select(
                    index,
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                if first_index is None:
                    first_index = index
        current = _model_index_for_key(model, current_key) if current_key else QModelIndex()
        if not current.isValid():
            current = first_index if first_index is not None else QModelIndex()
        if current.isValid():
            selection_model.setCurrentIndex(
                current, QItemSelectionModel.SelectionFlag.NoUpdate
            )


def _model_key(model: Any, index: QModelIndex) -> str | None:
    # ObjectTableModel 直接提供；其它模型回退 UserRole 约定。
    if isinstance(model, ObjectTableModel):
        return model.key_for_index(index)
    value = model.data(index, _ROW_KEY_ROLE)
    return str(value) if value is not None else None


def _model_index_for_key(model: Any, key: str) -> QModelIndex:
    if isinstance(model, ObjectTableModel):
        return model.index_for_key(key)
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        if model.data(index, _ROW_KEY_ROLE) == key:
            return index
    return QModelIndex()


def bind_table_defaults(view: QTableView) -> None:
    """统一表格外观（替代各页手写 table QSS 片段，01-ui-audit E3）。

    全局 QSS（tokens.build_qss）已覆盖 QTableView 底色/边框/选择态；
    这里只补齐行为默认值，不写样式表。
    """
    view.setAlternatingRowColors(True)
    view.setShowGrid(False)
    view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
    view.verticalHeader().setVisible(False)
    view.horizontalHeader().setStretchLastSection(False)
    view.horizontalHeader().setHighlightSections(False)
