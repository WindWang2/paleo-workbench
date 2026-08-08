from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.asset_table_model import (
    RESOURCE_TYPE_LABELS,
    AssetTableModel,
)
from paleo_workbench.ui.pages.data_table_columns import (
    COLUMN_BY_KEY,
    COLUMN_DEFINITIONS,
    DEFAULT_COLUMN_KEYS,
    HEADERS,
)
from paleo_workbench.ui.pages.data_view_models import AssetView
from paleo_workbench.ui.pages.filter_index import (
    ISSUE_STATUSES,
    REFERENCE_TYPES,
    FilterIndex,
    FilterQuery,
)

__all__ = [
    "COLUMN_BY_KEY",
    "COLUMN_DEFINITIONS",
    "DEFAULT_COLUMN_KEYS",
    "HEADERS",
    "ISSUE_STATUSES",
    "REFERENCE_TYPES",
    "RESOURCE_TYPE_LABELS",
    "DataAssetTable",
]


class DataAssetTable(QWidget):
    selected_asset_changed = Signal(object)
    selected_assets_changed = Signal(list)
    context_menu_requested = Signal(QPoint, object)  # (global_pos, asset or list of assets)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataAssetTable")
        self._resources: list[ResourceItem] = []
        self._artifacts: list[ExportArtifact] = []
        self._visible_assets: list[object] = []
        self._selected_asset: object | None = None
        self._selected_assets: list[object] = []
        self._filter_query = FilterQuery(node_type="all")
        self._search_text = ""
        self._visible_column_keys = list(DEFAULT_COLUMN_KEYS)
        self.column_actions: dict[str, QAction] = {}
        self._syncing_column_actions = False
        self._index = FilterIndex()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_2)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addStretch()
        self.column_settings_btn = QPushButton("列设置")
        self.column_settings_btn.setObjectName("SecondaryButton")
        self.column_settings_menu = QMenu(self.column_settings_btn)
        self._build_column_settings_menu()
        self.column_settings_btn.setMenu(self.column_settings_menu)
        toolbar.addWidget(self.column_settings_btn)
        layout.addLayout(toolbar)

        self.model = AssetTableModel(self)
        self.model.set_column_keys(self._visible_column_keys)
        self.table = QTableView()
        self.table.setObjectName("DataAssetGrid")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableView#DataAssetGrid {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; gridline-color: {tokens.BORDER}; }}"
        )
        self.table.selectionModel().selectionChanged.connect(self._emit_selection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.table)

    def update_assets(
        self,
        resources: list[ResourceItem],
        artifacts: list[ExportArtifact],
    ) -> None:
        self._resources = list(resources)
        self._artifacts = list(artifacts)
        assets: list[object] = [*self._resources, *self._artifacts]
        self._index.rebuild(assets)
        self._filter_query.search_text = self._search_text
        filtered = self._index.filter_query(self._filter_query)
        self.model.set_assets_filtered(
            assets,
            filtered,
            column_keys=self._visible_column_keys,
        )
        self._visible_assets = [assets[i] for i in filtered]
        # Auto-fit column widths to content on data refresh.
        # Temporarily disable stretch-last-section so resizeColumnsToContents
        # measures actual content, not the previously-stretched width.
        header = self.table.horizontalHeader()
        prev_stretch = header.stretchLastSection()
        header.setStretchLastSection(False)
        for col in range(header.count()):
            header.resizeSection(col, 50)
        self.table.resizeColumnsToContents()
        for col in range(header.count()):
            w = header.sectionSize(col)
            if w > 300:
                header.resizeSection(col, 300)
        header.setStretchLastSection(prev_stretch)
        if not self._sync_selection() and self._selected_asset is not None:
            self._selected_asset = None
            self._selected_assets = []
            self.selected_asset_changed.emit(None)
            self.selected_assets_changed.emit([])

    def set_category(self, category: str) -> None:
        query = self._index._parse_legacy_category(category, self._search_text)
        self.set_filter_query(query)

    def set_filter_query(self, query: FilterQuery) -> None:
        self._filter_query = query
        self._filter_query.search_text = self._search_text
        self._apply_filter()

    def set_search_text(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self._filter_query.search_text = self._search_text
        self._apply_filter()

    def visible_asset_count(self) -> int:
        return len(self._visible_assets)

    def asset_at(self, view_row: int) -> object | None:
        return self.model.asset_at(view_row)

    def view_at(self, view_row: int) -> AssetView | None:
        return self.model.view_at(view_row)

    def selected_assets(self) -> list[object]:
        return list(self._selected_assets)

    def visible_column_keys(self) -> list[str]:
        return list(self._visible_column_keys)

    def set_visible_columns(self, keys: list[str]) -> None:
        requested = set(keys)
        ordered = [
            column.key
            for column in COLUMN_DEFINITIONS
            if column.key in requested or column.required
        ]
        if not ordered:
            ordered = ["name"]
        self._visible_column_keys = ordered
        self.model.set_column_keys(self._visible_column_keys)
        self._sync_selection()
        self._sync_column_actions()

    def reset_columns(self) -> None:
        self._visible_column_keys = list(DEFAULT_COLUMN_KEYS)
        self.model.set_column_keys(self._visible_column_keys)
        self._sync_selection()
        self._sync_column_actions()

    def set_selected_asset(self, asset: object | None) -> None:
        self._selected_asset = asset
        self._selected_assets = [asset] if asset is not None else []
        self._sync_selection()

    def _apply_filter(self) -> None:
        assets = self.model.assets()
        if not assets and (self._resources or self._artifacts):
            self.update_assets(self._resources, self._artifacts)
            return
        filtered = self._index.filter_query(self._filter_query)
        self.model.set_filtered_rows(filtered)
        source = assets if assets else [*self._resources, *self._artifacts]
        self._visible_assets = [source[i] for i in filtered if 0 <= i < len(source)]
        if not self._sync_selection() and self._selected_asset is not None:
            self._selected_asset = None
            self._selected_assets = []
            self.selected_asset_changed.emit(None)
            self.selected_assets_changed.emit([])

    def _build_column_settings_menu(self) -> None:
        for column in COLUMN_DEFINITIONS:
            action = QAction(column.label, self)
            action.setCheckable(True)
            action.setChecked(column.key in self._visible_column_keys)
            action.setEnabled(not column.required)
            action.toggled.connect(
                lambda checked, key=column.key: self._set_column_visible_from_action(
                    key,
                    checked,
                )
            )
            self.column_settings_menu.addAction(action)
            self.column_actions[column.key] = action
        self.column_settings_menu.addSeparator()
        self.reset_columns_action = self.column_settings_menu.addAction("恢复默认列")
        self.reset_columns_action.triggered.connect(self.reset_columns)

    def _set_column_visible_from_action(self, key: str, checked: bool) -> None:
        if self._syncing_column_actions:
            return
        keys = self.visible_column_keys()
        if checked and key not in keys:
            keys.append(key)
        elif not checked:
            keys = [visible_key for visible_key in keys if visible_key != key]
        self.set_visible_columns(keys)

    def _sync_column_actions(self) -> None:
        self._syncing_column_actions = True
        try:
            visible = set(self._visible_column_keys)
            for key, action in self.column_actions.items():
                action.setChecked(key in visible)
        finally:
            self._syncing_column_actions = False

    def _emit_selection(self, *_args) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._selected_asset = None
            self._selected_assets = []
            self.selected_asset_changed.emit(None)
            self.selected_assets_changed.emit([])
            return

        selected_items = [self.model.asset_at(r.row()) for r in rows if self.model.asset_at(r.row()) is not None]
        self._selected_assets = selected_items
        first = selected_items[0] if selected_items else None
        self._selected_asset = first
        self.selected_asset_changed.emit(first)
        self.selected_assets_changed.emit(selected_items)

    def _on_context_menu(self, pos: QPoint) -> None:
        view_row = self.table.rowAt(pos.y())
        if view_row < 0:
            return

        selected_rows = [r.row() for r in self.table.selectionModel().selectedRows()]
        if view_row not in selected_rows:
            self.table.selectRow(view_row)
            selected_rows = [view_row]

        selected_items = [self.model.asset_at(r) for r in selected_rows if self.model.asset_at(r) is not None]
        if not selected_items:
            return

        global_pos = self.table.viewport().mapToGlobal(pos)
        target = selected_items[0] if len(selected_items) == 1 else selected_items
        self.context_menu_requested.emit(global_pos, target)

    def _asset_key(self, asset: object | None) -> tuple[str, str] | None:
        if asset is None:
            return None
        kind = "artifact" if isinstance(asset, ExportArtifact) else "resource"
        asset_id = getattr(asset, "id", str(id(asset)))
        return (kind, asset_id)

    def _sync_selection(self) -> bool:
        selected_key = self._asset_key(self._selected_asset)
        selected_row = next(
            (
                row
                for row, asset in enumerate(self._visible_assets)
                if self._asset_key(asset) == selected_key
            ),
            None,
        )
        selection_model = self.table.selectionModel()
        selection_model.blockSignals(True)
        self.table.clearSelection()
        if selected_row is not None:
            self.table.selectRow(selected_row)
        selection_model.blockSignals(False)
        return selected_row is not None
