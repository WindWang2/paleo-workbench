# ADR 0059: QGIS Authoring Core

## Status

Accepted (implements and supersedes the "optional render path" framing of
ADR 0057 for cartographic authoring; 0057's seam, lifecycle, licensing and
data-authority decisions remain in force).

## Context

ADR 0057 introduced the vendored QGIS integration as an *optional* render
adapter behind `UnifiedMapCanvas`, with a Python/QPainter fallback as the
always-available path. Two consequences of that framing became blocking:

1. **The symbol model was legacy-shaped.** The native bridge built every
   symbol through `Qgs{Fill,Line,Marker}Symbol::createSimple` from flat style
   fields (`fill`/`stroke`/`stroke_width`/`marker_size`). There were no
   symbol layers, no rule-based renderer, no persisted renderer state, and no
   path to QGIS symbology editing. Professional paleogeographic cartography
   (attribute-driven lithology/facies/fault symbology, multi-layer symbols,
   SVG markers) cannot be expressed in that model.
2. **Symbology UI was a weak clone.** The layer-properties dialog offered a
   renderer combo box plus a JSON textarea for classes — exactly the
   "feature-poor QGIS-like editor" the project decided not to build.

## Decision

**QGIS is the primary professional 2-D cartographic authoring core.**
Paleo Workbench remains the authority for project/data/version state.

### Style model (authoritative)

The authoritative cartographic representation of a vector layer is a QGIS
renderer payload: a serialized `QgsFeatureRenderer` (owning the complete
`QgsSymbol` / `QgsSymbolLayer` tree) plus an optional serialized PAL labeling
configuration, stored in the map document layer state under `style["qgis_style"]`
with `{schema_version, renderer_xml, labeling_xml, name, tags, revision}`.
Serialization uses QGIS's own XML (`QgsFeatureRenderer::save/load`) — Paleo
defines no parallel schema for symbology. `createSimple` survives only inside
the legacy-import builder (`build_renderer_from_spec`) for old projects and
minimal fallbacks; it is never the target model.

Renderers supported end-to-end (build → render → edit → persist):
single, categorized, graduated and **rule-based** (P0: attribute-driven
geological predicates such as `lithology == 'sandstone'`). Labeling payloads
round-trip (schema level); full labeling UI is deferred.

### Legacy compatibility

`VectorStyle` (flat dict) stays exactly where it is: old projects open
unchanged, the fallback backend keeps consuming it, and `STYLE_LIBRARY`
presets keep their meaning. Migration to the QGIS payload is lazy and
lossless-forward: the first native symbology edit materialises `qgis_style`
via `legacy_style_to_renderer_xml`, which preserves categories/ranges/rules
into real QGIS objects. Old projects never require migration to keep opening.

### Symbology GUI (vendored qgis_gui)

Real QGIS dialogs are used, hosted through a narrow command boundary:
Python calls `run_renderer_properties_dialog` /
`run_symbol_selector_dialog` / `run_style_manager_dialog`; C++ builds a
temporary memory mirror layer, runs the genuine modal dialog on the Qt GUI
thread, and returns the updated serialized payload. No `QWidget` crosses the
Python/pybind boundary and all QObject ownership stays RAII-side in C++.
This is the sanctioned §13-style bridge, chosen over raw widget wrapping for
ABI/lifetime safety across PySide6↔vendored Qt.

### Rendering seam unchanged, one fix

`MapRenderSnapshot → MapRenderBackend → RenderFrame` is untouched. The QGIS
backend is now the expected default when the bridge is built; the fallback
remains visibly `fallback` for tests/minimal/headless runtime and gains no new
professional features. During visual-fixture work the fixture exposed a real
z-order defect: QGIS renders its layer list bottom-last while host snapshots
order bottom-first; the bridge now reverses explicitly so screen composition
matches the fallback contract.

### Export parity

Screen PNG and SVG/PDF exports interpret the same renderer payload: the
bridge gained `export_vector` (SVG/PDF via `QgsMapRendererCustomPainterJob`
inside the bridge's Qt runtime). The canvas replays the map body into the
final SVG/PDF container through `QSvgRenderer` and paints host decorations on
top, so exports stay true-vector with one style interpreter. Raster-only
backends report unsupported and callers keep the painter fallback.

### Geometry operations

Professional GIS computation moves to the vendored QGIS engine
(`qgis_render_bridge.geometry`: union/split/difference/buffer/simplify/
smooth/densify/make-valid/multipart handling/clip, GeoJSON in/out).
`VectorEditSession` remains the transaction authority: results are recorded
as ordinary before/after commands (undo/redo/audit/commit→DataVersion);
QGIS never mutates host data and never bypasses revisions. Shapely remains
the documented fallback for hosts without the bridge.

### Runtime lifecycle

One process-wide QGIS runtime (existing `initialize` counting) now also
covers GUI registries: dialog sessions touch `QgsGui::instance()` lazily;
dialogs assert the QApplication thread. Build note: this machine's gcc 16.x
ICEs on a few vendored gui TUs; the vendor snapshot builds cleanly with
clang, the small extension TU set still compiles with gcc. Local envs must
align PySide6's bundled Qt version with the system Qt the vendor build links
(private `Qt_6_PRIVATE_API` symbols are version-checked at load).

## Consequences

* Symbology editing becomes professional-grade without maintaining a clone.
* Style saves round-trip through QGIS XML; nothing else needs to understand
  symbol-layer trees.
* Old projects keep rendering through both paths; new projects accumulate
  `qgis_style` only after explicit edits (or future batch migration).
* The weak JSON-textarea class editor is retired on QGIS-capable installs;
  it survives behind the availability check for minimal runtimes.
* Known deferred: full labeling UI, extended renderer types beyond the four
  P0 kinds (cluster/displacement/heatmap/inverted/merged), style-manager
  deep integration (QgsStyle database ships wired but library curation UI is
  entry-level), legend-driven rule visibility.

## Links

* ADR 0057 — QGIS-backed map authoring workbench (seam + authority model)
* ADR 0058 — unified render engine v2 (style vocabulary, batching fallback)
* `native/qgis_render_bridge/src/{style_codec,gui_service,geometry_service}.*`
* `paleo_workbench/mapping/qgis_style.py`, `paleo_workbench/ui/map_symbology_bridge.py`
