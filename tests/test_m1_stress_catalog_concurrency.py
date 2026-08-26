"""Milestone 1 Empirical Stress Tests: CatalogIndex Concurrency & Thread-Safety.

Stress-tests:
1. 25+ concurrent worker threads performing rapid open/close/write transactions via ThreadSafeCatalogSession.
2. Concurrent incremental sync and full rebuilds under heavy multi-threaded reader load (WAL mode validation).
3. Abrupt cross-thread CatalogIndex.close() / reset() under active multi-thread queries without segmentation faults.
4. High-frequency thread spawn/exit cycles with dead thread connection pruning under concurrent load.
"""

from __future__ import annotations

from pathlib import Path
import random
import sqlite3
import threading
from threading import Event
import time

import pytest

from paleo_workbench.catalog.db import CatalogIndex, ThreadSafeCatalogSession
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataStage,
    DataVersion,
    DataRun,
    Tag,
)


def _create_sample_catalog_document(revision: int = 1, num_assets: int = 20) -> CatalogDocument:
    assets = [
        DataAsset(
            id=f"asset_{i:03d}",
            name=f"Well_Log_{i:03d}",
            type="well_log",
            description=f"Description for well {i}",
            current_version_id=f"ver_{i:03d}_v1",
            metadata={"operator": "PaleoCorp", "depth_max": 3500 + i * 10},
        )
        for i in range(num_assets)
    ]
    versions = [
        DataVersion(
            id=f"ver_{i:03d}_v1",
            asset_id=f"asset_{i:03d}",
            version_number=1,
            stage=DataStage.RAW,
            path=f"data/raw/well_{i}.las",
            metadata={"format": "las2"},
        )
        for i in range(num_assets)
    ]
    tags = [Tag(id="tag_raw", name="raw", display_name="Raw Data")]
    asset_tags = {f"asset_{i:03d}": ["tag_raw"] for i in range(num_assets)}
    runs = [
        DataRun(
            id="run_init",
            operation="import",
            output_version_ids=[f"ver_{i:03d}_v1" for i in range(num_assets)],
        )
    ]
    return CatalogDocument(
        catalog_revision=revision,
        schema_version=1,
        assets=assets,
        versions=versions,
        tags=tags,
        asset_tags=asset_tags,
        runs=runs,
    )


