# ISSUE-018: Background Worker Signal Closure Leak and Unbounded Detached Job Accumulation

- **Severity**: Medium
- **Subproject**: `paleo_workbench` (`paleo_workbench/ui`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/ui/owned_worker_job.py#L190-L212`
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/ui/thread_keeper.py#L22-L45`

---

## Defect Description & Root Cause Analysis

1. In `paleo_workbench/ui/owned_worker_job.py`, `OwnedWorkerJob._release_identity()` cleans up worker references when a worker job completes:
```python
def _release_identity(self, thread: QThread, worker: QObject, *, delete_thread: bool) -> None:
    if self._thread is not thread or self._worker is not worker:
        return
    self._state["released"] = True
    self._thread = None
    self._worker = None
    self._cancel = None
    self._target = None
    self._result_connections = []
```
When a worker finishes normally (via `_on_thread_stopped`), `_release_identity()` simply reassigns `self._result_connections = []` without calling `self._disconnect_results()`. Consequently, the closure callbacks created in `start()` (`_guarded`) remain registered in Qt's internal signal table on the `worker` instance, retaining strong references to UI slots and outer variable closures until the worker QObject is garbage-collected.

2. In `paleo_workbench/ui/thread_keeper.py`, `DetachedJobKeeper.adopt()` tracks threads that fail to terminate within the graceful shutdown timeout:
```python
def adopt(self, thread: QThread, worker: QObject) -> None:
    key = id(thread)
    if key in self._jobs:
        return
    self._jobs[key] = (thread, worker)
    thread.finished.connect(lambda key=key: self.release_requested.emit(key))
```
If a background worker thread becomes blocked in an uncooperative call (such as a blocked C++ routine or network socket), `adopt()` holds `(thread, worker)` in `self._jobs`. If the thread never finishes, `self._jobs` accumulates these deadlocked objects indefinitely with no TTL, pruning, or size limit.

---

## Impact Analysis

- **Memory Leakage**: Signal closures and worker references accumulate over repeated worker launches.
- **Dangling Callbacks**: If a worker QObject is reused, stale signal connections may trigger unintended slot invocations.

---

## Reproduction Scenario & Execution Proof

### Code Trace
1. Start an `OwnedWorkerJob` connecting a large result callback closure.
2. Allow the worker job to finish normally.
3. Inspect the worker QObject's signal connection count: `_disconnect_results()` was never called; closure references persist in Qt's signal connection tables.

---

## Concrete Suggested Fix

Ensure `_disconnect_results()` is explicitly called during `_release_identity()`:

### Patch (`paleo_workbench/ui/owned_worker_job.py`)
```python
# In OwnedWorkerJob._release_identity():
self._disconnect_results()
self._result_connections = []
```
