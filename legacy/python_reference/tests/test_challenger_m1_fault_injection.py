"""Empirical Fault Injection & Edge-Case Stress Harness for Milestone 1.

Author: Challenger M1_2
Scope:
1. Worker exceptions in _FactorMapWorker & OwnedWorkerJob (propagation, thread teardown, no leaks).
2. SQLite database exceptions in ThreadSafeCatalogSession & CatalogIndex (lock leaks, rollbacks, concurrency).
3. Native backend fallback on C++ exceptions, disabling, and missing native modules.
"""
from __future__ import annotations

import gc
import math
import sqlite3
import threading
import time
import types
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from paleo_workbench.catalog.db import CatalogIndex, ThreadSafeCatalogSession
from paleo_workbench.mapping.layers import MapDocument
from paleo_workbench.native_backend import (
    NativeEngineBackend,
    _NATIVE_MODULES,
    disabled_acceleration,
    is_accelerated,
    native_backend,
    native_status,
)
from paleo_workbench.project.models import ProjectDocument, ProjectMeta
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.create_factor_map_dialog import (
    CreateFactorMapDialog,
    _FactorMapWorker,
)
from paleo_workbench.ui.thread_keeper import detached_job_keeper


# ============================================================================
# 1. WORKER EXCEPTION & THREAD TEARDOWN STRESS TESTS
# ============================================================================

class CustomDomainException(Exception):
    """Custom scientific exception."""
    pass


class _FaultyWorker(QObject):
    """Custom worker designed to throw configurable exceptions."""
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, exc_to_raise: Exception | None = None, delay: float = 0.0) -> None:
        super().__init__()
        self.exc_to_raise = exc_to_raise
        self.delay = delay
        self.started_event = threading.Event()
        self.ran_off_gui = False

    @Slot()
    def run(self) -> None:
        app = QApplication.instance()
        if app is not None:
            self.ran_off_gui = QThread.currentThread() is not app.thread()
        self.started_event.set()
        if self.delay > 0:
            time.sleep(self.delay)
        if self.exc_to_raise:
            if QThread.currentThread().isInterruptionRequested():
                return
            self.failed.emit(str(self.exc_to_raise))
        else:
            if QThread.currentThread().isInterruptionRequested():
                return
            self.finished.emit("SUCCESS")


@pytest.mark.parametrize(
    "exc",
    [
        ZeroDivisionError("division by zero in kriging weights"),
        RuntimeError("Singular matrix encountered during covariance inversion"),
        MemoryError("Out of memory allocating grid array"),
        ValueError("Invalid variogram model parameters"),
        KeyError("Missing required well property 'porosity'"),
        CustomDomainException("Geological facies boundary constraint violation"),
    ],
)
def test_factor_map_worker_exception_propagation_and_thread_teardown(qtbot, exc):
    """Test that all types of exceptions inside _FactorMapWorker emit 'failed' and cleanly terminate the QThread."""
    mock_service = Mock()
    mock_service.create_factor_map.side_effect = exc
    project = ProjectDocument(meta=ProjectMeta(name="fault_test_proj"))
    params = {"factor_name": "孔隙度", "grid_n": 50}

    worker = _FactorMapWorker(mock_service, project, params)
    job = OwnedWorkerJob()

    failed_messages: list[str] = []
    finished_results: list[object] = []
    released_signals: list[bool] = []

    job.released.connect(lambda: released_signals.append(True))
    job.start(
        worker,
        terminal_signals=(worker.finished, worker.failed),
        result_connections=(
            (worker.finished, finished_results.append),
            (worker.failed, failed_messages.append),
        ),
    )

    qtbot.waitUntil(lambda: len(failed_messages) == 1, timeout=3_000)
    assert len(finished_results) == 0
    assert str(exc) in failed_messages[0]

    # Verify thread teardown
    qtbot.waitUntil(lambda: job.is_running is False, timeout=3_000)
    assert job.thread is None
    assert job.worker is None
    assert released_signals == [True]


