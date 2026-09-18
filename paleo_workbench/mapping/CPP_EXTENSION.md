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

## Build notes (`geo-viz-engine/native/map_edit_core/`)

Phase-2 promote-down (PR-A #256): the C++ source now lives in the
`geo-viz-engine` submodule at `geo-viz-engine/native/map_edit_core/src/map_edit_core.cpp`
(pybind11 + C++17). The consumer (this repo) builds it - "source in
submodule, build in consumer".

```bash
# From repo root, with project venv active:
python -m pip install -e ".[native]"   # pulls pybind11
python -m pip install -e geo-viz-engine/native/map_edit_core

# Verify:
python -c "from geoviz_plots.map_edit import HAS_CPP; assert HAS_CPP"
```

In-place build (dev):

```bash
cd geo-viz-engine/native/map_edit_core && python setup.py build_ext --inplace
```

Behavioral parity: `tests/test_map_topology.py` (Python path) and
`tests/test_map_edit_core_cpp.py` (skipped when extension missing; asserts
when built). CI may add a job that builds the extension and requires
`HAS_CPP is True`.

Until the extension exists, `HAS_CPP` is `False` and all tests run on the
Python path.

## mapping_kernel facade (`pwb_mapping_kernel`, CONV-20)

The geological mapping numeric cores (`interpolate_factor`,
`extract_factors`, `nearest_neighbor_class_grid`) are ported to the Qt-free
C++ kernel `libs/mapping_kernel` (frozen against the Python oracles). The
optional pybind11 module `pwb_mapping_kernel` (source:
`libs/mapping_bind/`, CMake option `PWB_BUILD_CONV_20`) exposes them to
Python through the thin facade
`paleo_workbench/mapping/geological_pipeline/native_bind.py`:

| Facade function | C++ symbol |
|-----------------|------------|
| `native_bind.interpolate_factor(dataset, options)` | `pwb::mapping::interpolate_factor` |
| `native_bind.extract_factors(records, factor_name, ...)` | `pwb::mapping::extract_factors` |
| `native_bind.nearest_neighbor_class_grid(points, ...)` | `pwb::mapping::nearest_neighbor_class_grid` |

Same boundary rules as `map_edit_core`: `HAS_CPP` is True only when
`import pwb_mapping_kernel` succeeds; the facade returns the same Python
types (`FactorGridResult` / `GeologicalFactorDataset` /
`(grid_z, grid_x, grid_y, names)`); the pure-Python implementations remain
the fallback and the production pipeline modules are untouched.

Estimator honesty: kriging dispatches to C++ only when the pure-Python path
would run the same estimator (geoviz engine absent, or a moving
neighbourhood requested). With the geoviz WLS engine importable and no
neighbourhood knobs, kriging stays on Python.

Build (CMake, in-tree; the kernel and vendored pybind11 headers live in the
repo):

```bash
cmake -S . -B build/conv-20 -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPWB_BUILD_PLATFORM=OFF -DPWB_BUILD_DATA=ON -DPWB_BUILD_SCIENCE=OFF \
  -DPWB_BUILD_MAPPING_KERNEL=ON -DPWB_BUILD_CONV_20=ON -DBUILD_TESTING=ON
cmake --build build/conv-20 -j 2 --target mapping_bind_module
ctest --test-dir build/conv-20 -R 'mapping_bind.smoke' --output-on-failure

# Make the module importable in the current interpreter (per ADR 0067 the
# .so is built per host and never committed):
cp build/conv-20/libs/mapping_bind/pwb_mapping_kernel.*.so \
   "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
python -c "from paleo_workbench.mapping.geological_pipeline import HAS_CPP; assert HAS_CPP is True"
```

Parity: `libs/mapping_bind/mapping_bind_tests/smoke.py` (ctest
`mapping_bind.smoke`) replays the frozen oracle
`libs/mapping_bind/mapping_bind_tests/fixtures/bind_oracle.json` (generated
from the real Python implementations by
`libs/mapping_bind/oracle/generate_fixtures.py`), and
`tests/test_mapping_kernel_bind.py` (skipped when the module is missing)
compares facade vs pure Python live.


## Cartography registries (CONV-27)

The cartography style surface is ported to the Qt-free library
`libs/cartography` (`pwb::cartography`, alias `Pwb::Cartography`): color
ramp registry (11 builtins), `VectorStyle`/`TextStyle` value types + the 8
named presets, `ScalarStyleSpec` + numpy-exact classification
(linspace/quantile `_lerp`/Fisher-Jenks with pairwise sums and the PCG64
Floyd sample draw), the geological symbol V2 registry (15 symbols), the
geological style library V1 (12 entries), the componentized map template
library (factor map Python-parity + facies/prediction/constraint/
comprehensive variants), the QGIS render bridge payload adapter and the
product API facade (`cartography.hpp`). The renderer XML itself stays
authored by QGIS in `native/qgis_render_bridge` (C++); the adapter emits its
inputs.

Optional pybind facade: `libs/cartography/cartography_bind/` builds module
`pwb_cartography` (option `PWB_BUILD_CONV_27_BIND`, off by default, never in
the integrated gate), consumed by the `HAS_CPP` dispatch seam
`paleo_workbench/mapping/cartography_native.py`.

Parity: `libs/cartography/cartography_tests/` (8 ctest executables, frozen
fixtures from `tools/oracle/generate_cartography_fixtures.py` + a negative
self-check) and `tests/test_cartography_native_bind.py` (skipped when the
module is missing) compare facade vs pure Python live.

Python module status after CONV-27 (module docstrings carry the same note):
`color_ramps.py`, `map_styles.py`, `scalar_style.py`,
`geological_symbols.py`, `geological_style_library.py`, `qgis_style.py`,
`geological_pipeline/templates.py` — kept as oracle + legacy fallback; the
C++ library is authoritative for the product runtime. `renderers.py`
(SVG fallback), `facies_renderer_xml.py` (hand-rolled XML) and
`facies_taxonomy.py` stay Python-only by scope decision (CONV-27 D-9).
