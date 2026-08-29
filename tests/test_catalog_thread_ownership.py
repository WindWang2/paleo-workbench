"""SQLite connection thread-ownership invariants (Issue #1026).

The connection pool must obey one invariant set:

* a connection belongs to exactly one OS thread;
* only the owning thread (or a *provable* post-mortem reaper) closes it;
* liveness is judged by the OS thread id (``threading.get_native_id()`` /
  ``/proc/self/task/<tid>``), never by ``threading.enumerate()`` +
  ``Thread.is_alive()`` — foreign (Qt) threads register ``_DummyThread``
  objects whose ``is_alive()`` lies (returns False while the thread runs on
  Python <=3.12, raises RuntimeError after it dies on Python >=3.13);
* a recycled ``threading.get_ident()`` value must never hand a dead thread's
  cached connection to the new thread that inherited the id.
"""

from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

from paleo_workbench.catalog.db import CatalogIndex

pytestmark = pytest.mark.usefixtures("qapp")

# Liveness proofs read /proc/self/task — Linux only.
_linux_only = pytest.mark.skipif(
    not Path("/proc/self/task").is_dir(), reason="requires /proc"
)


def _open_conn_in_thread(
    index: CatalogIndex, release: threading.Event | None = None
) -> tuple[threading.Thread, int]:
    """Open a pooled connection from a managed thread; return (thread, ident).

    The thread stays alive until *release* is set (or exits immediately when
    no event is supplied).
    """
    started = threading.Event()
    holder: dict[str, int] = {}

    def run() -> None:
        index.open()
        holder["ident"] = threading.get_ident()
        started.set()
        if release is not None:
            release.wait(timeout=10.0)

    t = threading.Thread(target=run)
    t.start()
    started.wait(timeout=5.0)
    return t, holder["ident"]


# ---------------------------------------------------------------------------
# Pruning correctness
# ---------------------------------------------------------------------------


@_linux_only
def test_prune_closes_only_provably_dead_threads(tmp_path: Path):
    """Live managed threads keep their connections; dead ones are reaped."""
    index = CatalogIndex(tmp_path)
    release = threading.Event()
    live_threads: list[threading.Thread] = []
    live_idents: list[int] = []
    for _ in range(3):
        t, ident = _open_conn_in_thread(index, release)
        live_threads.append(t)
        live_idents.append(ident)

    index.prune_dead_threads()
    for ident in live_idents:
        assert ident in index._conns, "live thread's connection was pruned"

    release.set()
    for t in live_threads:
        t.join(timeout=5.0)

    dead = threading.Thread(target=lambda: index.open())
    dead.start()
    dead.join(timeout=5.0)
    assert not dead.is_alive()

    index.prune_dead_threads()
    assert dead.ident not in index._conns
    assert len(index._conns) == 0
    index.close()


@_linux_only
def test_prune_actually_closes_dead_thread_connections(tmp_path: Path):
    """After the owner dies and pruning runs, the handle is closed for good."""
    index = CatalogIndex(tmp_path)
    t, _ident = _open_conn_in_thread(index)
    conn_before_exit = _pooled_conn(index, t.ident)
    t.join(timeout=5.0)

    index.prune_dead_threads()
    assert t.ident not in index._conns
    with pytest.raises(sqlite3.ProgrammingError):
        conn_before_exit.execute("SELECT 1")
    index.close()


def test_prune_never_raises_and_drains_pool_after_foreign_qthread_exit(
    tmp_path: Path, qapp
):
    """Regression (#1026): a finished *foreign* (Qt) thread must not break pruning.

    ``threading.get_ident()`` never registers a foreign thread in
    ``threading._active``, so ``enumerate()``-based liveness cannot see it at
    all; once ``current_thread()`` registers a ``_DummyThread``,
    ``Thread.is_alive()`` misreports it (raises RuntimeError after death on
    some platforms/Python versions). Either way pruning must stay exact:
    never raise, and reap the dead thread's connection via its OS thread id.
    """
    from PySide6.QtCore import QThread

    class _OpeningThread(QThread):
        def run(self) -> None:  # executes on the new OS thread
            index.open()
            # Touch current_thread() so the foreign thread registers a
            # ``_DummyThread`` in ``threading._active`` — the state in which
            # Python >=3.13 makes ``Thread.is_alive()`` RAISE after death.
            threading.current_thread()

    index = CatalogIndex(tmp_path)
    qt = _OpeningThread()
    qt.start()
    qt.wait(5000)
    assert qt.isFinished()

    # Must neither raise nor leak the foreign thread's connection.
    index.prune_dead_threads()
    index.prune_dead_threads()  # idempotent
    assert len(index._conns) == 0
    index.close()


