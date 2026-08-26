# ISSUE-004: Missing `__version__` Attribute in `map_edit_core` Disables Native Acceleration

- **Severity**: High
- **Subproject**: `native` (`geo-viz-engine/native/map_edit_core`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/native/map_edit_core/src/map_edit_core.cpp#L497-L550`

---

## Defect Description & Root Cause Analysis

In `paleo_workbench/native_backend.py:192`, the acceleration manager enforces strict extension freshness validation. When querying `native_status("map_edit")`, it checks whether the imported C++ pybind11 module exposes a `__version__` attribute equal to `paleo_workbench.__version__` (`0.2.17a0`):

```python
# paleo_workbench/native_backend.py:192-205
def native_status(name: str) -> str:
    mod = _MODULES.get(name)
    if mod is None:
        return "not_found"
    mod_ver = getattr(mod, "__version__", None)
    if mod_ver != __version__:
        return "stale"
    return "available"
```

All sibling native C++ modules (`grid_render_core`, `layer_model_core`, `seismic_3d_core`, `well_log_core`, `qgis_render_bridge`) export their version via `m.attr("__version__") = "0.2.17a0";`.

However, in `geo-viz-engine/native/map_edit_core/src/map_edit_core.cpp`, `PYBIND11_MODULE(map_edit_core, m)` omitted the `m.attr("__version__")` definition entirely.

Because `getattr(mod, "__version__", None)` returns `None`, `native_status("map_edit")` always returns `"stale"`. Consequently, `is_accelerated("map_edit")` returns `False`, and a warning is emitted at startup, permanently forcing all map editing operations to fall back to pure-Python implementations even when the high-performance C++20 extension is compiled and loaded.

---

## Impact Analysis

- **Performance Degradation**: Fast C++20 ray-casting hit-testing, vertex snapping, segment splitting, and polygon topological validation are permanently bypassed across the Paleo Map editor.
- **System Diagnostics**: Emits continuous "stale native backend" warnings during application startup.

---

## Reproduction Scenario & Execution Proof

### Verifiable Code Trace
```python
from paleo_workbench.native_backend import native_status, is_accelerated

status = native_status("map_edit")
print("map_edit status:", status)               # Output: "stale"
print("is_accelerated:", is_accelerated("map_edit")) # Output: False
```

---

## Concrete Suggested Fix

Add `m.attr("__version__") = "0.2.17a0";` inside `PYBIND11_MODULE(map_edit_core, m)` in `map_edit_core.cpp`.

### Patch (`geo-viz-engine/native/map_edit_core/src/map_edit_core.cpp`)
```cpp
PYBIND11_MODULE(map_edit_core, m) {
    m.doc() = "Native geometry hot path for paleo mapping editor";
    m.attr("__version__") = "0.2.17a0";

    m.def(
        "hit_test",
        &map_edit_core::hit_test,
        ...
```
