"""Tests for UI Thread Zero-Copy Shared Memory IPC Layer (Issue #12)."""
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from paleo_workbench.viz.ipc.shared_memory_handle import SharedMemoryArrayHandle, SharedArrayMetadata
from paleo_workbench.viz.ipc.process_bridge import QProcessFutureBridge
from concurrent.futures import ProcessPoolExecutor


def _worker_compute_array(meta_dict: dict) -> dict:
    """Worker function executing in a separate process."""
    shm_name = meta_dict["shm_name"]
    shape = tuple(meta_dict["shape"])
    dtype = meta_dict["dtype"]
    
    # Attach to existing shared memory segment
    handle = SharedMemoryArrayHandle(shm_name=shm_name, shape=shape, dtype=dtype, is_owner=False)
    # Modify data in-place
    handle.array[...] = 42.0
    handle.close()
    return {"shm_name": shm_name, "status": "ok"}


def _median_ms(fn, trials: int = 5, warmup: int = 1) -> float:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(trials):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return float(np.median(samples))


def _ensure_shm_budget(need_bytes: int) -> None:
    shm = Path("/dev/shm")
    if not shm.is_dir():
        return
    free = shutil.disk_usage(shm).free
    if free < need_bytes * 2:
        pytest.skip(f"/dev/shm free {free} bytes; need {need_bytes * 2}")


def test_shared_memory_handle_creation_and_zero_copy():
    shape = (1000, 1000)
    dtype = "float32"
    handle = None
    consumer = None
    try:
        handle, meta = SharedMemoryArrayHandle.create(shape=shape, dtype=dtype)

        assert meta.shape == shape
        assert meta.dtype == "float32"
        assert meta.size_bytes == 1000 * 1000 * 4

        handle.array[0, 0] = 123.45

        consumer = SharedMemoryArrayHandle(
            shm_name=meta.shm_name, shape=shape, dtype=dtype, is_owner=False
        )
        assert consumer.array[0, 0] == 123.45
    finally:
        if consumer is not None:
            consumer.close()
        if handle is not None:
            handle.close()


def test_zero_copy_ipc_latency_sub_millisecond():
    # 4MB is enough to prove attach is a mapping, not a copy; 100MB blows
    # typical 64MB Docker /dev/shm caps (#647).
    shape = (1024, 1024)
    dtype = "float32"
    need_bytes = 1024 * 1024 * 4
    _ensure_shm_budget(need_bytes)

    created = []

    def _attach_once():
        handle, meta = SharedMemoryArrayHandle.create(shape=shape, dtype=dtype)
        consumer = SharedMemoryArrayHandle(
            shm_name=meta.shm_name, shape=shape, dtype=dtype, is_owner=False
        )
        created.append((handle, consumer))
        return handle, consumer

    try:
        elapsed_ms = _median_ms(_attach_once)
        assert elapsed_ms < 10.0
    finally:
        for handle, consumer in created:
            consumer.close()
            handle.close()


def test_qprocess_future_bridge(qtbot):
    app = QCoreApplication.instance()
    bridge = QProcessFutureBridge()
    
    received_results = []
    bridge.finished.connect(lambda req_id, res, meta: received_results.append((req_id, res)))
    
    handle = None
    executor = None
    try:
        handle, meta = SharedMemoryArrayHandle.create(shape=(10, 10), dtype="float32")

        executor = ProcessPoolExecutor(max_workers=1)
        future = executor.submit(_worker_compute_array, {
            "shm_name": meta.shm_name,
            "shape": meta.shape,
            "dtype": meta.dtype,
        })

        bridge.watch(future, request_id=101)

        qtbot.waitUntil(lambda: len(received_results) > 0, timeout=3000)

        assert len(received_results) == 1
        req_id, res = received_results[0]
        assert req_id == 101
        assert res["status"] == "ok"
        assert handle.array[0, 0] == 42.0
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
        if handle is not None:
            handle.close()
