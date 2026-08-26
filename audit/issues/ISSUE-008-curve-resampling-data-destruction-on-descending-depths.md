# ISSUE-008: Data Destruction on Descending Depth Arrays during Curve Resampling

- **Severity**: High
- **Subproject**: `well-log-engine` (`apps/wellplot-desktop/well_log_workstation`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/curve_resample.py#L76-L81`

---

## Defect Description & Root Cause Analysis

In `well_log_workstation/curve_resample.py`, `resample_curve()` resamples well log curves onto uniform depth grids:

```python
new_depth = np.arange(d0, d1 + target_interval / 2.0, target_interval)
new_values = np.interp(new_depth, depth, work, left=np.nan, right=np.nan)
```

The underlying interpolation function `numpy.interp` strictly requires the source coordinate array `xp` (`depth`) to be monotonically increasing.

In wireline logging operations, logging tools are typically pulled upward from the bottom of the wellbore to the surface during data acquisition. Consequently, raw wireline log datasets frequently have descending depth arrays (where `depth[0] > depth[-1]`).

When `np.interp` receives a monotonically decreasing `depth` array, its internal binary search fails, causing it to treat all target evaluation points in `new_depth` as outside the domain bounds. As a result, 100% of the returned curve values are evaluated as `np.nan`.

---

## Impact Analysis

- **Total Data Loss**: Resampling any bottom-to-top logged well curve completely erases all data samples, returning an array of pure `NaN` values.
- **Silent Degradation**: Resampled curves appear completely empty without throwing an exception, leading users to believe the original log contained no data.

---

## Reproduction Scenario & Execution Proof

### Verifiable Python Code Execution
```python
import numpy as np
from well_log_workstation.curve_resample import resample_curve

# Ascending depth array:
d_asc = np.array([1000.0, 1500.0, 2000.0])
v_asc = np.array([10.0, 15.0, 20.0])
_, res_asc, _ = resample_curve(d_asc, v_asc, None, 100.0)
print("Ascending resample valid count:", np.count_nonzero(~np.isnan(res_asc)))  # 11 valid samples

# Descending depth array (typical wireline upward pass):
d_desc = np.array([2000.0, 1500.0, 1000.0])
v_desc = np.array([20.0, 15.0, 10.0])
_, res_desc, _ = resample_curve(d_desc, v_desc, None, 100.0)
print("Descending resample valid count:", np.count_nonzero(~np.isnan(res_desc))) # Buggy Output: 0 valid samples!
```

---

## Concrete Suggested Fix

Detect descending depth arrays and reverse both `depth` and `work` before passing them to `np.interp`.

### Patch (`well-log-engine/apps/wellplot-desktop/well_log_workstation/curve_resample.py`)
```python
# In resample_curve():
# BEFORE:
# new_values = np.interp(new_depth, depth, work, left=np.nan, right=np.nan)

# AFTER:
if depth[0] > depth[-1]:
    depth_eval = depth[::-1]
    work_eval = work[::-1]
else:
    depth_eval = depth
    work_eval = work
new_values = np.interp(new_depth, depth_eval, work_eval, left=np.nan, right=np.nan)
```
