# ISSUE-016: Logarithmic Scale Domain Filtering & NaN Clamping in Multi-Track Canvas

- **Severity**: Medium
- **Subproject**: `well-log-engine` (`apps/wellplot-desktop/well_log_workstation`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/multi_track_canvas.py#L598-L604`
  - `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/multi_track_canvas.py#L1541-L1551`

---

## Defect Description & Root Cause Analysis

In `well_log_workstation/multi_track_canvas.py`, logarithmic scale transformation logic bounds track limits using Python's built-in `max()`:

```python
if mode == "log":
    vmin = max(vmin, 1e-6)
    vmax = max(vmax, vmin * 10)
    log_min, log_max = math.log10(vmin), math.log10(vmax)
```

In Python, `max(float('nan'), 1e-6)` returns `nan` when `float('nan')` is the first argument. If an uninitialized curve or an all-null log track is displayed, `vmin` is `NaN`.
Consequently, `log_min` evaluates to `math.log10(float('nan'))`, which raises `ValueError: math domain error` or yields `NaN`.

Furthermore, in `depth_at_x()` (line 602), evaluating `10 ** (log_min + ...)` results in `NaN` or unhandled exceptions during mouse hover readout calculations in the UI status bar.

---

## Impact Analysis

- **Status Bar Display Errors**: Mouse hovering over logarithmic resistivity tracks with uninitialized or empty data displays `NaN` coordinates or causes GUI exceptions.
- **Rendering Instability**: Logarithmic tracks fail to establish valid default display viewports for empty curve sets.

---

## Reproduction Scenario & Execution Proof

### Python Code Trace
```python
import math

vmin = float("nan")
vmax = float("nan")

# Buggy behavior:
v1 = max(vmin, 1e-6)
print("max(nan, 1e-6):", v1)  # Output: nan
try:
    math.log10(v1)
except ValueError as e:
    print("Raised:", e)  # Output: Raised: math domain error
```

---

## Concrete Suggested Fix

Sanitize `vmin` and `vmax` with `math.isfinite()` checks before logarithmic mapping:

### Patch (`well-log-engine/apps/wellplot-desktop/well_log_workstation/multi_track_canvas.py`)
```python
# In multi_track_canvas.py:
if mode == "log":
    vmin = vmin if math.isfinite(vmin) and vmin > 1e-6 else 1e-6
    vmax = vmax if math.isfinite(vmax) and vmax > vmin * 10 else vmin * 10
    log_min, log_max = math.log10(vmin), math.log10(vmax)
```
