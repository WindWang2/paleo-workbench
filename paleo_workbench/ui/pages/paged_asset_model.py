"""Paged catalog browsing for the Data Explorer (P0-B virtualization).

Above ``PAGED_MODE_THRESHOLD`` catalog assets the explorer must not
materialize one Python view object per asset on the GUI thread. This module
serves the table from the catalog's SQLite index instead:

* :class:`CatalogPageProvider` — query translation (FilterQuery → SQL
  predicates) + deterministic LIMIT/OFFSET pages + index-backed counts;
* :class:`PagedAssetTableModel` — a :class:`AssetTableModel`-compatible
  model that fetches pages lazily through ``canFetchMore``/``fetchMore``
  and exposes the same ``asset_at``/``view_at``/``sort`` surface the table
  widget already drives.

Honest degradation: integrity/entity filters need in-memory joins or
filesystem probes the index cannot answer — the provider reports them as
unmappable and the data page falls back to the materialized path for that
view. Unfetched rows display "…" rather than pretending to have data.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QModelIndex, Qt

from paleo_workbench.ui.pages.asset_table_model import AssetTableModel
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    DataStage,
    IntegrityState,
    LineageView,
)
from paleo_workbench.ui.tokens import format_size

logger = logging.getLogger(__name__)

PAGED_MODE_THRESHOLD = 25_000
PAGE_SIZE = 500

# FilterQuery.node_type values the SQL path can answer. "integrity" needs a
# filesystem probe; "entity"/"entity_group" need the in-memory link join.
_UNMAPPABLE_NODE_TYPES = {"integrity", "entity", "entity_group", "auxiliary"}

# Table column keys → SQL order keys. Columns without a SQL equivalent are
# ignored in paged mode (sorting them would order only the fetched prefix
# and lie about the rest).
_COLUMN_TO_ORDER = {
    "name": "name",
    "type": "type",
    "stage": "stage",
    "size": "size",
    "modified": "modified",
    "version": "version",
}


class SqlCatalogAssetRef:
    """Tiny row identity for a SQL-paged catalog asset.

    The data page's action paths address rows through ``getattr``; this ref
    carries exactly the fields those paths read, without materializing the
    full pydantic ``DataAsset``.
    """

    __slots__ = ("id", "name", "type", "path", "metadata", "trashed")

    def __init__(self, row: dict) -> None:
        self.id = str(row.get("id") or "")
        self.name = str(row.get("name") or "")
        self.type = str(row.get("type") or "unknown")
        self.path = str(row.get("current_path") or "")
        self.metadata = _load_metadata(row.get("metadata"))
        self.trashed = bool(row.get("trashed"))


def _load_metadata(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def asset_view_from_sql_row(row: dict, project_root: Path | None = None) -> AssetView:
    """Build one lightweight :class:`AssetView` from a paged SQL row."""
    stage_raw = str(row.get("current_stage") or "raw").lower()
    try:
        stage = DataStage(stage_raw)
    except ValueError:
        stage = DataStage.RAW
    ref = SqlCatalogAssetRef(row)
    version_number = row.get("current_version_number")
    current_version = f"v{int(version_number)}" if version_number else "—"
    size_bytes = row.get("current_size_bytes")
    checksum = row.get("current_sha256")
    integrity = (
        IntegrityState.VERIFIED
        if checksum
        else IntegrityState.UNKNOWN
    )
    path = str(row.get("current_path") or "")
    governance = {
        key: str(value)
        for key, value in ref.metadata.items()
        if key in ("review_status", "owner", "source_system") and value
    }
    return AssetView(
        id=ref.id,
        name=ref.name,
        type=ref.type,
        type_label=ref.type,
        format=str(row.get("current_format") or ""),
        stage=stage,
        current_version=current_version,
        versions=[],
        tags=[],
        managed=bool(row.get("current_managed", 1)),
        integrity_state=integrity,
        checksum=checksum,
        path=path,
        size_bytes=int(size_bytes) if size_bytes is not None else None,
        size_formatted=format_size(size_bytes),
        created_at=str(row.get("current_created_at") or ""),
        modified_at=str(row.get("updated_at") or ""),
        source="catalog",
        lineage=LineageView(),
        raw_asset=ref,
        trashed=ref.trashed,
        governance=governance,
    )


class CatalogPageProvider:
    """SQL-backed row source for :class:`PagedAssetTableModel`."""

    def __init__(self, index, project_root: Path | None = None) -> None:
        self._index = index
        self._project_root = project_root
        self._text: str | None = None
        self._stage: DataStage | str | None = None
        self._type: str | None = None
        self._tags: list[str] = []
        self._tag_op: str = "and"
        self._asset_id: str | None = None
        self._include_trashed = False
        self._order_by: str = "name"
        self._page_cursors: dict[int, tuple[str, str] | None] = {}

    @property
    def index(self):
        return self._index

    # -- query translation ------------------------------------------------

    def apply_filter_query(self, query) -> bool:
        """Translate a :class:`FilterQuery`; False when unmappable."""
        node_type = str(getattr(query, "node_type", "all") or "all")
        if node_type in _UNMAPPABLE_NODE_TYPES:
            return False
        stage = getattr(query, "stage", None)
        data_type = getattr(query, "data_type", None)
        tags = list(getattr(query, "tags", None) or [])
        singular = getattr(query, "tag", None)
        if singular:
            tags.append(singular)
        review = getattr(query, "review_status", None)
        if review:
            # review_status filters through the metadata JSON path; the paged
            # path keeps it simple by refusing (rare smart view).
            return False
        self._text = (getattr(query, "search_text", "") or "").strip() or None
        self._stage = stage
        self._type = data_type
        self._tags = tags
        self._tag_op = str(getattr(query, "tag_operator", "and") or "and")
        self._asset_id = getattr(query, "asset_id", None)
        self._include_trashed = node_type == "trash"
        self._page_cursors.clear()  # a new result set invalidates every cursor
        if node_type == "stage":
            self._stage = getattr(query, "node_value", None) or stage
        elif node_type == "type":
            self._type = getattr(query, "node_value", None) or data_type
        elif node_type == "tag":
            value = getattr(query, "node_value", None)
            if value:
                self._tags = [value, *tags]
        elif node_type == "legacy_category":
            # Legacy categories map onto resource types; the caller keeps the
            # resource-side view, the SQL side stays unfiltered here.
            self._type = getattr(query, "data_type", None)
        return True

    # -- row source --------------------------------------------------------

    def total(self) -> int:
        return int(
            self._index.count_assets(
                text=self._text,
                stage=self._stage,
                tags=self._tags,
                tag_op=self._tag_op,
                type=self._type,
                asset_id=self._asset_id,
                include_trashed=self._include_trashed,
            )
        )

    def page(self, offset: int, limit: int = PAGE_SIZE) -> list[AssetView]:
        """Fetch one page. ``offset`` counts from the provider's start; the
        default name order additionally uses a keyset cursor so deep pages
        stay O(log n) instead of scanning OFFSET rows."""
        keyset = None
        if self._order_by == "name" and offset > 0:
            # The cursor is the last row of the previous sequential page —
            # cached so repeated fetchMore calls do not re-read it.
            cursor = self._cursor_for_offset(offset)
            if cursor is not None:
                keyset = cursor
        rows = self._index.search_assets_page(
            text=self._text,
            stage=self._stage,
            tags=self._tags,
            tag_op=self._tag_op,
            type=self._type,
            asset_id=self._asset_id,
            include_trashed=self._include_trashed,
            order_by=self._order_by,
            limit=limit,
            offset=0 if keyset is not None else offset,
            after=keyset,
        )
        views = [asset_view_from_sql_row(row, self._project_root) for row in rows]
        if self._order_by == "name":
            self._page_cursors[offset + len(views)] = (
                (views[-1].name, views[-1].raw_asset.id) if views else None
            )
        return views

    def _cursor_for_offset(self, offset: int) -> tuple[str, str] | None:
        cache = getattr(self, "_page_cursors", None)
        if cache is None:
            cache = {}
            self._page_cursors = cache
        # Exact page boundary (the model's sequential fetch pattern); a miss
        # degrades to OFFSET paging for that one call.
        return cache.get(offset)

    def set_order(self, column_key: str | None, descending: bool) -> bool:
        """Order pages by a table column; False when it has no SQL order."""
        if column_key == "name" and descending:
            self._order_by = "name_desc"
            self._page_cursors.clear()
            return True
        order = _COLUMN_TO_ORDER.get(column_key or "")
        if order is None:
            return False
        self._order_by = order
        self._page_cursors.clear()
        return True


class PagedAssetTableModel(AssetTableModel):
    """AssetTableModel surface backed by lazy SQL pages.

    Row count is the index-backed total; row content is fetched page by page
    as the view asks for more (``fetchMore``). Unfetched rows answer "…"
    from :meth:`data` instead of fabricating values.
    """

    def __init__(self, provider: CatalogPageProvider, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._fetched: list[AssetView] = []
        self._total: int = 0

    # -- configuration -----------------------------------------------------

    def refresh(self) -> None:
        """Re-run the count and restart paging from the first page."""
        self._total = self._provider.total()
        self.beginResetModel()
        self._fetched = self.provider_page(0)
        self.endResetModel()

    def provider_page(self, offset: int) -> list[AssetView]:
        try:
            return self._provider.page(offset)
        except Exception:
            logger.debug("paged fetch at %s failed", offset, exc_info=True)
            return []

    def apply_query(self, query) -> bool:
        if not self._provider.apply_filter_query(query):
            return False
        self.refresh()
        return True

    # -- Qt paging protocol --------------------------------------------------

    def canFetchMore(self, parent=QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid():
            return False
        return len(self._fetched) < self._total

    def fetchMore(self, parent=QModelIndex()) -> None:  # noqa: N802
        if parent.isValid():
            return
        current = len(self._fetched)
        if current >= self._total:
            return
        page = self.provider_page(current)
        if not page:
            # A failed/short read must not wedge the pager at partial state.
            self._total = current
            return
        self.beginInsertRows(QModelIndex(), current, current + len(page) - 1)
        self._fetched.extend(page)
        self.endInsertRows()

    # -- AssetTableModel surface ---------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        # Report the TOTAL, not the fetched length — that is what makes the
        # scroll bar honest and drives the view's fetchMore calls.
        return self._total

    def view_at(self, view_row: int) -> AssetView | None:
        if 0 <= view_row < len(self._fetched):
            return self._fetched[view_row]
        return None

    def asset_at(self, view_row: int) -> object | None:
        view = self.view_at(view_row)
        return view.raw_asset if view is not None else None

    def assets(self) -> list[object]:
        return [view.raw_asset for view in self._fetched]

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        view = self.view_at(index.row())
        if view is None:
            # Callers may pass the role as a raw int (tests, legacy hosts);
            # normalize so the placeholder is served either way.
            if int(role) == int(Qt.ItemDataRole.DisplayRole):
                return "…"
            return None
        return super().data(index, role)

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Sort the WHOLE result through SQL order, never the fetched prefix."""
        if not 0 <= column < len(self._column_keys):
            return
        key = self._column_keys[column]
        descending = order == Qt.SortOrder.DescendingOrder
        if not self._provider.set_order(key, descending):
            logger.debug("paged mode: column %r has no SQL order; sort ignored", key)
            return
        self._last_sort = (column, order)
        self.refresh()

    # -- unsupported legacy entry points (kept explicit) ----------------------

    def set_assets(self, assets: list[object]) -> None:  # pragma: no cover
        raise TypeError("PagedAssetTableModel is provider-backed; use refresh()")

    def set_assets_filtered(self, assets, rows, column_keys=None, views=None):  # pragma: no cover
        raise TypeError("PagedAssetTableModel is provider-backed; use apply_query()")

    def set_filtered_rows(self, rows: list[int]) -> None:  # pragma: no cover
        raise TypeError("PagedAssetTableModel is provider-backed; use apply_query()")
