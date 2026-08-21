# Findings — QGIS Authoring Core

## Environment facts
- Vendored QGIS 4.2.0 at `third_party/qgis` (UPSTREAM.md pins final-4_2_0).
  Only targets `resources qgis_core qgis_gui qgis_analysis` are built (2877 TUs,
  ~40 min at -j8 on this 16-core/62 GB box). Desktop/server/python disabled.
- System Qt 6.11.2 dev packages present (pkg-config Qt6Core/Gui/Widgets/Xml OK).
  PySide6 in venv = 6.11.1 (same soname libQt6Core.so.6 → single-runtime symbol
  resolution; this is how the existing bridge already works against the PySide6
  QApplication: bridge requires `QCoreApplication::instance()` non-null).
- venv: `/home/kevin/projects/paleo_project/main/.venv` (py3.12, PySide6, pytest,
  pytest-qt, numpy, shapely). Worktree has no own venv; reuse main venv.
- Bridge install: `PALEO_WITH_QGIS_RENDERER=1 pip install -e native/qgis_render_bridge`.
  NOTE: setup.py currently links ONLY qgis_core → must add qgis_gui (+analysis)
  for symbology GUI / geometry work. CMakeLists.txt path already links all three.
- Tests conditionalized via `tests/qgis_support.py`, marker `qgis`, skip unless
  extension importable. CI main gate does NOT build QGIS (dedicated workflow).

## Architecture archaeology (HEAD da1b9834)
- Seam: `MapRenderSnapshot → MapRenderBackend` (map_render_backend.py).
  `QgisMapRenderBackend` encodes layers to a narrow native payload
  (`_qgis_snapshot`: id/name/crs/revisions/visible/opacity/style-dict/features
  WKT+attrs); native `QgisRenderBridge` owns revision-keyed QgsMapLayer mirrors,
  QgsMapRendererParallelJob, generation coalescing, cancellation. Host receives
  RGBA bytes only. Fallback = QPainter pipeline (tests/minimal runtime only).
