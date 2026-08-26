# ISSUE-020: Constrained IDW Mesh Axis Degeneracy on Collinear Boundaries

- **Severity**: Medium
- **Subproject**: `paleo_workbench` (`paleo_workbench/_vendored/haiyou_constrained_idw`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/paleo_workbench/_vendored/haiyou_constrained_idw/drawing/single_factor/constrained_engine.py#L1733-L1748`

---

## Defect Description & Root Cause Analysis

In `_build_grid_axes()` inside `constrained_engine.py`:
```python
def _build_grid_axes(
    boundaries: Sequence[BoundaryPolygon],
    resolution: int,
    margin_ratio: float,
) -> Tuple[np.ndarray, np.ndarray]:
    points = [pt for boundary in boundaries for pt in boundary.exterior]
    if not points:
        raise ValueError("边界面缺少有效顶点")
    xs = np.asarray([p[0] for p in points], dtype=float)
    ys = np.asarray([p[1] for p in points], dtype=float)
    span = max(float(xs.max() - xs.min()), float(ys.max() - ys.min()), 1.0)
    margin = span * max(0.0, float(margin_ratio))
    return (
        np.linspace(float(xs.min() - margin), float(xs.max() + margin), resolution),
        np.linspace(float(ys.min() - margin), float(ys.max() + margin), resolution),
    )
```

If all vertices of `boundaries` share identical X or Y coordinates (e.g. collinear boundary polygon where `xs.max() == xs.min()`) and `margin_ratio == 0.0`:
`np.linspace(xs.min(), xs.max(), resolution)` generates an array where every element has the same numerical value ($x_0 = x_1 = \dots = x_N$).

Consequently, the spatial mesh step size $\Delta x = x_1 - x_0 = 0.0$. In subsequent grid index calculations, dividing by $\Delta x$ raises `ZeroDivisionError: float division by zero`, crashing the interpolation engine.

---

## Impact Analysis

- **Interpolation Engine Crash**: Single-factor constrained IDW map generation crashes with `ZeroDivisionError` when boundary polygons are degenerate or collinear along either axis.

---

## Reproduction Scenario & Execution Proof

### Python Code Execution
```python
import numpy as np

# Collinear X vertices with 0 margin ratio:
xs = np.array([100.0, 100.0, 100.0])
margin = 0.0
grid_x = np.linspace(xs.min() - margin, xs.max() + margin, 50)
dx = grid_x[1] - grid_x[0]
print("dx step size:", dx) # Output: 0.0 -> Causes ZeroDivisionError in coordinate lookups
```

---

## Concrete Suggested Fix

Enforce a non-zero minimum span and margin when coordinate extrema are degenerate:

### Patch (`paleo_workbench/_vendored/haiyou_constrained_idw/drawing/single_factor/constrained_engine.py`)
```python
# In _build_grid_axes():
x_span = max(float(xs.max() - xs.min()), 1.0)
y_span = max(float(ys.max() - ys.min()), 1.0)
margin_x = x_span * max(0.0, float(margin_ratio))
margin_y = y_span * max(0.0, float(margin_ratio))
if xs.max() == xs.min():
    margin_x = max(margin_x, 10.0)
if ys.max() == ys.min():
    margin_y = max(margin_y, 10.0)
return (
    np.linspace(float(xs.min() - margin_x), float(xs.max() + margin_x), resolution),
    np.linspace(float(ys.min() - margin_y), float(ys.max() + margin_y), resolution),
)
```
