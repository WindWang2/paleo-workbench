from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class MapTopologyIssuePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QLabel("当前没有拓扑问题")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["要素", "问题", "级别"])
        layout.addWidget(self.summary)
        layout.addWidget(self.table)

    def set_issues(self, issues: list[dict]) -> None:
        self.summary.setText(f"拓扑问题：{len(issues)}")
        self.table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            for column, key in enumerate(("feature_id", "message", "severity")):
                self.table.setItem(row, column, QTableWidgetItem(str(issue.get(key, ""))))
