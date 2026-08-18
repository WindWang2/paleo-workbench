# 1. Unified Render Engine v2: Layered Style/Symbol System, Batching Renderer, Export Parity

* Status: accepted
* Date: 2026-08-15

## Context and Problem Statement

The unified map authoring canvas (ADR 0057) renders through a renderer-neutral seam
(`MapRenderSnapshot → MapLayerSnapshot → MapRenderBackend`) with a QGIS bridge and a
pure-Qt fallback. Four structural problems limited professional cartographic use:

1. **Styles were untyped dicts scattered across three defaults** — no schema, no
   symbol vocabulary (fault traces, well markers, contour labels), no library that
   survives save/load. The fallback backend honoured only `fill`/`stroke`/
   `stroke_width`/`marker_size`, so its output diverged from the QGIS bridge.
2. **Every refresh re-walked all data** — `document_render_snapshot` hashed every
   coordinate with `json.dumps` per layer per refresh, the scene adapter deep-compared
   feature tuples, and the fallback renderer re-parsed and re-painted every feature
   per frame on the GUI thread.
3. **Export was inconsistent** — the fallback ignored `set_dpi`, decorations
   (legend/scale bar/north arrow) used fixed pixel sizes, the 2400×1600 default
   could stretch geometry, and the unified canvas exported PNG only.
4. **Catalog provenance stopped at the render seam** — `MapLayerSnapshot` carried no
   DataVersion reference, so exports could not cite their inputs.

## Decision Drivers

* Six-figure feature counts (100k+ wells/contours/polygons) must pan/zoom without
  blocking the UI thread.
* Screen display and exported PNG/SVG/PDF must come from one pipeline.
* Layer state (visibility, style, z-order, provenance) must round-trip through
  project saves with a stable schema.
* No behavioural break for existing projects: colours, document JSON, and the QGIS
  bridge payload keep their established keys.

## Decision Outcome

**Style/symbol system (`mapping/map_styles.py`, Qt-free).** `VectorStyle`,
`TextStyle`, `LinePattern` (incl. `fault`), `MarkerSymbol` (incl. `well`) are frozen
dataclasses with tolerant `from_dict`/`to_dict`. `to_dict` keeps every established
dict key and only adds new ones, so persisted projects, the QGIS bridge payload and
the properties dialog stay compatible. `STYLE_LIBRARY` holds named geological
presets (断层线/等值线/地层界线/井符号/注记/相带) whose values equal the previously
hard-coded defaults; save/load gives cross-document reuse.

**Revision-driven refresh fast path.** `MapAuthoringDocument.records()` caches per
kind keyed by `(data_revision, session revision)`. `document_render_snapshot`
accepts authoritative `data_revisions` and caches built features+extents per
`(document, kind, revision)`, computing extents inline during the single record walk
(the old recursive second pass is gone). `LegacyDocumentSceneAdapter` compares
revisions instead of deep-comparing feature tuples and pushes only changed layers
(`assume_changed=True` skips the scene's internal tuple comparison).
`UnifiedMapCanvas.set_layer_snapshot` skips the render request entirely when the
snapshot signature (ids + revisions + visibility + opacity) is unchanged.

**Batching fallback renderer.** Geometry is parsed once per `(layer, data_revision)`
into flat concatenated arrays (`_PreparedLayer`). Each frame then performs a handful
of vectorised world→screen transforms over the whole layer, feature and part culling
by bbox, global pixel-grid LOD simplification, and a hard vertex budget
(`PALEO_RENDER_VERTEX_BUDGET`, default 150k) that stride-decimates oversampled
frames so worst-case rasterisation time is bounded independently of dataset size.
Lines draw as stroke-only `QPainterPath`s built from `moveTo`/`lineTo` (measured
fastest), polygon rings of one feature share a path to keep OddEvenFill holes, and
points batch into single `drawPoints` calls (complex well/star markers degrade to
dots beyond a cap). Point/vertex diagnostics are exposed via `render_diagnostics()`.

**Threaded rendering.** `FallbackMapRenderBackend(threaded=True)` (the default from
`create_map_render_backend`) rasterises each FULL frame on a one-worker
`ThreadPoolExecutor`; stale/cancelled generations are discarded by generation
number. Worker frames paint geometry only: QPainter on a privately-owned
QImage is thread-safe for primitives, but Qt font engines are not (painting
label text off the GUI thread segfaulted Python 3.13 runs), so label
placements are collected as plain data and painted during GUI-thread
finalisation — the only font work left, proportional to label count (≤1500
per layer), never to vertex count (#822). The synchronous contract used by
tests and direct constructors is unchanged and produces byte-identical
frames (both orders geometry-then-labels).

**Export parity.** `render_to_painter` runs the identical composition pipeline into
any `QPaintDevice`, backing `export_svg`/`export_pdf` (vector) and
`export_png` (with `setDotsPerMeter`). Stroke widths, marker sizes and all chrome
decorations scale by `dpi / 96`; export extents letterbox to the view aspect so
geometry never stretches; `export_service` now routes SVG/PDF for the unified map
surface.

**Catalog provenance through the seam.** `MapLayerSnapshot` carries
`source_version_id` (from `MapLayer.provenance_ref`), `metadata`, and optional
`scale_range`; factor grids seed provenance from the managed artifact DataVersion,
and `MappingPage.export_native_factor_map` folds the composition's version ids into
export lineage.

### Positive Consequences

* Unchanged-refresh cost drops from O(all coordinates) to O(layers); 100k-feature
  snapshot rebuild is ~0.1 ms warm; frame cache makes identical re-renders ~0.03 ms.
* Zoomed-in frames cull to the visible subset (~1% drawn at 5% viewport), and the
  vertex budget bounds the worst frame regardless of data size.
* First-time preparation AND per-frame rasterisation run off the GUI thread;
  GUI-thread work per delivered frame is label painting + a byte copy (#822 —
  previously only `_prepare_layers` ran off-thread and full-frame painting
  blocked the GUI for 0.7-8.4 s at 10k-100k features).
* Screen, PNG, SVG and PDF now come from one pipeline with DPI-correct symbols and
  chrome; the fallback backend honours the same style vocabulary as the QGIS bridge
  (patterns, markers, labels, categorized fills).

### Negative Consequences

* Excessive frames decimate sub-pixel-dense geometry by stride (endpoints kept) —
  visually equivalent at screen resolution but not byte-identical to full-detail
  renders; the budget is configurable for fidelity-critical exports.
* Points draw above lines/polygons of the same layer (cartographic convention, but
  a change for mixed-order layers).
* Polygon centre labels are not drawn by the fallback backend yet (point labels
  are); QGIS remains the full labelling engine.
* `raster_source` layers still render only through the QGIS bridge; the fallback
  skips them as before.

## Links

* ADR 0057 — QGIS-backed map authoring workbench (the seam this builds on)
* `benchmarks/render_engine_benchmark.py` — local benchmark incl. embedded
  origin/main renderer for same-process A/B comparison
* `tests/test_render_engine.py`, `tests/test_map_styles.py`,
  `tests/test_map_export_consistency.py`, `tests/test_layer_lifecycle.py`,
  `tests/test_render_engine_review_fixes.py` (regressions for the adversarial
  review round: dash rendering, categorized fills, thread supersession,
  rollback-safe record caching, owner-scoped feature cache, budget-exempt rings,
  export chrome correctness)
