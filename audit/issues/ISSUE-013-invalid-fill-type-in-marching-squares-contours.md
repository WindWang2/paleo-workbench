# ISSUE-013: Invalid `FillType` Option `"Separate"` in `extract_filled_contours`

- **Severity**: Medium
- **Subproject**: `geo-viz-engine` (`geo-viz-engine/packages/geoviz_plots`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/packages/geoviz_plots/geoviz_plots/surface/marching_squares.py#L136,L174,L190`

---

## Defect Description & Root Cause Analysis

In `geoviz_plots/surface/marching_squares.py:136`, `extract_filled_contours()` defines:
```python
def extract_filled_contours(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    levels: Sequence[float],
    fill_type: Literal["OuterOffset", "Separate"] = "OuterOffset",
) -> list[FilledContourBand]:
```

In `contourpy`, `"Separate"` is a `LineType` (used for `extract_contour_lines()`), not a valid `FillType`. The valid `FillType` options for filled contours are `"OuterOffset"`, `"OuterCode"`, `"ChunkCombinedOffset"`, etc.

When a caller invokes `extract_filled_contours(..., fill_type="Separate")`, `contourpy.contour_generator(..., fill_type="Separate")` raises `ValueError: 'Separate' is not a valid FillType`.
Furthermore, line 190 unpacks `polys, offsets = cg.filled(lv_min, lv_max)`, which specifically requires the 2-tuple structure returned by `"OuterOffset"`.

---

## Impact Analysis

- **API Failure**: Any caller selecting `fill_type="Separate"` crashes immediately with `ValueError`.
- **Type Signature Inconsistency**: The type annotation suggests `"Separate"` is supported when it is invalid.

---

## Reproduction Scenario & Execution Proof

### Python Code Execution
```python
import numpy as np
from geoviz_plots.surface.marching_squares import extract_filled_contours

x = np.linspace(0, 10, 10)
y = np.linspace(0, 10, 10)
z = np.sin(x[:, None]) + np.cos(y[None, :])

extract_filled_contours(x, y, z, [0.0, 0.5], fill_type="Separate")
# Raises: ValueError: 'Separate' is not a valid FillType
```

---

## Concrete Suggested Fix

Restrict `fill_type` to valid `FillType` options (`Literal["OuterOffset"]`) and document that filled polygon extraction requires `OuterOffset`.

### Patch (`geo-viz-engine/packages/geoviz_plots/geoviz_plots/surface/marching_squares.py`)
```python
# In extract_filled_contours():
def extract_filled_contours(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    levels: Sequence[float],
    fill_type: Literal["OuterOffset"] = "OuterOffset",
) -> list[FilledContourBand]:
```
