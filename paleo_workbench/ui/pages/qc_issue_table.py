from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.qc_helpers import derive_rule_result

COLUMN_HEADERS = ["检查项目", "检查说明", "结果说明", "定位"]
COLUMN_WIDTHS = [160, 0, 160, 100]  # 0 = stretch (检查说明)


class QCIssueTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("QCIssueTable")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.setAlternatingRowColors(True)
        # Inherit global QTableWidget / QHeaderView rules from tokens.QSS_TEMPLATE.
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
        self._spatial_by_rule: dict[str, list[dict]] = {}

    def update_state(self, reports: list) -> None:
        self.table.setRowCount(0)
        self._spatial_by_rule = {}
        if not reports:
            return
        report = reports[0]
        from paleo_workbench.workflow.qc import spatial_issues

        for issue in spatial_issues(getattr(report, "issues", None)):
            rule = str(issue.get("rule") or "")
            self._spatial_by_rule.setdefault(rule, []).append(issue)

        for row, rule in enumerate(report.rules):
            self.table.insertRow(row)
            description = tokens.RULE_DESCRIPTIONS.get(rule, rule)
            severity, result_text, result_color = derive_rule_result(rule, report.issues)
            spatial = self._spatial_by_rule.get(rule) or []
            if spatial:
                first = spatial[0]
                loc = first.get("feature_id") or first.get("ref") or "可定位"
                if len(spatial) > 1:
                    loc = f"{loc} (+{len(spatial) - 1})"
            else:
                loc = "—"
            items = [
                QTableWidgetItem(rule),
                QTableWidgetItem(description),
                QTableWidgetItem(result_text),
                QTableWidgetItem(str(loc)),
            ]
            for col, item in enumerate(items):
                if col == 2:
                    item.setForeground(QColor(result_color))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 28)

    def spatial_issues_for_rule(self, rule: str) -> list[dict]:
        return list(self._spatial_by_rule.get(rule) or [])
