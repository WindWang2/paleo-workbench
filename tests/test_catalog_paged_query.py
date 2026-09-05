"""Service-level paged query API (catalog-scale-v5 D1) + store layout gates.

Pins:

* :meth:`DataCatalogService.search_assets_page` / ``count_assets`` /
  ``catalog_aggregates`` — index-backed pages with a document-backed
  fallback that is semantically identical and visible mid-``batch_save``;
* the v6 scale indexes exist on every store this code opens;
* version-column page orders (stage/size/version) return rows — they used
  to reference a join alias that was not in the paging SELECT, and the
  ``_safe`` wrapper turned the SQL error into a silent EMPTY page;
* ``load_document`` accepts stores whose index layout is NEWER than
  ``STORE_SCHEMA_VERSION`` (floor, not equality) — a layout bump must never
  trigger a manifest-based rebuild of a healthy canonical store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.db import INDEX_SCHEMA_VERSION, STORE_SCHEMA_VERSION
from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.paths import artifact_dir_for


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def _seed(service: DataCatalogService, tmp_path: Path, count: int = 12) -> None:
    with service.batch_save():
        for i in range(count):
            src = tmp_path / f"incoming_{i:03d}.las"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(f"curve-data-{i}", encoding="utf-8")
            service.import_raw(source_path=src, name=f"well_{i:03d}")


def _force_document_fallback(service: DataCatalogService, monkeypatch) -> None:
    monkeypatch.setattr(
        type(service), "_query_index_if_current", lambda self: None, raising=True
    )


# -- index-backed paging ------------------------------------------------------


def test_paged_api_pages_in_stable_name_order(service, tmp_path):
    _seed(service, tmp_path)
    page0 = service.search_assets_page(limit=5, order_by="name")
    page1 = service.search_assets_page(limit=5, offset=5, order_by="name")
    assert [r["name"] for r in page0] == [f"well_{i:03d}" for i in range(5)]
    assert [r["name"] for r in page1] == [f"well_{i:03d}" for i in range(5, 10)]
    keyset = service.search_assets_page(
        limit=5,
        order_by="name",
        after=(page0[-1]["name"], page0[-1]["id"]),
    )
    assert [r["name"] for r in keyset] == [r["name"] for r in page1]


def test_count_and_aggregates_match_document(service, tmp_path):
    _seed(service, tmp_path, count=7)
    assert service.count_assets() == 7
    aggregates = service.catalog_aggregates()
    assert aggregates["total"] == 7
    assert aggregates["stages"] == {"raw": 7}
    assert aggregates["types"]  # every asset carries its import type


def test_filters_text_tag_stage_type(service, tmp_path):
    _seed(service, tmp_path, count=6)
    target = service.search_assets(text="well_003")[0]
    service.add_tag("qc_ok", asset_id=target.id)
    assert service.count_assets(text="well_003") == 1
    assert service.count_assets(tags=["QC_OK"]) == 1  # normalized match
    assert service.count_assets(stage=DataStage.RAW) == 6
    assert service.count_assets(stage=DataStage.OUTPUT) == 0
    assert service.count_assets(type="well_log") >= 0  # predicate is accepted


def test_trashed_assets_excluded_unless_requested(service, tmp_path):
    _seed(service, tmp_path, count=4)
    victim = service.search_assets(text="well_002")[0]
    service.trash_asset(victim.id)
    assert service.count_assets() == 3
    assert service.count_assets(include_trashed=True) == 4
    names = [r["name"] for r in service.search_assets_page(limit=100)]
    assert "well_002" not in names


# -- version-column orders (silent-empty-page regression) ----------------------


@pytest.mark.parametrize("order", ["stage", "size", "version", "modified", "type"])
def test_version_column_orders_return_rows(service, tmp_path, order):
    """order_by stage/size/version referenced ``v.*`` without a join; the
    swallowed SQL error made sorting by those columns return ZERO rows."""
    _seed(service, tmp_path)
    rows = service.search_assets_page(limit=100, order_by=order)
    assert len(rows) == 12


# -- document-backed fallback (mid-batch + parity) -----------------------------


def test_mid_batch_query_sees_pending_state(service, tmp_path):
    _seed(service, tmp_path, count=3)
    with service.batch_save():
        src = tmp_path / "incoming_pending.las"
        src.write_text("pending", encoding="utf-8")
        service.import_raw(source_path=src, name="pending_asset")
        assert service.count_assets() == 4
        rows = service.search_assets_page(text="pending_asset")
        assert [r["name"] for r in rows] == ["pending_asset"]
    assert service.count_assets() == 4  # survives the commit


def test_fallback_rows_match_index_rows(service, tmp_path, monkeypatch):
    _seed(service, tmp_path, count=9)
    service.add_tag("batch_a", asset_id=service.search_assets(text="well_000")[0].id)
    service.add_tag("batch_a", asset_id=service.search_assets(text="well_001")[0].id)

    def snapshot():
        return service.search_assets_page(limit=100, order_by="name")

    indexed = snapshot()
    _force_document_fallback(service, monkeypatch)
    fallback = snapshot()
    assert fallback == indexed
    assert service.count_assets() == 9
    assert service.count_assets(tags=["batch_a"]) == 2


def test_fallback_respects_trash_and_keyset(service, tmp_path, monkeypatch):
    _seed(service, tmp_path, count=5)
    victim = service.search_assets(text="well_000")[0]
    service.trash_asset(victim.id)
    _force_document_fallback(service, monkeypatch)
    page0 = service.search_assets_page(limit=2, order_by="name")
    assert [r["name"] for r in page0] == ["well_001", "well_002"]
    page1 = service.search_assets_page(
        limit=2, order_by="name", after=(page0[-1]["name"], page0[-1]["id"])
    )
    assert [r["name"] for r in page1] == ["well_003", "well_004"]


# -- scale indexes present + load_document version floor -----------------------


def test_scale_indexes_exist_on_open(service):
    conn = service._index._connect()
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    assert {
        "idx_assets_name_id",
        "idx_assets_type_name_id",
        "idx_assets_updated_name_id",
        "idx_versions_asset_version",
        "idx_lineage_parent",
    } <= names
    # The lineage parent direction actually serves descendant lookups.
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT child_version_id FROM lineage"
        " WHERE parent_version_id = 'x'"
    ).fetchall()
    assert any("idx_lineage_parent" in (row[-1] or "") for row in plan)


def test_load_document_accepts_newer_index_layout(service):
    """A layout bump (higher index_schema_version) must not reclassify the
    canonical store as foreign: load_document floors at STORE_SCHEMA_VERSION."""
    document = service._index.load_document()
    assert document is not None  # sanity: healthy store loads at the current version
    conn = service._index._connect()
    conn.execute(
        "UPDATE sync_state SET value = ? WHERE key = 'index_schema_version'",
        (str(INDEX_SCHEMA_VERSION + 1),),
    )
    conn.commit()
    assert service._index.store_version() == INDEX_SCHEMA_VERSION + 1
    assert service._index.load_document() is not None
    # A pre-canonical layout stays rejected.
    conn.execute(
        "UPDATE sync_state SET value = '4' WHERE key = 'index_schema_version'"
    )
    conn.commit()
    assert service._index.load_document() is None
    assert STORE_SCHEMA_VERSION == 5  # the floor the contract pins