def test_live_foreign_qthread_connection_survives_prune(tmp_path: Path, qapp):
    """A *running* foreign thread's connection must never be pruned (#1026)."""
    from PySide6.QtCore import QThread

    opened = threading.Event()
    release = threading.Event()
    errors: list[Exception] = []

    class _HoldingThread(QThread):
        def run(self) -> None:
            try:
                conn = index.open()
                opened.set()
                # Stay alive while the main thread prunes repeatedly.
                deadline = time.monotonic() + 1.0
                while not release.is_set() and time.monotonic() < deadline:
                    conn.execute("SELECT 1").fetchall()
                    time.sleep(0.005)
            except Exception as exc:  # pragma: no cover - failure signal
                errors.append(exc)
            finally:
                opened.set()

    index = CatalogIndex(tmp_path)
    qt = _HoldingThread()
    qt.start()
    assert opened.wait(timeout=5.0)

    for _ in range(10):
        index.prune_dead_threads()
        assert len(index._conns) == 1, "live foreign connection was pruned"

    release.set()
    qt.wait(5000)
    assert errors == []
    index.close()


# ---------------------------------------------------------------------------
# Ident recycling
# ---------------------------------------------------------------------------


def _pooled_conn(index: CatalogIndex, ident: int):
    """Raw connection behind a pooled entry, whatever the pool's entry type."""
    entry = index._conns[ident]
    return getattr(entry, "conn", entry)


@_linux_only
def test_recycled_ident_never_inherits_dead_threads_connection(tmp_path: Path):
    """A new thread that recycles a dead ident must not reuse its handle.

    ``threading.get_ident()`` values are recyclable; the pool keys on them.
    Pre-fix, ``_connect()`` returned the stale cached handle to whichever
    thread next inherited the id (``check_same_thread=False`` masked the
    violation), silently sharing one connection across two OS threads.
    """
    index = CatalogIndex(tmp_path)
    # Simulate the hazard deterministically: a pooled entry registered under
    # THIS thread's ident but created by a different (now dead) OS thread.
    foreign_conn = sqlite3.connect(":memory:", check_same_thread=False)
    index._conns[threading.get_ident()] = _stale_entry_for(foreign_conn)

    conn = index.open()
    assert conn is not foreign_conn, "_connect() handed over a foreign handle"

    with pytest.raises(sqlite3.ProgrammingError):
        # The stale handle must have been closed, not merely dropped.
        foreign_conn.execute("SELECT 1")
    index.close()


def _stale_entry_for(conn: sqlite3.Connection):
    """Build the pooled-entry shape for *conn* as if owned by a dead thread.

    Uses the module's own entry type (or a pre-fix plain connection, which
    the test detects through behaviour rather than structure).
    """
    from paleo_workbench.catalog import db as db_module

    entry_cls = getattr(db_module, "_ConnEntry", None)
    if entry_cls is None:
        return conn  # pre-fix pool stores bare connections
    dead_native_id = _find_dead_native_id()
    return entry_cls(conn=conn, native_id=dead_native_id)


def _find_dead_native_id() -> int:
    """A native id that provably belongs to no live thread of this process."""
    import os

    candidate = threading.get_native_id()
    while candidate < 2**31:
        if not os.path.exists(f"/proc/self/task/{candidate}"):
            return candidate
        candidate += 1
    raise AssertionError("no dead native id found")  # pragma: no cover


# ---------------------------------------------------------------------------
# Lifecycle under load
# ---------------------------------------------------------------------------


