"""工程资源清单表（Data 侧小表）。

V11 Model/View 迁移（goal §8 / 01-ui-audit D2）：此前 ``insertRow``-in-loop
逐格建 QTableWidgetItem 且页内重述表格 QSS（与 tokens.QSS_TEMPLATE 的
QTableView/QHeaderView 全局规则重复）。现改 ``QTableView + ObjectTableModel``
虚拟化，外观统一走全局 QSS + :func:`bind_table_defaults`；状态列着色经
``ColumnSpec.foreground_role`` 返回 token 名。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableView, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.components.states import PwbEmptyState
from paleo_workbench.ui.modelview import (
    ColumnSpec,
    ObjectTableModel,
    bind_table_defaults,
)

COLUMN_HEADERS = ["文件名", "类型", "格式", "状态", "路径"]
COLUMN_WIDTHS = [200, 100, 80, 100, 0]  # 0 = stretch


def _status_token(status: str) -> str:
    if status == "parsed":
        return "SUCCESS"
    if status == "error":
        return "ERROR_RED"
    return "TEXT_SECONDARY"


class _ResourceCellProxy:
    """Test-facing cell handle: ``item(row, col).text()`` without QTableWidgetItem."""

    def __init__(self, model, row: int, column: int) -> None:
        self._model = model
        self._row = row
        self._column = column

    def text(self) -> str:
        value = self._model.data(self._model.index(self._row, self._column))
        return "" if value is None else str(value)


class _ResourceTableView(QTableView):
    """QTableView + QTableWidget 兼容访问器（差分测试沿用 widget 式断言）。"""

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
        return _ResourceCellProxy(model, row, column)

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


class ResourceTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResourceTable")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._model = ObjectTableModel(
            columns=[
                ColumnSpec("name", COLUMN_HEADERS[0], lambda res: str(getattr(res, "name", "") or "")),
                ColumnSpec(
                    "type",
                    COLUMN_HEADERS[1],
                    lambda res: tokens.RESOURCE_LABELS.get(
                        getattr(res, "type", ""), str(getattr(res, "type", ""))
                    ),
                ),
                ColumnSpec("format", COLUMN_HEADERS[2], lambda res: str(getattr(res, "format", "") or "")),
                ColumnSpec(
                    "status",
                    COLUMN_HEADERS[3],
                    lambda res: str(getattr(res, "status", "") or ""),
                    foreground_role=lambda res: _status_token(str(getattr(res, "status", "") or "")),
                ),
                ColumnSpec("path", COLUMN_HEADERS[4], lambda res: str(getattr(res, "path", "") or "")),
            ],
            key_of=lambda res: str(
                getattr(res, "id", "") or getattr(res, "path", "") or getattr(res, "name", "")
            ),
            parent=self,
        )
        self.table = _ResourceTableView()
        self.table.setModel(self._model)
        bind_table_defaults(self.table)
        header = self.table.horizontalHeader()
        for i, w in enumerate(COLUMN_WIDTHS):
            if w > 0:
                header.resizeSection(i, w)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        # 空资源清单的统一空态（词汇与任务中心一致）。
        self._empty_state = PwbEmptyState("暂无资源", "导入数据后将在此列出工程资源。", parent=self)
        self._empty_state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_state.setParent(self.table)
        self._empty_state.hide()
        self._model.modelReset.connect(self._update_empty_state)
        self._model.rowsInserted.connect(self._update_empty_state)
        self._model.rowsRemoved.connect(self._update_empty_state)

    def update_resources(self, resources: list) -> None:
        self._model.set_rows(list(resources or []))
        self._update_empty_state()

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
