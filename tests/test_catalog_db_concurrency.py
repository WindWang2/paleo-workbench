"""Tests for CatalogIndex concurrency, cross-thread close, and dead thread connection pruning (Issues #971, #1009)."""

from pathlib import Path
import sqlite3
import threading
import time

from paleo_workbench.catalog.db import CatalogIndex


def test_catalog_index_close_while_worker_executing(tmp_path: Path):
    """close() during a live cross-thread execute must never free that handle.

    Regression for the deterministic CI SIGSEGV (both 3.12/3.13 legs): the
    Save As rollback closed ALL pooled connections from the GUI thread while
    catalog-maintenance was mid-rebuild, use-after-freeing the sqlite3 handle
    in the worker (#394 / C31). Foreign-thread connections must be
    interrupted — sqlite3's only guaranteed cross-thread API — never closed.
    """
    index = CatalogIndex(tmp_path)
    index.open()  # main-thread handle so close() has its own conn to close
    stop = threading.Event()
    worker_error: list[Exception] = []

    def worker() -> None:
        try:
            conn = index.open()
            i = 0
            while not stop.is_set() and i < 20_000:
                conn.execute("CREATE TABLE IF NOT EXISTS probe (k INTEGER)")
                conn.execute("INSERT INTO probe VALUES (?)", (i,))
                i += 1
        except Exception as e:  # cleanly interrupted mid-statement lands here
            worker_error.append(e)

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)  # let the worker get mid-loop before closing
    index.close()
    stop.set()
    t.join(timeout=10)

    assert not t.is_alive()
    # The worker either finished its bounded loop or was interrupted with an
    # ordinary sqlite3 error — never a crash of the interpreter.
    if worker_error:
        assert isinstance(worker_error[0], sqlite3.Error)
    assert len(index._conns) == 0


def test_cross_thread_catalog_index_close_no_error(tmp_path: Path):
    """CatalogIndex.close() called from main thread after worker query must not raise ProgrammingError."""
    index = CatalogIndex(tmp_path)

    worker_error = []

    def worker():
        try:
            conn = index.open()
            # Perform query on worker thread
            conn.execute("SELECT 1").fetchall()
        except Exception as e:
            worker_error.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert not worker_error

    # Close index from main thread - must not raise sqlite3.ProgrammingError
    index.close()
    assert len(index._conns) == 0


def test_catalog_index_prunes_dead_threads(tmp_path: Path):
    """CatalogIndex._connect prunes connections belonging to exited threads."""
    index = CatalogIndex(tmp_path)

    def worker():
        index.open()

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    # Worker thread is now dead, but connection is in _conns
    assert t.ident in index._conns

    # Calling open/connect from main thread prunes dead thread
    index.open()
    assert t.ident not in index._conns
    index.close()
