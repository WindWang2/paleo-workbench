# ISSUE-026: `extract_fence_strip` Crashes with `TypeError` When Parameters Default to `None`

- **Severity**: Low
- **Subproject**: `geo-viz-engine` (`geo-viz-engine/packages/geoviz_well_seismic_3d`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/fence.py#L117`

---

## Defect Description & Root Cause Analysis

In `geoviz_well_seismic_3d/fence.py`, `extract_fence_strip` declares optional parameters `xy_to_il_xl=None` and `registration=None`.

When neither parameter is provided by the caller, line 117 attempts to execute:
```python
il, xl = xy_to_il_xl(float(x), float(y))
```
Since `xy_to_il_xl` is `None`, Python raises `TypeError: 'NoneType' object is not callable` instead of raising a clear, descriptive `ValueError` informing the user that spatial coordinate registration is required.

---

## Impact Analysis

- **Poor Error Reporting**: Confusing `TypeError` traceback obscures the missing required parameter.

---

## Reproduction Scenario & Execution Proof

### Code Trace
```python
from geoviz_well_seismic_3d.fence import extract_fence_strip
# Calling with volume and fence but omitting coordinate registration:
extract_fence_strip(vol, fence=fence)
# Raises: TypeError: 'NoneType' object is not callable
```

---

## Concrete Suggested Fix

Add parameter validation at the beginning of `extract_fence_strip()`:

### Patch (`geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/fence.py`)
```python
# In extract_fence_strip():
if registration is None and xy_to_il_xl is None:
    raise ValueError("extract_fence_strip requires either 'registration' or 'xy_to_il_xl'")
```
