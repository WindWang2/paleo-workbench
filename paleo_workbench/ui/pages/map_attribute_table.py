from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import style, tokens
from paleo_workbench.ui.modelview.reconcile import reconcile_widget_items

# Display keys shown in the property grid (geometry summarized, not fully listed).
_DISPLAY_KEYS = ("id", "kind", "name", "text", "topology_status")

# 占位行 key（"— 未选择 —"）：与业务要素 id 空间不冲突。
_PLACEHOLDER_KEY = ""

# 可见窗口上限（V11 01-ui-audit D2 ②）：要素选择器永不全量物化 N 条
# 下拉字符串——任何时刻列表里至多出现 _MAX_VISIBLE 个匹配要素。
_MAX_VISIBLE = 500

# 选择器列表高度：约 7 行，属性格仍占面板主体。
_SELECTOR_LIST_MAX_HEIGHT = 168


class _FeatureSelectorList(QListWidget):
    """有界要素选择列表（保留旧 QComboBox 的访问面）。

    旧 ``feature_combo`` 的既有接线/测试使用 ``count()`` / ``currentData()``
    / ``findData()`` / ``itemText()`` / ``setCurrentIndex()``——QListWidget
    原生提供 ``count``/``model``（ComboSpy 的 rowsInserted/rowsRemoved
    统计继续有效），这里补齐其余 QComboBox 同名方法，宿主无需感知形态
    变化；差异仅在于条目数被可见窗口截断（结构性上限，而非行为变化）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

    def currentData(self, role: int = Qt.ItemDataRole.UserRole):
        item = self.currentItem()
        return None if item is None else item.data(role)

    def findData(self, data, role: int = Qt.ItemDataRole.UserRole) -> int:
        for row in range(self.count()):
            if self.item(row).data(role) == data:
                return row
        return -1

    def itemText(self, row: int) -> str:
        item = self.item(row)
        return "" if item is None else item.text()

    def setCurrentIndex(self, row: int) -> None:  # noqa: N802 — QComboBox 兼容
        self.setCurrentRow(row)


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

        # 要素选择器（V11 D2 ②）：搜索框 + 有界列表 + 计数脚注。旧实现是
        # 一个每要素一条的 QComboBox（10 万要素图层下 filter/sort 全量重灌）
        # ——现在只物化“匹配 + 排序 + 置顶选中”后的前 _MAX_VISIBLE 条。
        self.feature_search = QLineEdit(self)
        self.feature_search.setObjectName("MapAttributeFeatureSearch")
        self.feature_search.setPlaceholderText("搜索要素…")
        self.feature_search.setClearButtonEnabled(True)
        layout.addWidget(self.feature_search)

        self.feature_combo = _FeatureSelectorList(self)
        self.feature_combo.setObjectName("MapAttributeFeatureSelector")
        self.feature_combo.setToolTip("活动图层要素选择（输入过滤；列表有界显示前 500 项）")
        self.feature_combo.setMaximumHeight(_SELECTOR_LIST_MAX_HEIGHT)
        layout.addWidget(self.feature_combo)

        self._feature_count_label = QLabel("", self)
        self._feature_count_label.setObjectName("MapAttributeFootnote")
        style.bind(
            self._feature_count_label,
            lambda: (
                f"color: {style.palette()['TEXT_SECONDARY']};"
                f" font-size: {tokens.FONT_SIZE_STATUS};"
            ),
        )
        self._feature_count_label.hide()
        layout.addWidget(self._feature_count_label)

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
        # V11：用户在搜索框输入的过滤词（与宿主 field filter 正交叠加）。
        self._search_needle: str = ""
        # V11：搜索防抖（评审 P1-1：全量过滤扫描不逐键执行）。
        from PySide6.QtCore import QTimer

        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(200)
        self._search_debounce.timeout.connect(self._apply_search_now)
        self.table.itemChanged.connect(self._on_item_changed)
        self.feature_combo.currentItemChanged.connect(self._on_feature_selected)
        self.feature_search.textChanged.connect(self._on_search_changed)
        # 初始占位行（构造期不发出选择信号——旧空 QComboBox 同语义）。
        self._suppress_feature_selection = True
        try:
            self._refresh_selector()
        finally:
            self._suppress_feature_selection = False

    # -- 可见窗口 ---------------------------------------------------------------

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
        search = self._search_needle.strip().lower()
        if search:
            # 搜索框按“下拉展示文本 + 要素 id”过滤（D2 ②：输入过滤收窄
            # 可见窗口，不触碰宿主侧的 field filter）。
            def _matches_search(feature_id: str) -> bool:
                label = self._combo_label(self._layer_features[feature_id], feature_id)
                return search in label.lower() or search in feature_id.lower()

            ids = [fid for fid in ids if _matches_search(fid)]
        if self._sort_field:
            def _sort_key(feature_id: str) -> str:
                feature = self._layer_features[feature_id]
                props = feature.get("properties") or {}
                value = props.get(self._sort_field, feature.get(self._sort_field))
                return str(value or "")

            ids.sort(key=_sort_key)
        return ids

    def _selector_keys(self, visible: list[str], pin_id: str | None = None) -> list[str]:
        """占位行 + 置顶选中 + 过滤/排序窗口（截断到 _MAX_VISIBLE）。"""
        pin = self._feature_id if pin_id is None else pin_id
        window = list(visible)
        if pin in window:
            # 最新选中的要素始终排在窗口首位——大图层下选中即“跳”到顶部，
            # 不必在 500 条里翻找。首次绑定时即以目标选中置顶，后续同键
            # 绑定零结构操作（保住 C-P0-3 的差量语义）。
            window.remove(pin)
            window.insert(0, pin)
        return [_PLACEHOLDER_KEY] + window[:_MAX_VISIBLE]

    def _make_feature_item(self, key: str) -> QListWidgetItem:
        if not key:
            return QListWidgetItem("— 未选择 —")
        feature = self._layer_features.get(key)
        label = self._combo_label(feature, key) if feature is not None else key
        return QListWidgetItem(label)

    def _update_feature_item(self, item: QListWidgetItem, key: str) -> None:
        if not key:
            if item.text() != "— 未选择 —":
                item.setText("— 未选择 —")
            item.setData(Qt.ItemDataRole.UserRole, "")
            return
        item.setData(Qt.ItemDataRole.UserRole, key)
        feature = self._layer_features.get(key)
        if feature is None:
            return  # 已被过滤/解绑的键——reconcile 随后会移除
        label = self._combo_label(feature, key)
        if item.text() != label:
            item.setText(label)

    def _refresh_selector(self, pin_id: str | None = None) -> None:
        """把可见窗口同步进选择器列表（调用方负责选择抑制）。

        键差分（reconcile_widget_items）：要素 id 集/顺序不变时零结构
        操作，仅原地刷新标签——与旧“same-ids 只改标签”差量路径同语义；
        截断保证列表条目数有界，10 万要素图层也只建 ≤ _MAX_VISIBLE 条。
        """
        visible = self._visible_feature_ids()
        keys = self._selector_keys(visible, pin_id)
        reconcile_widget_items(
            self.feature_combo,
            keys,
            make_item=self._make_feature_item,
            update_item=self._update_feature_item,
        )
        # 当前选中行：仍可见则落在置顶行；否则回落占位行（不清属性格——
        # 仅 apply_filter 的显式清选路径会 set_feature(None)+emit("")）。
        current = pin_id if pin_id is not None else self._feature_id
        row = self.feature_combo.findData(current) if current else -1
        self.feature_combo.setCurrentRow(max(0, row))
        if len(visible) > _MAX_VISIBLE:
            self._feature_count_label.setText(
                f"共 {len(visible)} 个要素，显示前 {_MAX_VISIBLE}，输入过滤…"
            )
            self._feature_count_label.show()
        else:
            self._feature_count_label.hide()

    def _on_search_changed(self, text: str) -> None:
        self._search_needle = str(text or "")
        # 评审 P1-1：过滤是全量 O(n) 扫描（10 万要素层每次击键 100ms+）——
        # 200ms 防抖（与 TagManagerDialog 同口径）。
        self._search_debounce.start()

    def _apply_search_now(self) -> None:
        self._suppress_feature_selection = True
        try:
            self._refresh_selector()
        finally:
            self._suppress_feature_selection = False

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
        try:
            self._refresh_selector(pin_id=selected)
        finally:
            self._suppress_feature_selection = False
        if selected not in visible:
            self.set_feature(None)
            # the previously selected feature is now hidden — the map must
            # drop its highlight too, or host and grid diverge (review R3-P3)
            self.feature_selection_requested.emit("")
            return visible
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
        self._layer_features = new_features
        self._suppress_feature_selection = True
        try:
            # 键差分统一了旧的“same-ids 只刷标签 / id 集变化全量重灌”两条
            # 路径：id 序不变时零结构操作（C-P0-3 语义保持）。置顶键用
            # 本次目标选中（而非旧的 _feature_id），保证连续同键绑定的
            # 窗口顺序一致、零结构操作。
            self._refresh_selector(pin_id=selected)
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
        记录与（可见窗口内的）下拉标签，绝不重建条目。未绑定的 id 忽略
        ——id 集变化必须走 ``set_layer_features`` 全量路径。
        """
        for feature in features:
            if not isinstance(feature, dict):
                continue
            feature_id = str(feature.get("id") or "")
            if not feature_id or feature_id not in self._layer_features:
                continue
            self._layer_features[feature_id] = dict(feature)
        self._suppress_feature_selection = True
        try:
            self._refresh_selector()
        finally:
            self._suppress_feature_selection = False
        self.set_selected_ids(selected_ids)

    def set_selected_ids(
        self, selected_ids: set[str] | tuple[str, ...] | list[str],
    ) -> None:
        """Move the selector/feature selection without rebuilding feature entries.

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
        try:
            if self.feature_combo.findData(selected) < 0:
                # 选中要素不在当前可见窗口（被过滤/截断）——重排窗口置顶；
                # 列表条目仍受 _MAX_VISIBLE 约束。
                self._refresh_selector(pin_id=selected)
            row = self.feature_combo.findData(selected)
            self.feature_combo.setCurrentRow(max(0, row))
        finally:
            self._suppress_feature_selection = False
        self.set_feature(self._layer_features.get(selected))

    def _on_feature_selected(self, current, _previous) -> None:
        if self._suppress_feature_selection or current is None:
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