def test_stress_25_concurrent_workers_high_frequency_transactions(tmp_path: Path):
    """25 concurrent worker threads executing high-frequency read/write transactions via sessions."""
    index = CatalogIndex(tmp_path)
    doc = _create_sample_catalog_document(revision=1, num_assets=50)
    index.rebuild(doc)
    # Release main-thread setup connection so we isolate worker sessions
    index.drop_current_connection()

    worker_count = 25
    iterations_per_worker = 40
    errors: list[Exception] = []
    barrier = threading.Barrier(worker_count)

    def worker_func(worker_id: int):
        try:
            barrier.wait()
            for i in range(iterations_per_worker):
                with index.session() as conn:
                    # Random mix of queries
                    op = random.choice(["count", "select_asset", "search_like", "insert_temp"])
                    if op == "count":
                        row = conn.execute("SELECT count(*) as c FROM assets").fetchone()
                        assert row["c"] >= 50
                    elif op == "select_asset":
                        aid = f"asset_{random.randint(0, 49):03d}"
                        row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
                        assert row is not None
                        assert row["id"] == aid
                    elif op == "search_like":
                        rows = conn.execute("SELECT * FROM assets WHERE name LIKE '%Well%'").fetchall()
                        assert len(rows) >= 50
                    elif op == "insert_temp":
                        # Perform private thread transaction on temp table
                        conn.execute("CREATE TABLE IF NOT EXISTS _thread_audit (tid INT, iter INT)")
                        conn.execute("INSERT INTO _thread_audit VALUES (?, ?)", (threading.get_ident(), i))
                # Outside session context, verify connection was dropped
                assert threading.get_ident() not in index._conns
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker_func, args=(w,)) for w in range(worker_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert errors == [], f"Encountered errors in concurrent sessions: {errors}"
    assert len(index._conns) == 0, f"Leaked connections in pool: {index._conns}"


def test_stress_catalog_index_rebuild_and_sync_under_heavy_concurrent_reads(tmp_path: Path):
    """20 reader threads running queries while 1 writer continuously syncs (incremental) and rebuilds.
    
    Validates:
    - Incremental syncs succeed without disrupting readers.
    - Full rebuilds interrupt active in-flight statements cleanly with sqlite3.OperationalError('interrupted'),
      avoiding SIGSEGV use-after-free.
    """
    index = CatalogIndex(tmp_path)
    doc = _create_sample_catalog_document(revision=1, num_assets=30)
    index.rebuild(doc)
    index.drop_current_connection()

    stop_event = Event()
    reader_errors: list[Exception] = []
    writer_errors: list[Exception] = []
    read_count = [0]
    num_readers = 20

    def reader_func():
        while not stop_event.is_set():
            try:
                with index.session() as conn:
                    rows = conn.execute("SELECT count(*) as c FROM assets").fetchone()
                    assert rows["c"] >= 30
                    read_count[0] += 1
                time.sleep(0.001)
            except Exception as exc:
                reader_errors.append(exc)

    def writer_func():
        try:
            curr_rev = 1
            for step in range(15):
                curr_rev += 1
                new_doc = _create_sample_catalog_document(revision=curr_rev, num_assets=30 + step)
                if step % 2 == 0:
                    index.sync(new_doc)
                else:
                    index.rebuild(new_doc)
                time.sleep(0.01)
        except Exception as exc:
            writer_errors.append(exc)

    readers = [threading.Thread(target=reader_func) for _ in range(num_readers)]
    writer = threading.Thread(target=writer_func)

    for r in readers:
        r.start()
    writer.start()

    writer.join(timeout=10.0)
    stop_event.set()
    for r in readers:
        r.join(timeout=5.0)

    assert writer_errors == [], f"Writer encountered errors: {writer_errors}"
    # Rebuild interrupts active foreign connections by design (ADR 0056 / C31);
    # any error raised must be sqlite3.OperationalError("interrupted") or sqlite3.Error.
    for r_err in reader_errors:
        assert isinstance(r_err, sqlite3.Error), f"Unexpected non-sqlite error: {type(r_err)}: {r_err}"
    assert read_count[0] > 100, f"Expected >100 successful reads, got {read_count[0]}"
    index.drop_current_connection()
    assert len(index._conns) == 0


def test_stress_concurrent_catalog_close_races(tmp_path: Path):
    """CatalogIndex.close() called from main thread while 30 workers execute tight query loops."""
    index = CatalogIndex(tmp_path)
    doc = _create_sample_catalog_document(revision=1, num_assets=20)
    index.rebuild(doc)

    stop = Event()
    worker_exceptions: list[Exception] = []
    num_workers = 30

    def tight_worker():
        try:
            conn = index.open()
            while not stop.is_set():
                conn.execute("SELECT count(*) FROM assets").fetchone()
                time.sleep(0.0005)
        except Exception as e:
            # Expected: sqlite3.ProgrammingError or sqlite3.OperationalError on interrupt/close
            worker_exceptions.append(e)

    workers = [threading.Thread(target=tight_worker) for _ in range(num_workers)]
    for w in workers:
        w.start()

    time.sleep(0.05)
    # Abruptly close index across all threads from main thread
    index.close()
    stop.set()

    for w in workers:
        w.join(timeout=5.0)

    # All connections must be cleared from pool
    assert len(index._conns) == 0
    # Any exceptions captured should be benign SQLite interrupt/error, never crashes
    for exc in worker_exceptions:
        assert isinstance(exc, sqlite3.Error), f"Unexpected non-sqlite exception: {type(exc)}: {exc}"


def test_stress_dead_thread_pruning_under_churn(tmp_path: Path):
    """Rapidly spawn 100 short-lived threads opening connections; prune dead connections concurrently."""
    index = CatalogIndex(tmp_path)
    doc = _create_sample_catalog_document(revision=1, num_assets=10)
    index.rebuild(doc)
    index.drop_current_connection()

    def short_lived_worker():
        conn = index.open()
        conn.execute("SELECT 1").fetchone()
        # Exits without calling session exit, leaving conn in _conns for pruning

    # Spawn 100 threads in batches
    threads = []
    for _ in range(100):
        t = threading.Thread(target=short_lived_worker)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=5.0)

    # All 100 worker threads are dead now. Concurrently call prune from multiple threads.
    prune_errors = []
    def pruner():
        try:
            index.prune_dead_threads()
        except Exception as exc:
            prune_errors.append(exc)

    pruners = [threading.Thread(target=pruner) for _ in range(5)]
    for p in pruners:
        p.start()
    for p in pruners:
        p.join()

    assert prune_errors == []
    # Final prune pass once all pruner threads have fully joined
    index.prune_dead_threads()
    
    # All dead thread connections must be pruned
    alive_tids = {t.ident for t in threading.enumerate() if t.is_alive()}
    for tid in list(index._conns.keys()):
        assert tid in alive_tids, f"Dead thread TID {tid} remained in pool"
    index.close()
    assert len(index._conns) == 0
