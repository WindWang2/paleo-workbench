# ISSUE-025: Division by Zero & NaN Generation in `compute_reflectivity`

- **Severity**: Low
- **Subproject**: `geo-viz-engine` (`geo-viz-engine/packages/geoviz_well_tie`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/packages/geoviz_well_tie/geoviz_well_tie/synthetic.py#L30-L36`

---

## Defect Description & Root Cause Analysis

In `geoviz_well_tie/synthetic.py`:
```python
def compute_reflectivity(sonic: np.ndarray, density: np.ndarray) -> np.ndarray:
    velocity = 1.0e6 / sonic  # µs/m → m/s
    impedance = velocity * density
    z_upper = impedance[:-1]
    z_lower = impedance[1:]
    denom = z_lower + z_upper
    # ...
    reflectivity = (z_lower - z_upper) / denom
    return reflectivity
```

If `sonic` contains zero or negative values (e.g. unmasked null readings, telemetry dropouts, or corrupted log points), `1.0e6 / sonic` computes `inf` or negative velocities, emitting `RuntimeWarning: divide by zero encountered in divide`.

When propagated into `impedance`, `inf + inf` and `inf - inf` evaluate to `NaN`, polluting downstream synthetic seismogram convolution.

---

## Impact Analysis

- **Arithmetic Warnings**: Spams Python standard error with runtime floating-point divide-by-zero warnings.
- **NaN Seismograms**: Unclipped sonic logs produce corrupted NaN reflection coefficients.

---

## Reproduction Scenario & Execution Proof

### Verifiable Python Code Execution
```python
import numpy as np
from geoviz_well_tie.synthetic import compute_reflectivity

sonic = np.array([100.0, 0.0, 100.0])
density = np.array([2.5, 2.5, 2.5])

refl = compute_reflectivity(sonic, density)
print("Reflectivity output:", refl)
# Emits RuntimeWarning: divide by zero encountered in divide
# Output contains [nan, nan]
```

---

## Concrete Suggested Fix

Clamp sonic transit time values to a physically plausible positive minimum before computing acoustic velocity:

### Patch (`geo-viz-engine/packages/geoviz_well_tie/geoviz_well_tie/synthetic.py`)
```python
# In compute_reflectivity():
sonic = np.asarray(sonic, dtype=np.float64)
sonic = np.maximum(sonic, 1.0)
```
