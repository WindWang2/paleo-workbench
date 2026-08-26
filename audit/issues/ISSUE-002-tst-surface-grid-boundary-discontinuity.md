# ISSUE-002: True Stratigraphic Thickness (TST) Surface Grid Boundary Discontinuity

- **Severity**: Critical
- **Subproject**: `well-log-engine` (C++ SDK) & `wellplot-desktop` (Python Workstation)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/well-log-engine/src/scene/tst.cpp#L141-L160`
  - `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/tst.py#L290-L295`

---

## Defect Description & Root Cause Analysis

In both the C++20 engine (`well-log-engine/src/scene/tst.cpp`) and the Python workstation application (`well_log_workstation/tst.py`), the spatial cell coordinates `fx` and `fy` across a structural surface grid are converted into cell indices `i, j` and bilinear fractional weights `u, v`.

To prevent out-of-bounds indexing during bilinear sampling, cell indices `i` and `j` are clamped to `x_nodes - 2` and `y_nodes - 2` so that interpolation can safely read neighboring grid nodes `[i, i + 1]` and `[j, j + 1]`.

However, the fractional coordinates `u` and `v` were calculated using `fx - std::floor(fx)` (C++) and `fx - math.floor(fx)` (Python):

```cpp
// well-log-engine/src/scene/tst.cpp:
const std::size_t i = std::min(static_cast<std::size_t>(std::floor(fx)), s.x_nodes - 2);
const std::size_t j = std::min(static_cast<std::size_t>(std::floor(fy)), s.y_nodes - 2);
double u = fx - std::floor(fx);
double v = fy - std::floor(fy);
```

```python
# well_log_workstation/tst.py:
i = min(int(math.floor(fx)), s.x_nodes - 2)
j = min(int(math.floor(fy)), s.y_nodes - 2)
u = min(max(fx - math.floor(fx), 0.0), 1.0)
v = min(max(fy - math.floor(fy), 0.0), 1.0)
```

When a point falls exactly on the right or top boundary edge of the grid domain (`x == x_max` or `y == y_max`), `fx = x_nodes - 1`. The index `i` is clamped to `x_nodes - 2`. However, `std::floor(fx)` evaluates to `x_nodes - 1`.
As a result:
$$u = (x\_nodes - 1) - (x\_nodes - 1) = 0.0 \quad (\text{instead of } 1.0!)$$

Consequently, at the exact grid boundary $x = x_{\max}$, the bilinear interpolation evaluates $(1 - u) z_i + u z_{i+1} = (1 - 0) z_{x\_nodes - 2} = z_{x\_nodes - 2}$ (node $N-2$) instead of $z_{x\_nodes - 1}$ (node $N-1$). This causes a massive, non-physical step discontinuity in interpolated surface elevation, bed dip, and true stratigraphic thickness (TST) at grid boundaries.

---

## Impact Analysis

- **Geological Calculation Accuracy**: Any wellbore trajectory or stratigraphic contact intersecting near or on the outer boundary of a geological horizon grid suffers a severe artificial elevation drop (e.g. jumping backwards by hundreds of meters to the penultimate grid node value).
- **Surface Normal Distortion**: Bilinear normal calculations produce reversed or orthogonal dip vectors at grid edges, resulting in corrupt TST (True Stratigraphic Thickness) and TVT (True Vertical Thickness) logs.

---

## Reproduction Scenario & Execution Proof

### Verifiable Python Code Execution
```python
from well_log_workstation.tst import SurfaceGrid, _surface_height

grid = SurfaceGrid(
    x_origin_m=0.0, y_origin_m=0.0, x_step_m=10.0, y_step_m=10.0,
    x_nodes=3, y_nodes=3,
    z_tvd=[100.0, 200.0, 300.0, 100.0, 200.0, 300.0, 100.0, 200.0, 300.0]
)

h_19_9 = _surface_height(grid, 19.99, 10.0)
print(f"Height at x=19.99: {h_19_9:.2f} m")  # Output: 299.90 m

h_20_0 = _surface_height(grid, 20.00, 10.0)
print(f"Height at x=20.00: {h_20_0:.2f} m")  # Buggy Output: 200.00 m! Expected: 300.00 m!
```

---

## Concrete Suggested Fix

Compute fractional coordinates relative to the clamped cell index `i` (i.e. `fx - static_cast<double>(i)`) rather than relative to `std::floor(fx)`.

### C++ Patch (`well-log-engine/src/scene/tst.cpp`)
```cpp
// In grid_cell():
const std::size_t i = std::min(static_cast<std::size_t>(std::floor(fx)), s.x_nodes - 2);
const std::size_t j = std::min(static_cast<std::size_t>(std::floor(fy)), s.y_nodes - 2);
double u = fx - static_cast<double>(i);
double v = fy - static_cast<double>(j);
```

### Python Patch (`well-log-engine/apps/wellplot-desktop/well_log_workstation/tst.py`)
```python
# In _grid_cell():
i = min(int(math.floor(fx)), s.x_nodes - 2)
j = min(int(math.floor(fy)), s.y_nodes - 2)
u = min(max(fx - float(i), 0.0), 1.0)
v = min(max(fy - float(j), 0.0), 1.0)
```
