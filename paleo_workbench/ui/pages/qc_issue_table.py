from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens

COLUMN_HEADERS = ["检查项目", "检查说明", "结果说明"]
COLUMN_WIDTHS = [160, 0, 160]  # 0 = stretch (检查说明)


class QCIssueTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("QCIssueTable")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {tokens.BG_SIDEBAR};"
            f" alternate-background-color: {tokens.BG_HEADER};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
            f" QHeaderView::section {{ background: {tokens.BG_HEADER};"
            f" font-weight: 600; font-size: 12.5px;"
            f" color: {tokens.TEXT_PRIMARY};"
            f" border: none; border-bottom: 1px solid {tokens.BORDER}; }}"
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        for i, w in enumerate(COLUMN_WIDTHS):
            if w > 0:
                header.resizeSection(i, w)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def update_state(self, reports: list) -> None:
        self.table.setRowCount(0)
        if not reports:
            return
        report = reports[0]
        issues_by_rule = {issue.get("rule"): issue for issue in report.issues}
        for row, rule in enumerate(report.rules):
            self.table.insertRow(row)
            description = tokens.RULE_DESCRIPTIONS.get(rule, rule)
            issue = issues_by_rule.get(rule)
            if issue is not None:
                severity = issue.get("severity", "warning")
                result_text = f"{tokens.QC_RESULT_LABELS[severity]} {issue.get('message', '')}"
                result_color = tokens.QC_RESULT_COLORS[severity]
            else:
                result_text = tokens.QC_RESULT_LABELS["pass"]
                result_color = tokens.SUCCESS
            items = [
                QTableWidgetItem(rule),
                QTableWidgetItem(description),
                QTableWidgetItem(result_text),
            ]
            for col, item in enumerate(items):
                if col == 2:
                    item.setForeground(QColor(result_color))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 28)
