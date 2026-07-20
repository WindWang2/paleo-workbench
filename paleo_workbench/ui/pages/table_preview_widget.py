from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QHeaderView, QSizePolicy, QTableWidget, QTableWidgetItem

from paleo_workbench.tokens import BORDER, FONT_FAMILY


class TablePreviewWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.auto_fit_columns = True

        self.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
                border: 1px solid {BORDER};
                border-radius: 6px;
                font-family: {FONT_FAMILY};
                color: #1e293b;
                selection-background-color: #e0f2fe;
                selection-color: #0369a1;
                outline: none;
            }}
            QTableWidget::item {{
                padding: 5px 8px;
                border-bottom: 1px solid #f1f5f9;
            }}
            QTableWidget::item:hover {{
                background-color: #f1f5f9;
            }}
            QTableWidget::item:selected {{
                background-color: #e0f2fe;
                color: #0369a1;
                font-weight: 600;
            }}
            QHeaderView::section {{
                background-color: #f1f5f9;
                color: #475569;
                padding: 6px 8px;
                font-weight: 600;
                font-size: 12px;
                border: none;
                border-bottom: 2px solid #cbd5e1;
                border-right: 1px solid #e2e8f0;
            }}
            QHeaderView::section:horizontal {{
                border-top: none;
            }}
            QHeaderView::section:vertical {{
                background-color: #f8fafc;
                color: #94a3b8;
                font-size: 11px;
                font-weight: 500;
                border-right: 1px solid #e2e8f0;
            }}
            """
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setDefaultSectionSize(28)

    def apply_settings(self, settings) -> None:
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
        self.auto_fit_columns = settings.auto_fit_columns
        mode = (
            QHeaderView.ResizeMode.ResizeToContents
            if self.auto_fit_columns
            else QHeaderView.ResizeMode.Interactive
        )
        self.horizontalHeader().setSectionResizeMode(mode)

    @staticmethod
    def _is_number(val: str) -> bool:
        if val == "NaN":
            return True
        try:
            float(val)
            return True
        except ValueError:
            return False

    def load_table(
        self,
        headers: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
    ) -> None:
        self.clear()
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(list(headers))
        self.setRowCount(len(rows))

        is_curve_def = len(headers) >= 3 and headers[0] in ("曲线", "Mnemonic")

        for row_index, row in enumerate(rows):
            self.setRowHeight(row_index, 28)
            for column_index, value in enumerate(row):
                val_str = str(value).strip() if value is not None else ""
                item = QTableWidgetItem(val_str)
                header_name = headers[column_index] if column_index < len(headers) else ""

                # 1. Depth column (DEPT / DEPTH / 深度)
                if header_name.upper() in ("DEPT", "DEPTH", "深度"):
                    item.setFont(QFont("Cascadia Code", 9, QFont.Weight.Bold))
                    item.setForeground(QColor("#1d4ed8"))
                    item.setBackground(QColor("#f0f9ff"))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                # 2. Curve mnemonic tag formatting in curve definition table
                elif is_curve_def and column_index == 0:
                    item.setFont(QFont("Cascadia Code", 9, QFont.Weight.Bold))
                    item.setForeground(QColor("#0f766e"))
                    item.setBackground(QColor("#f0fdf4"))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

                # 3. Unit column formatting
                elif is_curve_def and column_index == 1:
                    item.setFont(QFont("Cascadia Code", 9))
                    item.setForeground(QColor("#64748b"))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

                # 4. Numeric curve data formatting
                elif self._is_number(val_str):
                    item.setFont(QFont("Cascadia Code", 9))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if val_str == "NaN":
                        item.setForeground(QColor("#94a3b8"))

                self.setItem(row_index, column_index, item)

        if self.auto_fit_columns:
            self.resizeColumnsToContents()
            for col in range(self.columnCount()):
                width = max(self.columnWidth(col) + 16, 75)
                self.setColumnWidth(col, width)
