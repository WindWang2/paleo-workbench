# ISSUE-007: Zero Division in Y-Mapping and Interactive Hit-Testing on Flat Depth Spans

- **Severity**: High
- **Subproject**: `well-log-engine` (`apps/wellplot-desktop/well_log_workstation`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/multi_track_canvas.py#L1563-L1565`
  - `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/export_plot.py#L239-L241`
  - `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/section_canvas.py#L529-L531`
  - `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/correlation_canvas.py#L385-L386`

---

## Defect Description & Root Cause Analysis

Across multiple canvas rendering and hit-testing modules in `well_log_workstation`, depth coordinate normalization closures perform unshielded divisions by `(d1 - d0)`:

```python
# multi_track_canvas.py:1563
def y_map(d: float) -> float:
    return y0 + ((d - d0) / (d1 - d0)) * th

# export_plot.py:239
def y_map(d: float) -> float:
    return y0 + ((d - d0) / (d1 - d0)) * th

# section_canvas.py:529
def y_map(d: float) -> float:
    return top + ((d - d0) / (d1 - d0)) * (bottom - top)

# correlation_canvas.py:385
ly = top_band + ((ld - d0) / (d1 - d0)) * (bottom - top_band) * ve
```

When a well dataset contains only a single depth point, when user zoom sets $d_0 = d_1$, or when an uninitialized track is rendered, `d1 - d0 == 0.0`. Invoking `y_map(d)` or mouse-hovering over correlation links immediately throws `ZeroDivisionError: float division by zero`.

---

## Impact Analysis

- **GUI Crash / Freeze**: In Qt paint events (`paintEvent`), an unhandled Python exception terminates the event handler, corrupting the canvas display or causing application termination.
- **Interactive Failure**: Mouse move events over degenerate depth intervals trigger immediate unhandled exceptions.

---

## Reproduction Scenario & Execution Proof

### Code Trace
```python
d0, d1 = 1500.0, 1500.0
th = 400.0
y0 = 20.0

def y_map(d: float) -> float:
    return y0 + ((d - d0) / (d1 - d0)) * th

y_map(1500.0)
# Output: ZeroDivisionError: float division by zero
```

---

## Concrete Suggested Fix

Safely compute the span `span = d1 - d0` and return default mid-point scaling when `span == 0`.

### Patch
```python
# In multi_track_canvas.py:
def y_map(d: float) -> float:
    span = d1 - d0
    t = (d - d0) / span if span != 0 else 0.5
    return y0 + t * th

# In export_plot.py:
def y_map(d: float) -> float:
    span = d1 - d0
    return y0 + ((d - d0) / span if span != 0 else 0.5) * th

# In section_canvas.py:
def y_map(d: float) -> float:
    span = d1 - d0
    return top + ((d - d0) / span if span != 0 else 0.5) * (bottom - top)

# In correlation_canvas.py:
span = d1 - d0 if d1 > d0 else 1.0
ly = top_band + ((ld - d0) / span) * (bottom - top_band) * ve
ry = top_band + ((rd - d0) / span) * (bottom - top_band) * ve
```
