from __future__ import annotations

from pathlib import Path

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
from paleo_workbench.ui.pages.paged_asset_model import (
    CatalogPageProvider,
    PagedAssetTableModel,
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
    # Paged mode could not serve the requested view (unmappable filter);
    # the host must rebuild through the materialized path.
    paged_mode_unavailable = Signal()

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
        self._project_root: Path | None = None
        self._visible_column_keys = list(DEFAULT_COLUMN_KEYS)
        self.column_actions: dict[str, QAction] = {}
        self._syncing_column_actions = False
        self._index = FilterIndex()
        # Column-width memory (#894-1): the header is Interactive, so a width
        # change observed outside an auto-fit pass means the user dragged a
        # section.  Those keys are exempt from later auto-fits, and auto-fit
        # itself only runs on the first fill / when the column set changes —
        # never on a routine data refresh.
        self._user_resized_columns: set[str] = set()
        self._auto_fit_columns_key: tuple[str, ...] | None = None
        self._fitting_columns = False

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
        self._paged_model: PagedAssetTableModel | None = None
        self._in_paged_mode = False
        self.table = QTableView()
        self.table.setObjectName("DataAssetGrid")
        self.table.setModel(self.model)
        # Connected after setModel so this handler runs last on modelReset,
        # after the view/selection-model reset handling has cleared the
        # selection (see _on_model_reset).
        self.model.modelReset.connect(self._on_model_reset)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Header clicks are routed through _on_header_clicked instead of the
        # view's built-in sorting so the user's sort intent is tracked
        # explicitly (Qt's implicit sortByColumn(0, descending) on setModel
        # must never be mistaken for a user sort — #850-1).
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.horizontalHeader().sectionResized.connect(self._on_section_resized)
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
        project_root: Path | None = None,
        *,
        extra_assets: list[object] | None = None,
        enricher=None,
        views: list[object] | None = None,
    ) -> None:
        # A materialized rebuild always leaves paged mode: the host decided
        # to serve rows itself (small project, or an unmappable filter).
        if self._in_paged_mode:
            self.exit_paged_mode()
        self._resources = list(resources)
        self._artifacts = list(artifacts)
        self._project_root = project_root
        prev_primary = self._selected_asset
        prev_multi = list(self._selected_assets)
        pre_build_sort = self.model.last_sort
        assets: list[object] = [*self._resources, *self._artifacts, *(extra_assets or [])]
        # project_root makes project-relative paths resolvable so relative
        # assets are not misreported as MISSING (F4).
        self._index.rebuild(
            assets, project_root=project_root, enricher=enricher, views=views
        )
        self.model.set_project_root(project_root)
        self.model.set_view_enricher(enricher)
        self._filter_query.search_text = self._search_text
        filtered = self._index.filter_query(self._filter_query)
        self.model.set_assets_filtered(
            assets,
            filtered,
            column_keys=self._visible_column_keys,
            views=self._index.views,  # reuse the index's views (#527)
        )
        self._visible_assets = [assets[i] for i in filtered]
        # Auto-fit column widths to content on the FIRST fill and whenever the
        # column set changes — never on a routine data refresh, which would
        # discard widths the user dragged (#894-1).  Skip the O(rows×cols)
        # content measurement on large tables.  The budget is in CELLS, but
        # this table is only 8 columns wide, so a 10k-cell budget did not
        # engage until ~1250 rows — leaving the 1k-row catalog that motivated
        # the guard on the slow path at ~400ms, while 2k rows completed in
        # ~46ms on the fast path (#883).  4k cells puts 1k rows on the fast
        # path and keeps content fitting for the small tables where it is
        # cheap.  Note the 50px seed below forces a full re-measure, so this
        # branch's cost is not something Qt can short-circuit.
        header = self.table.horizontalHeader()
        columns_key = tuple(self._visible_column_keys)
        if columns_key != self._auto_fit_columns_key:
            self._auto_fit_columns_key = columns_key
            self._user_resized_columns = {
                key for key in self._user_resized_columns if key in columns_key
            }
            # Widths the user dragged survive even a column-set-change refit.
            user_widths = {
                col: header.sectionSize(col)
                for col, key in enumerate(self._visible_column_keys)
                if key in self._user_resized_columns and col < header.count()
            }
            self._fitting_columns = True
            try:
                prev_stretch = header.stretchLastSection()
                header.setStretchLastSection(False)
                cell_count = self.model.rowCount() * self.model.columnCount()
                if cell_count <= 4_000:
                    for col in range(header.count()):
                        header.resizeSection(col, 50)
                    self.table.resizeColumnsToContents()
                    for col in range(header.count()):
                        w = header.sectionSize(col)
                        if w > 300:
                            header.resizeSection(col, 300)
                else:
                    # No content measurement on big tables; keep a readable
                    # fixed width.
                    for col in range(header.count()):
                        header.resizeSection(col, 120)
                for col, w in user_widths.items():
                    header.resizeSection(col, w)
                header.setStretchLastSection(prev_stretch)
            finally:
                self._fitting_columns = False
        # The model rebuild above dropped the header sort; re-apply it so the
        # visible order stays honest with the indicator (#850-1).
        self._reapply_sort(pre_build_sort)
        self._sync_selection()
        # Notify consumers whenever a refresh shrank/cleared the selection, so
        # batch operations can never act on rows that are no longer visible
        # (#850-2).  Intermediary restores during model resets are transient;
        # compare against the pre-refresh state.
        self._emit_selection_changes(prev_primary, prev_multi)

    def set_category(self, category: str) -> None:
        query = self._index._parse_legacy_category(category, self._search_text)
        self.set_filter_query(query)

    # ------------------------------------------------------------------
    # Paged mode (large catalogs, P0-B)
    # ------------------------------------------------------------------

    def update_paged(self, provider: CatalogPageProvider) -> None:
        """Serve the table from SQL pages instead of materialized rows.

        The classic model stays constructed (small projects never see this
        path); the view simply displays the paged model. Filter/search
        changes re-query through the provider; unmappable queries emit
        :attr:`paged_mode_unavailable` so the host can fall back.
        """
        if self._paged_model is None or self._paged_model.provider is not provider:
            self._paged_model = PagedAssetTableModel(provider, self)
            self._paged_model.set_column_keys(self._visible_column_keys)
            self._paged_model.modelReset.connect(self._on_model_reset)
        self._in_paged_mode = True
        self._filter_query.search_text = self._search_text
        if not self._paged_model.apply_query(self._filter_query):
            self.exit_paged_mode()
            self.paged_mode_unavailable.emit()
            return
        self._install_model(self._paged_model)
        self._visible_assets = list(self._paged_model.assets())
        self._sync_selection()

    def exit_paged_mode(self) -> None:
        """Return to the classic materialized model (host rebuilds rows)."""
        if not self._in_paged_mode:
            return
        self._in_paged_mode = False
        self._install_model(self.model)
        self._visible_assets = []
        self._selected_assets = []
        self._selected_asset = None

    def in_paged_mode(self) -> bool:
        return self._in_paged_mode

    def _install_model(self, model) -> None:
        if self.table.model() is model:
            return
        self.table.setModel(model)
        # setModel creates a fresh selection model: rewire the emitters.
        self.table.selectionModel().selectionChanged.connect(self._emit_selection)

    def set_filter_query(self, query: FilterQuery) -> None:
        self._filter_query = query
        self._filter_query.search_text = self._search_text
        if self._in_paged_mode and self._paged_model is not None:
            if self._paged_model.apply_query(self._filter_query):
                self._visible_assets = list(self._paged_model.assets())
                self._sync_selection()
                return
            self.exit_paged_mode()
            self.paged_mode_unavailable.emit()
            return
        self._apply_filter()

    def set_search_text(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.set_filter_query(self._filter_query)

    def visible_asset_count(self) -> int:
        return len(self._visible_assets)

    def _active_model(self):
        """The model currently installed in the view (classic or paged)."""
        return self.table.model() if self.table.model() is not None else self.model

    def asset_at(self, view_row: int) -> object | None:
        return self._active_model().asset_at(view_row)

    def view_at(self, view_row: int) -> AssetView | None:
        return self._active_model().view_at(view_row)

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
            self.update_assets(
                self._resources, self._artifacts, project_root=self._project_root
            )
            return
        prev_primary = self._selected_asset
        prev_multi = list(self._selected_assets)
        pre_build_sort = self.model.last_sort
        filtered = self._index.filter_query(self._filter_query)
        self.model.set_filtered_rows(filtered)
        source = assets if assets else [*self._resources, *self._artifacts]
        self._visible_assets = [source[i] for i in filtered if 0 <= i < len(source)]
        # Re-apply the header sort lost by the model rebuild so the visible
        # order stays honest with the sort indicator (#850-1).
        self._reapply_sort(pre_build_sort)
        self._sync_selection()
        # Same shrink-notification contract as update_assets (#850-2).
        self._emit_selection_changes(prev_primary, prev_multi)

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

    def _on_model_reset(self) -> None:
        """Keep the row -> asset mapping in lockstep with the model.

        The model is the single source of truth for the display order
        (filters and header sorting both reset it).  Rebuild ``_visible_assets``
        from the model and restore the selection on its correct row, so a sort
        (or any reset) can never leave highlight and selection on different
        rows (see #412).
        """
        active = self._active_model()
        self._visible_assets = [
            asset
            for row in range(active.rowCount())
            if (asset := active.asset_at(row)) is not None
        ]
        self._sync_selection()

    def _on_section_resized(self, logical_index: int, _old_size: int, new_size: int) -> None:
        """Record user-dragged column widths so auto-fit never rewrites them.

        ``sectionResized`` fires for programmatic resizes too, so the
        ``_fitting_columns`` guard (raised around every auto-fit pass in
        :meth:`update_assets`) leaves only genuine Interactive drags — i.e.
        anything Qt emits outside our own fitting — recorded here (#894-1).
        """
        if self._fitting_columns:
            return
        if not (0 <= logical_index < len(self._visible_column_keys)):
            return
        if new_size <= 0:
            return
        self._user_resized_columns.add(self._visible_column_keys[logical_index])

    def _on_header_clicked(self, column: int) -> None:
        """Sort by the clicked column, toggling direction on repeat clicks.

        Replaces the view's built-in sorting so the user's sort intent is
        recorded explicitly (see ``_reapply_sort`` / #850-1).
        """
        header = self.table.horizontalHeader()
        if (
            column == header.sortIndicatorSection()
            and header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
        ):
            order = Qt.SortOrder.DescendingOrder
        else:
            order = Qt.SortOrder.AscendingOrder
        header.setSortIndicator(column, order)
        header.setSortIndicatorShown(True)
        self._active_model().sort(column, order)

    def _reapply_sort(self, pre_build_sort=None) -> None:
        """Re-apply the user's header sort after a filter/refresh model rebuild.

        A model rebuild resets the rows (canonical order) while the header
        keeps its indicator; re-sorting keeps the shown order honest with the
        indicator instead of silently resetting it (#850-1). *pre_build_sort*
        is the sort captured before the rebuild — the rebuild itself clears the
        model's recorded sort so Qt's reset-time auto-sort is never mistaken
        for a user action.
        """
        active = self._active_model()
        last = pre_build_sort if pre_build_sort is not None else getattr(
            active, "last_sort", None
        )
        if last is None:
            return
        column, order = last
        if not (0 <= column < active.columnCount()):
            return
        self.table.sortByColumn(column, order)

    def _emit_selection_changes(self, prev_primary, prev_multi: list[object]) -> None:
        """Emit selection signals when a refresh/filter shrank or cleared it.

        Compares the current selection (already rebuilt onto the visible rows)
        against the pre-mutation state so consumers stop acting on rows that
        are no longer visible (#850-2).
        """
        current_primary = self._selected_asset
        primary_changed = (prev_primary is None) != (current_primary is None) or (
            prev_primary is not None
            and current_primary is not None
            and self._asset_key(prev_primary) != self._asset_key(current_primary)
        )
        multi_changed = [
            self._asset_key(a) for a in prev_multi
        ] != [self._asset_key(a) for a in self._selected_assets]
        if primary_changed:
            self.selected_asset_changed.emit(current_primary)
        if multi_changed:
            self.selected_assets_changed.emit(list(self._selected_assets))

    def _sync_selection(self) -> bool:
        """Restore the selection onto the current visible rows.

        Rebuilds ``_selected_assets`` from what is actually visible so a
        filter/search change can never leave the multi-selection pointing at
        rows the user can no longer see (#850-2).  Emits nothing itself
        (callers notify via :meth:`_emit_selection_changes`).  Returns True
        when at least one previously selected asset is still visible.
        """
        wanted_keys = {
            key
            for key in (
                self._asset_key(self._selected_asset),
                *(self._asset_key(a) for a in self._selected_assets),
            )
            if key is not None
        }

        selection_model = self.table.selectionModel()
        selection_model.blockSignals(True)
        self.table.clearSelection()
        restored: list[object] = []
        for row, asset in enumerate(self._visible_assets):
            if self._asset_key(asset) in wanted_keys:
                self.table.selectRow(row)
                restored.append(asset)
        selection_model.blockSignals(False)

        self._selected_assets = list(restored)
        self._selected_asset = restored[0] if restored else None
        return bool(restored)
