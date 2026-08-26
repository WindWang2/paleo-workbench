# Paleo Workbench Core Convergence: Runtime Stability & Native Safety Specification

**Author:** Runtime Stability & Native Safety Team (Worker M1)  
**Status:** Converged Specification & Implementation Guide  
**Date:** 2026-08-25  

---

## 1. Overview & Objectives

Desktop scientific applications encounter complex stability challenges: long-running mathematical computations, multithreaded database access, asynchronous GPU resource management, and C++ native memory boundary management.

This document specifies the converged **Runtime Stability Architecture** across four foundational domains:
1. **Background Worker Thread Lifecycle & Cooperative Cancellation**
2. **SQLite Database Thread Confinement & Concurrency**
3. **Context-Scoped Deferred OpenGL Resource Management**
4. **Native C++ pybind11 Memory, GIL, and Metadata Safety**

---

## 2. Worker Thread Lifecycle Architecture (`OwnedWorkerJob`)

### 2.1 The Problem
Direct subclassing of `QThread` (e.g. `class MyWorker(QThread)`) with `parent=self` inside UI widgets introduces severe teardown races:
- If a dialog or tab is closed while the thread's `run()` method is executing, the parent QObject destructor deletes the child `QThread` instance while the OS thread is active. This produces the fatal Qt runtime abort: `QThread: Destroyed while thread is still running`.
- Computation loops lack interruption polling, blocking the application event loop or causing hangs upon exit.
- Signal connections made directly across threads risk invoking GUI mutation slots on background threads.

### 2.2 The Converged Solution: `OwnedWorkerJob` & `_FactorMapWorker`
All background workers adhere to the standard cooperative worker pattern:

```python
class _FactorMapWorker(QObject):
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, service, project, params, parent=None):
        super().__init__(parent)  # Must be constructed with parent=None when passed to OwnedWorkerJob
        self.service = service
        self.project = project
        self.params = params

    @Slot()
    def run(self) -> None:
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
            map_doc, task = self.service.create_factor_map(...)
            if QThread.currentThread().isInterruptionRequested():
                return
            self.finished.emit(map_doc, task)
        except Exception as exc:
            if QThread.currentThread().isInterruptionRequested():
                return
            self.failed.emit(str(exc))
```

### 2.3 Host Dialog Lifecycle Integration
Every modal dialog or widget hosting a worker job must manage its lifecycle explicitly:

```python
class CreateFactorMapDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self._job = OwnedWorkerJob(self)

    def closeEvent(self, event) -> None:
        """Cleanly request worker cancellation and shutdown thread before dialog destruction."""
        if self._job.is_running:
            self._job.shutdown(wait_ms=1000)
        super().closeEvent(event)

    def reject(self) -> None:
        """Cleanly abort background computation on dialog cancel/reject."""
        if self._job.is_running:
            self._job.shutdown(wait_ms=1000)
        super().reject()
```

### 2.4 Lifecycle Guarantees
1. **Parentless Worker Rule**: `OwnedWorkerJob.start()` enforces `worker.parent() is None` before invoking `worker.moveToThread(thread)`.
2. **Queued Signal Delivery**: Completion and failure slots are connected with `Qt.ConnectionType.QueuedConnection` and wrapped in guarded callables that drop late deliveries if the job has been released.
3. **DetachedJobKeeper Fallback**: If `shutdown(wait_ms=1000)` times out on a stubborn thread, the active thread and worker are adopted by `DetachedJobKeeper` rather than being destroyed, preventing crash-on-exit.

---

## 3. SQLite Database Thread Confinement (`CatalogIndex`)

### 3.1 The Problem
- SQLite connections are not thread-safe. Accessing a single `sqlite3.Connection` across multiple threads causes `sqlite3.ProgrammingError` or database corruption.
- Conversely, closing a foreign thread's connection while that thread is mid-query causes use-after-free segfaults at the SQLite C library layer.
- Background `QThread` workers exiting without explicitly closing their connection leave orphaned file handles in the connection pool.

