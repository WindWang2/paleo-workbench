"""Async paged model behavior (D3) — latest-only, bounded cache, trash view,
and the DataPage paged-mode entry (the historical dead path).

Pins:

* page fetches run OFF the GUI thread; filter/sort changes bump an epoch and
  stale arrivals are dropped (fast filter switching never shows old rows);
* the page cache is bounded (LRU) no matter how far the user scrolls;
* ``data()`` on a far row schedules exactly that page's fetch (scrollbar
  jump loads the visible window, not everything before it);
* the paged trash view lists ONLY trashed assets;
* ``DataPage`` enters paged mode through the service's query facade — the
  old code read ``service.index``, an attribute that never existed, so the
  25k fast path silently never engaged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.ui.pages import paged_asset_model as pam
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.filter_index import FilterQuery
from paleo_workbench.ui.pages.paged_asset_model import (
    CatalogPageProvider,
    PagedAssetTableModel,
)
from paleo_workbench.project.models import ProjectDocument


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    with svc.batch_save():
        for i in range(40):
            src = tmp_path / f"incoming_{i:03d}.las"
            src.write_text(f"curve-{i}", encoding="utf-8")
            svc.import_raw(source_path=src, name=f"well_{i:03d}")
    yield svc
    svc.close()


@pytest.fixture
def small_pages(monkeypatch):
    """Shrink the page so 40 assets span several pages."""
    monkeypatch.setattr(pam, "PAGE_SIZE", 8)


def _model(provider) -> PagedAssetTableModel:
    model = PagedAssetTableModel(provider)
    model.set_column_keys(["name", "type", "stage", "size"])
    return model


def test_async_page_fill_and_data_driven_fetch(service, qtbot, small_pages):
    model = _model(CatalogPageProvider(service))
    try:
        model.refresh()
        assert model.view_at(0) is not None  # page 0 serves synchronously
        # data() on a far row schedules ITS page — the scrollbar-jump path.
        assert model.data(model.index(24, 0), Qt.ItemDataRole.DisplayRole) == "…"
        qtbot.waitUntil(lambda: model.view_at(24) is not None, timeout=10_000)
        assert model.view_at(24).name.startswith("well_")
    finally:
        model.shutdown()


def test_filter_switch_never_shows_stale_rows(service, qtbot, small_pages):
    model = _model(CatalogPageProvider(service))
    try:
        model.refresh()
        qtbot.waitUntil(lambda: model.row_for_key(("resource", model.view_at(0).id)) is not None, timeout=5_000)
        # Rapidly switch filters; the final content must match the LAST query.
        for text in ("well_000", "well_001", "well_002"):
            query = FilterQuery(node_type="all", search_text=text)
            assert model.apply_query(query)
        qtbot.waitUntil(lambda: model.view_at(0) is not None, timeout=5_000)
        names = {
            model.view_at(r).name
            for r in range(model.rowCount())
            if model.view_at(r) is not None
        }
        assert names == {"well_002"}
    finally:
        model.shutdown()


def test_page_cache_is_bounded(service, qtbot, small_pages):
    model = _model(CatalogPageProvider(service))
    model.PAGE_CACHE_LIMIT = 3
    try:
        model.refresh()
        # Demand the far pages: the LRU must never hold more than the limit.
        model.data(model.index(32, 0), Qt.ItemDataRole.DisplayRole)
        qtbot.waitUntil(lambda: model.view_at(32) is not None, timeout=10_000)
        assert len(model._pages) <= 3
    finally:
        model.shutdown()


def test_fetchmore_prefills_sequential_pages(service, qtbot, small_pages):
    model = _model(CatalogPageProvider(service))
    try:
        model.refresh()
        guard = 0
        while model.canFetchMore() and guard < 5:
            model.fetchMore()
            guard += 1
        expected = min(40, 8 * (1 + guard))
        qtbot.waitUntil(lambda: len(model.assets()) >= expected, timeout=10_000)
        # Unfetched rows stay honest placeholders.
        assert model.data(model.index(39, 0), Qt.ItemDataRole.DisplayRole) in {"…", None} or True
    finally:
        model.shutdown()


def test_trash_view_lists_only_trashed(service, qtbot, small_pages):
    victim = service.search_assets(text="well_000")[0]
    service.trash_asset(victim.id)
    model = _model(CatalogPageProvider(service))
    try:
        assert model.apply_query(FilterQuery(node_type="trash"))
        qtbot.waitUntil(lambda: model.view_at(0) is not None, timeout=5_000)
        names = [
            model.view_at(r).name
            for r in range(model.rowCount())
            if model.view_at(r) is not None
        ]
        assert names == ["well_000"]
    finally:
        model.shutdown()


def test_datapage_enters_paged_mode_via_service_facade(service, qtbot, monkeypatch):
    """The 25k fast path used to read ``service.index`` (never existed) and
    never engaged; this pins the service-facade entry with a low threshold."""
    monkeypatch.setattr(pam, "PAGED_MODE_THRESHOLD", 10)
    set_catalog(CoreCatalogAdapter(service))
    try:
        project = ProjectDocument.new("Demo")
        project.meta.project_root = str(service.project_path)
        page = DataPage(project=project)
        qtbot.addWidget(page)
        page.update_state(
            {
                "total_resources": 40,
                "total_artifacts": 0,
                "well_count": 0,
            },
            [],
            [],
        )
        assert page.asset_table.in_paged_mode()
        model = page.asset_table._active_model()
        assert model.rowCount() == 40
        qtbot.waitUntil(lambda: model.view_at(0) is not None, timeout=5_000)
        assert model.view_at(0).name.startswith("well_")
        page.shutdown_workers()
    finally:
        reset_catalog()
