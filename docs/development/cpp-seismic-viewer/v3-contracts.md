# CPP-D v3 Contracts — Seismic 2-D Slice Viewer (`Pwb::SeismicViewer`)

Branch `codex/cpp-v2-seismic-viewer`, base `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`.
Scope: `libs/seismic_viewer/`, `tests/cpp/seismic_viewer/`, `docs/development/cpp-seismic-viewer/` only.

## 1. Consumed interfaces (C-line, published, read-only)

The viewer consumes exactly these published `pwb::viz` interfaces and adds **no**
extension request this round (they proved sufficient):

- `ISeismicVolume` — `geometry()`, `read_slice(axis, index, span)`, `chunk_plan()`, `lifetime()`
- `VolumeGeometryV1` — `shape/strides/origin/step/unit/missing_value`, `axis_value`, `axis_extent`, `effective_strides`
- `make_in_memory_volume` (borrowed, any valid strides) and `make_owning_volume` (packed C-order)
- `IndexedSlice` + `map_slice_to_indexed8` — the **only** stretch/NaN/degenerate rule set in the module; the viewer never re-implements numeric color semantics
- `pwb::viz::SelectionEventV1` / `DepthDomainKind` — depth-domain vocabulary reused for linkage

## 2. Delivered public interface (headers under `include/pwb/seismic_viewer/`)

### 2.1 `color_maps.hpp`
- `color_lut(name)` → 256-entry RGB LUT; registry frozen: `grayscale`, `seismic` (blue-white-red), `heat`. Unknown name → empty vector. Index 0 = lowest value and the color of non-finite samples (consequence of frozen `map_slice_to_indexed8`).

### 2.2 `slice_controller.hpp` — Qt-free scheduling core
- One worker thread per `SliceController`; **only that thread touches the source** (`ISeismicVolume` is not thread-safe; reads are strictly serialized).
- `submit(axis, index, value_range)` never blocks; queue capacity is **1** (fast drags merge: a newer request replaces a still-queued one, `stats().coalesced` counts replacements) plus **1** in-flight.
- Generation/epoch staleness: every request gets a global monotonic generation; `set_source` bumps the epoch and drops queue + cache. A computed result is delivered only if `epoch == current` and `generation == newest submitted`; otherwise `discarded_stale++`. **A late result from an old source or superseded request can never be applied.**
- Plane cache: raw float planes keyed `(epoch, axis, index)`, LRU, small fixed cap from the host (viewer default 4). Never a whole-volume copy; cache misses issue exactly one `read_slice` of one plane.
- Result delivery: `ResultSink` invoked **on the worker thread**; sinks must not re-enter the controller. After `request_shutdown()` / destructor entry, the sink never fires again.
- Failure semantics: null/empty source, out-of-bounds index or `read_slice == 0` produce `SliceResult{ok=false, diagnostic=...}` — visible state, retained diagnostics, no white-image pretend success; the controller keeps serving later requests after a failure.

### 2.3 `seismic_slice_widget.hpp` — embeddable QWidget host
- Input: `set_volume(shared_ptr<ISeismicVolume>, VolumeIdentity, revision)` — lifecycle-controlled volume owned via `shared_ptr`; no Python array, no QGIS object, no database handle. `clear_volume()` returns to `no_source`.
- One-widget/one-slice UX with programmatic mirrors: `set_axis`, `set_slice_index`, `set_color_map`, `set_auto_range` / `set_explicit_range`, `reset_view`, `set_view_transform(scale, ox, oy)`; states: `no_source | empty | loading | ok | degenerate | failed` with `last_diagnostic()` retained.
- Rendering: raster Qt only (QImage indexed8 + 256-color LUT + QPainter), no OpenGL engine; slice read/coloring never run on the GUI thread.
- **Display layout (frozen; image x/y ↔ index mapping tested):**

| displayed axis | image x | image y | plane canonical order (rows, cols) |
|---|---|---|---|
| `inline_` | crossline index | sample index (time DOWN) | rows = crossline, cols = sample |
| `crossline` | inline index | sample index (time DOWN) | rows = inline, cols = sample |
| `sample` | crossline index | inline index (DOWN) | rows = inline, cols = crossline |

