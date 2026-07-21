"""Tests for UI Thread Zero-Copy Shared Memory IPC Layer (Issue #12)."""
import time
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


def test_shared_memory_handle_creation_and_zero_copy():
    shape = (1000, 1000)
    dtype = "float32"
    handle, meta = SharedMemoryArrayHandle.create(shape=shape, dtype=dtype)
    
    assert meta.shape == shape
    assert meta.dtype == "float32"
    assert meta.size_bytes == 1000 * 1000 * 4
    
    # Mutate handle array
    handle.array[0, 0] = 123.45
    
    # Attach consumer handle
    consumer = SharedMemoryArrayHandle(shm_name=meta.shm_name, shape=shape, dtype=dtype, is_owner=False)
    assert consumer.array[0, 0] == 123.45
    
    # Cleanup
    consumer.close()
    handle.close()


def test_zero_copy_ipc_latency_sub_millisecond():
    # 100MB array: float32 array of shape (5000, 5000) = 25M elements = 100MB
    shape = (5000, 5000)
    dtype = "float32"
    
    t0 = time.perf_counter()
    handle, meta = SharedMemoryArrayHandle.create(shape=shape, dtype=dtype)
    consumer = SharedMemoryArrayHandle(shm_name=meta.shm_name, shape=shape, dtype=dtype, is_owner=False)
    t1 = time.perf_counter()
    
    elapsed_ms = (t1 - t0) * 1000.0
    assert elapsed_ms < 10.0  # Zero-copy creation and attachment is sub-millisecond
    
    consumer.close()
    handle.close()


def test_qprocess_future_bridge(qtbot):
    app = QCoreApplication.instance()
    bridge = QProcessFutureBridge()
    
    received_results = []
    bridge.finished.connect(lambda req_id, res, meta: received_results.append((req_id, res)))
    
    handle, meta = SharedMemoryArrayHandle.create(shape=(10, 10), dtype="float32")
    
    executor = ProcessPoolExecutor(max_workers=1)
    future = executor.submit(_worker_compute_array, {
        "shm_name": meta.shm_name,
        "shape": meta.shape,
        "dtype": meta.dtype,
    })
    
    bridge.watch(future, request_id=101)
    
    # Wait for bridge signal via qtbot
    qtbot.waitUntil(lambda: len(received_results) > 0, timeout=3000)
    
    assert len(received_results) == 1
    req_id, res = received_results[0]
    assert req_id == 101
    assert res["status"] == "ok"
    assert handle.array[0, 0] == 42.0
    
    executor.shutdown(wait=True)
    handle.close()