def test_owned_worker_job_sequential_fault_and_recovery(qtbot):
    """Stress test reusing OwnedWorkerJob across alternating failures and successes."""
    job = OwnedWorkerJob()

    # Pass 1: Failure
    w1 = _FaultyWorker(exc_to_raise=RuntimeError("Worker 1 Fault"))
    f1: list[str] = []
    job.start(
        w1,
        terminal_signals=(w1.finished, w1.failed),
        result_connections=((w1.failed, f1.append),),
    )
    qtbot.waitUntil(lambda: len(f1) == 1, timeout=3_000)
    qtbot.waitUntil(lambda: not job.is_running, timeout=3_000)
    assert f1 == ["Worker 1 Fault"]

    # Pass 2: Success
    w2 = _FaultyWorker(exc_to_raise=None)
    succ2: list[object] = []
    job.start(
        w2,
        terminal_signals=(w2.finished, w2.failed),
        result_connections=((w2.finished, succ2.append),),
    )
    qtbot.waitUntil(lambda: len(succ2) == 1, timeout=3_000)
    qtbot.waitUntil(lambda: not job.is_running, timeout=3_000)
    assert succ2 == ["SUCCESS"]

    # Pass 3: Another Failure
    w3 = _FaultyWorker(exc_to_raise=ValueError("Worker 3 Fault"))
    f3: list[str] = []
    job.start(
        w3,
        terminal_signals=(w3.finished, w3.failed),
        result_connections=((w3.failed, f3.append),),
    )
    qtbot.waitUntil(lambda: len(f3) == 1, timeout=3_000)
    qtbot.waitUntil(lambda: not job.is_running, timeout=3_000)
    assert f3 == ["Worker 3 Fault"]


def test_worker_exception_during_dialog_destruction_race(qtbot):
    """Stress test race condition where worker fails while dialog is closing/rejecting."""
    started = threading.Event()
    release = threading.Event()

    def _stuck_then_fail(*args, **kwargs):
        started.set()
        release.wait(timeout=5.0)
        raise RuntimeError("Late failure after dialog close")

    mock_service = Mock()
    mock_service.create_factor_map.side_effect = _stuck_then_fail

    project = ProjectDocument(meta=ProjectMeta(name="race_test_proj"))
    dialog = CreateFactorMapDialog(project)
    qtbot.addWidget(dialog)
    dialog.service = mock_service

    dialog._on_create_clicked()
    assert started.wait(timeout=2.0)
    assert dialog._job.is_running is True

    # Close dialog immediately
    dialog.close()
    assert not dialog._job.is_running

    # Release worker to fail in detached state
    release.set()
    time.sleep(0.1)
    QApplication.processEvents()


def test_guarded_slot_drops_delivery_when_qobject_deleted(qtbot):
    """Verify that _guarded slot in OwnedWorkerJob silently drops calls when target QObject is deleted."""
    worker = _FaultyWorker(exc_to_raise=None)
    job = OwnedWorkerJob()

    invoked = []

    def slot_raising_runtime_error(res):
        invoked.append(True)
        # Simulate PySide6: "Internal C++ object (QWidget) already deleted"
        raise RuntimeError("Internal C++ object (QWidget) already deleted")

    job.start(
        worker,
        terminal_signals=(worker.finished, worker.failed),
        result_connections=((worker.finished, slot_raising_runtime_error),),
    )

    qtbot.waitUntil(lambda: len(invoked) == 1, timeout=3_000)
    qtbot.waitUntil(lambda: not job.is_running, timeout=3_000)
    assert job.thread is None
    assert job.worker is None


def test_factor_map_worker_with_corrupted_parameters(qtbot):
    """Verify _FactorMapWorker handles invalid / empty parameter dictionaries gracefully."""
    mock_service = Mock()
    mock_service.create_factor_map.side_effect = KeyError("factor_name")
    project = ProjectDocument(meta=ProjectMeta(name="corrupted_params_proj"))
    # Missing 'factor_name'
    bad_params = {}

    worker = _FactorMapWorker(mock_service, project, bad_params)
    job = OwnedWorkerJob()

    failures = []
    job.start(
        worker,
        terminal_signals=(worker.finished, worker.failed),
        result_connections=((worker.failed, failures.append),),
    )

    qtbot.waitUntil(lambda: len(failures) == 1, timeout=3_000)
    assert "'factor_name'" in failures[0]
    qtbot.waitUntil(lambda: not job.is_running, timeout=3_000)


# ============================================================================
# 2. SQLITE DATABASE EXCEPTION & LOCK LEAK STRESS TESTS
# ============================================================================

def test_sqlite_exception_in_session_drops_connection_and_releases_locks(tmp_path):
    """Test that SQLite syntax or runtime errors inside ThreadSafeCatalogSession cleanly close connection."""
    index = CatalogIndex(tmp_path)
    tid = threading.get_ident()

    # Verify normal entry and exception exit
    with pytest.raises(RuntimeError, match="Synthetic app fault"):
        with index.session() as conn:
            assert tid in index._conns
            conn.execute("CREATE TABLE test_data (id INT, val TEXT)")
            conn.execute("INSERT INTO test_data VALUES (1, 'val1')")
            raise RuntimeError("Synthetic app fault")

    # Connection must be purged from pool immediately
    assert tid not in index._conns

    # Verify a new session can immediately open and operate without locks
    with index.session() as conn2:
        assert tid in index._conns
        conn2.execute("CREATE TABLE IF NOT EXISTS test_data (id INT, val TEXT)")
        conn2.execute("INSERT INTO test_data VALUES (2, 'val2')")
        rows = conn2.execute("SELECT count(*) as cnt FROM test_data").fetchone()
        assert rows["cnt"] >= 1

    assert tid not in index._conns


