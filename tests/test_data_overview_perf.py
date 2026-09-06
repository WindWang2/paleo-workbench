# tests/test_data_overview_perf.py
"""C-P0-1 / C-P1 — 数据概览与回收站刷新的大工程可扩展性。

Three scalability contracts on the data page (Phase 5 audit):

* (a) 工区概览 counts must come from the catalog service's cached SQL
  aggregates — the click path must NOT materialize every asset on the GUI
  thread (100k assets = multi-second freeze), and a plain refresh must not
  display zeroed counts when a cached aggregate exists.
* (b) the legacy/name id maps are keyed by ``catalog_revision``: repeated
  calls within one revision reuse the map; a revision bump invalidates it.
* (c) in paged (large-catalog) mode the trash badge comes from a SQL count —
  no per-refresh companion reconstruction (``get_trashed_assets`` walk).

The service doubles below implement the paged facade contract
(``count_assets`` / ``search_assets_page`` / ``catalog_aggregates`` /
``cached_catalog_aggregates``) the same way ``DataCatalogService`` does.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

import paleo_workbench.ui.pages.data_page as data_page_module
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.filter_index import FilterQuery
from paleo_workbench.ui.pages.paged_asset_model import PAGED_MODE_THRESHOLD

_LARGE_TOTAL = PAGED_MODE_THRESHOLD + 5_000

_AGGREGATES = {
    "total": _LARGE_TOTAL,
    "stages": {"raw": 10, "derived": 4, "intermediate": 2, "output": 6},
    "types": {"well_log": 12, "seismic": 10},
    "tags": {"主力层": 3},
    "review_status": {"approved": 5},
}

_SQL_ROWS = [
    {
        "id": "a000001",
        "name": "asset-000001",
        "type": "well_log",
        "current_stage": "raw",
        "current_version_id": "v000001",
        "current_version_number": 1,
        "current_format": "las",
        "current_path": "raw/a000001/v000001/f.las",
        "current_size_bytes": 128,
        "current_sha256": "hash1",
        "current_created_at": "2026-08-01",
        "trashed": False,
        "metadata": None,
    },
    {
        "id": "a000002",
        "name": "asset-000002",
        "type": "seismic",
        "current_stage": "output",
        "current_version_id": "v000002",
        "current_version_number": 2,
        "current_format": "sgy",
        "current_path": "raw/a000002/v000002/f.sgy",
        "current_size_bytes": 256,
        "current_sha256": "hash2",
        "current_created_at": "2026-08-02",
        "trashed": False,
        "metadata": None,
    },
]

_DOCUMENT_ASSETS = [
    SimpleNamespace(
        id="a000001",
        name="asset-000001",
        type="well_log",
        trashed=False,
        legacy_resource_id="r1",
    ),
    SimpleNamespace(
        id="a000002",
        name="asset-000002",
        type="seismic",
        trashed=False,
        legacy_resource_id="r2",
    ),
]


class FakeCatalogService:
    """Paged-facade service double with spy counters (thread-safe reads)."""

    def __init__(self, *, total: int = _LARGE_TOTAL, trashed: int = 4):
        self.calls = {
            "list_assets": 0,
            "get_trashed_assets": 0,
            "catalog_aggregates": 0,
            "count_assets_trashed": 0,
        }
        self._total = total
        self._trashed = trashed
        self._warm = True
        self._aggregate_gate: threading.Event | None = None
        self.document = SimpleNamespace(
            catalog_revision=7,
            assets=list(_DOCUMENT_ASSETS),
            tags=[],
            asset_tags={},
        )

    # -- aggregates ------------------------------------------------------

    def cached_catalog_aggregates(self, include_trashed: bool = False):
        """Warm aggregates only — None means cold (never computes)."""
        if not self._warm:
            return None
        return _AGGREGATES

    def catalog_aggregates(self, include_trashed: bool = False) -> dict:
        self.calls["catalog_aggregates"] += 1
        gate = self._aggregate_gate
        if gate is not None:
            gate.wait(timeout=10)
        self._warm = True
        return _AGGREGATES

    # -- paged facade ------------------------------------------------------

    def count_assets(self, **kwargs) -> int:
        if kwargs.get("trashed_only"):
            self.calls["count_assets_trashed"] += 1
            return self._trashed
        return self._total

    def search_assets_page(self, **kwargs) -> list[dict]:
        return list(_SQL_ROWS)

    # -- document walks (the paths the fixes must avoid) --------------------

    def list_assets(self, include_trashed: bool = False) -> list:
        self.calls["list_assets"] += 1
        if include_trashed:
            return list(self.document.assets)
        return [a for a in self.document.assets if not a.trashed]

    def get_trashed_assets(self) -> list:
        self.calls["get_trashed_assets"] += 1
        return [a for a in self.document.assets if a.trashed]

    def list_tags(self) -> list:
        return []


def _make_page(qtbot) -> DataPage:
    page = DataPage(ProjectDocument.new("Perf"))
    qtbot.addWidget(page)
    return page


# ---------------------------------------------------------------------------
# (a) overview counts from cached aggregates — no materialization
# ---------------------------------------------------------------------------


class TestOverviewCachedAggregates:
    def test_click_serves_warm_aggregates_without_materializing(
        self, qtbot, monkeypatch
    ):
        page = _make_page(qtbot)
        service = FakeCatalogService()
        monkeypatch.setattr(page._lifecycle, "catalog_service", lambda: service)
        compute_calls: list[int] = []
        monkeypatch.setattr(
            data_page_module,
            "compute_catalog_counts",
            lambda *a, **k: compute_calls.append(1),
        )
        only_rows_calls: list[int] = []
        monkeypatch.setattr(
            page._lifecycle,
            "catalog_only_rows",
            lambda *a, **k: only_rows_calls.append(1) or [],
        )

        # The real click entry: navigation node 工区概览.
        page._on_navigation_filter_query(FilterQuery(node_type="overview"))

        assert page.workspace.overview_visible()
        # The materializing pass must NOT run on the click path.
        assert compute_calls == []
        assert only_rows_calls == []
        assert service.calls["list_assets"] == 0
        assert service.calls["catalog_aggregates"] == 0  # warm cache suffices
        # ...while the cached SQL aggregates DID feed the panel.
        values = page.workspace.overview_panel._values
        assert values["raw"].text() == "10"
        assert values["derived"].text() == "6"  # derived + intermediate
        assert values["output"].text() == "6"
        # Integrity is not part of the aggregates — unknown, never faked as 0.
        assert values["issues"].text() == "—"
        page.shutdown_workers()

    def test_cold_aggregates_compute_off_thread(self, qtbot, monkeypatch):
        page = _make_page(qtbot)
        service = FakeCatalogService()
        service._warm = False
        gate = threading.Event()
        service._aggregate_gate = gate
        monkeypatch.setattr(page._lifecycle, "catalog_service", lambda: service)
        compute_calls: list[int] = []
        monkeypatch.setattr(
            data_page_module,
            "compute_catalog_counts",
            lambda *a, **k: compute_calls.append(1),
        )

        page._on_navigation_filter_query(FilterQuery(node_type="overview"))
        values = page.workspace.overview_panel._values

        # Honest interim state: a placeholder, not fabricated zeros, and the
        # GUI thread never ran the group-by pass.
        assert values["raw"].text() == "—"
        assert compute_calls == []

        gate.set()
        qtbot.waitUntil(lambda: values["raw"].text() == "10", timeout=10_000)
        assert service.calls["catalog_aggregates"] == 1
        assert compute_calls == []
        page.shutdown_workers()

    def test_plain_refresh_in_paged_mode_uses_cached_counts(
        self, qtbot, monkeypatch
    ):
        page = _make_page(qtbot)
        service = FakeCatalogService()
        monkeypatch.setattr(page._lifecycle, "catalog_service", lambda: service)

        page.update_state({}, [])
        assert page.asset_table.in_paged_mode()
        page.workspace.show_overview(True)
        # Plain refresh (F5 path): same cached source must feed the overview.
        page.update_state({}, [])

        values = page.workspace.overview_panel._values
        assert values["raw"].text() == "10"
        assert values["output"].text() == "6"
        assert service.calls["catalog_aggregates"] == 0
        page.shutdown_workers()


# ---------------------------------------------------------------------------
# (b) legacy/name map reuse within a revision
# ---------------------------------------------------------------------------


class TestAssetMapRevisionCache:
    def test_legacy_map_reuses_within_revision_and_invalidates_on_bump(
        self, qtbot, monkeypatch
    ):
        page = _make_page(qtbot)
        service = FakeCatalogService(total=10)
        monkeypatch.setattr(page._lifecycle, "catalog_service", lambda: service)

        first = page._asset_legacy_map()
        assert page._asset_legacy_map() is first  # same object → reused
        assert service.calls["list_assets"] == 1

        service.document.catalog_revision = 8
        second = page._asset_legacy_map()
        assert service.calls["list_assets"] == 2  # revision bump → rebuild
        assert second == first
        page.shutdown_workers()

    def test_name_map_reuses_within_revision_and_invalidates_on_bump(
        self, qtbot, monkeypatch
    ):
        page = _make_page(qtbot)
        service = FakeCatalogService(total=10)
        monkeypatch.setattr(page._lifecycle, "catalog_service", lambda: service)

        first = page._asset_name_map()
        assert page._asset_name_map() is first  # same object → reused
        assert service.calls["list_assets"] == 1

        # A catalog mutation (revision bump) must invalidate even when the
        # legacy resource count is unchanged.
        service.document.catalog_revision = 9
        page._asset_name_map()
        assert service.calls["list_assets"] == 2
        page.shutdown_workers()


# ---------------------------------------------------------------------------
# (c) trashed-companions fast path in paged mode
# ---------------------------------------------------------------------------


class TestTrashedCompanionsPagedFastPath:
    def test_paged_refresh_uses_sql_trash_count(self, qtbot, monkeypatch):
        page = _make_page(qtbot)
        service = FakeCatalogService(trashed=4)
        monkeypatch.setattr(page._lifecycle, "catalog_service", lambda: service)
        badge: list[int] = []
        real_set = page.navigation_tree.set_trash_count
        monkeypatch.setattr(
            page.navigation_tree,
            "set_trash_count",
            lambda n: (badge.append(n), real_set(n)),
        )

        page.update_state({}, [])

        assert page.asset_table.in_paged_mode()
        # The companion-reconstruction pass must not run in paged mode...
        assert service.calls["get_trashed_assets"] == 0
        assert service.calls["list_assets"] == 0
        # ...the trash badge came from the SQL count instead.
        assert service.calls["count_assets_trashed"] >= 1
        assert 4 in badge
        page.shutdown_workers()

    def test_small_projects_still_rebuild_companions(self, qtbot, monkeypatch):
        """Below the paged threshold the 回收站 listing keeps its companions."""
        page = _make_page(qtbot)
        service = FakeCatalogService(total=10, trashed=2)
        service.document.assets = [
            SimpleNamespace(
                id="t1",
                name="trash-1",
                type="well_log",
                trashed=True,
                legacy_resource_id=None,
            )
        ]
        monkeypatch.setattr(page._lifecycle, "catalog_service", lambda: service)

        page.update_state({}, [])
        assert not page.asset_table.in_paged_mode()
        # The materialized path reconstructs companions via the document walk.
        assert service.calls["get_trashed_assets"] >= 1
        page.shutdown_workers()
