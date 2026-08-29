"""Scale / algorithmic regression tests for the catalog (P4 spec §1).

Builds N-asset catalogs via direct document construction (no file copies) and
pins ALGORITHMIC behavior with generous ceilings / baseline ratios — never
brittle absolute milliseconds:

- index rebuild linear in N (not quadratic);
- search_assets per-filter sub-linear after the index build;
- descendants BFS flat on a deep chain (total catalog grows, chain fixed);
- batch verify_integrity linear in total bytes;
- trash / restore linear in N;
- project open linear in N;
- the in-memory FALLBACK paths (SQLite index deleted) stay correct and O(N).

The big-N loop is env-gated via ``CATALOG_SCALE_N`` (e.g.
``CATALOG_SCALE_N=2000`` for the 2000/4000/8000 run); the default loop uses a
small N so the suite stays fast while still exercising every path.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.db import CatalogIndex
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataStage,
    DataVersion,
)
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import catalog_dir_for
from paleo_workbench.catalog.store import CatalogStore

BASE_N = int(os.environ.get("CATALOG_SCALE_N", "64"))
LEVELS = [BASE_N, BASE_N * 2, BASE_N * 4]
# The trash test saves TWICE per version — the tombstone first, then the
# path update after the payload move (save-then-move crash safety) — and the
# canonical store re-serializes the whole document per save (inherent O(N²)
# in total save bytes), so its levels are capped tighter than the others to
# keep the big-N run inside the CI per-test timeout while still exercising
# the 4x ratio. #841: the 32/128 ladder still blew the 45s budget on slow
# fsync-bound 3.12 CI runners; halved to 16/64, keeping the same 4x ratio
# (quadratic behavior still trips LINEAR_CEILING) at ~4x less absolute
# write volume.
TRASH_LEVELS = [max(BASE_N // 4, 16), min(BASE_N // 2, 64), min(BASE_N, 128)]
CHAIN_DEPTH = max(8, BASE_N // 4)
REPS = 3
# Generous ratio ceilings over a 4x data increase (linear ⇒ ~4x, quadratic ⇒
# ~16x, sub-linear ⇒ ≲1x). +FLOOR absorbs noise at tiny sizes — where the
# baseline itself is ~5ms, a 10ms floor left the ceiling within scheduler
# noise of the measured value (40.5ms vs 38ms, #1107); 20ms restores the
# intended margin without weakening the quadratic tripwire (16x ⇒ 90ms+).
LINEAR_CEILING = 5.0
SUB_LINEAR_CEILING = 2.5
FLOOR_MS = 20.0


def _measure(fn, reps: int = REPS) -> float:
    """Min-of-reps wall time in ms (robust to scheduler noise)."""
    best: float | None = None
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - start) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    assert best is not None
    return best


def _scaled_document(n: int, *, chain: bool = False) -> CatalogDocument:
    """A catalog with *n* assets + *n* versions (direct construction).

    With ``chain=True``, the first ``CHAIN_DEPTH`` versions form a parent
    chain and the remaining versions are unrelated (so descendants BFS on the
    chain head visits only ``CHAIN_DEPTH`` nodes regardless of *n*).

    The first 16 assets carry the constant-selectivity type ``needle_type``
    (used by the sub-linear search test: the filter always matches 16 rows no
    matter how large the catalog grows); everything else gets a bulk type.
    """
    assets: list[DataAsset] = []
    versions: list[DataVersion] = []
    for i in range(1, n + 1):
        asset = DataAsset(
            id=f"asset_{i:05d}",
            name=f"asset {i}",
            type="needle_type" if i <= 16 else f"bulk_{i % 8}",
        )
        parent_ids: list[str] = []
        if chain and 1 < i <= CHAIN_DEPTH:
            parent_ids = [f"ver_{i - 1:05d}"]
        version = DataVersion(
            id=f"ver_{i:05d}",
            asset_id=asset.id,
            version_number=1,
            stage=DataStage.RAW,
            path=f"demo.artifacts/raw/asset_{i:05d}/ver_{i:05d}/f.bin",
            sha256=f"{i:064x}",
            parent_version_ids=parent_ids,
        )
        assets.append(asset)
        versions.append(version)
    return CatalogDocument(
        catalog_revision=n,
        assets=assets,
        versions=versions,
    )


def _write_payloads(project_path: Path, n: int, payload: bytes) -> None:
    """Create payload files directly at each version's recorded path."""
    import stat

    for i in range(1, n + 1):
        target = (
            project_path.parent
            / f"demo.artifacts/raw/asset_{i:05d}/ver_{i:05d}/f.bin"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.chmod(target.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass
        target.write_bytes(payload)


def _make_project(tmp_path: Path, n: int, *, chain: bool = False) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _open_scaled(tmp_path: Path, n: int) -> tuple[Path, DataCatalogService]:
    project = _make_project(tmp_path, n)
    svc = DataCatalogService.open(project)
    doc = _scaled_document(n)
    svc.document = doc  # tests operate on the constructed document
    svc.rebuild_index()
    return project, svc


# ------------------------------------------------------------------ helpers


def _db_path(project: Path) -> Path:
    return catalog_dir_for(project) / "catalog.sqlite"


# ================================================================== tests


def test_index_rebuild_linear_in_n(tmp_path: Path):
    times: dict[int, float] = {}
    for n in LEVELS:
        project = _make_project(tmp_path / str(n), n)
        doc = _scaled_document(n)

        def _rebuild():
            index = CatalogIndex(project)
            index.rebuild(doc)
            index.close()

        _rebuild()  # warm-up (page cache, shards)
        times[n] = _measure(_rebuild)
        # Correctness at every level.
        assert index_revision_is(doc, project) is True

    assert times[LEVELS[-1]] < LINEAR_CEILING * times[LEVELS[0]] + FLOOR_MS, times
    assert times[LEVELS[-1]] < LINEAR_CEILING * times[LEVELS[1]] + FLOOR_MS, times


def index_revision_is(doc, project) -> bool:
    index = CatalogIndex(project)
    try:
        return index.revision() == doc.catalog_revision
    finally:
        index.close()


def test_search_sublinear_after_index_build(tmp_path: Path):
    """A filter with CONSTANT selectivity (16 of N assets) must stay ~flat as
    the catalog grows 4x: the index answers in O(result) ≈ O(1), while a full
    table scan would cost O(N) ⇒ ~4x (and the sub-linear bound would fail)."""
    queries = 30

    def _search_time(n: int) -> float:
        project, svc = _open_scaled(tmp_path / str(n), n)
        try:
            def _run():
                for _ in range(queries):
                    results = svc.search_assets(type="needle_type")
                    assert len(results) == 16  # correctness: constant selectivity

            return _measure(_run)
        finally:
            svc.close()

    t_small = _search_time(LEVELS[0])
    t_big = _search_time(LEVELS[-1])
    # Sub-linear: 4x the data must cost well under 2.5x the total query time
    # (a linear scan would be ~4x).
    assert t_big < SUB_LINEAR_CEILING * t_small + FLOOR_MS, (t_small, t_big)


def test_descendants_flat_on_deep_chain(tmp_path: Path):
    """Descendants BFS visits only the chain, independent of total catalog
    size: growing N 4x with a fixed chain must not grow the query time."""
    adapter_cache: dict[int, tuple[DataCatalogService, CoreCatalogAdapter]] = {}

    def _descendants_time(n: int) -> float:
        project = _make_project(tmp_path / str(n), n)
        svc = DataCatalogService.open(project)
        svc.document = _scaled_document(n, chain=True)
        svc.rebuild_index()
        adapter = CoreCatalogAdapter(svc)
        adapter_cache[n] = (svc, adapter)

        def _run():
            refs = adapter.query_lineage("ver_00001", direction="descendants")
            assert len(refs) == CHAIN_DEPTH - 1  # correctness

        return _measure(_run)

    try:
        t_small = _descendants_time(LEVELS[0])
        t_big = _descendants_time(LEVELS[-1])
        assert t_big < SUB_LINEAR_CEILING * t_small + FLOOR_MS, (t_small, t_big)
    finally:
        for svc, _adapter in adapter_cache.values():
            svc.close()


def test_verify_integrity_linear_in_total_bytes(tmp_path: Path):
    import hashlib

    n = min(BASE_N * 2, 256)
    small_bytes, big_bytes = 16 * 1024, 32 * 1024  # 2x total payload bytes

    def _verify_time(payload_size: int) -> float:
        project = _make_project(tmp_path / str(payload_size), n)
        _write_payloads(project, n, b"x" * payload_size)
        svc = DataCatalogService.open(project)
        doc = _scaled_document(n)
        digest = hashlib.sha256(b"x" * payload_size).hexdigest()
        for version in doc.versions:
            version.sha256 = digest  # truthful hashes so hashing actually runs
        svc.document = doc
        svc.rebuild_index()
        try:
            def _run():
                report = svc.verify_integrity()
                assert report.ok  # all payloads verified

            return _measure(_run)
        finally:
            svc.close()

    t_small = _verify_time(small_bytes)
    t_big = _verify_time(big_bytes)
    # Doubling total bytes ⇒ ~2x time (linear); 2.5x ceiling is generous.
    assert t_big < 2.5 * t_small + FLOOR_MS, (t_small, t_big)


def test_trash_restore_linear_in_n(tmp_path: Path):
    """Per-version trash+restore cost must grow at most linearly with the
    catalog size (4x data ⇒ <5x per-version time; quadratic per-version
    scans would blow past that). Note: the canonical store re-serializes the
    whole document on every save, so trashing ALL N versions is inherently
    O(N²) in total save bytes — this test pins the OPERATION's per-version
    scaling, not the canonical-write asymptote."""

    def _trash_restore_time(n: int) -> float:
        project = _make_project(tmp_path / str(n), n)
        _write_payloads(project, n, b"payload")
        svc = DataCatalogService.open(project)
        svc.document = _scaled_document(n)
        svc.rebuild_index()
        version_ids = [v.id for v in svc.document.versions]
        try:
            def _run():
                for vid in version_ids:
                    svc.trash_version(vid, reason="scale")
                for vid in version_ids:
                    svc.restore_version(vid)

            return _measure(_run)
        finally:
            svc.close()

    t_small = _trash_restore_time(TRASH_LEVELS[0])
    t_big = _trash_restore_time(TRASH_LEVELS[-1])
    per_small = t_small / TRASH_LEVELS[0]
    per_big = t_big / TRASH_LEVELS[-1]
    assert per_big < LINEAR_CEILING * per_small + FLOOR_MS, (
        t_small, t_big, per_small, per_big
    )
    # Correctness: everything restored and verifiable (truthful hashes).
    import hashlib

    check_dir = tmp_path / "check"
    project = _make_project(check_dir, TRASH_LEVELS[0])
    _write_payloads(project, TRASH_LEVELS[0], b"payload")
    svc = DataCatalogService.open(project)
    doc = _scaled_document(TRASH_LEVELS[0])
    digest = hashlib.sha256(b"payload").hexdigest()
    for version in doc.versions:
        version.sha256 = digest
    svc.document = doc
    svc.rebuild_index()
    try:
        assert svc.verify_integrity().ok
    finally:
        svc.close()


def test_project_open_linear_in_n(tmp_path: Path):
    def _open_time(n: int) -> float:
        project = _make_project(tmp_path / str(n), n)
        doc = _scaled_document(n)
        CatalogStore(project).save(doc)  # canonical document on disk
        svc = DataCatalogService.open(project)  # warm
        svc.close()

        def _run():
            svc2 = DataCatalogService.open(project)
            assert svc2.document.catalog_revision == doc.catalog_revision
            svc2.close()

        return _measure(_run)

    t_small = _open_time(LEVELS[0])
    t_big = _open_time(LEVELS[-1])
    assert t_big < LINEAR_CEILING * t_small + FLOOR_MS, (t_small, t_big)


def test_inmemory_fallback_paths_linear_and_correct(tmp_path: Path):
    """Delete the SQLite index: queries fall back to the in-memory document
    scans and must stay correct and O(N) (never O(N²)). The fallback scans
    every asset per query, so 4x data ⇒ ≤~8x (cache effects, fixed overhead);
    a quadratic scan would be ~16x and blows past this ceiling."""

    def _fallback_search_time(n: int) -> float:
        project, svc = _open_scaled(tmp_path / str(n), n)
        try:
            svc._index.close()  # Windows: pooled handles block deletion
            _db_path(project).unlink()  # force the fallback path
            assert svc.index_revision() is None
            results = svc.search_assets(type="bulk_3")
            # 16 assets are the needle type; the rest are bulk_{i%8}.
            assert len(results) == max(0, (n - 16) // 8)  # correctness on fallback

            def _run():
                for _ in range(20):
                    svc.search_assets(type="bulk_3")

            return _measure(_run)
        finally:
            svc.close()

    t_small = _fallback_search_time(LEVELS[0])
    t_big = _fallback_search_time(LEVELS[-1])
    # O(N) fallback over a 4x catalog ⇒ ≤ ~8x; quadratic would be ~16x.
    assert t_big < 8.0 * t_small + FLOOR_MS, (t_small, t_big)


def test_rebuild_self_heals_deleted_index_with_scale(tmp_path: Path):
    """Deleting the DB mid-scale then saving rebuilds incrementally-safe."""
    project = _make_project(tmp_path, BASE_N)
    svc = DataCatalogService.open(project)
    svc.document = _scaled_document(BASE_N)
    svc.rebuild_index()
    try:
        # Simulate an EXTERNAL deletion: pooled connections must be closed
        # first (Windows refuses to delete a file any handle holds; the
        # service reconnects lazily on the next write — the contract under
        # test is the self-heal, not raw unlink semantics).
        svc._index.close()
        _db_path(project).unlink()
        # A save after index loss must recover the index (self-heal).
        svc.document.assets[0].name = "renamed"
        svc.document.catalog_revision += 1
        svc._save()
        assert svc.index_revision() == svc.document.catalog_revision
        assert svc.search_assets(text="renamed")
    finally:
        svc.close()
