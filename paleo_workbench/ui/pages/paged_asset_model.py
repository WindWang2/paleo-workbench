"""Paged catalog browsing for the Data Explorer (P0-B / catalog-scale-v5 D3).

Above ``PAGED_MODE_THRESHOLD`` catalog assets the explorer must not
materialize one Python view object per asset on the GUI thread. This module
serves the table from the catalog's query seam (the DataCatalogService paged
facade, or a raw CatalogIndex in tests):

* :class:`CatalogPageProvider` — query translation (FilterQuery → SQL
  predicates) + deterministic pages + index-backed counts. The query
  parameters are snapshotted per request so a filter change can never tear
  an in-flight page fetch.
* :class:`PagedAssetTableModel` — a :class:`AssetTableModel`-compatible
  model with a SPARSE, bounded LRU page cache. Row count is always the
  index-backed total (honest scrollbar); pages are fetched OFF the GUI
  thread by a single worker (latest-only via an epoch counter), prefetched
  one page ahead, and rendered as "…" placeholders until they arrive.
  Every query/sort change bumps the epoch: stale results are dropped on
  arrival, never displayed.

Honest degradation: integrity/entity filters need in-memory joins or
filesystem probes the index cannot answer — the provider reports them as
unmappable and the data page falls back to the materialized path for that
view. Unfetched rows display "…" rather than pretending to have data.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QModelIndex, Qt, QThreadPool, Signal

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


def _load_metadata(raw) -> dict:
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
    """SQL-backed row source for :class:`PagedAssetTableModel`.

    ``source`` is the catalog query seam: the :class:`DataCatalogService`
    paged facade in production, or a raw ``CatalogIndex`` in tests. Both
    expose the same ``search_assets_page`` / ``count_assets`` /
    ``catalog_aggregates`` keyword contract.
    """

    def __init__(self, source, project_root: Path | None = None) -> None:
        self._source = source
        self._project_root = project_root
        self._text: str | None = None
        self._stage: DataStage | str | None = None
        self._type: str | None = None
        self._tags: list[str] = []
        self._tag_op: str = "and"
        self._asset_id: str | None = None
        self._include_trashed = False
        self._trashed_only = False
        self._order_by: str = "name"
        self._page_cursors: dict[int, tuple[str, str] | None] = {}

    @property
    def index(self):
        """Backwards-compatible alias for the query source."""
        return self._source

    def total_source_aggregates(self) -> dict:
        """Group-by badges from the query source (service facade caches)."""
        try:
            return self._source.catalog_aggregates() or {}
        except Exception:
            logger.debug("catalog_aggregates failed", exc_info=True)
            return {}

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
        self._include_trashed = False
        self._trashed_only = node_type == "trash"
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

    # -- parameter snapshot -------------------------------------------------

    def snapshot_params(self) -> dict:
        """Copy the current query parameters for an off-thread fetch.

        A filter change that lands while a page fetch is queued must never
        tear that fetch's query (half old, half new predicates) — requests
        carry their own frozen copy.
        """
        return {
            "text": self._text,
            "stage": self._stage,
            "tags": list(self._tags),
            "tag_op": self._tag_op,
            "type": self._type,
            "asset_id": self._asset_id,
            "include_trashed": self._include_trashed,
            "trashed_only": self._trashed_only,
            "order_by": self._order_by,
        }

    # -- row source --------------------------------------------------------

    def total(self) -> int:
        return int(
            self._source.count_assets(**self._count_params())
        )

    def _count_params(self) -> dict:
        return {
            "text": self._text,
            "stage": self._stage,
            "tags": self._tags,
            "tag_op": self._tag_op,
            "type": self._type,
            "asset_id": self._asset_id,
            "include_trashed": self._include_trashed or self._trashed_only,
            "trashed_only": self._trashed_only,
        }

    def page(self, offset: int, limit: int | None = None) -> list[AssetView]:
        """Fetch one page under the CURRENT query parameters."""
        return self.page_with(self.snapshot_params(), offset, limit)

    def page_with(
        self, params: dict, offset: int, limit: int | None = None
    ) -> list[AssetView]:
        """Fetch one page under *params* (a prior :meth:`snapshot_params`).

        The default name order uses a keyset cursor so deep pages stay
        O(log n) instead of scanning OFFSET rows.
        """
        limit = int(limit or PAGE_SIZE)  # module global: tests shrink it
        keyset = None
        order_by = params.get("order_by") or "name"
        if order_by == "name" and offset > 0:
            # The cursor is the last row of the previous sequential page —
            # cached so repeated fetchMore calls do not re-read it.
            cursor = self._cursor_for_offset(offset)
            if cursor is not None:
                keyset = cursor
        rows = self._source.search_assets_page(
            text=params.get("text"),
            stage=params.get("stage"),
            tags=params.get("tags"),
            tag_op=params.get("tag_op", "and"),
            type=params.get("type"),
            asset_id=params.get("asset_id"),
            include_trashed=bool(params.get("include_trashed")),
            trashed_only=bool(params.get("trashed_only")),
            order_by=order_by,
            limit=limit,
            offset=0 if keyset is not None else offset,
            after=keyset,
        )
        views = [asset_view_from_sql_row(row, self._project_root) for row in rows]
        if order_by == "name":
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


class _PageFetchSignals(QObject):
    """Lives on the GUI thread; runnables emit through it and Qt queues the
    deliveries back to the model's thread."""

    page_ready = Signal(int, int, object)  # epoch, offset, list[AssetView]
    page_failed = Signal(int, int, str)  # epoch, offset, error text


