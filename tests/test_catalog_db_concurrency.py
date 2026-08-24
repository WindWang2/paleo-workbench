"""Tests for CatalogIndex concurrency, cross-thread close, and dead thread connection pruning (Issues #971, #1009)."""

from pathlib import Path
import threading
from paleo_workbench.catalog.db import CatalogIndex


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
