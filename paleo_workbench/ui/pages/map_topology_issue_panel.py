"""编图工作台底部「拓扑问题」面板。

V11 Model/View 迁移（goal §8 / 01-ui-audit D2）：问题表改
``QTableView + ObjectTableModel``——拓扑检查可产生无上限条目，此前
setItemCount+setItem 逐格重建；行为对象为 issue dict，列取值即
``issue.get(key)``。无问题时表上覆盖统一空态（词汇与任务中心一致）。
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import QLabel, QTableView, QVBoxLayout, QWidget

from paleo_workbench.ui.components.states import PwbEmptyState
from paleo_workbench.ui.modelview import (
    ColumnSpec,
    ObjectTableModel,
    bind_table_defaults,
)


class _TopologyCellProxy:
    """Test-facing cell handle（row/column/text），无 QTableWidgetItem。"""

    def __init__(self, model, row: int, column: int) -> None:
        self._model = model
        self._row = row
        self._column = column

    def row(self) -> int:
        return self._row

    def column(self) -> int:
        return self._column

    def text(self) -> str:
        value = self._model.data(self._model.index(self._row, self._column))
        return "" if value is None else str(value)


class _TopologyTableView(QTableView):
    """QTableView + QTableWidget 兼容访问器（双击信号/单元格定位）。"""

    # QTableWidget 兼容信号：测试与调用方仍按 (row, column)/(item) 语义驱动。
    itemDoubleClicked = Signal(object)

    def rowCount(self) -> int:  # noqa: N802
        model = self.model()
        return 0 if model is None else model.rowCount()

    def item(self, row: int, column: int):
        model = self.model()
        if model is None:
            return None
        if row < 0 or column < 0 or row >= model.rowCount() or column >= model.columnCount():
            return None
        return _TopologyCellProxy(model, row, column)

    def setCurrentCell(self, row: int, column: int) -> None:  # noqa: N802
        model = self.model()
        if model is None:
            return
        self.setCurrentIndex(model.index(row, column))

    def _emit_item_double_clicked(self, index: QModelIndex) -> None:
        self.itemDoubleClicked.emit(self.item(index.row(), index.column()))


class MapTopologyIssuePanel(QWidget):
    locate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QLabel("当前没有拓扑问题")
        self._issues: list[dict] = []
        self._model = ObjectTableModel(
            columns=[
                ColumnSpec("feature_id", "要素", lambda pair: str(pair[1].get("feature_id", "") or "")),
                ColumnSpec("message", "问题", lambda pair: str(pair[1].get("message", "") or "")),
                ColumnSpec("severity", "级别", lambda pair: str(pair[1].get("severity", "") or "")),
            ],
            key_of=lambda pair: pair[0],
            parent=self,
        )
        self.table = _TopologyTableView()
        self.table.setModel(self._model)
        bind_table_defaults(self.table)
        layout.addWidget(self.summary)
        layout.addWidget(self.table)

        self._empty_state = PwbEmptyState("未发现拓扑问题", "图幅拓扑检查通过。", parent=self)
        self._empty_state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_state.setParent(self.table)
        self._empty_state.hide()
        self._model.modelReset.connect(self._update_empty_state)
        self._model.rowsInserted.connect(self._update_empty_state)
        self._model.rowsRemoved.connect(self._update_empty_state)

        self.table.activated.connect(self._on_row_activated)
        self.table.doubleClicked.connect(self.table._emit_item_double_clicked)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._update_empty_state()

    def _on_item_double_clicked(self, item) -> None:
        if item is not None:
            index = self._model.index(item.row(), item.column())
            self._on_row_activated(index)

    def set_issues(self, issues: list[dict]) -> None:
        self._issues = list(issues)
        self.summary.setText(f"拓扑问题：{len(issues)}")
        # 行对象包一层 (稳定键, issue)：issue dict 无业务 id，键由确定性
        # 序号+要素 id 构成，重复 set_issues 走 set_rows 差分路径。
        self._model.set_rows(
            [
                (f"{i}:{issue.get('feature_id', '')}", issue)
                for i, issue in enumerate(self._issues)
            ]
        )

    def _on_row_activated(self, index: QModelIndex) -> None:
        """Double-click / Enter on a row asks to locate its feature."""
        row = index.row()
        if not 0 <= row < len(self._issues):
            return
        feature_id = str(self._issues[row].get("feature_id", "") or "")
        if feature_id:
            self.locate_requested.emit(feature_id)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._empty_state.isVisible():
            self._empty_state.setGeometry(self.table.viewport().rect())

    def _update_empty_state(self, *_args) -> None:
        if self._model.rowCount() == 0:
            self._empty_state.setGeometry(self.table.viewport().rect())
            self._empty_state.show()
            self._empty_state.raise_()
        else:
            self._empty_state.hide()
