from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens

# Display keys shown in the property grid (geometry summarized, not fully listed).
_DISPLAY_KEYS = ("id", "kind", "name", "text")


class MapAttributeTable(QFrame):
    """Bottom property grid for the selected map feature."""

    property_changed = Signal(str, str, object)  # feature_id, key, value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapAttributeTable")
        self.setStyleSheet(
            f"QFrame#MapAttributeTable {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        title = QLabel("属性")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(title)

        self.table = QTableWidget(0, 2)
        self.table.setObjectName("MapAttributeTableWidget")
        self.table.setHorizontalHeaderLabels(["属性", "值"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setStyleSheet(
            f"QTableWidget {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; }}"
        )
        layout.addWidget(self.table, 1)

        self._feature: dict[str, Any] | None = None
        self._feature_id: str = ""
        self._suppress_item_changed = False
        self.table.itemChanged.connect(self._on_item_changed)

    def set_feature(self, feature: dict[str, Any] | None) -> None:
        self._feature = dict(feature) if feature is not None else None
        self._feature_id = str((feature or {}).get("id") or "")
        self._rebuild()

    def _rebuild(self) -> None:
        self._suppress_item_changed = True
        self.table.setRowCount(0)
        if not self._feature:
            self._suppress_item_changed = False
            return

        rows: list[tuple[str, str, bool]] = []
        for key in _DISPLAY_KEYS:
            if key not in self._feature and key != "text":
                continue
            if key == "text" and "text" not in self._feature:
                continue
            value = self._feature.get(key, "")
            editable = key in {"name", "text"}
            rows.append((key, "" if value is None else str(value), editable))

        coords = self._feature.get("coordinates")
        if coords is not None:
            rows.append(("geometry", self._geometry_summary(coords), False))

        self.table.setRowCount(len(rows))
        for row, (key, value, editable) in enumerate(rows):
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            value_item = QTableWidgetItem(value)
            if not editable:
                value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            value_item.setData(Qt.ItemDataRole.UserRole, key)
            self.table.setItem(row, 0, key_item)
            self.table.setItem(row, 1, value_item)

        self._suppress_item_changed = False

    @staticmethod
    def _geometry_summary(coords: Any) -> str:
        if not isinstance(coords, (list, tuple)):
            return str(coords)
        if not coords:
            return "empty"
        first = coords[0]
        if isinstance(first, (list, tuple)):
            return f"{len(coords)} pts"
        if len(coords) >= 2:
            return f"({coords[0]}, {coords[1]})"
        return str(coords)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suppress_item_changed:
            return
        if item.column() != 1:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key or not self._feature_id:
            return
        value = item.text()
        if self._feature is not None:
            self._feature[str(key)] = value
        self.property_changed.emit(self._feature_id, str(key), value)