### 3.2 Thread-Confined Isolation Model
`CatalogIndex` manages thread-confined connections in WAL (Write-Ahead Logging) mode:
1. **Thread-Indexed Pool**: `_conns: dict[int, sqlite3.Connection]` guarded by `_conns_lock`.
2. **Safe Cross-Thread Shutdown**: `close()` closes the current thread's connection and calls `conn.interrupt()` on foreign connections.
3. **Deterministic Session Scoping**: The `ThreadSafeCatalogSession` context manager ensures worker threads drop their connections immediately upon exit:

```python
with index.session() as conn:
    rows = conn.execute("SELECT * FROM assets WHERE type = ?", (asset_type,)).fetchall()
# Connection automatically closed and purged from index._conns on context exit
```

4. **OS-Aware Dead Thread Pruning**: `_prune_dead_threads()` monitors active Python threads via `threading.enumerate()` AND inspects Linux OS task records (`/proc/self/task/<tid>`) to clean up exited native and Qt worker threads.

---

## 4. Context-Scoped Deferred OpenGL Cleanup (`geoviz_seismic`)

### 4.1 The Problem
In Qt OpenGL applications (`QOpenGLWidget`), an OpenGL rendering context is current ONLY during `initializeGL()` and `paintGL()`. GUI thread callbacks (e.g. closing a tab, resetting a 3D volume, changing colormaps) execute without an active context. Calling `glDeleteTextures()` or `glDeleteProgram()` without a current context is a silent no-op, leading to unbounded GPU VRAM leaks.

Furthermore, in multi-window / multi-context setups, deleting texture IDs in an unrelated context causes OpenGL state corruption.

### 4.2 Context-Bound Deletion Queue Architecture
`renderer_3d.py` establishes context-scoped deferred deletion queues:

```
[UI / Worker Clean] -> queue_gl_texture_delete(tex_id, context=ctx)
                    -> queue_gl_program_delete(prog_id, context=ctx)
                              |
                     [Context Deletion Registry]
                     _CONTEXT_PENDING_TEXTURE_DELETES[ctx_key]
                     _CONTEXT_PENDING_PROGRAM_DELETES[ctx_key]
                              |
[paintGL() / Context A active] -> flush_pending_gl_deletes(context=ctx_A)
                                  -> glDeleteTextures (only ctx_A textures)
                                  -> glDeleteProgram (only ctx_A programs)
```

### 4.3 Key Methods
- `queue_gl_texture_delete(tex, context=None)`: Enqueues a texture ID bound to a specific context or widget.
- `queue_gl_program_delete(program, context=None)`: Enqueues a shader program bound to a specific context.
- `flush_pending_gl_deletes(context=None)`: Executes OpenGL deletion calls for all items queued for the matching active context.

---

## 5. Native C++ Pybind11 Safety & Metadata Export

### 5.1 GIL Release & Acquisition Protocol
- **Heavy Compute Loops**: All computationally intensive C++ loops (`compute_coherence_3d`, `marching_cubes_3d`, `minmax_downsample`, `render_grid_rgba`) release the Global Interpreter Lock via `py::gil_scoped_release` to enable multi-core parallelism.
- **Progress Callbacks**: Any native function accepting a Python progress callback MUST acquire the GIL with `py::gil_scoped_acquire` before invoking the Python callable.

### 5.2 Module Versioning & Hardware Acceleration Gating
`NativeBackendService` verifies that native extensions carry exact build metadata matching the host package (`0.2.17a0`):

```cpp
PYBIND11_MODULE(map_edit_core, m) {
    m.doc() = "Native geometry hot path for paleo mapping editor";
    m.attr("__version__") = "0.2.17a0";
    // ... function bindings ...
}
```

If a binary is missing `__version__` or has a version mismatch, `NativeBackendService` classifies it as `"stale"` and safely diverts calls to the byte-identical pure-Python fallback.

---

## 6. Verification & Automated Test Coverage

The runtime stability layer is verified by a dedicated test suite:
- `tests/test_owned_worker_job.py`: Cooperative execution, parentless worker enforcement, detached thread adoption on destruction, `CreateFactorMapDialog` close/reject lifecycle.
- `tests/test_catalog_db_concurrency.py`: WAL mode multi-threading, safe cross-thread close interruption, `ThreadSafeCatalogSession` context management, concurrent worker reader integrity.
- `tests/test_native_backend.py`: Acceleration state detection, stale binary diversion, `map_edit_core` version export and geometry algorithm parity.
