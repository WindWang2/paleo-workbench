# ISSUE-027: `QThread` Teardown Race in GeoViz Desktop Application Worker Threads

- **Severity**: Low
- **Subproject**: `geo-viz-engine` (`geo-viz-engine/src/pages`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/src/pages/well_log/page.py`
  - `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/src/pages/seismic/page.py`

---

## Defect Description & Root Cause Analysis

In `geo-viz-engine/src/pages/well_log/page.py` and `seismic/page.py`, background `QThread` instances are used to load large LAS log files and SEG-Y seismic volumes asynchronously.

During widget teardown or fast application window closing, these background worker threads are deleted without explicitly executing `thread.quit()` and `thread.wait()`.

Qt emits runtime warnings:
`QThread: Destroyed while thread '' is still running`

---

## Impact Analysis

- **Qt Runtime Warnings**: Emits thread destruction warnings in terminal output.
- **Potential Crash on Fast Exit**: If a background thread attempts to emit a signal to a partially deallocated parent widget during window closure, a segmentation fault can occur.

---

## Reproduction Scenario & Execution Proof

### Execution Trace
1. Open a well log or seismic volume in the GeoViz desktop application.
2. Immediately close the window while the file is reading.
3. Observe terminal output: `QThread: Destroyed while thread '' is still running`.

---

## Concrete Suggested Fix

In page `closeEvent()` and destructors, gracefully request thread termination and wait for completion:

### Patch (`geo-viz-engine/src/pages/well_log/page.py`)
```python
def closeEvent(self, event):
    if self._worker_thread is not None and self._worker_thread.isRunning():
        self._worker_thread.quit()
        self._worker_thread.wait(2000)
    super().closeEvent(event)
```
