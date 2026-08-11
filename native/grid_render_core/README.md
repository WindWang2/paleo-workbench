# grid_render_core

Native scalar-grid rasterisation hot path for the single-factor-map renderer.

This is the C++ per-pixel path that the native factor-map goal requires to stay out of
Python (`渲染热点路径必须在 native C++`). It maps a `float32` grid through an RGBA colour
ramp to a `uint8` RGBA buffer in a single deterministic pass, honouring nodata, mask and
opacity.

## Layout

| File | Purpose |
|------|---------|
| `src/grid_render_core.hpp` / `.cpp` | Pure-C++ algorithm (no Python). |
| `src/scalar_grid_layer.hpp` / `.cpp` | C++-owned grid/mask/LUT payload, independent data/style revisions, and native RGBA cache. |
| `src/bindings.cpp` | Thin pybind11 wrapper (GIL released around the loop). |
| `src/standalone_test.cpp` | Plain-`g++` numeric selftest — verifies the algorithm **without** pybind11/Python. |

The pure-C++ core is intentionally separated from the pybind11 binding so the hot-path
maths can be verified with a bare compiler; only the binding needs pybind11 (built in CI).

## Verify the algorithm locally (no Python toolchain)

```
g++ -std=c++17 -O2 -Wall -Wextra src/grid_render_core.cpp src/scalar_grid_layer.cpp src/standalone_test.cpp -o grid_render_selftest
./grid_render_selftest   # -> ALL GRID_RENDER_CORE SELFTESTS PASSED
```

## Behaviour contract (shared with the pure-Python parity fallback)

`render_grid_rgba(width, height, grid_z, mask, lut, lut_size, lo, hi, gamma, opacity, out)`

- `grid_z` float32 row-major; non-finite (NaN/±Inf) → nodata.
- `mask` uint8 (1=valid, 0=masked) or `nullptr`; masked → nodata.
- Normalise `t = clamp((v - lo) / (hi - lo), 0, 1)`, then `t = t ** gamma`.
- Index `idx = trunc(t * (lut_size - 1))` (truncation toward zero → byte-identical in C++ and Python).
- Values outside `[lo, hi]` clamp to the ramp endpoints (NOT transparent).
- Nodata / masked → `(0, 0, 0, 0)`. Valid → LUT colour with `alpha = lut_alpha * opacity / 255`.
- Defaults: `hi <= lo` → `t = 0`; `gamma <= 0` → `gamma = 1`.

## Registration

Registered in `paleo_workbench/native_backend.py` as feature `grid_render`, function
`render_grid_rgba`, with the pure-Python parity fallback `_py_render_grid_rgba`. The
public facade is `paleo_workbench.viz.grid_render`. The SymmetricParityContract (C++ ==
Python within tolerance) is enforced in `tests/test_grid_render_core_cpp.py`.

## Native scalar layer

`grid_render_core.ScalarGridLayer` owns the completed float32 grid and optional mask in
C++, then lazily caches its RGBA raster. Its data revision changes only when the grid or
mask changes; its style revision changes for LUT/range/gamma changes. Rasterization runs
without the GIL. Registry-level visibility and opacity remain in `layer_model_core` and
are applied during Qt composition, so toggling/opacity changes neither rerasterize the
grid nor rerun interpolation.

`paleo_workbench.viz.native_factor_map.NativeMapScene` transfers a finished
`FactorGridResult` (or managed `.factor_grid.npz` artifact) into this native layer and
`paleo_workbench.ui.native_map_canvas.NativeMapCanvas` composes it with contours and
sample points. The vertical contract is covered by `tests/test_scalar_grid_layer_cpp.py`,
`tests/test_native_factor_map.py`, and `tests/test_native_map_canvas.py`.
