# Progress — QGIS Authoring Core

## Files changed (branch feat/qgis-authoring-core)

### Native bridge (C++)
- `native/qgis_render_bridge/src/style_codec.{hpp,cpp}` — NEW: renderer XML
  round-trip, legacy spec → renderer builder (single/categorized/graduated/
  rule), dialog layer factory.
- `native/qgis_render_bridge/src/gui_service.{hpp,cpp}` — NEW: modal
  QgsRendererPropertiesDialog / QgsSymbolSelectorDialog /
  QgsStyleManagerDialog host; RAII session (mirror layer + QgsStyle).
- `native/qgis_render_bridge/src/geometry_service.{hpp,cpp}` — NEW: QGIS
  geometry ops, GeoJSON in/out.
- `native/qgis_render_bridge/src/qgis_render_bridge.{hpp,cpp}` — renderer_xml/
  labeling_xml/rules on VectorLayerSpec; mirror diagnostics counters;
  export_vector (SVG/PDF via CustomPainterJob); z-order fix (reverse layer
  list for QgsMapSettings).
- `native/qgis_render_bridge/src/bindings.cpp` — new API surface + dict-tolerant
  geometry args.
- `native/qgis_render_bridge/setup.py`, `CMakeLists.txt` — link qgis_gui +
  qgis_analysis + Qt6Svg; compile new modules.

### Python mapping
- `paleo_workbench/mapping/qgis_style.py` — NEW: QgisStylePayload,
  migrate_legacy_style, availability probe.
- `paleo_workbench/mapping/geometry_service.py` — NEW: QGIS-backed merge/split
  routed through VectorEditSession.
- `paleo_workbench/mapping/vector_operations.py` — routes to QGIS when built,
  Shapely kept as explicit fallback.
- `paleo_workbench/mapping/map_render_backend.py` — `_flatten_qgis_style`
  wire promotion; base/QGIS `export_map_body`.

### UI
- `paleo_workbench/ui/map_symbology_bridge.py` — NEW: native symbology dialog
  entry points (typed errors, payload bumping).
- `paleo_workbench/ui/map_layer_properties.py` — professional path: native
  editor button + renderer info; legacy form retained for no-bridge runtimes.
- `paleo_workbench/ui/pages/mapping_page.py` — features/fields passed to the
  properties dialog; `qgis_style` applied through the normal style path.
- `paleo_workbench/ui/unified_map_canvas.py` — SVG/PDF export prefers native
  map-body export (true vector) and paints decorations on top.

### Tests
NEW: test_qgis_style_payload.py (no bridge), test_qgis_authoring_codec.py,
test_qgis_rule_renderer.py, test_qgis_geometry_service.py,
test_qgis_geometry_edit_session.py, test_qgis_symbology_dialog_bridge.py,
test_qgis_style_revision.py, test_qgis_screen_export_parity.py,
test_qgis_visual_regression.py (4-layer geological scene: facies categorized,
fault rule, contour, wells+labels; composition/z-order/histogram/determinism).
UPDATED: test_map_layer_properties.py (legacy fixture + new QGIS-path test).

### Docs
- docs/adr/0059-qgis-authoring-core.md (new)

## Test status
- `-m qgis`: 63 passed, 2 skipped (pre-existing skips)
- focused suites: render backend / snapshot encoding / canvas / frame delivery /
  authoring / styles / layer tree / export worker / interaction / edit commands:
  all green except one PRE-EXISTING baseline failure documented below.
- full suite: running (see findings.md for baseline-failure policy)

## Benchmarks
- (pending)

## Known issues
- BASELINE (pre-existing on pristine origin/main, this machine):
  test_map_export_consistency.py::test_export_png_matches_screen_frame_and_
  carries_dpi_metadata fails with the fallback backend (screen frame blank at
  probes while export renders). Reproduces with branch changes stashed and in
  the main worktree. Not introduced here; not fixed here (surgical scope).

## Remaining
- benchmarks (10k/100k), full-suite triage, commit split, push, PR.