- Native mirrors already revision-keyed (#519 semantics): vector rebuild only on
  data_revision change; vector style re-applied in place on style_revision change;
  raster rebuilds on either. Pan/zoom never rebuilds layers. GOOD — keep.
- Symbol model today: `symbol_for()` in qgis_render_bridge.cpp uses
  `Qgs{Fill,Line,Marker}Symbol::createSimple()` ONLY. Renderer kinds:
  single/categorized/graduated. NO rule renderer, NO symbol layers, NO
  serialization. This is the core gap (task §8-10).
- Legacy style model: `VectorStyle` (map_styles.py, frozen dataclass, Qt-free)
  + STYLE_LIBRARY presets (facies/well/contour/formation_boundary/fault/line/
  annotation/label). Persisted inside PaleoMapDocument layer state dicts.
  Fallback honors fill/stroke/stroke_width/patterns/markers/categories/ranges.
- Edit authority: `VectorLayer` + `VectorEditSession` (vector_layer.py) own
  working copy, undo/redo, commit→data_revision, audit. Geometry ops today =
  Shapely in vector_operations.py (merge_selected_polygons, split_polygon_by_line)
  applied THROUGH session commands. Keep transaction ownership; swap engine to
  QGIS (P1).
- Properties UI today: `MapLayerPropertiesDialog` (ui/map_layer_properties.py) —
  simple form (fill/stroke/renderer combo/classes JSON textarea). This is the
  "weak clone" Decision 2 forbids growing; replace symbology editing with QGIS
  dialogs behind the same apply-payload seam.
- Export today: PNG via backend.render_sync (QGIS when available);
  SVG/PDF via `_paint_export_vector` → throwaway FALLBACK painter backend.
  Export-parity gap for QGIS path (task §23).
- Canvas: UnifiedMapCanvas keeps snapshot→backend→frame→display; decorations
  painted host-side. Do not rewrite (§21).

## Vendored QGIS 4.2 API inventory (verified in source)
- Serialization: `QgsFeatureRenderer::save(QDomDocument&, QgsReadWriteContext&)`,
  static `QgsFeatureRenderer::load(QDomElement&, ctx)`;
  `QgsSymbolLayerUtils::saveSymbol/loadSymbol`. → payload = renderer XML string.
- Symbology GUI (src/gui/symbology/, all vendored & built):
  - `QgsSymbolSelectorWidget/QgsSymbolSelectorDialog(QgsSymbol*, QgsStyle*,
    QgsVectorLayer*, QWidget*, bool embedded)`
  - `QgsRendererPropertiesDialog(QgsVectorLayer*, QgsStyle*, bool embedded,
    QWidget*)`; static-init `initRendererWidgetFunctions()` registers widgets for
    singleSymbol/categorizedSymbol/graduatedSymbol/RuleRenderer/pointDisplacement/
    pointCluster/invertedPolygon/mergedFeature/heatmap/null/embedded;
    `apply()` writes renderer into the layer; `widgetChanged` signal.
  - `QgsStyleManagerDialog(QgsStyle*, ...)`, `QgsStyle` core API:
    addSymbol/symbol/addColorRamp/tagSymbol/addGroup/createDatabase/load.
  - `QgsGui::instance()` lazy singleton constructs GUI registries.
- Rule renderer: `QgsRuleBasedRenderer` (core) + widget registered above.
- Geometry: `QgsGeometry` (union/difference/buffer/simplify/makeValid/...),
  `qgsgeometryengine.h`, analysis lib for processing-style ops.

## Capability matrix
| Capability | Paleo now | Native bridge now | Vendored QGIS | Gap | Target |
|---|---|---|---|---|---|
| Map renderer | fallback QPainter | QgsMapRendererParallelJob, RGBA frames | full | none | QGIS default path |
| Point/Line/Polygon symbol | VectorStyle flat fields | createSimple only | full symbology | multilayer+types | renderer XML payload |
| Symbol layers | none | none | Simple/SVG/Font/Filled/MarkerLine/Hashed/Arrow/Interpolated/Gradient/Shapeburst/PointPattern/LinePattern/Centroid/GeomGen | all | via XML roundtrip + editor |
| Single renderer | yes (both backends) | yes | yes | – | keep |
| Categorized | yes (both) | yes (value→color) | yes | labels/expr | XML |
| Graduated | yes (both) | yes (ranges) | yes | – | XML |
| Rule-based | NO | NO | yes | P0 | rules spec + XML |
| Labeling | TextStyle point labels (fallback), basic PAL fields in bridge | fieldName/size/color/buffer | full PAL | placement/priority/collision | XML payload (schema first, UI later) |
| Style manager | STYLE_LIBRARY JSON | none | QgsStyle+dialog | library | QgsStyle db + dialog (P1) |
| Symbol selector UI | form dialog (weak) | none | QgsSymbolSelectorDialog | P0 | modal bridge call |
| Renderer props UI | combo+JSON textarea | none | QgsRendererPropertiesDialog | P0 | modal bridge call |
| Geometry ops | Shapely merge/split | none | QgsGeometry | engine swap | QgisGeometryService (P1) |
| Snapping/topology | map_edit_snap/topology (host overlays) | n/a | advanced | keep host | unchanged |
| Selection/editing/undo | VectorEditSession | none | edit buffer | keep Paleo authority | unchanged |
| Undo bypass risk | – | none (read-only mirrors) | – | – | mirrors stay read-only |
| Export | PNG=backend, SVG/PDF=fallback painter | render_sync only | CustomPainterJob | SVG/PDF parity | bridge export_vector (SVG/PDF) |
| Legacy migration | n/a | n/a | – | old docs must open | legacy→XML lazy migrate |

## Key design decisions (made autonomously per mandate)
1. Keep directory `native/qgis_render_bridge/`, split internal modules:
   `style_codec.*`, `gui_service.*`, `geometry_service.*` + existing render
   bridge (option B of §5; lowest-risk, same build system).
2. GUI crossing = **modal dialog bridge**: Python calls
   `bridge.run_renderer_properties(spec, renderer_xml)` etc. on the GUI thread;
   C++ builds a temporary memory QgsVectorLayer mirror, creates the real QGIS
   dialog, exec()s it, serializes result back to XML. No raw QWidget crosses
   the Python boundary (avoids shiboken/ABI fragility; matches §13 sanctioned
   pattern). Ownership entirely C++-side (RAII), zero leaks.
3. Authoritative persisted style = QGIS renderer XML string stored in the map
   document layer state as `qgis_style` payload {schema_version, renderer_xml,
   name, tags, revision}. Legacy `style` dict kept in sync (single/categorized/
   graduated projections) so fallback/tests/old projects keep working.
4. Migration is lazy + lossless-forward: opening an old doc keeps working; first
   QGIS edit materializes `qgis_style` via native `legacy_style_to_renderer_xml`.
5. Export parity: bridge gains `export_vector(path, svg|pdf, ...)` using
   QgsMapRendererCustomPainterJob inside the bridge's Qt runtime (raster-free
   true-vector output; avoids passing QPainter* across pybind).