def test_sqlite_abandoned_transaction_rollback_and_lock_freedom(tmp_path):
    """Verify that an uncommitted transaction abandoned by an exception releases WAL write locks."""
    index = CatalogIndex(tmp_path)

    # Initialize table
    with index.session() as conn:
        conn.execute("CREATE TABLE account (id INT PRIMARY KEY, balance REAL)")
        conn.execute("INSERT INTO account VALUES (1, 100.0)")
        conn.commit()

    # Thread 1 starts transaction, modifies row, then raises exception before commit
    t1_done = threading.Event()
    t1_error = []

    def faulty_writer():
        try:
            with index.session() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE account SET balance = 500.0 WHERE id = 1")
                raise ValueError("Crash before committing transaction")
        except Exception as e:
            t1_error.append(e)
        finally:
            t1_done.set()

    t1 = threading.Thread(target=faulty_writer)
    t1.start()
    t1.join(timeout=5.0)

    assert len(t1_error) == 1
    assert isinstance(t1_error[0], ValueError)

    # Thread 2 immediately attempts write; must succeed without database locked error
    with index.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE account SET balance = 200.0 WHERE id = 1")
        conn.commit()
        row = conn.execute("SELECT balance FROM account WHERE id = 1").fetchone()
        assert row["balance"] == 200.0