class _PageFetchRunnable(QRunnable):
    """One off-thread page fetch (pooled — no persistent worker thread)."""

    def __init__(self, signals: _PageFetchSignals, provider, epoch: int, offset: int, params: dict):
        super().__init__()
        self.setAutoDelete(True)
        self._signals = signals
        self._provider = provider
        self._epoch = epoch
        self._offset = offset
        self._params = params

    def run(self) -> None:  # pragma: no branch - trivial dispatch
        try:
            views = self._provider.page_with(self._params, self._offset)
            self._signals.page_ready.emit(self._epoch, self._offset, views)
        except Exception as exc:  # noqa: BLE001 — reported, never swallowed
            logger.debug("paged fetch offset=%s failed", self._offset, exc_info=True)
            self._signals.page_failed.emit(self._epoch, self._offset, str(exc))


class PagedAssetTableModel(AssetTableModel):
    """AssetTableModel surface backed by a sparse, async page cache.

    Row count is the index-backed total; row CONTENT is fetched page by
    page, off the GUI thread, into a bounded LRU of
    :data:`PAGE_CACHE_LIMIT` pages. Uncached rows answer "…" from
    :meth:`data` — and their (coalesced) fetch is scheduled as a side
    effect, so a scrollbar jump loads exactly the visible window.
    """

    PAGE_CACHE_LIMIT = 24  # pages resident (24 × 500 AssetViews)
    MAX_INFLIGHT = 4  # outstanding off-thread fetches
    SEEN_KEYS_LIMIT = 8192  # key→row memory for selection restore

    def __init__(self, provider: CatalogPageProvider, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._total: int = 0
        self._pages: OrderedDict[int, list[AssetView]] = OrderedDict()
        self._inflight: dict[int, dict] = {}  # offset → frozen params
        self._epoch = 0
        self._watermark = 0  # next sequential page for the fetch protocol
        self._seen_rows: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._signals = _PageFetchSignals()
        self._signals.page_ready.connect(self._on_page_ready)
        self._signals.page_failed.connect(self._on_page_failed)
        # Dedicated small pool: MAX_INFLIGHT runnables at most, no persistent
        # thread to outlive the model.
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(self.MAX_INFLIGHT)

    @property
    def provider(self) -> CatalogPageProvider:
        return self._provider

    # -- lifecycle -----------------------------------------------------------

    def set_provider(self, provider: CatalogPageProvider) -> None:
        """Swap the row source (same query surface, new filters/cursors)."""
        self._provider = provider

    def shutdown(self) -> None:
        """Drain queued fetches (host teardown)."""
        self._pool.clear()
        self._pool.waitForDone(2_000)

    # -- query lifecycle ------------------------------------------------------

    def refresh(self) -> None:
        """Re-run the count, drop every cached page, serve page 0.

        Page 0 is fetched synchronously (one bounded SQL page — the first
        paint must show rows, and tests stay deterministic); every other
        page fills asynchronously.
        """
        self._epoch += 1
        self._pages.clear()
        self._inflight.clear()
        self._seen_rows.clear()
        self._total = self._provider.total()
        self.beginResetModel()
        first = self._safe_page(self._provider.page(0))
        if first:
            self._store_page(0, first)
        self.endResetModel()
        self._watermark = 1 if first else 0
        if self._watermark * PAGE_SIZE < self._total:
            self._request_page(self._watermark)

    def provider_page(self, offset: int) -> list[AssetView]:
        """Synchronous single-page fetch (kept for compatibility/tests)."""
        try:
            return self._provider.page(offset)
        except Exception:
            logger.debug("paged fetch at %s failed", offset, exc_info=True)
            return []

    def _safe_page(self, views: list[AssetView]) -> list[AssetView]:
        return views or []

    def apply_query(self, query) -> bool:
        if not self._provider.apply_filter_query(query):
            return False
        self.refresh()
        return True

    # -- Qt paging protocol --------------------------------------------------

    def canFetchMore(self, parent=QModelIndex()) -> bool:  # noqa: N802
        if parent.isValid():
            return False
        return self._watermark * PAGE_SIZE < self._total

    def fetchMore(self, parent=QModelIndex()) -> None:  # noqa: N802
        """Schedule the next sequential page OFF-thread (no row insertions —
        the row count is the fixed total; pages appear via dataChanged)."""
        if parent.isValid():
            return
        self._request_page(self._watermark)

    # -- Qt model surface ------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        # Report the TOTAL, not the resident rows — that is what makes the
        # scroll bar honest and drives the view's fetchMore calls.
        return self._total

    def view_at(self, view_row: int) -> AssetView | None:
        if not 0 <= view_row < self._total:
            return None
        page = self._pages.get(view_row // PAGE_SIZE)
        if page is None:
            return None
        within = view_row % PAGE_SIZE
        if within >= len(page):
            return None
        self._pages.move_to_end(view_row // PAGE_SIZE)
        return page[within]

    def asset_at(self, view_row: int) -> object | None:
        view = self.view_at(view_row)
        return view.raw_asset if view is not None else None

    def assets(self) -> list[object]:
        """Raw assets of the RESIDENT pages, in page order (bounded)."""
        out: list[object] = []
        for page in self._pages.values():
            out.extend(view.raw_asset for view in page)
        return out

    def row_for_key(self, key: tuple[str, str] | None) -> int | None:
        """Row of a previously-resident asset by stable key, or None."""
        if key is None:
            return None
        row = self._seen_rows.get(key)
        if row is None:
            return None
        self._seen_rows.move_to_end(key)
        return row

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        view = self.view_at(index.row())
        if view is None:
            # Uncached row: serve the placeholder AND schedule its page.
            # (Callers may pass the role as a raw int — normalize.)
            if int(role) == int(Qt.ItemDataRole.DisplayRole):
                self._request_page(index.row() // PAGE_SIZE)
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

    # -- async page plumbing ----------------------------------------------------

    def _request_page(self, page_index: int) -> None:
        """Coalesced, bounded, off-thread fetch scheduling."""
        if page_index * PAGE_SIZE >= self._total:
            return
        if page_index in self._pages or page_index in self._inflight:
            return
        if len(self._inflight) >= self.MAX_INFLIGHT:
            return
        params = self._provider.snapshot_params()
        self._inflight[page_index] = params
        self._pool.start(
            _PageFetchRunnable(self._signals, self._provider, self._epoch, page_index, params)
        )

    def _on_page_ready(self, epoch: int, offset: int, views: list) -> None:
        self._inflight.pop(offset, None)
        if epoch != self._epoch:
            return  # stale query: latest-only, drop on arrival
        if not views:
            # A short read past the end means the total shrank underneath us
            # (concurrent mutation); clamp honestly.
            self._total = min(self._total, offset * PAGE_SIZE)
            if offset == self._watermark:
                self._advance_watermark()
            return
        self._store_page(offset, views)
        top = offset * PAGE_SIZE
        bottom = top + len(views) - 1
        if bottom >= self._total:
            bottom = self._total - 1
        if bottom >= top:
            self.dataChanged.emit(
                self.index(top, 0), self.index(bottom, max(0, self.columnCount() - 1))
            )
        if offset == self._watermark:
            self._advance_watermark()
        # One-page lookahead keeps sequential scrolling smooth.
        self._request_page(self._watermark)

    def _on_page_failed(self, epoch: int, offset: int, _error: str) -> None:
        self._inflight.pop(offset, None)
        if epoch != self._epoch:
            return

    def _store_page(self, offset: int, views: list) -> None:
        self._pages[offset] = views
        self._pages.move_to_end(offset)
        while len(self._pages) > self.PAGE_CACHE_LIMIT:
            self._pages.popitem(last=False)
        for within, view in enumerate(views):
            key = ("resource", view.id)
            self._seen_rows[key] = offset * PAGE_SIZE + within
            self._seen_rows.move_to_end(key)
        while len(self._seen_rows) > self.SEEN_KEYS_LIMIT:
            self._seen_rows.popitem(last=False)

    def _advance_watermark(self) -> None:
        while (
            self._watermark * PAGE_SIZE < self._total
            and self._watermark in self._pages
        ):
            self._watermark += 1

    # -- unsupported legacy entry points (kept explicit) ----------------------

    def set_assets(self, assets: list[object]) -> None:  # pragma: no cover
        raise TypeError("PagedAssetTableModel is provider-backed; use refresh()")

    def set_assets_filtered(self, assets, rows, column_keys=None, views=None):  # pragma: no cover
        raise TypeError("PagedAssetTableModel is provider-backed; use apply_query()")

    def set_filtered_rows(self, rows: list[int]) -> None:  # pragma: no cover
        raise TypeError("PagedAssetTableModel is provider-backed; use apply_query()") 