- Physical coordinates: every label/cursor/selection coordinate is `geometry.axis_value(axis, index)` (`origin + index*step`, negative steps honored); units: sample axis → `geometry.unit` (e.g. `ms`), inline/crossline are unitless line numbers. Array indexes are never displayed as physical values.
- Mouse: wheel zoom, left-drag pan, double-click reset, click point-pick, Shift+vertical-drag time range (section views). Source swap (`set_volume`) drops old queue/cache; late old-volume results are discarded by epoch.

### 2.4 `slice_selection.hpp` — viewer-owned selection events
- `SliceSelectionEvent`: `origin` (per-widget stable id), `document_id`/`revision` (from `VolumeIdentity`/`set_volume`), `axis`, `index`, `axis_coordinate`, `axis_unit`, optional point pick (physical row/col coordinates + units), optional dragged time range (`time_top/time_bottom/time_unit`), domain kind and conversion status.
- Feedback-loop rule: `apply_selection(external)` updates the view and **never re-emits**; a host rebroadcast must skip events with `origin == self`. Programmatic setting is the same path (`set_axis`/`set_slice_index` do not emit).
- Unit policy (frozen): time units (`ms`, `s`) and length units (`m`, `ft`) never convert implicitly — without an explicit `LinearTimeDepth{origin_ms, ms_per_m}` supplied via `set_time_depth_relation`, cross-domain events report `ConversionStatus::not_convertible`; the viewer never treats m as ms.

## 3. Threading, lifetime and close order (frozen)

1. GUI thread: widget controls, `submit`, QImage construction from delivered planes.
2. Worker thread: serialized `read_slice` + `map_slice_to_indexed8`; sink → widget via queued `QMetaObject::invokeMethod(widget, …)`; the widget context guarantees no callback runs after widget destruction.
3. Close order: widget destructor → `SliceController` destructor joins the worker (no sink after) → Qt children destroyed; queued functor calls on the dead widget are dropped by Qt's posted-event cleanup.
4. Source swap: `set_volume` → controller `set_source` (epoch++, queue/cache cleared) → widget state `loading` → resubmit. In-flight old read may finish; its result is discarded on epoch mismatch before any GUI effect.

## 4. Build & consumption contract

- Standalone: `cmake -S libs/seismic_viewer -B build/cpp-seismic-viewer` (Ninja, C++20). Consumable: `add_subdirectory(libs/seismic_viewer)` — reuses `Pwb::Visualization` when already defined, else adds the same checkout's base library; module sources are never duplicated.
- Exports `Pwb::SeismicViewer` (+ example consumer `seismic_viewer_example`). `BUILD_TESTING=OFF` (or `PWB_SEISMIC_VIEWER_BUILD_TESTS=OFF`) still yields the production targets; enabling tests without Qt 6.8+ Widgets or without the frozen fixtures is a **configure error** (fail-closed), never a skip.
- Tests: names `seismic_viewer.*`, registered in `tests/cpp/seismic_viewer/`; frozen oracle input read-only at `tests/cpp/science/fixtures/seismic/tiny_sgy/`; new D-line fixtures only under `tests/cpp/seismic_viewer/fixtures/`.
- SDK note (honest deviation): A's single Qt ABI manifest targets the Windows host (Qt 6.8.0/MSVC). This development host is Linux with the distro Qt 6.11.2 SDK (`/usr/lib/cmake/Qt6`, GCC 14, `QT_QPA_PLATFORM=offscreen` for headless tests) — a real, verifiable Qt SDK (not Conda/PySide). Windows-side ABI conformance remains A's integration step.

## 5. What D expects from other lines this round

- C: nothing further — the published `pwb::viz` interfaces above are sufficient; no blocking dependencies.
- A: embedding via `set_volume` + `set_selection_callback` (see `examples/seismic_viewer_consumer.cpp`); cross-domain conversion glue belongs to `libs/application` (A), not this module.
- B/E: computed-result volumes enter as plain `ISeismicVolume` instances with `VolumeIdentity{volume_id, version}`; the viewer is agnostic to their provenance.
