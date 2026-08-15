"""Tests for CatalogIndex incremental sync (P4 write-amplification fix).

``CatalogIndex.sync`` must keep the index byte-equivalent to a full rebuild
while upserting only the changed rows when the database is exactly one
revision behind. These tests pin the behavior deterministically (INSERT
counting via the SQLite trace hook — no timings), plus the equivalence of the
incremental path against a full rebuild after realistic mutation sequences.
"""

from __future__ import annotations

from pathlib import Path


from paleo_workbench.catalog.db import CatalogIndex
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataRun,
    DataStage,
    DataVersion,
    Tag,
)


def _seed(document: CatalogDocument, count: int = 5) -> None:
    for i in range(1, count + 1):
        asset = DataAsset(
            id=f"a{i}", name=f"asset {i}", type="well_log" if i % 2 else "table"
        )
        version = DataVersion(
            id=f"v{i}",
            asset_id=asset.id,
            version_number=1,
            stage=DataStage.RAW,
            path=f"raw/a{i}/v{i}/f.bin",
            sha256=f"h{i}",
            parent_version_ids=[],
        )
        document.assets.append(asset)
        document.versions.append(version)


def _snapshot(index: CatalogIndex, document: CatalogDocument) -> dict:
    """Query-level fingerprint of the index, comparable across indexes."""
    return {
        "revision": index.revision(),
        "assets": {a["id"] for a in index.search_assets()},
        "by_type": {
            "table": {a["id"] for a in index.search_assets(type="table")}
        },
        "tags": index.assets_for_tag("qc"),
        "lineage": {
            v.id: index.lineage_edges(v.id) for v in document.versions
        },
        "versions": {
            a.id: [v["id"] for v in index.list_versions(a.id)]
            for a in document.assets
        },
    }