@_linux_only
def test_pool_drains_after_many_worker_threads_finish(tmp_path: Path):
    """The pool returns to zero after workers exit and pruning runs."""
    index = CatalogIndex(tmp_path)
    with index.session() as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO items VALUES (1)")

    threads = [
        threading.Thread(target=lambda: index.open().execute("SELECT * FROM items"))
        for _ in range(24)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    index.prune_dead_threads()
    assert len(index._conns) == 0
    index.close()


def test_close_leaves_no_handles_and_survives_concurrent_use(tmp_path: Path):
    """close() under concurrent workers: no crash, no pool residue."""
    index = CatalogIndex(tmp_path)
    stop = threading.Event()
    failures: list[BaseException] = []

    def churn(worker_id: int) -> None:
        try:
            while not stop.is_set():
                try:
                    conn = index.open()
                    conn.execute("SELECT 1").fetchall()
                except sqlite3.OperationalError:
                    pass  # interrupted mid-flight is acceptable
        except BaseException as exc:  # pragma: no cover - failure signal
            failures.append(exc)

    threads = [threading.Thread(target=churn, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    time.sleep(0.1)
    index.close()
    index.close()  # idempotent
    stop.set()
    for t in threads:
        t.join(timeout=10.0)

    assert failures == []
    # Workers may legitimately have reconnected after close(); once they are
    # all joined, pruning must return the pool to zero. Bounded poll:
    # join() can return before OS-thread termination finishes, so the
    # first probe may still see owners alive (Windows teardown race).
    import time as _time

    deadline = _time.monotonic() + 5.0
    while index._conns and _time.monotonic() < deadline:
        index.prune_dead_threads()
        if index._conns:
            _time.sleep(0.02)
    assert len(index._conns) == 0


# ---------------------------------------------------------------------------
# Adversarial production-path stress (#1026 acceptance)
# ---------------------------------------------------------------------------


def _run_worker_storm(project_dir: Path, worker_count: int, stop: threading.Event):
    """Mixed read/write/cancel/abrupt-exit storm through production paths.

    Returns (service, errors). Cohorts:
    * readers   — service.list_assets + raw index sessions (parallel reads),
                  honouring the cooperative stop event (cancellation);
    * writers   — service.import_raw of unique tiny files (serialized writes);
    * leakers   — open a connection, return WITHOUT session exit (worker
                  exits mid-operation; the next prune must reap it).
    """
    from paleo_workbench.catalog.service import DataCatalogService

    service = DataCatalogService.open(project_dir)
    errors: list[BaseException] = []
    start = threading.Barrier(worker_count)
    # Cooperative cancellation deadline: readers must observe and exit.
    cancel = threading.Timer(1.5, stop.set)
    cancel.start()

    def reader(wid: int) -> None:
        try:
            start.wait(timeout=10.0)
            while not stop.is_set():
                service.list_assets()
                with service._index.session() as conn:
                    conn.execute("SELECT count(*) FROM assets").fetchone()
        except BaseException as exc:
            errors.append(exc)

    def writer(wid: int) -> None:
        try:
            start.wait(timeout=10.0)
            for i in range(6):
                if stop.is_set():
                    break
                src = project_dir / f"w{wid}-{i}.dat"
                src.write_bytes(f"payload-{wid}-{i}".encode())
                service.import_raw(src, name=f"stress-{wid}-{i}", type="raw")
        except BaseException as exc:
            errors.append(exc)

    def leaker(wid: int) -> None:
        # Abrupt exit: connection stays pooled; the next prune must reap it.
        start.wait(timeout=10.0)
        service._index.open().execute("SELECT 1").fetchall()

    threads = []
    for w in range(worker_count):
        cohort = w % 8
        target = reader if cohort < 5 else writer if cohort < 7 else leaker
        threads.append(threading.Thread(target=target, args=(w,)))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
        assert not t.is_alive(), "worker thread hung under stress"
    cancel.cancel()  # the deadline fired during the storm; nothing pending
    return service, errors


def test_worker_storm_no_crash_no_leak_across_project_switch(tmp_path: Path):
    """64-worker storm on two projects: no crash, no residue, pool drains."""
    project_a = tmp_path / "proj-a"
    project_a.mkdir()
    stop = threading.Event()
    service_a, errors_a = _run_worker_storm(project_a, 64, stop)
    stop.set()

    # Project switch: close the first catalog, storm a second project.
    service_a._index.prune_dead_threads()
    pool_a = len(service_a._index._conns)
    main_had_conn = threading.get_ident() in service_a._index._conns
    imported_a = len(service_a.list_assets())
    service_a.close()

    project_b = tmp_path / "proj-b"
    project_b.mkdir()
    stop_b = threading.Event()
    service_b, errors_b = _run_worker_storm(project_b, 56, stop_b)
    stop_b.set()
    service_b._index.prune_dead_threads()

    assert errors_a == []
    assert errors_b == []
    # After workers terminate only the MAIN thread's own connection may
    # remain (created by DataCatalogService.open on this thread); every
    # dead worker's connection must have been reaped.
    assert pool_a == (1 if main_had_conn else 0), "pool did not drain"
    assert len(service_b._index._conns) <= 1
    assert imported_a > 0, "writers made no progress under contention"
    service_b.close()


def test_shutdown_during_active_statement_interrupts_cleanly(tmp_path: Path):
    """close() while a worker is mid-statement: interrupt, never SIGSEGV."""
    from paleo_workbench.catalog.service import DataCatalogService

    project = tmp_path / "proj"
    project.mkdir()
    service = DataCatalogService.open(project, ensure_index=False)
    observed: list[BaseException] = []

    def long_runner() -> None:
        try:
            conn = service._index.open()
            conn.execute(
                "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c"
                " WHERE x < 200000000) SELECT count(*) FROM c"
            ).fetchall()
        except sqlite3.Error as exc:
            observed.append(exc)  # interrupt lands here, never a crash
        except BaseException as exc:  # pragma: no cover - failure signal
            observed.append(exc)

    t = threading.Thread(target=long_runner)
    t.start()
    time.sleep(0.2)  # let the recursive CTE get executing
    service.close()
    t.join(timeout=15.0)

    assert not t.is_alive()
    assert observed, "worker finished before close() — test did not race"
    assert all(isinstance(e, sqlite3.OperationalError) for e in observed), observed
    assert len(service._index._conns) == 0
