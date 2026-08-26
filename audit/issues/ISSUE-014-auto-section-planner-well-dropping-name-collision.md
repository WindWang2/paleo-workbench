# ISSUE-014: Well Dropping Bug in `plan_section_nearest_neighbor` On Name Collisions

- **Severity**: Medium
- **Subproject**: `geo-viz-engine` (`geo-viz-engine/packages/geoviz_cross_well`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/auto_section_planner.py#L118-L153`

---

## Defect Description & Root Cause Analysis

In `geoviz_cross_well/auto_section_planner.py`, `plan_section_nearest_neighbor(wells, ...)` computes a traveling-salesperson-style nearest-neighbor path across wells to form a cross-section line.

It constructs a lookup dictionary `parsed` keyed on well name strings:
```python
parsed = {}
for w in wells:
    name, lng, lat = _extract_coords(w)
    parsed[name] = (lng, lat, w)
```

If wells are passed as coordinate dictionaries without names (e.g. `{"x": 1.0, "y": 2.0}`, where `_extract_coords` defaults `name=""`) or if multiple wells share the same name/identifier, `parsed` overwrites previous entries with subsequent wells sharing that name.

When the routing loop executes:
```python
start_name = ...
path = [parsed[start_name][2]]
visited = {start_name}
current_name = start_name
while len(path) < len(wells):
    # Searches unvisited names in parsed
    # ...
    if nearest_name is None:
        break
```
Because `visited` already contains `start_name`, no unvisited keys remain in `parsed`. The loop immediately terminates at the first iteration, silently dropping all remaining wells from the calculated cross-section route.

---

## Impact Analysis

- **Silent Data Loss**: Cross-well automatic routing drops input wells from the generated fence profile whenever input data contains duplicate names or unnamed coordinate tuples.
- **Incomplete Cross-Sections**: Cross-well plots render only a single well instead of the full sequence.

---

## Reproduction Scenario & Execution Proof

### Verifiable Python Code Execution
```python
from geoviz_cross_well.auto_section_planner import plan_section_nearest_neighbor

wells = [
    {"x": 100.0, "y": 200.0},
    {"x": 150.0, "y": 250.0},
    {"x": 200.0, "y": 300.0},
]
result = plan_section_nearest_neighbor(wells)
print("Input wells:", len(wells), "Planned path wells:", len(result))
# Output: Input wells: 3 Planned path wells: 1  (2 wells were silently dropped!)
```

---

## Concrete Suggested Fix

Key the `parsed` dictionary and `visited` set by integer index (`0` to `N-1`) instead of well name strings.

### Patch (`geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/auto_section_planner.py`)
```python
# In plan_section_nearest_neighbor():
parsed = {i: (_extract_coords(w)[1], _extract_coords(w)[2], w) for i, w in enumerate(wells)}
start_idx = 0
path = [parsed[start_idx][2]]
visited = {start_idx}
current_idx = start_idx

while len(path) < len(wells):
    curr_lng, curr_lat, _ = parsed[current_idx]
    nearest_idx = None
    min_dist = float("inf")
    for idx, (lng, lat, _) in parsed.items():
        if idx in visited:
            continue
        dist = (lng - curr_lng) ** 2 + (lat - curr_lat) ** 2
        if dist < min_dist:
            min_dist = dist
            nearest_idx = idx
    if nearest_idx is None:
        break
    path.append(parsed[nearest_idx][2])
    visited.add(nearest_idx)
    current_idx = nearest_idx
```
