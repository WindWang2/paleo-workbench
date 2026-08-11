# layer_model_core

Authoritative C++ layer data model for the native map engine (goal §7/§8). Holds the
single source of truth for layer render state — metadata, ordering, visibility, opacity,
scale-dependent visibility, groups, and the data/style revision counters that key the
render cache.

**Why C++ / why pure:** the goal requires the C++ layer model to be authoritative and
Python to be a control/display surface only. Keeping the data model Qt-free lets the
behaviour be verified with a bare compiler. The C2 pybind11 binding exposes the same
registry to Python; `paleo_workbench.ui.native_layer_tree.NativeLayerModel` adapts it to
a Qt `QAbstractItemModel` without storing a second layer-state copy.

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

## Python + Qt control surface (C2)

Build the extension locally, then run the binding and offscreen Qt contracts:

```
python -m pip install -e native/layer_model_core
QT_QPA_PLATFORM=offscreen python -m pytest -q \
  tests/test_layer_model_core_cpp.py tests/test_native_layer_tree.py
```

The binding keeps safe shared Python handles while the registry remains the authority for
membership and render order. The Qt model has only selection-local state; name,
visibility, opacity, hierarchy, order, extent, and revision values resolve directly from
the native registry. Double-clicking a layer emits its id and extent for the canvas to
apply as a zoom request.

## Next composition slice

Compose managed `FactorGridResult` artifacts as `ScalarGridLayer`s with
`grid_render_core`, then connect the native tree's changes and zoom requests to the host
canvas.
