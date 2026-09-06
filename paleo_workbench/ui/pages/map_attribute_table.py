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
        # M8: field-based filter + sort state over the bound layer.
        self._filter_field: str = ""
        self._filter_needle: str = ""
        self._sort_field: str = ""
        self.table.itemChanged.connect(self._on_item_changed)
        self.feature_combo.currentIndexChanged.connect(self._on_feature_selected)

    def _visible_feature_ids(self) -> list[str]:
        """Feature ids surviving the current filter, in current sort order."""
        ids = list(self._layer_features)
        field, needle = self._filter_field, self._filter_needle.strip().lower()
        if field and needle:
            def _matches(feature_id: str) -> bool:
                feature = self._layer_features[feature_id]
                props = feature.get("properties") or {}
                value = props.get(field, feature.get(field))
                return needle in str(value or "").lower()

            ids = [fid for fid in ids if _matches(fid)]
        if self._sort_field:
            def _sort_key(feature_id: str) -> str:
                feature = self._layer_features[feature_id]
                props = feature.get("properties") or {}
                value = props.get(self._sort_field, feature.get(self._sort_field))
                return str(value or "")

            ids.sort(key=_sort_key)
        return ids

    def apply_filter(self, *, field: str = "", needle: str = "") -> list[str]:
        """Restrict the feature selector to features matching a field substring.

        Empty *field*/*needle* clears the filter. Case-insensitive substring
        over ``properties[field]`` (falling back to the top-level key). The
        current selection survives when it still matches; returns the visible
        ids so hosts can mirror the filter to map highlighting.
        """
        self._filter_field = str(field or "")
        self._filter_needle = str(needle or "")
        visible = self._visible_feature_ids()
        selected = str(self.feature_combo.currentData() or "")
        self._suppress_feature_selection = True
        self.feature_combo.clear()
        self.feature_combo.addItem("— no selection —", "")
        for feature_id in visible:
            feature = self._layer_features[feature_id]
            self.feature_combo.addItem(self._combo_label(feature, feature_id), feature_id)
        if selected in visible:
            self.feature_combo.setCurrentIndex(
                max(0, self.feature_combo.findData(selected))
            )
        else:
            self.feature_combo.setCurrentIndex(0)
            self._suppress_feature_selection = False
            self.set_feature(None)
            # the previously selected feature is now hidden — the map must
            # drop its highlight too, or host and grid diverge (review R3-P3)
            self.feature_selection_requested.emit("")
            return visible
        self._suppress_feature_selection = False
        return visible

    def sort_features(self, field: str = "") -> list[str]:
        """Sort the selector by a property field ("" restores bind order)."""
        self._sort_field = str(field or "")
        visible = self.apply_filter(
            field=self._filter_field, needle=self._filter_needle
        )
        return visible

    def set_feature(self, feature: dict[str, Any] | None) -> None:
        self._feature = dict(feature) if feature is not None else None
        self._feature_id = str((feature or {}).get("id") or "")
        self._rebuild()

    @staticmethod
    def _combo_label(feature: dict[str, Any], feature_id: str) -> str:
        return str(feature.get("name") or feature.get("text") or feature_id)

    def _refill_feature_combo(self) -> None:
        """清空并重灌要素下拉（placeholder + 全部绑定要素）。"""
        self.feature_combo.clear()
        self.feature_combo.addItem("— no selection —", "")
        for feature_id, feature in self._layer_features.items():
            self.feature_combo.addItem(self._combo_label(feature, feature_id), feature_id)

    def _refresh_combo_labels(self) -> None:
        """要素 id 集不变时下拉条目标签的就地刷新（不增删条目）。"""
        combo = self.feature_combo
        for index in range(combo.count()):
            feature_id = str(combo.itemData(index) or "")
            feature = self._layer_features.get(feature_id)
            if feature is None:
                continue  # placeholder 或已被过滤隐藏的条目
            label = self._combo_label(feature, feature_id)
            if combo.itemText(index) != label:
                combo.setItemText(index, label)

    def set_layer_features(
        self, features: list[dict[str, Any]] | tuple[dict[str, Any], ...], *, selected_ids: set[str] | tuple[str, ...] = (),
    ) -> None:
        """Bind the property grid to one active vector layer without edit shadow state."""
        new_features = {
            str(feature.get("id") or ""): dict(feature)
            for feature in features
            if isinstance(feature, dict) and str(feature.get("id") or "")
        }
        selected = next(iter(sorted(str(value) for value in selected_ids)), "")
        if selected not in new_features:
            selected = ""
        # 差量路径（C-P0-3）：要素 id 序列不变（纯属性编辑）时不清空重灌
        # 下拉——只原地刷新条目标签；id 集或顺序变化（图层切换 / 增删
        # 要素）仍走全量重灌。
        same_ids = list(new_features) == list(self._layer_features)
        self._layer_features = new_features
        self._suppress_feature_selection = True
        try:
            if same_ids:
                self._refresh_combo_labels()
            else:
                self._refill_feature_combo()
            target = self.feature_combo.findData(selected)
            self.feature_combo.setCurrentIndex(max(0, target))
        finally:
            self._suppress_feature_selection = False
        self.set_feature(self._layer_features.get(selected))

    def update_layer_features(
        self,
        features: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        selected_ids: set[str] | tuple[str, ...] | list[str] = (),
    ) -> None:
        """差量更新已绑定要素的记录（要素 id 集不变；C-P0-3）。

        宿主经编辑会话日志定位受影响要素后调用：只刷新这些要素的绑定
        记录、下拉标签与（若选中）属性格，绝不 clear/重灌下拉。未绑定
        的 id 忽略——id 集变化必须走 ``set_layer_features`` 全量路径。
        """
        combo = self.feature_combo
        for feature in features:
            if not isinstance(feature, dict):
                continue
            feature_id = str(feature.get("id") or "")
            if not feature_id or feature_id not in self._layer_features:
                continue
            self._layer_features[feature_id] = dict(feature)
            index = combo.findData(feature_id)
            if index < 0:
                continue
            label = self._combo_label(feature, feature_id)
            if combo.itemText(index) != label:
                combo.setItemText(index, label)
        self.set_selected_ids(selected_ids)

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
