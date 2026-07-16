from __future__ import annotations

from PySide6.QtCore import Signal
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

    boundary_activated = Signal(str)  # double-click / Enter → set as target

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

        self.empty_label = QLabel("未配置层序界面（双击行可设为目标层位）")
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
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.table, 1)

    def _on_item_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        name_item = self.table.item(row, 0)
        if name_item is not None and name_item.text().strip():
            self.boundary_activated.emit(name_item.text().strip())

    def update_state(self, stratigraphy) -> None:
        boundaries = field_value(stratigraphy, "sequence_boundaries", []) or []
        target = field_value(stratigraphy, "target_horizon", "") or "未设置"

        self.table.setRowCount(len(boundaries))
        self.empty_label.setHidden(bool(boundaries))
        for row, boundary in enumerate(boundaries):
            self.table.setItem(row, 0, QTableWidgetItem(str(boundary)))
            self.table.setItem(row, 1, QTableWidgetItem(target))
            note = "当前目标" if str(boundary) == str(target) else f"第 {row + 1} 层序界面"
            self.table.setItem(row, 2, QTableWidgetItem(note))
