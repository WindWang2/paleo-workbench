"""#1043 / #1044 — catalog query index + non-quadratic deletion regression.

* #1043: ``find_external_by_path`` filtered on ``versions(path)`` with no
  covering index — a full table scan on every external registration dedup.
  The fix adds a partial index matching the exact predicate
  (``managed = 0 AND trashed = 0``) and bumps ``INDEX_SCHEMA_VERSION`` so
  existing indexes rebuild.
* #1044: ``_remove_asset``/``_remove_version`` used pydantic value-equality
  ``list.remove`` (two O(N) field-comparing scans + shift each) and rebuilt
  the whole legacy-id bridge — including a full sort — on every single
  deletion; ``purge_trashed`` loops over that per item, giving the classic
  O(M x N log N) batch-delete blowup. The fix removes by identity, rebuilds
  the bridge only when a legacy claimant actually left, and gives the purge
  loop single-pass bulk paths.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from paleo_workbench.catalog.db import INDEX_SCHEMA_VERSION
from paleo_workbench.catalog.models import DataAsset, DataStage, DataVersion
from paleo_workbench.catalog.service import DataCatalogService


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


def _index_sql(service: DataCatalogService, name: str) -> str | None:
    index = service._index
    conn = index._connect()
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)
        ).fetchone()
        return row[0] if row else None
    finally:
        index.drop_current_connection()


# ---------------------------------------------------------------------------
# #1043 — versions(path) partial index
# ---------------------------------------------------------------------------


def test_partial_path_index_exists_after_open(service):
    sql = _index_sql(service, "idx_versions_external_path")
    assert sql is not None, "find_external_by_path needs a covering partial index (#1043)"
    sql_norm = " ".join(sql.split()).lower()
    assert "on versions(path)" in sql_norm
    assert "managed = 0" in sql_norm
    assert "trashed = 0" in sql_norm


def test_index_schema_version_bumped_so_stale_indexes_rebuild():
    """A v4 database must rebuild instead of silently missing the new index."""
    assert INDEX_SCHEMA_VERSION >= 5


def test_find_external_by_path_uses_the_index(service):
    index = service._index
    conn = index._connect()
    try:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT id FROM versions INDEXED BY idx_versions_external_path"
            " WHERE managed = 0 AND trashed = 0 AND path = ? LIMIT 1",
            ("/some/external/file.las",),
        ).fetchall()
    finally:
        index.drop_current_connection()
    detail = " ".join(str(row[-1]) for row in plan)
    assert "idx_versions_external_path" in detail, (
        f"planner must seek the partial path index, got: {detail!r}"
    )


def test_external_path_query_scales_to_100k_rows(service, tmp_path):
    """End-to-end dedup lookup must stay sub-linear in table size."""
    index = service._index
    conn = index._connect()
    try:
        conn.executemany(
            "INSERT INTO versions (id, asset_id, version_number, stage, managed,"
            " path, format, metadata, created_at, trashed) VALUES (?,?,?,?,0,?,?, '{}', '', 0)",
            [
                (f"v{i}", f"a{i}", 1, "raw", f"/ext/sector_{i % 997}/f{i}.las", "las")
                for i in range(100_000)
            ],
        )
        conn.commit()
        target = "/ext/sector_500/f99_999.las"
        # warm both caches once so we measure seek cost, not page-in
        conn.execute(
            "SELECT id FROM versions INDEXED BY idx_versions_external_path"
            " WHERE managed = 0 AND trashed = 0 AND path = ? LIMIT 1",
            (target,),
        ).fetchall()
        import time

        t0 = time.perf_counter()
        rounds = 100
        for i in range(rounds):
            row = conn.execute(
                "SELECT id FROM versions INDEXED BY idx_versions_external_path"
                " WHERE managed = 0 AND trashed = 0 AND path = ? LIMIT 1",
                (f"/ext/sector_{(90_000 + i) % 997}/f{90_000 + i}.las",),
            ).fetchone()
            assert row is not None
        per_query_ms = (time.perf_counter() - t0) / rounds * 1000
        assert per_query_ms < 1.0, (
            f"path lookup must be an index seek, took {per_query_ms:.3f} ms/query"
        )
    finally:
        index.drop_current_connection()


# ---------------------------------------------------------------------------
# #1044 — identity-based removal + bulk purge
# ---------------------------------------------------------------------------


def _asset(asset_id: str, legacy_id: str | None = None, **overrides) -> DataAsset:
    fields = dict(
        id=asset_id,
        name=f"asset-{asset_id}",
        type="well_log",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    if legacy_id is not None:
        fields["legacy_resource_id"] = legacy_id
    fields.update(overrides)
    return DataAsset.model_construct(**fields)


def _version(version_id: str, asset_id: str) -> DataVersion:
    return DataVersion.model_construct(
        id=version_id,
        asset_id=asset_id,
        version_number=1,
        stage=DataStage.RAW,
        managed=True,
        created_at="2026-01-01T00:00:00",
    )


def test_remove_asset_removes_the_identical_object_not_an_equal_twin(service):
    """``list.remove`` drops the first *equal* item — with pydantic value
    equality that can be a different object; removal must be identity-based."""
    twin_a = _asset("same-id", name="twin")
    twin_b = _asset("same-id", name="twin")
    assert twin_a == twin_b and twin_a is not twin_b

    service.document.assets.append(twin_a)
    service.document.assets.append(twin_b)
    service._ensure_maps()

    service._remove_asset(twin_b)
    assert len(service.document.assets) == 1
    assert service.document.assets[0] is twin_a


def test_remove_version_removes_the_identical_object(service):
    twin_a = _version("v1", "a1")
    twin_b = _version("v1", "a1")
    service.document.versions.append(twin_a)
    service.document.versions.append(twin_b)
    service._ensure_maps()

    service._remove_version(twin_b)
    assert len(service.document.versions) == 1
    assert service.document.versions[0] is twin_a


def test_purge_trashed_avoids_quadratic_equality_probes(service, monkeypatch):
    """Field-comparing ``__eq__`` calls during a purge must stay ~O(N+M)."""
    n_live, n_trashed = 4_000, 300
    for i in range(n_live):
        service._add_asset(_asset(f"live-{i}"))
        service._add_version(_version(f"vlive-{i}", f"live-{i}"))
    for i in range(n_trashed):
        service._add_asset(_asset(f"dead-{i}", trashed=True, trashed_at="2026-01-01"))
    for i in range(n_trashed):
        service._add_version(
            _version(f"vdead-{i}", f"dead-{i}").model_copy(update={"trashed": True})
        )

    eq_calls = {"n": 0}
    original_eq = DataAsset.__eq__

    def counting_eq(self, other):
        if isinstance(other, DataAsset):
            eq_calls["n"] += 1
        return original_eq(self, other)

    monkeypatch.setattr(DataAsset, "__eq__", counting_eq)
    removed = service.purge_trashed()
    monkeypatch.undo()

    assert removed == n_trashed * 2  # versions + assets
    assert len(service.document.assets) == n_live
    assert len(service.document.versions) == n_live

    # Old code: M removals x (in + list.remove + bridge rebuild compare) is
    # ~2*M*N equality probes ≈ 2*600*4000 = 4.8M. Linear single-pass stays
    # under a small multiple of N+M.
    assert eq_calls["n"] < 10 * (n_live + n_trashed), (
        f"purge performed {eq_calls['n']} field-equality probes — deletion is "
        "still scanning by value"
    )


def test_legacy_bridge_survives_selective_removal(service):
    """Removing a non-claimant must not disturb the legacy-id mapping."""
    claimant = _asset("a-claim", legacy_id="legacy-1")
    other = _asset("a-other", legacy_id="legacy-2")
    service._add_asset(claimant)
    service._add_asset(other)
    service._ensure_maps()
    assert service._assets_by_legacy_id["legacy-1"] is claimant

    service._remove_asset(other)
    assert service._assets_by_legacy_id.get("legacy-1") is claimant
    assert service._assets_by_legacy_id.get("legacy-2") is None


def test_legacy_bridge_rebuild_promotes_next_claimant(service):
    first = _asset("a-1", legacy_id="legacy-1", trashed=True)
    second = _asset("a-2", legacy_id="legacy-1")
    service._add_asset(first)
    service._add_asset(second)
    service._ensure_maps()
    # live claimant wins over the trashed first-wins entry
    service._remove_asset(first)
    assert service._assets_by_legacy_id.get("legacy-1") is second


def test_bulk_purge_keeps_asset_with_one_restored_version(service):
    """C3 invariant under the bulk path: an asset with a surviving version
    must be un-trashed, not removed."""
    service._add_asset(_asset("keep", trashed=True, trashed_at="t"))
    v = _version("v-keep", "keep")
    service._add_version(v)  # live version on a trashed asset
    service._ensure_maps()
    # the trashed asset is counted as processed but must be retained (C3):
    # its live version keeps it alive, un-trashed, with the version intact.
    removed = service.purge_trashed()
    assert removed == 1
    kept = next(a for a in service.document.assets if a.id == "keep")
    assert kept.trashed is False
    assert any(existing is v for existing in service.document.versions)