def test_concurrent_threads_heavy_fault_injection_on_sqlite(tmp_path):
    """Stress test 40 concurrent threads mixing normal ops, syntax errors, and custom exceptions."""
    index = CatalogIndex(tmp_path)

    with index.session() as conn:
        conn.execute("CREATE TABLE logs (tid INT, step INT, data TEXT)")
        conn.commit()

    num_threads = 40
    thread_errors: list[Exception] = []

    def stress_worker(worker_id: int):
        for step in range(10):
            try:
                with index.session() as conn:
                    if worker_id % 3 == 0:
                        # Fault 1: Syntax error
                        conn.execute("MALFORMED SQL SYNTAX !!!")
                    elif worker_id % 3 == 1:
                        # Fault 2: Python exception mid-operation
                        conn.execute("INSERT INTO logs VALUES (?, ?, ?)", (worker_id, step, "partial"))
                        if step % 2 == 1:
                            raise ArithmeticError("Fault injection error")
                        conn.commit()
                    else:
                        # Normal valid write
                        conn.execute("INSERT INTO logs VALUES (?, ?, ?)", (worker_id, step, "ok"))
                        conn.commit()
            except (sqlite3.OperationalError, ArithmeticError):
                pass
            except Exception as e:
                thread_errors.append(e)
            time.sleep(0.001)

    threads = [threading.Thread(target=stress_worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert thread_errors == []
    # All thread connections must be dropped
    assert len(index._conns) == 0

    # Main thread can query database cleanly
    with index.session() as conn:
        row = conn.execute("SELECT count(*) as cnt FROM logs").fetchone()
        assert row["cnt"] >= 0


def test_drop_current_connection_on_unopened_and_closed_conn(tmp_path):
    """Verify drop_current_connection handles non-existent or already-closed handles idempotently."""
    index = CatalogIndex(tmp_path)
    # Calling drop when no connection exists
    index.drop_current_connection()
    assert len(index._conns) == 0

    # Open, close explicitly, then drop
    conn = index.open()
    conn.close()
    index.drop_current_connection()
    assert len(index._conns) == 0


def _prune_until_empty(index, timeout_s: float = 5.0) -> None:
    """Bounded prune poll: Thread.join() can return before the OS thread
    finishes terminating (CPython releases the join lock inside thread
    bootstrap), so a single immediate prune legitimately still sees the
    thread alive. Poll until the pool drains or the deadline — the
    contract under test is "pruned after teardown", not "within
    microseconds of join()".
    """
    import time as _time

    deadline = _time.monotonic() + timeout_s
    while index._conns and _time.monotonic() < deadline:
        index.prune_dead_threads()
        if index._conns:
            _time.sleep(0.02)


def test_dead_thread_pruning_under_proc_task(tmp_path):
    """Verify dead thread connections are correctly pruned even when threads terminate abruptly."""
    index = CatalogIndex(tmp_path)

    dead_tids = []

    def unmanaged_worker():
        conn = index.open()
        dead_tids.append(threading.get_ident())
        conn.execute("SELECT 1")

    t = threading.Thread(target=unmanaged_worker)
    t.start()
    t.join(timeout=5.0)

    assert dead_tids[0] in index._conns

    # Trigger prune (bounded poll — see _prune_until_empty)
    _prune_until_empty(index)
    assert dead_tids[0] not in index._conns


# ============================================================================
# 3. NATIVE BACKEND FALLBACK & C++ EXCEPTION STRESS TESTS
# ============================================================================

def test_all_12_native_fallback_functions_execute_under_disabled_acceleration():
    """Verify all 12 functions in _FALLBACK_TABLE execute properly under disabled_acceleration()."""
    with disabled_acceleration():
        # 1. fast_slice_extract
        vol = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
        s1 = native_backend.dispatch("fast_slice_extract", vol, 0, 1)
        assert s1.shape == (3, 4)

        # 2. fast_slice_to_indexed8
        s2, vmin, vmax = native_backend.dispatch("fast_slice_to_indexed8", vol, 0, 1)
        assert s2.shape == (3, 4)
        assert s2.dtype == np.uint8

        # 3. fast_resample_volume_3d
        s3 = native_backend.dispatch("fast_resample_volume_3d", vol, (4, 6, 8))
        assert s3.shape == (4, 6, 8)

        # 4. compute_coherence_3d
        s4 = native_backend.dispatch("compute_coherence_3d", vol, 3)
        assert s4.shape == vol.shape

        # 5. marching_cubes_3d
        verts, faces = native_backend.dispatch("marching_cubes_3d", vol, 10.0)
        assert isinstance(verts, np.ndarray)
        assert isinstance(faces, np.ndarray)

        # 6. minmax_downsample
        depths = np.linspace(0, 100, 500, dtype=np.float32)
        values_arr = np.sin(depths).astype(np.float32)
        d_out, v_out = native_backend.dispatch("minmax_downsample", depths, values_arr, 50)
        assert len(d_out) <= 100

        # 7. fast_las_parse_data
        las_txt = "~VERSION\n~CURVE\nDEPT.M :\nGR.GAPI :\n~A\n100.0 55.0\n100.5 60.0\n"
        headers, data = native_backend.dispatch("fast_las_parse_data", las_txt, -999.0)
        assert "DEPT" in headers
        assert data.shape == (2, 2)

        # 8. hit_test
        features = [{"id": "feat_1", "coordinates": [[0.0, 0.0], [1.0, 1.0]]}]
        hit = native_backend.dispatch("hit_test", features, 0.05, 0.05, 0.1)
        assert hit == "feat_1"

        # 9. snap_point
        pts = [(0.0, 0.0), (10.0, 10.0)]
        snap = native_backend.dispatch("snap_point", pts, 9.9, 10.1, 0.5)
        assert snap == (10.0, 10.0)

        # 10. validate_ring
        ring = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
        val = native_backend.dispatch("validate_ring", ring)
        assert isinstance(val, list)

        # 11. render_grid_rgba
        grid_z = np.ones((10, 10), dtype=np.float32)
        lut = np.ones((256, 4), dtype=np.uint8) * 255
        rgba = native_backend.dispatch("render_grid_rgba", grid_z, None, lut, 0.0, 2.0, 1.0, 255)
        assert rgba.shape == (10, 10, 4)
        assert rgba.dtype == np.uint8

        # 12. dtw_match_curves
        c1 = np.array([1.0, 2.0, 3.0, 4.0])
        c2 = np.array([1.1, 1.9, 3.2, 4.0])
        cost, p1, p2 = native_backend.dispatch("dtw_match_curves", c1, c2)
        assert cost >= 0.0
        assert len(p1) > 0


def test_missing_native_module_triggers_seamless_fallback(monkeypatch):
    """When a native module is completely absent (None), dispatch transparently uses Python fallback."""
    fake_backend = NativeEngineBackend()
    monkeypatch.setattr(fake_backend, "has_cpp", lambda feat: False)

    # Dispatch fast_slice_extract
    vol = np.zeros((4, 4, 4), dtype=np.float32)
    res = fake_backend.dispatch("fast_slice_extract", vol, 0, 0)
    assert res.shape == (4, 4)


def test_cpp_exception_handling_in_dispatch(monkeypatch):
    """Verify that if a C++ extension raises a C++ exception, it surfaces cleanly in Python without SIGSEGV."""
    mock_cpp_mod = Mock()
    mock_cpp_mod.fast_slice_extract.side_effect = RuntimeError("C++ std::runtime_error: out of bounds")

    backend = NativeEngineBackend()
    monkeypatch.setattr(backend, "is_accelerated", lambda feat: True)
    monkeypatch.setitem(backend._FUNCTION_MODULE_MAP, "fast_slice_extract", ("seismic_3d", mock_cpp_mod))

    vol = np.zeros((4, 4, 4), dtype=np.float32)
    with pytest.raises(RuntimeError, match="C\\+\\+ std::runtime_error"):
        backend.dispatch("fast_slice_extract", vol, 0, 100)


def test_nested_and_multithreaded_disabled_acceleration():
    """Verify disabled_acceleration context manager correctly handles nesting and thread safety.

    Self-contained (#1101): the old version asserted the AMBIENT acceleration
    state, which is an environment property (module present and status
    "fresh") and an ordering property (a prior test's leaked toggle).  The
    toggle contract itself only needs the acceleration to be observable —
    skip cleanly where the C++ module is absent/stale.
    """
    if not is_accelerated("map_edit"):
        pytest.skip("map_edit native acceleration not available/fresh in this environment")

    with disabled_acceleration():
        assert is_accelerated("map_edit") is False
        with disabled_acceleration():
            assert is_accelerated("map_edit") is False
        assert is_accelerated("map_edit") is False

    assert is_accelerated("map_edit") is True


def test_disabled_acceleration_exit_order_cannot_leak():
    """Regression #1101: exiting contexts in reverse order (the cross-thread
    interleaving worst case) must restore acceleration exactly once the LAST
    context exits — never leave the forced fallback stuck on."""
    from paleo_workbench.native_backend import native_backend

    if not is_accelerated("map_edit"):
        pytest.skip("map_edit native acceleration not available/fresh in this environment")

    outer = native_backend.disabled_acceleration()
    inner = native_backend.disabled_acceleration()
    outer.__enter__()
    inner.__enter__()
    try:
        assert is_accelerated("map_edit") is False
    finally:
        # Outer exits BEFORE inner — under the old save/restore bool this
        # restored prev=True and leaked the disabled state permanently.
        outer.__exit__(None, None, None)
        inner.__exit__(None, None, None)
    assert is_accelerated("map_edit") is True


def test_disabled_acceleration_depth_transitions_are_environment_independent():
    """#1101: the depth counter must count in/out exactly, even on hosts
    without any native module (where is_accelerated is False regardless) —
    this pins the toggle mechanics the skip-guarded tests cannot reach."""
    from paleo_workbench.native_backend import native_backend

    assert native_backend._force_depth == 0
    outer = native_backend.disabled_acceleration()
    inner = native_backend.disabled_acceleration()
    outer.__enter__()
    inner.__enter__()
    try:
        assert native_backend._force_depth == 2
        assert is_accelerated("map_edit") is False
    finally:
        outer.__exit__(None, None, None)
        assert native_backend._force_depth == 1
        inner.__exit__(None, None, None)
    assert native_backend._force_depth == 0


def test_adversarial_inputs_to_native_fallbacks():
    """Stress test boundary inputs (NaNs, Infs, non-contiguous, out of bounds) against Python fallbacks."""
    with disabled_acceleration():
        # Slicing out of bounds must raise IndexError
        vol = np.zeros((3, 3, 3), dtype=np.float32)
        with pytest.raises(IndexError):
            native_backend.dispatch("fast_slice_extract", vol, axis=0, index=99)

        # Slice to indexed8 with all NaNs
        nan_vol = np.full((3, 3, 3), np.nan, dtype=np.float32)
        idx8, vmin, vmax = native_backend.dispatch("fast_slice_to_indexed8", nan_vol, 0, 0)
        assert np.all(idx8 == 0)
        assert vmin == 0.0 and vmax == 0.0

        # Minmax downsample with empty array
        empty_d = np.array([], dtype=np.float32)
        empty_v = np.array([], dtype=np.float32)
        d_out, v_out = native_backend.dispatch("minmax_downsample", empty_d, empty_v, 10)
        assert len(d_out) == 0

        # Render grid RGBA with invalid opacity
        grid_z = np.ones((5, 5), dtype=np.float32)
        lut = np.ones((10, 4), dtype=np.uint8)
        with pytest.raises(ValueError, match="opacity must be in 0..255"):
            native_backend.dispatch("render_grid_rgba", grid_z, None, lut, 0.0, 1.0, 1.0, 300)
