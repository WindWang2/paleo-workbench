# ISSUE-003: Survey Trajectory Initial Station Depth Reset and Elevation Collapse

- **Severity**: Critical
- **Subproject**: `well-log-engine` (`apps/wellplot-desktop/well_log_workstation`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/survey.py#L108-L115`

---

## Defect Description & Root Cause Analysis

In `well_log_workstation/survey.py`, the trajectory integration routine `compute_trajectory()` calculates True Vertical Depth (`tvd`), Northing (`dx`), and Easting (`dy`) from directional survey stations (Measured Depth `md`, Inclination `inc`, Azimuth `azi`):

```python
md[0] = pts[0][0]
tvd[0] = pts[0][0] if pts[0][1] == 0.0 else 0.0
# First station: if vertical (inc 0), TVD accumulates from 0 to md;
# otherwise the well starts deviating immediately — place TVD at 0 and
# let the first segment add to it.
tvd[0] = 0.0 if n > 1 else pts[0][0]
```

Line 113 unconditionally executes `tvd[0] = 0.0 if n > 1 else pts[0][0]`, completely overwriting the conditional initialization on line 109.

When a well survey dataset contains multiple stations ($n > 1$) and begins at a non-zero measured depth (e.g. $MD_0 = 1000\text{ m}$ for sidetrack wellbores, subsea tiebacks, or logging runs starting below casing shoes), line 113 forces $TVD_0 = 0.0$.

During subsequent minimum curvature integration between station $k$ and $k+1$, incremental TVD segments ($\Delta TVD$) are added onto $tvd[0] = 0.0$. Consequently, the entire $1000\text{ m}$ vertical hole section prior to the survey start is erased.

---

## Impact Analysis

- **Wellbore Positioning Error**: The entire calculated trajectory TVD and TVDSS arrays are shifted upwards by $MD_0$ meters.
- **Stratigraphic Miscorrelation**: At $MD = 1200\text{ m}$, TVD is computed as $200\text{ m}$ instead of $1200\text{ m}$. All well log tracks, formation tops, perforation intervals, and seismic cross-sections indexed by TVD/TVDSS are displayed in the wrong depth coordinate space by thousands of meters.

---

## Reproduction Scenario & Execution Proof

### Verifiable Python Code Execution
```python
from well_log_workstation.survey import SurveyStation, compute_trajectory

# Sidetrack well starting survey at 1000m MD:
stations = [
    SurveyStation(1000.0, 0.0, 0.0),
    SurveyStation(1100.0, 0.0, 0.0),
    SurveyStation(1200.0, 0.0, 0.0),
]
traj = compute_trajectory(stations)

print("MD array: ", traj.md)   # [1000.0, 1100.0, 1200.0]
print("TVD array:", traj.tvd)  # Buggy Output: [0.0, 100.0, 200.0] -> Missing 1000m!
```

---

## Concrete Suggested Fix

Compute the initial station TVD by projecting the starting measured depth along the initial inclination angle ($MD_0 \cdot \cos(\text{inc}_0)$), or preserve vertical accumulation:

### Patch (`well-log-engine/apps/wellplot-desktop/well_log_workstation/survey.py`)
```python
# Replace lines 108-115 in compute_trajectory():
# BEFORE:
# md[0] = pts[0][0]
# tvd[0] = pts[0][0] if pts[0][1] == 0.0 else 0.0
# tvd[0] = 0.0 if n > 1 else pts[0][0]

# AFTER:
md[0] = pts[0][0]
tvd[0] = pts[0][0] * math.cos(math.radians(pts[0][1]))
```
