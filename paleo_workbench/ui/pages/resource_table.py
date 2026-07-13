from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens

COLUMN_HEADERS = ["文件名", "类型", "格式", "状态", "路径"]
COLUMN_WIDTHS = [200, 100, 80, 100, 0]  # 0 = stretch


class ResourceTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResourceTable")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {tokens.BG_SIDEBAR};"
            f" alternate-background-color: {tokens.BG_HEADER};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
            f" QHeaderView::section {{ background: {tokens.BG_HEADER};"
            f" font-weight: 600; font-size: {tokens.FONT_SIZE_BASE};"
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

    def update_resources(self, resources: list) -> None:
        self.table.setRowCount(0)
        for row, res in enumerate(resources):
            self.table.insertRow(row)
            type_label = tokens.RESOURCE_LABELS.get(res.type, res.type)
            status_text = res.status
            status_color = tokens.SUCCESS if res.status == "parsed" else tokens.TEXT_SECONDARY
            if res.status == "error":
                status_color = tokens.ERROR_RED
            items = [
                QTableWidgetItem(res.name),
                QTableWidgetItem(type_label),
                QTableWidgetItem(res.format),
                QTableWidgetItem(status_text),
                QTableWidgetItem(res.path),
            ]
            for col, item in enumerate(items):
                if col == 3:
                    item.setForeground(QColor(status_color))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 28)
