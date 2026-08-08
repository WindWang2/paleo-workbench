"""Tests for the rebuildable SQLite catalog index (ADR 0056, catalog/db.py).

The index is a pure cache over ``metadata/catalog.json``; corruption or
deletion must never break the project — ``revision()`` reports ``None`` and
queries fall back to empty results, with ``rebuild()`` recreating everything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataRun,
    DataStage,
    DataVersion,
    Tag,
)
from paleo_workbench.catalog.db import CatalogIndex


def make_document(catalog_revision: int = 7) -> CatalogDocument:
    """A small but representative document: 2 assets, 3 versions, 1 run, 1 tag."""
    return CatalogDocument(
        catalog_revision=catalog_revision,
        assets=[
            DataAsset(id="asset_1", name="Gamma Ray", type="well_log"),
            DataAsset(id="asset_2", name="Density", type="well_log"),
        ],
        versions=[
            DataVersion(
                id="ver_1",
                asset_id="asset_1",
                version_number=1,
                stage=DataStage.RAW,
                path="raw/asset_1/ver_1/gr.las",
            ),
            DataVersion(
                id="ver_2",
                asset_id="asset_1",
                version_number=2,
                stage=DataStage.DERIVED,
                path="derived/asset_1/ver_2/gr.npy",
                parent_version_ids=["ver_1"],
                run_id="run_1",
            ),
            DataVersion(
                id="ver_3",
                asset_id="asset_2",
                version_number=1,
                stage=DataStage.RAW,
                path="raw/asset_2/ver_3/dens.las",
            ),
        ],
        runs=[
            DataRun(
                id="run_1",
                operation="compute",
                input_version_ids=["ver_1"],
                output_version_ids=["ver_2"],
            )
        ],
        tags=[Tag(id="tag_1", name="QC Passed", display_name="QC Passed")],
        asset_tags={"asset_1": ["tag_1"]},
        version_tags={"ver_2": ["tag_1"]},
    )


def test_empty_document_rebuild_matches_revision(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    index.rebuild(CatalogDocument())

    assert index.revision() == 0
    assert index.is_fresh(CatalogDocument()) is True
    assert index.search_assets() == []


def test_open_connect_are_idempotent_and_empty_db_reports_none(tmp_path: Path):
    index = CatalogIndex(tmp_path)

    conn = index.open()
    assert conn is index.connect()
    # A bare connection (no tables) must not raise: report no revision.
    assert index.revision() is None
    index.close()
    # Reconnecting lazily behaves the same.
    assert index.revision() is None


def test_queries_after_rebuild(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    index.rebuild(make_document())

    assert index.revision() == 7
    assert index.is_fresh(make_document()) is True

    # search_assets: no filters -> all assets
    assert {a["id"] for a in index.search_assets()} == {"asset_1", "asset_2"}

    # text: case-insensitive name substring
    assert [a["id"] for a in index.search_assets(text="gamma")] == ["asset_1"]
    assert [a["id"] for a in index.search_assets(text="ENS")] == ["asset_2"]

    # type filter
    assert len(index.search_assets(type="well_log")) == 2
    assert index.search_assets(type="table") == []

    # stage filter: only assets that have a version in that stage
    assert [a["id"] for a in index.search_assets(stage="derived")] == ["asset_1"]
    assert {a["id"] for a in index.search_assets(stage="raw")} == {
        "asset_1",
        "asset_2",
    }
    assert index.search_assets(stage="output") == []
    assert index.search_assets(stage=DataStage.OUTPUT) == []

    # tag filter: normalized (case/whitespace-insensitive) tag name
    assert [a["id"] for a in index.search_assets(tag="QC PASSED")] == ["asset_1"]
    assert [a["id"] for a in index.search_assets(tag="qc   passed")] == ["asset_1"]
    # combined filters still apply (asset_2 has no tags)
    assert index.search_assets(text="density", tag="qc passed") == []

    # list_versions: ordered by version_number
    versions = index.list_versions("asset_1")
    assert [v["id"] for v in versions] == ["ver_1", "ver_2"]
    assert versions[1]["stage"] == "derived"
    assert versions[1]["version_number"] == 2
    assert index.list_versions("missing_asset") == []

    # lineage: parents + children (from parent_version_ids and the run)
    assert index.lineage_edges("ver_1") == {"parents": [], "children": ["ver_2"]}
    assert index.lineage_edges("ver_2") == {"parents": ["ver_1"], "children": []}
    assert index.lineage_edges("ver_3") == {"parents": [], "children": []}

    # assets_for_tag: normalized match, asset ids only
    assert index.assets_for_tag("QC PASSED") == ["asset_1"]
    assert index.assets_for_tag("qc passed") == ["asset_1"]
    assert index.assets_for_tag("missing") == []


def test_missing_db_revision_none_and_rebuild_recovers(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    assert index.revision() is None
    assert index.search_assets() == []

    index.rebuild(make_document())
    assert index.revision() == 7

    # Deleting the file (even while the connection is open) reads as stale.
    index.db_path.unlink()
    assert index.revision() is None
    assert index.is_fresh(make_document()) is False

    index.rebuild(make_document())
    assert index.revision() == 7


def test_corrupt_db_is_tolerated_and_reset_recovers(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    index.rebuild(make_document())
    index.close()
    index.db_path.write_bytes(b"this is not a sqlite database........")

    # No raise anywhere: revision/is_fresh signal "needs rebuild", queries empty.
    assert index.revision() is None
    assert index.is_fresh(make_document()) is False
    assert index.search_assets() == []
    assert index.list_versions("asset_1") == []
    assert index.assets_for_tag("qc passed") == []
    assert index.lineage_edges("ver_1") == {"parents": [], "children": []}

    index.reset()
    index.rebuild(make_document())
    assert index.revision() == 7
    assert {a["id"] for a in index.search_assets()} == {"asset_1", "asset_2"}


def test_rebuild_self_heals_corrupt_db(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    index.rebuild(make_document())
    index.close()
    index.db_path.write_bytes(b"garbage!")

    # rebuild() deletes the corrupt file and recreates from the document.
    index.rebuild(make_document())
    assert index.revision() == 7
    assert [a["id"] for a in index.search_assets(stage="derived")] == ["asset_1"]


def test_stale_revision_sync_rebuilds(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    index.rebuild(make_document(catalog_revision=7))
    assert index.revision() == 7

    newer = make_document(catalog_revision=8)
    assert index.is_fresh(newer) is False
    assert index.sync(newer) is True
    assert index.revision() == 8
    assert index.is_fresh(newer) is True

    # Syncing an already-fresh document is a no-op.
    assert index.sync(newer) is False


def test_schema_version_mismatch_means_not_fresh(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    doc = make_document()
    index.rebuild(doc)
    assert index.is_fresh(doc) is True

    # A document from a future schema is not fresh, and sync rebuilds it.
    future = make_document()
    future.schema_version = 2
    assert index.is_fresh(future) is False
    assert index.sync(future) is True
    assert index.is_fresh(future) is True
    assert index.revision() == 7
