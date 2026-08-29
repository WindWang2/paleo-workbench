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

    # Calling open/connect from main thread prunes dead thread. Bounded
    # poll: Thread.join() may return before OS-thread termination
    # completes, so the first probe can still see the owner alive.
    import time as _time

    deadline = _time.monotonic() + 5.0
    while t.ident in index._conns and _time.monotonic() < deadline:
        # Prune DIRECTLY: open()/_connect() early-returns the main
        # thread's pooled connection and would never reach the pruning
        # pass on subsequent iterations.
        index.prune_dead_threads()
        if t.ident in index._conns:
            _time.sleep(0.02)
    from paleo_workbench.catalog.db import native_thread_alive

    probe_state = {
        tid: native_thread_alive(entry.native_id)
        for tid, entry in index._conns.items()
    }
    assert t.ident not in index._conns, (
        f"[DEBUG-win-prune] worker ident {t.ident} survived poll; "
        f"pool={ {tid: e.native_id for tid, e in index._conns.items()} } "
        f"probes={probe_state}"
    )
    index.close()


def test_thread_safe_catalog_session_context_manager(tmp_path: Path):
    """ThreadSafeCatalogSession opens a thread connection and safely drops it upon exit."""
    from paleo_workbench.catalog.db import ThreadSafeCatalogSession

    index = CatalogIndex(tmp_path)
    tid = threading.get_ident()

    assert tid not in index._conns
    with ThreadSafeCatalogSession(index) as conn:
        assert tid in index._conns
        assert conn is not None
        row = conn.execute("SELECT 42 AS val").fetchone()
        assert row["val"] == 42

    # Upon exit from context manager, the thread connection must be explicitly dropped
    assert tid not in index._conns


def test_catalog_index_session_method(tmp_path: Path):
    """CatalogIndex.session() provides a context manager that drops connection on exit."""
    index = CatalogIndex(tmp_path)
    tid = threading.get_ident()

    with index.session() as conn:
        assert tid in index._conns
        conn.execute("CREATE TABLE IF NOT EXISTS test_table (id INT)")
        conn.execute("INSERT INTO test_table VALUES (1)")

    assert tid not in index._conns


def test_drop_current_connection_explicit(tmp_path: Path):
    """Calling drop_current_connection explicitly frees the connection from the pool."""
    index = CatalogIndex(tmp_path)
    tid = threading.get_ident()

    conn = index.open()
    assert tid in index._conns
    conn.execute("SELECT 1")

    index.drop_current_connection()
    assert tid not in index._conns


def test_concurrent_worker_threads_with_sessions(tmp_path: Path):
    """Multiple concurrent worker threads using sessions perform queries cleanly with zero leaks."""
    index = CatalogIndex(tmp_path)
    # Initialize table in main thread
    with index.session() as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
        for i in range(50):
            conn.execute("INSERT INTO items VALUES (?, ?)", (i, f"item_{i}"))
        conn.commit()

    errors = []
    thread_count = 10

    def reader_task(worker_id: int):
        try:
            with index.session() as conn:
                for _ in range(20):
                    rows = conn.execute("SELECT count(*) as cnt FROM items").fetchone()
                    assert rows["cnt"] == 50
                    time.sleep(0.001)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reader_task, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []
    # All worker connections dropped on session exit
    assert len(index._conns) == 0

