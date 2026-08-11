# layer_model_core

Authoritative C++ layer data model for the native map engine (goal §7/§8). Holds the
single source of truth for layer render state — metadata, ordering, visibility, opacity,
scale-dependent visibility, groups, and the data/style revision counters that key the
render cache.

**Why C++ / why pure:** the goal requires the C++ layer model to be authoritative and
Python to be a control/display surface only. Keeping this module Qt-free (pure C++) lets
the data-model behaviour be verified with a bare compiler; the pybind11 binding (and the
`QAbstractItemModel` adapter) land in Phase C2 alongside the first Python consumer.

## Field set (from goal §7)

`id` (immutable), `name`, `type`, `visible`, `opacity` (0..1, clamped), `crs`, `extent`,
`scale_range` (min/max scale denominator; ≤0 = unbounded), `source_ref`, `provenance_ref`,
free-form `metadata`, `data_revision`, `style_revision`, `dirty`.

## Key invariants

- **Vector index == z-order** (0 = bottom, drawn first). No separate z field → no
  dual source of truth.
- **Data vs style revisions are independent.** `set_extent`/`set_crs`/`set_source_ref`
  bump `data_revision` only; `set_visible`/`set_opacity`/`set_name`/`set_scale_range`
  bump `style_revision` only. This is what lets a style change refresh the render
  without recomputing interpolation.
- **Group visibility propagates:** a layer is effectively visible only if it and all
  ancestor groups are visible and within scale range.
- **Stable ids, never recycled** within a session; duplicate ids rejected.
- Removing a group detaches (orphans) its children rather than cascade-deleting.

## Verify locally (no Python / no pybind11)

```
g++ -std=c++17 -O2 -Wall -Wextra src/layer_model.cpp src/standalone_test.cpp \
    -o layer_model_selftest && ./layer_model_selftest
```

CI runs the same selftest (see `.github/workflows/ci.yml` “Native C++ selftests”).

## Next (Phase C2)

- pybind11 binding exposing `LayerRegistry` + `MapLayer` ops.
- A Python `QAbstractItemModel` adapter that reads/writes the C++ registry (the
  `LayerTreeView` stays a thin Qt view).
- Composition with `grid_render_core` to draw `ScalarGridLayer`s.
