from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QHeaderView, QSizePolicy, QTableWidget, QTableWidgetItem

from paleo_workbench.ui import tokens


class TablePreviewWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.auto_fit_columns = True

        # The global QSS (tokens.build_qss) already styles QTableWidget
        # (background, border, radius, gridline, selection) and QHeaderView::section.
        # We only add the alternating-row tint here, since
        # setAlternatingRowColors(True) is enabled and the global sheet has no
        # alternate-background-color rule.
        self.setStyleSheet(
            f"""
            QTableWidget {{
                alternate-background-color: {tokens.BG_SEARCH};
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
                    item.setForeground(QColor(tokens.PRIMARY))
                    item.setBackground(QColor(tokens.BG_SELECTION))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                # 2. Curve mnemonic tag formatting in curve definition table
                elif is_curve_def and column_index == 0:
                    item.setFont(QFont("Cascadia Code", 9, QFont.Weight.Bold))
                    item.setForeground(QColor(tokens.TEAL))
                    item.setBackground(QColor(tokens.BG_SEARCH))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

                # 3. Unit column formatting
                elif is_curve_def and column_index == 1:
                    item.setFont(QFont("Cascadia Code", 9))
                    item.setForeground(QColor(tokens.TEXT_SECONDARY))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

                # 4. Numeric curve data formatting
                elif self._is_number(val_str):
                    item.setFont(QFont("Cascadia Code", 9))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if val_str == "NaN":
                        item.setForeground(QColor(tokens.PRIMARY_DISABLED))

                self.setItem(row_index, column_index, item)

        if self.auto_fit_columns:
            self.resizeColumnsToContents()
            for col in range(self.columnCount()):
                width = max(self.columnWidth(col) + 16, 75)
                self.setColumnWidth(col, width)
