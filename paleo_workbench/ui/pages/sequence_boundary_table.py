from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.sequence_helpers import field_value


class SequenceBoundaryTable(QFrame):
    """Center panel listing sequence boundary names for the active horizon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SequenceBoundaryTable")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("层序界面清单")
        self.title_label.setObjectName("MapDockTitle")
        layout.addWidget(self.title_label)

        self.empty_label = QLabel("未配置层序界面")
        self.empty_label.setObjectName("EmptyStateLabel")
        layout.addWidget(self.empty_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["界面", "目标层位", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        # Inherit global QTableWidget / QHeaderView rules from tokens.QSS_TEMPLATE.
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

    def update_state(self, stratigraphy) -> None:
        boundaries = field_value(stratigraphy, "sequence_boundaries", []) or []
        target = field_value(stratigraphy, "target_horizon", "") or "未设置"

        self.table.setRowCount(len(boundaries))
        self.empty_label.setHidden(bool(boundaries))
        for row, boundary in enumerate(boundaries):
            self.table.setItem(row, 0, QTableWidgetItem(str(boundary)))
            self.table.setItem(row, 1, QTableWidgetItem(target))
            self.table.setItem(row, 2, QTableWidgetItem(f"第 {row + 1} 层序界面"))
