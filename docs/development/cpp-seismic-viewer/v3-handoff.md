# CPP-D v3 Handoff — Seismic 2-D Slice Viewer (`Pwb::SeismicViewer`)

For A (embedding), B/E (result volumes), C (interface baseline). Verification
data: `v3-verification.md`; frozen interface contract: `v3-contracts.md`.

## 1. What A gets and how to embed

Targets (from `add_subdirectory(libs/seismic_viewer)`; standalone entry is the
same file):

- `Pwb::SeismicViewer` — static lib, PUBLIC `Pwb::Visualization` + `Qt6::Widgets`, C++20.
- `seismic_viewer_example` — minimal production consumer (also the embedding sample: `libs/seismic_viewer/examples/seismic_viewer_consumer.cpp`).

Minimal embedding (see the example for the full version):

```cpp
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>

auto* viewer = new pwb::seismic_viewer::SeismicSliceWidget(parent);
viewer->set_selection_callback([](const pwb::seismic_viewer::SliceSelectionEvent& e) {
    // fan out to the application layer; skip e.origin == own-id on rebroadcast
});
viewer->set_volume(volume /*shared_ptr<ISeismicVolume>*/,
                   pwb::seismic_viewer::VolumeIdentity{volume_id, version}, revision);
viewer->set_time_depth_relation(pwb::seismic_viewer::LinearTimeDepth{0.0, ms_per_m});
```

- Input ownership: `set_volume` takes a `std::shared_ptr<ISeismicVolume>`; the
  viewer never copies the volume and never reads it on the GUI thread. Swapping
  volumes (e.g. a newly computed attribute body from B/E) is
  `set_volume(new_volume, identity, new_revision)` — old queue/cache drop
  automatically; a late plane from the old volume can never be displayed.
- Programmatic view control: `set_axis / set_slice_index / set_color_map /
  set_auto_range / set_explicit_range / reset_view / set_view_transform /
  apply_selection`. External selections applied via `apply_selection` never
  re-emit (feedback-loop rule); reject paths return `false` (stale revision,
  foreign `document_id`).
- States for UI chrome: `state()` ∈ `no_source|empty|loading|ok|degenerate|failed`
  with `last_diagnostic()` retained — never a white image pretending success.
- Display orientation (frozen; see contracts §2.3): section views put time
  (sample axis) vertical-down; the sample slice is a crossline×inline map.
  Physical labels are `origin + index*step` with negative steps honored; inline/
  crossline are unitless line numbers, the sample axis carries `geometry.unit`.

## 2. Event fields A must forward

`SliceSelectionEvent` (own namespace, Qt-free): `origin`, `document_id`,
`revision`, `axis`, `index`, `axis_coordinate`, `axis_unit`, optional point
(`row/col_coordinate` + units), optional time range (`time_top/bottom/unit`),
`domain`, `conversion` (`native|converted|not_convertible`; `converted_*`
valid iff `converted`). Cross-domain rule: without an explicit
`LinearTimeDepth` relation a time range is reported `not_convertible` to
depth — the viewer never treats m as ms. Cross-domain conversion glue belongs
in A's `libs/application`, not here.

## 3. Error/degenerate conventions

- Failed reads surface as `ViewerState::failed` + diagnostic text overlay +
  `ControllerStats::read_failures`; the viewer keeps serving (recovery proven).
- Degenerate planes (constant / all-invalid / min==max range) render the
  frozen all-zero plane PLUS a visible overlay and `degenerate` state — the
  oracle numeric semantics are never duplicated or softened.
- Null/empty sources are rejected with diagnostics before any read.

## 4. Dependencies & SDK

- Consumed C-line interfaces (unchanged baseline `53e22b67`):
  `ISeismicVolume`, `VolumeGeometryV1`, `make_in_memory_volume`,
  `make_owning_volume`, `map_slice_to_indexed8`, `pwb::viz::DepthDomainKind`.
  **No C-line extension was needed this round.**
- Qt: developed/verified against the system Qt 6.11.2 SDK on the Linux mirror
  (GCC/Clang). A's Windows Qt 6.8.0/MSVC ABI conformance is A's integration
  step; nothing in the module uses APIs newer than Qt 6.8 (checked: only
  QWidget/QPainter/QImage/QComboBox/QSlider/QSpinBox/QDoubleSpinBox/QCheckBox/
  QPushButton/QLabel + functor `QMetaObject::invokeMethod`, no moc, no QML).

## 5. Test/CI wiring for A

- Suite: 5 ctest names `seismic_viewer.*` (contracts/controller/render/widget/
  performance), `--no-tests=error` safe, offscreen (`QT_QPA_PLATFORM=offscreen`
  set per-test), TIMEOUT 240–300 s, artifacts (PNG) under the test binary dir.
- Gates in `libs/seismic_viewer/CMakeLists.txt`: tests ON + missing Qt Widgets
  or missing frozen tiny_sgy fixture ⇒ configure FATAL_ERROR (fail-closed).
- `BUILD_TESTING=OFF` (or `PWB_SEISMIC_VIEWER_BUILD_TESTS=OFF`) yields the
  production targets only — verified.

## 6. Known limitations / next steps

- No SEG-Y/Zarr parsing (this round's scope); a chunked backend plugs in via
  `ISeismicVolume` without viewer changes (`chunk_plan()` still unused).
- Drag time-range selection exists on section views only.
- Colormap set frozen at three (grayscale/seismic/heat); registry is a single
  function to extend.
- If A wants axis-flip (time up) or annotation overlays (well tops), that is a
  presentation-layer change in `seismic_slice_widget.cpp` only — the frozen
  mapping functions (`plane_axes`, `plane_flat_index`) are the single seam.