6. Threading: dialogs asserted on QApplication thread; renders stay async;
   geometry service is pure computation (no QObject creation off-thread).

## Risks
- PySide6 Qt 6.11.1 vs system 6.11.2 headers: patch-level diff; existing bridge
  proves load-time resolution works for core; GUI adds more surface — watch for
  missing-symbol ImportError on first import after adding gui_service.
- QgsStyleManagerDialog pulls heavy deps (browser widgets etc.) — verify link;
  if too heavy, defer to P2 with QgsStyle API-only library management.
- Test teardown crashes: keep process-global QGIS runtime (never exitQgis),
  mirrors RAII-owned; follow #519/#447 patterns.
- 100k-feature perf: mirror reuse already proven; new code must not touch the
  per-feature encode path (payload cache keyed by data_revision stays).

## Performance baselines (to fill after benchmarks)
- (pending local bench run)

## Test findings
- Existing suites to keep green: test_map_render_backend, test_qgis_*,
  test_unified_map_*, test_map_authoring*, test_map_styles, test_map_export_*,
  test_layer_lifecycle, visual regression suite.

## Build log (appendix)
- gcc 16.2.1 ICEs on 4 qgis_gui TUs (deterministic; Arch gcc bug). Solution:
  vendored QGIS rebuilt with clang 22.1.8 (-j8, ~35 min). Extension TU compile
  stays on gcc — fine.
- Extension build fixes: pybind11 MUST precede Qt/QGIS includes in bindings.cpp
  (Qt `slots` macro corrupts Python.h PyType_Spec); qgis_render_bridge.hpp must
  stay Qt-free for the same reason; `emit` is a Qt macro (renamed helper);
  QgsFeatureRenderer::save() is non-const → serialize via clone;
  symbols(QgsRenderContext&) signature in 4.2 needs a context; ui_* headers at
  build/qgis-vendor/src/ui; Qt6Svg needed for QSvgGenerator export.
- Runtime alignment: system Qt 6.11.2 + vendored QGIS(6.11.2 headers) vs
  PySide6 6.11.1 private-symbol mismatch (_ZN14QObjectPrivateC2E16QtPrivate_…).
  Fix = upgrade venv to PySide6 6.11.2 (repo allows pyside6>=6.6). CI legs pin
  their own env so this is a local-env alignment only.
- BASELINE FAILURE (pre-existing, pristine origin/main, unrelated to diff):
  tests/test_map_export_consistency.py::test_export_png_matches_screen_frame_
  and_carries_dpi_metadata fails on this machine with the fallback backend
  (screen frame blank at probes while export renders content). Reproduced with
  changes stashed AND in the main worktree. Recorded per §32; not introduced
  by this branch.
