# map_edit_core C++ extension (pybind11)

The mapping editor geometry hot path is exposed through the pure-Python façade
`paleo_workbench.mapping.map_edit_api`. When a native module named
`map_edit_core` is importable, the façade prefers it for:

| Façade function | C++ symbol |
|-----------------|------------|
| `hit_test` | `hit_test` |
| `snap_point` | `snap` |
| `move_features` (per feature coords) | `move_feature` |
| `set_vertex` | `set_vertex` |
| `insert_vertex` | `insert_vertex` |
| `delete_vertex` | `delete_vertex` |
| `validate_ring` | `validate` |

If the import fails or a symbol is missing, the pure Python path runs. The
public flag is:

```python
from paleo_workbench.mapping.map_edit_api import HAS_CPP  # bool
```

`HAS_CPP` is `True` only when `import map_edit_core` succeeds. Individual
symbols may still be absent; the façade checks each with `getattr` and falls
back per call.

## Boundary rule

Cross the language bridge with **feature id + compact coordinate buffers**, not
per-vertex Python callbacks. Prefer mutating coordinate lists in place so undo
commands in Python continue to hold references to the same lists.

## Target pybind11 signatures

These are the contracts implementers should bind. Types use Python names that
map cleanly to pybind11 (`list`, `tuple`, `optional` / `None`).

```cpp
// module: map_edit_core
// Prefer PYBIND11_MODULE(map_edit_core, m)

// Hit-test: return feature id under (x, y) within tol, or None.
// features: sequence of (id, coordinates)
//   - point coordinates: [x, y]
//   - ring / line: [[x, y], ...]
// Order is last-wins / first-hit is implementation-defined; matching the
// Python path (first matching record in list order) is preferred.
std::optional<std::string> hit_test(
    const std::vector<std::pair<std::string, py::list>>& features,
    double x,
    double y,
    double tol
);

// Snap (x, y) to nearest candidate within tol. Return original point if none.
std::pair<double, double> snap(
    const std::vector<std::pair<double, double>>& candidates,
    double x,
    double y,
    double tol
);

// Translate all coordinates in-place by (dx, dy).
// coordinates is either [x, y] or [[x, y], ...].
void move_feature(
    py::list coordinates,
    double dx,
    double dy
);

// Vertex ops on a ring/line buffer [[x, y], ...]. Closed rings store a
// duplicate close point; keep first/last synced on set/delete when closed.
void set_vertex(
    py::list ring,
    int index,
    double x,
    double y
);

void insert_vertex(
    py::list ring,
    int index,
    double x,
    double y
);

// Return true if a vertex was removed. Refuse deletion that would drop a
// closed ring below 3 unique vertices or an open line below 2 vertices.
bool delete_vertex(
    py::list ring,
    int index
);

// Topology validation for a single ring. Return a list of issue dicts:
//   {"code": "self_intersection", "message": "...", "edges": ((i0,i1),(j0,j1))}
// Empty list means ok. Adjacency across multiple rings may be added later
// (Python currently owns validate_adjacency).
std::vector<py::dict> validate(
    const py::list& ring
);
```

### Suggested pybind11 binding sketch

```cpp
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PYBIND11_MODULE(map_edit_core, m) {
    m.doc() = "Native geometry hot path for paleo mapping editor";
    m.def("hit_test", &hit_test, py::arg("features"), py::arg("x"),
          py::arg("y"), py::arg("tol") = 0.0);
    m.def("snap", &snap, py::arg("candidates"), py::arg("x"),
          py::arg("y"), py::arg("tol") = 0.5);
    m.def("move_feature", &move_feature, py::arg("coordinates"),
          py::arg("dx"), py::arg("dy"));
    m.def("set_vertex", &set_vertex, py::arg("ring"), py::arg("index"),
          py::arg("x"), py::arg("y"));
    m.def("insert_vertex", &insert_vertex, py::arg("ring"), py::arg("index"),
          py::arg("x"), py::arg("y"));
    m.def("delete_vertex", &delete_vertex, py::arg("ring"), py::arg("index"));
    m.def("validate", &validate, py::arg("ring"));
}
```

## Build notes (`native/map_edit_core/`)

Source lives at `native/map_edit_core/src/map_edit_core.cpp` (pybind11 + C++17).

```bash
# From repo root, with project venv active:
python -m pip install -e ".[native]"   # pulls pybind11
python -m pip install -e native/map_edit_core

# Verify:
python -c "from paleo_workbench.mapping.map_edit_api import HAS_CPP; assert HAS_CPP"
```

In-place build (dev):

```bash
cd native/map_edit_core && python setup.py build_ext --inplace
```

Behavioral parity: `tests/test_map_topology.py` (Python path) and
`tests/test_map_edit_core_cpp.py` (skipped when extension missing; asserts
when built). CI may add a job that builds the extension and requires
`HAS_CPP is True`.

Until the extension exists, `HAS_CPP` is `False` and all tests run on the
Python path.
