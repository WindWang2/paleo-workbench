from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_table_columns import (
    COLUMN_BY_KEY,
    COLUMN_TOOLTIPS,
)
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    DataStage,
    IntegrityState,
    RESOURCE_TYPE_DISPLAY_LABELS,
    asset_view_from_object,
    stage_icon,
    stage_label,
)
from paleo_workbench.ui.tokens import format_size

RESOURCE_TYPE_LABELS = {
    **tokens.RESOURCE_LABELS,
    "spreadsheet": "表格",
    "tabular": "表格",
    "time_depth": "时深",
    "horizon": "层位",
    "well_stratification": "井分层",
    "document": "文档",
    "image_reference": "影像",
    "reference_map": "参考图",
    "well_reference": "测井参考",
    "geojson": "GeoJSON矢量",
    "vector": "矢量",
    "unknown": "未知",
}


def _review_status_display(view: AssetView) -> str:
    from paleo_workbench.catalog.governance import governance_display

    value = view.governance.get("review_status", "")
    return governance_display("review_status", value) if value else "—"


_VERSION_NUMBERS = re.compile(r"\d+")


def _sort_tuple(view: AssetView, key: str, format_cell) -> tuple:
    """Sort by meaning, not by the formatted display string (#651)."""
    if key == "size":
        size = view.size_bytes
        return (1, 0) if size is None else (0, int(size))
    if key == "version":
        text = view.current_version or ""
        if not text or text == "—":
            return (1, (), "")
        nums = tuple(int(n) for n in _VERSION_NUMBERS.findall(text))
        return (0, nums, text)
    if key == "type":
        return (0, view.type_label or view.type)
    if key == "modified":
        text = view.modified_at or ""
        return (1, "") if (not text or text == "—") else (0, text)
    val = getattr(view, key, format_cell(view, key))
    if isinstance(val, (DataStage, IntegrityState)):
        val = val.value
    if val is None:
        val = ""
    return (0, val)


def _match_positions_by_identity(
    old_assets: list, new_assets: list
) -> list[int | None]:
    """Per-position old-index matches for identical asset objects.

    Returns, for each entry of *new_assets*, the index of the equal-by-
    identity (``is``) entry in *old_assets*, or None. Duplicate objects
    consume old positions greedily in order, so a repeated object beyond its
    old multiplicity gets None (conservative: rebuild). Object identity is
    the only reuse key — the same object cannot have changed content, so
    reusing its view is exact; everything else rebuilds (#1063).
    """
    if not old_assets:
        return [None] * len(new_assets)
    from collections import deque

    positions: dict[int, deque] = {}
    for idx, asset in enumerate(old_assets):
        positions.setdefault(id(asset), deque()).append(idx)
    matches: list[int | None] = []
    for asset in new_assets:
        bucket = positions.get(id(asset))
        matches.append(bucket.popleft() if bucket else None)
    return matches


class AssetTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw_assets: list[object] = []
        self._views: list[AssetView] = []
        self._filtered_rows: list[int] = []
        self._column_keys: list[str] = []
        self._project_root: Path | None = None
        # Optional view -> view overlay (catalog enrichment) applied once per
        # row build; None keeps the legacy behavior for un-bridged projects.
        self._view_enricher = None
        # Last (column, order) sorted by — None until the model is sorted.
        # Survives model rebuilds so the host can re-apply the user's sort
        # after a filter/refresh reset (#850-1).
        self._last_sort: tuple[int, object] | None = None
        # View-reuse is only valid while the view-building inputs are
        # unchanged: a different project root or enricher would render
        # recycled views stale (#1063).
        self._view_build_token: tuple | None = None

    def set_project_root(self, root: Path | str | None) -> None:
        if root:
            self._project_root = Path(root)
        else:
            self._project_root = None

    def set_view_enricher(self, enricher) -> None:
        self._view_enricher = enricher

    def _view_inputs_token(self) -> tuple:
        return (self._project_root, self._view_enricher)

    def set_column_keys(self, keys: list[str]) -> None:
        self.beginResetModel()
        self._column_keys = list(keys)
        self._last_sort = None
        self.endResetModel()

    def set_assets(self, assets: list[object]) -> None:
        """Install a full asset list; identical objects keep their views.

        The list-level API is unchanged — incrementality is internal
        (#1063): rows arriving as the very same object as before reuse the
        previously built AssetView (exact, since an unchanged object cannot
        have new content), everything else rebuilds. The user's last sort
        is re-applied after the rebuild instead of being dropped (#1064).
        """
        new_assets = list(assets)
        token = self._view_inputs_token()
        can_reuse = token == self._view_build_token
        old_views = self._views
        matches = (
            _match_positions_by_identity(self._raw_assets, new_assets)
            if can_reuse
            else [None] * len(new_assets)
        )
        self.beginResetModel()
        self._views = [
            old_views[m] if m is not None else self._build_view(asset)
            for m, asset in zip(matches, new_assets)
        ]
        self._raw_assets = new_assets
        self._view_build_token = token
        self._filtered_rows = list(range(len(new_assets)))
        # #850-1 dropped the sort because the reset-time view auto-sort
        # mutated stale rows; re-sorting explicitly after the rebuild is
        # safe and keeps the user's ordering across refreshes (#1064).
        self._apply_last_sort()
        self.endResetModel()

    def _build_view(self, asset: object) -> AssetView:
        view = asset_view_from_object(asset, project_root=self._project_root)
        if self._view_enricher is not None:
            view = self._view_enricher(view)
        return view

    def set_filtered_rows(self, rows: list[int]) -> None:
        self.beginResetModel()
        self._filtered_rows = list(rows)
        self._apply_last_sort()
        self.endResetModel()

    def set_assets_filtered(
        self,
        assets: list[object],
        rows: list[int],
        column_keys: list[str] | None = None,
        views: list[object] | None = None,
    ) -> None:
        """Filtered variant of :meth:`set_assets` (host refresh entry).

        Same incremental semantics (#1063): caller-provided views win for
        their rows; rows without one reuse the previous view when the asset
        object is identical, else rebuild. The caller's row selection is
        respected verbatim; the user's last sort is re-applied (#1064).
        """
        new_assets = list(assets)
        token = self._view_inputs_token()
        old_views = self._views
        if views is not None and len(views) == len(new_assets):
            new_views = list(views)  # shared prebuilt views (#527)
        elif token == self._view_build_token:
            matches = _match_positions_by_identity(self._raw_assets, new_assets)
            new_views = [
                old_views[m] if m is not None else self._build_view(asset)
                for m, asset in zip(matches, new_assets)
            ]
        else:
            new_views = [self._build_view(a) for a in new_assets]
        self.beginResetModel()
        if column_keys is not None:
            self._column_keys = list(column_keys)
        self._raw_assets = new_assets
        self._views = new_views
        self._view_build_token = token
        self._filtered_rows = list(rows)
        self._apply_last_sort()
        self.endResetModel()

    def _apply_last_sort(self) -> None:
        """Re-order the current filtered rows by the user's last sort.

        No-op until the user has sorted once. Applied inside every row-set
        mutation so ordering survives refreshes and filter changes (#1064).
        """
        last = self._last_sort
        if last is None:
            return
        column, order = last
        if column < 0 or column >= len(self._column_keys):
            return
        key = self._column_keys[column]
        reverse = order == Qt.SortOrder.DescendingOrder

        def sort_key(row_idx: int) -> tuple:
            return _sort_tuple(self._views[row_idx], key, self._format_cell_display)

        self._filtered_rows.sort(key=sort_key, reverse=reverse)

    def asset_at(self, view_row: int) -> object | None:
        if view_row < 0 or view_row >= len(self._filtered_rows):
            return None
        idx = self._filtered_rows[view_row]
        if idx < 0 or idx >= len(self._raw_assets):
            return None
        return self._raw_assets[idx]

    def view_at(self, view_row: int) -> AssetView | None:
        if view_row < 0 or view_row >= len(self._filtered_rows):
            return None
        idx = self._filtered_rows[view_row]
        if idx < 0 or idx >= len(self._views):
            return None
        return self._views[idx]

    def assets(self) -> list[object]:
        return list(self._raw_assets)

    @property
    def last_sort(self) -> tuple[int, object] | None:
        """Last (column, order) the model was sorted by, or None."""
        return self._last_sort

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._filtered_rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._column_keys)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if section < 0 or section >= len(self._column_keys):
                return None
            key = self._column_keys[section]
            if role == Qt.ItemDataRole.DisplayRole:
                return COLUMN_BY_KEY[key].label
            if role == Qt.ItemDataRole.ToolTipRole:
                return COLUMN_TOOLTIPS.get(key, COLUMN_BY_KEY[key].label)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        view = self.view_at(index.row())
        if view is None:
            return None

        key = self._column_keys[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._format_cell_display(view, key)

        if role == Qt.ItemDataRole.ToolTipRole:
            return self._format_cell_tooltip(view, key)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if key in ("size", "version"):
                return int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

        return None

    def _format_cell_display(self, view: AssetView, key: str) -> str:
        if key == "name":
            return view.name
        if key == "type":
            return view.type_label
        if key == "stage":
            return f"{stage_icon(view.stage)} {stage_label(view.stage)}"
        if key == "version":
            return view.current_version
        if key == "tags":
            return ", ".join(view.tags) if view.tags else "—"
        if key == "managed":
            return "受管" if view.managed else "外部"
        if key == "integrity":
            return f"{view.integrity_state.icon_symbol} {view.integrity_state.label}"
        if key == "lineage":
            return view.lineage_status or "—"
        if key == "review_status":
            return _review_status_display(view)
        if key == "format":
            return view.format
        if key == "status":
            if view.trashed:
                return view.trashed_label
            return view.status
        if key == "role":
            if isinstance(view.raw_asset, ExportArtifact):
                return "成果"
            if isinstance(view.raw_asset, ResourceItem):
                role = view.raw_asset.artifact_role or "input"
                return {"input": "输入", "derived": "成果", "export": "成果"}.get(role, role)
            return stage_label(view.stage)
        if key == "size":
            return view.size_formatted
        if key == "modified":
            return view.modified_at
        if key == "source":
            return view.source
        if key == "path":
            return view.path
        return ""

    def _format_cell_tooltip(self, view: AssetView, key: str) -> str:
        if key == "stage":
            return f"生命周期: {stage_label(view.stage)} ({view.stage.value})"
        if key == "integrity":
            return f"完整性: {view.integrity_state.label}\n校验和: {view.checksum_display}"
        if key == "lineage":
            return (
                f"血缘: {view.lineage_status}"
                if view.lineage_status
                else "血缘: 未连接数据目录"
            )
        if key == "review_status":
            return "审核状态 (治理元数据)"
        if key == "path":
            return view.path
        if key == "tags":
            return "标签: " + (", ".join(view.tags) if view.tags else "无")
        return self._format_cell_display(view, key)

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        if column < 0 or column >= len(self._column_keys):
            return
        self._last_sort = (column, order)
        self.beginResetModel()
        self._apply_last_sort()
        self.endResetModel()
