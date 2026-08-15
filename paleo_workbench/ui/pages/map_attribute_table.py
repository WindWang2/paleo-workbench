from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens

# Display keys shown in the property grid (geometry summarized, not fully listed).
_DISPLAY_KEYS = ("id", "kind", "name", "text", "topology_status")


class MapAttributeTable(QFrame):
    """Bottom property grid for the selected map feature."""

    property_changed = Signal(str, str, object)  # feature_id, key, value
    feature_selection_requested = Signal(str)  # authoritative feature id, or "" to clear

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapAttributeTable")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.SPACE_2,
            tokens.PANEL_PADDING,
            tokens.SPACE_2,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("属性")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.feature_combo = QComboBox(self)
        self.feature_combo.setObjectName("MapAttributeFeatureSelector")
        self.feature_combo.setToolTip("Active-layer feature selection")
        layout.addWidget(self.feature_combo)

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
        layout.addWidget(self.table, 1)

        self._feature: dict[str, Any] | None = None
        self._feature_id: str = ""
        self._layer_features: dict[str, dict[str, Any]] = {}
        self._suppress_item_changed = False
        self._suppress_feature_selection = False
        self.table.itemChanged.connect(self._on_item_changed)
        self.feature_combo.currentIndexChanged.connect(self._on_feature_selected)

    def set_feature(self, feature: dict[str, Any] | None) -> None:
        self._feature = dict(feature) if feature is not None else None
        self._feature_id = str((feature or {}).get("id") or "")
        self._rebuild()

    def set_layer_features(
        self, features: list[dict[str, Any]] | tuple[dict[str, Any], ...], *, selected_ids: set[str] | tuple[str, ...] = (),
    ) -> None:
        """Bind the property grid to one active vector layer without edit shadow state."""
        self._layer_features = {
            str(feature.get("id") or ""): dict(feature)
            for feature in features
            if isinstance(feature, dict) and str(feature.get("id") or "")
        }
        selected = next(iter(sorted(str(value) for value in selected_ids)), "")
        if selected not in self._layer_features:
            selected = ""
        self._suppress_feature_selection = True
        self.feature_combo.clear()
        self.feature_combo.addItem("— no selection —", "")
        for feature_id, feature in self._layer_features.items():
            label = str(feature.get("name") or feature.get("text") or feature_id)
            self.feature_combo.addItem(label, feature_id)
        target = self.feature_combo.findData(selected)
        self.feature_combo.setCurrentIndex(max(0, target))
        self._suppress_feature_selection = False
        self.set_feature(self._layer_features.get(selected))

    def set_selected_ids(
        self, selected_ids: set[str] | tuple[str, ...] | list[str],
    ) -> None:
        """Move the combo/feature selection without rebuilding feature entries.

        The property grid is keyed to the feature list bound by the last
        ``set_layer_features`` call; this keeps selection-only updates O(1)
        instead of re-converting every feature record.
        """
        if not self._layer_features:
            return
        selected = next(iter(sorted(str(value) for value in selected_ids)), "")
        if selected not in self._layer_features:
            selected = ""
        self._suppress_feature_selection = True
        target = self.feature_combo.findData(selected)
        self.feature_combo.setCurrentIndex(max(0, target))
        self._suppress_feature_selection = False
        self.set_feature(self._layer_features.get(selected))

    def _on_feature_selected(self, _index: int) -> None:
        if self._suppress_feature_selection:
            return
        feature_id = str(self.feature_combo.currentData() or "")
        self.feature_selection_requested.emit(feature_id)

    def _rebuild(self) -> None:
        self._suppress_item_changed = True
        self.table.setRowCount(0)
        if not self._feature:
            self._suppress_item_changed = False
            return

        rows: list[tuple[str, str, bool]] = []
        for key in _DISPLAY_KEYS:
            if key not in self._feature and key not in {"text", "topology_status"}:
                continue
            if key == "text" and "text" not in self._feature:
                continue
            if key == "topology_status" and "topology_status" not in self._feature:
                continue
            value = self._feature.get(key, "")
            if key == "topology_status":
                # Friendlier display for topology warnings.
                display = "警告" if value == "warning" else str(value or "ok")
                rows.append((key, display, False))
                continue
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
