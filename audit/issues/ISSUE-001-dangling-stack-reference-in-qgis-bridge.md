# ISSUE-001: Dangling Stack Reference in `qgis_render_bridge` Geometry Submodule

- **Severity**: Critical
- **Subproject**: `native` (`native/qgis_render_bridge`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/native/qgis_render_bridge/src/bindings.cpp#L424-L503`

---

## Defect Description & Root Cause Analysis

Inside `PYBIND11_MODULE(qgis_render_bridge, module)` in `native/qgis_render_bridge/src/bindings.cpp`, the helper lambda `geometry_arg` is defined as a local variable on the stack frame of the module initialization function:

```cpp
auto geometry_arg = [](const py::handle& value) -> std::string {
    if (py::isinstance<py::str>(value)) {
        return py::cast<std::string>(value);
    }
    return py::module_::import("json").attr("dumps")(value).cast<std::string>();
};
```

Following its definition, 15 geometric functions registered on the submodule (`union`, `split_by_line`, `intersection`, `difference`, `symdifference`, `buffer`, `offset_curve`, `simplify`, `smooth`, `densify`, `make_valid`, `is_valid`, `multipart_to_singlepart`, `singlepart_to_multipart`, `clip`) capture `&geometry_arg` **by reference**:

```cpp
geometry.def(
    "union",
    [&geometry_arg](const py::iterable& parts) {
        std::vector<std::string> items;
        for (const py::handle item : parts) {
            items.push_back(geometry_arg(item));
        }
        return pwb::qgis_render::geometry_union(items);
    },
    py::arg("geometries"),
    "Merge an iterable of GeoJSON geometries into a single union geometry."
);
```

When module initialization completes and the initialization function returns, its stack frame is destroyed and popped. The captured reference `&geometry_arg` becomes a dangling reference pointing to deallocated stack memory. Any subsequent invocation of any `qgis_render_bridge.geometry.*` function from Python dereferences invalid memory, resulting in undefined behavior, heap/stack corruption, or immediate segmentation faults (`SIGSEGV`).

---

## Impact Analysis

- **Memory Safety**: Severe undefined behavior and memory corruption.
- **Runtime Crash**: Calling any vector geometry analysis or clipping operation in `qgis_render_bridge.geometry` (such as layer polygon clipping, smoothing, simplifying, or buffering) crashes the Python interpreter process.
- **Data Integrity**: Under corrupted memory reads, invalid JSON or garbage strings may be passed to the underlying C++ QGIS geometry engine, leading to silent calculation errors before crashing.

---

## Reproduction Scenario & Execution Proof

### Code Trace
1. Import the native extension: `import qgis_render_bridge`
2. Call any geometry method: `qgis_render_bridge.geometry.buffer('{"type":"Point","coordinates":[0,0]}', 10.0)`
3. The lambda executes and dereferences `geometry_arg` via the dangling reference `&geometry_arg`.
4. In ASan/UBSan builds, address sanitizer immediately reports `stack-use-after-scope` or `stack-use-after-return`. In release builds, random memory corruption or `SIGSEGV` occurs.

---

## Concrete Suggested Fix

Move `geometry_arg` into an anonymous namespace as a free static function, or capture the lambda by value `[geometry_arg]` in all geometry definitions.

### Patch
```cpp
// In native/qgis_render_bridge/src/bindings.cpp:

namespace {

std::string geometry_arg(const py::handle& value) {
    if (py::isinstance<py::str>(value)) {
        return py::cast<std::string>(value);
    }
    return py::module_::import("json").attr("dumps")(value).cast<std::string>();
}

}  // namespace

// Inside PYBIND11_MODULE(qgis_render_bridge, module):
// Remove the local `auto geometry_arg = ...;` and update submodule bindings:

geometry.def(
    "union",
    [](const py::iterable& parts) {
        std::vector<std::string> items;
        for (const py::handle item : parts) {
            items.push_back(geometry_arg(item));
        }
        return pwb::qgis_render::geometry_union(items);
    },
    py::arg("geometries"),
    "Merge an iterable of GeoJSON geometries into a single union geometry."
);
```