def test_single_revision_gap_syncs_incrementally_not_full_rebuild(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    document = CatalogDocument(catalog_revision=0)
    index.rebuild(document)
    _seed(document)
    document.catalog_revision = 1

    # Prime the snapshot from the document (as the service does on open).
    index.prime(document)
    counts = {"inserts": 0, "rebuilds": 0}
    original_rebuild = CatalogIndex.rebuild

    def _spy_rebuild(self, doc):
        counts["rebuilds"] += 1
        return original_rebuild(self, doc)

    CatalogIndex.rebuild = _spy_rebuild  # type: ignore[method-assign]
    conn = index._connect()

    def _trace(sql: str) -> None:
        tokens = sql.strip().split()
        if tokens and tokens[0].upper() == "INSERT":
            counts["inserts"] += 1

    conn.set_trace_callback(_trace)
    try:
        assert index.sync(document) is True
    finally:
        conn.set_trace_callback(None)
        CatalogIndex.rebuild = original_rebuild  # type: ignore[method-assign]

    assert counts["rebuilds"] == 0, "incremental path did not engage"
    # 5 assets + 5 versions + 3 sync_state rows = 13, NOT a full ~13+N rewrite.
    assert counts["inserts"] <= 16, counts["inserts"]
    assert index.is_fresh(document) is True


def test_no_revision_gap_is_a_noop(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    document = CatalogDocument(catalog_revision=0)
    index.rebuild(document)
    _seed(document)
    document.catalog_revision = 1
    index.rebuild(document)
    assert index.sync(document) is False  # already fresh


def test_gap_larger_than_one_falls_back_to_full_rebuild(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    document = CatalogDocument(catalog_revision=0)
    index.rebuild(document)
    _seed(document)
    document.catalog_revision = 3  # skipped two revisions
    assert index.rebuild is not None
    index.sync(document)
    assert index.is_fresh(document) is True
    assert {a["id"] for a in index.search_assets()} == {"a1", "a2", "a3", "a4", "a5"}


def test_missing_snapshot_falls_back_to_full_rebuild(tmp_path: Path):
    """A fresh index (no in-memory row snapshot) must rebuild, not guess."""
    index = CatalogIndex(tmp_path)
    document = CatalogDocument(catalog_revision=0)
    index.rebuild(document)
    _seed(document)
    document.catalog_revision = 1
    # Simulate a process that opened a fresh database without priming:
    index._last_state = None
    index.sync(document)
    assert index.is_fresh(document) is True
    assert {a["id"] for a in index.search_assets()} == {"a1", "a2", "a3", "a4", "a5"}


def test_incremental_matches_rebuild_after_mutation_sequence(tmp_path: Path):
    """The realistic lifecycle: many single-revision mutations (imports, tags,
    trash, lineage, runs, purge) must leave the index query-equivalent to a
    fresh full rebuild."""
    tmp = tmp_path / "incr"
    tmp.mkdir()
    index = CatalogIndex(tmp)
    document = CatalogDocument(catalog_revision=0, assets=[], versions=[])
    index.rebuild(document)
    for i in range(1, 21):
        asset = DataAsset(
            id=f"a{i}", name=f"asset {i}", type="well_log" if i % 2 else "table"
        )
        version = DataVersion(
            id=f"v{i}", asset_id=asset.id, version_number=1, stage=DataStage.RAW,
            path=f"raw/a{i}/v{i}/f.bin", sha256=f"h{i}",
        )
        document.assets.append(asset)
        document.versions.append(version)
        document.catalog_revision += 1
        index.sync(document)

    document.catalog_revision += 1
    document.versions[4].parent_version_ids.append("v1")
    index.sync(document)
    document.catalog_revision += 1
    document.tags.append(Tag(id="t1", name="QC Passed"))
    document.asset_tags.setdefault("a3", []).append("t1")
    index.sync(document)
    document.catalog_revision += 1
    document.versions[6].trashed = True
    document.versions[6].trashed_at = "2026-01-01T00:00:00+00:00"
    index.sync(document)
    document.catalog_revision += 1
    document.versions[6].trashed = False
    document.versions[6].trashed_at = None
    index.sync(document)
    document.catalog_revision += 1
    document.runs.append(
        DataRun(
            id="r1", operation="compute",
            input_version_ids=["v1"], output_version_ids=["v5"],
        )
    )
    index.sync(document)
    document.catalog_revision += 1
    document.versions[10].parent_version_ids.append("v5")
    index.sync(document)
    # Purge: delete the first five assets+versions (as purge_trashed does).
    document.catalog_revision += 1
    document.versions = [v for v in document.versions if v.id not in {
        "v1", "v2", "v3", "v4", "v5"
    }]
    document.assets = [a for a in document.assets if a.id not in {
        "a1", "a2", "a3", "a4", "a5"
    }]
    index.sync(document)

    fresh = CatalogIndex(tmp_path / "fresh")
    fresh.rebuild(document)
    assert _snapshot(index, document) == _snapshot(fresh, document)
    # The run-retained edge (v1 → v5) survives the purge of both endpoints.
    assert index.lineage_edges("v1") == {"parents": [], "children": ["v5"]}
    assert index.lineage_edges("v5") == {"parents": ["v1"], "children": ["v11"]}
    assert {a["id"] for a in index.search_assets()} == {
        f"a{i}" for i in range(6, 21)
    }


def test_incremental_upsert_updates_changed_row_in_place(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    document = CatalogDocument(catalog_revision=0)
    index.rebuild(document)
    _seed(document)
    document.catalog_revision = 1
    index.rebuild(document)

    # Rename an asset + change a version's sha256 in one revision.
    document.catalog_revision += 1
    document.assets[0].name = "renamed asset"
    document.versions[0].sha256 = "new-hash"
    counts = {"inserts": 0}
    conn = index._connect()

    def _trace(sql: str) -> None:
        tokens = sql.strip().split()
        if tokens and tokens[0].upper() == "INSERT":
            counts["inserts"] += 1

    conn.set_trace_callback(_trace)
    try:
        index.sync(document)
    finally:
        conn.set_trace_callback(None)
    # Only the changed asset + version + sync_state rows are written.
    assert counts["inserts"] <= 7, counts["inserts"]
    assert index.search_assets(text="renamed")[0]["id"] == "a1"
    row = conn.execute("SELECT sha256 FROM versions WHERE id = 'v1'").fetchone()
    assert row[0] == "new-hash"
    # Unchanged rows still hold their values.
    row = conn.execute("SELECT name FROM assets WHERE id = 'a2'").fetchone()
    assert row[0] == "asset 2"


def test_attach_lineage_append_reflects_incrementally(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    document = CatalogDocument(catalog_revision=0)
    index.rebuild(document)
    _seed(document)
    document.catalog_revision = 1
    index.rebuild(document)

    document.catalog_revision += 1
    document.versions[3].parent_version_ids.append("v1")
    index.sync(document)
    assert index.lineage_edges("v1") == {"parents": [], "children": ["v4"]}
    # Appending a second parent is reflected too.
    document.catalog_revision += 1
    document.versions[3].parent_version_ids.append("v2")
    index.sync(document)
    assert index.lineage_edges("v4") == {"parents": ["v1", "v2"], "children": []}


def test_wal_mode_engaged_and_reset_cleans_wal_files(tmp_path: Path):
    index = CatalogIndex(tmp_path)
    document = CatalogDocument(catalog_revision=0)
    index.rebuild(document)
    mode = index._connect().execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    # reset() must remove the WAL/SHM sidecar files (rebuildable guarantee).
    index.close()
    index.reset()
    assert not Path(f"{index.db_path}-wal").exists()
    assert not Path(f"{index.db_path}-shm").exists()
    assert not index.db_path.exists()


def test_alternating_thread_writes_keep_index_in_sync(tmp_path: Path):
    """Cross-thread saves (InferenceWorker pattern) must neither silently
    stale the index nor trigger rebuild churn: one connection per thread
    (issue #394 / C31)."""
    import threading

    from paleo_workbench.catalog.service import DataCatalogService

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    index = svc._index
    # Open rebuilt once; count ONLY post-open rebuilds.
    rebuilds = {"count": 0}
    original_rebuild = index.rebuild

    def _counting(document):
        rebuilds["count"] += 1
        return original_rebuild(document)

    index.rebuild = _counting  # type: ignore[method-assign]

    def _saves(n: int) -> None:
        for i in range(10):
            src = tmp_path / f"w{n}-{i}.bin"
            src.write_bytes(b"payload")
            svc.import_raw(src)

    # First write on the MAIN thread so the main thread owns its connection.
    src = tmp_path / "m0.bin"
    src.write_bytes(b"payload")
    svc.import_raw(src)
    try:
        threads = [threading.Thread(target=_saves, args=(n,)) for n in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert svc.index_revision() == svc.document.catalog_revision
        assert len(svc.document.versions) == 21
        # No delete-and-rebuild churn from cross-thread failures.
        assert rebuilds["count"] == 0
    finally:
        svc.close()
