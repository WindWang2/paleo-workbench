from __future__ import annotations

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class MapTopologyIssuePanel(QWidget):
    locate_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QLabel("当前没有拓扑问题")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["要素", "问题", "级别"])
        layout.addWidget(self.summary)
        layout.addWidget(self.table)
        self._issues: list[dict] = []
        self.table.activated.connect(self._on_row_activated)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)

    def _on_item_double_clicked(self, item: QTableWidgetItem) -> None:
        if item is not None:
            idx = self.table.model().index(item.row(), item.column())
            self._on_row_activated(idx)

    def set_issues(self, issues: list[dict]) -> None:
        self._issues = list(issues)
        self.summary.setText(f"拓扑问题：{len(issues)}")
        self.table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            for column, key in enumerate(("feature_id", "message", "severity")):
                self.table.setItem(row, column, QTableWidgetItem(str(issue.get(key, ""))))

    def _on_row_activated(self, index: QModelIndex) -> None:
        """Double-click / Enter on a row asks to locate its feature."""
        row = index.row()
        if not 0 <= row < len(self._issues):
            return
        feature_id = str(self._issues[row].get("feature_id", "") or "")
        if feature_id:
            self.locate_requested.emit(feature_id)
