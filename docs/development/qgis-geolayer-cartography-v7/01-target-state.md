# 01 — Target State (V7)

What must be true at the end of this goal. Every item maps to a goal section
(§n) and to a verification in `05-verification.md`.

## T1 — Generic vector ops run on QGIS (§4)
- One facade (`mapping/geometry_operations.py`) exposes the full §4 op list
  (buffer, clip, intersection, union, difference, dissolve,
  multipart↔singlepart, simplify, densify, validate, repair, polygonize,
  line merge, spatial index, CRS transform, area/length, bounding geometry,
  nearest feature, point-in-polygon, topology checks).
- Every op returns/executes via the bridge (`qgis_render_bridge.geometry`)
  when available; documented degraded engines (shapely/pure-python) only
  where they pre-exist, always disclosed (engine marker), never silent.
- Cold paths (product geometry, repairs, merge/split, exports) are
  bridge-first. Hot editing paths (snapping index, render culling) remain
  host-authoritative — documented decision, not a second GIS kernel
  (they are editing-authority internals, not generic GIS reimplementation).
- Duplicates consolidated: one PIP module (vectorized core + scalar
  wrapper), one extent util, one repair entry, shared edge-stitching util.

## T2 — GeologicalLayerSpec V2 drives QGIS layers (§3)
- `mapping_workspace/geological_layer_spec.py`: declarative
  `GeologicalLayerSpec` (id, role, geometry_type/QgsWkbType-compatible kind,
  fields, field_constraints, value_domains, defaults, renderer_binding,
  label_binding, scale_visibility, snapping_policy, topology_policy,
  edit_policy, stage_policy, maturity_policy, provenance_policy) covering
  ≥15 roles: well point, fault, facies, source/provenance line, provenance
  direction, spreading/distribution line, shoreline, facies boundary, mask,
  interpolation boundary, break line, integrated facies, integrated
  boundary, map extent (+ factor grid/contour/uncertainty/QC specs).
- `LayerType`(runtime) ↔ `LayerRole` ↔ spec ↔ `QgsFields` formally bound in
  ONE registry. Field schema (types/constraints/domains/defaults) reaches
  the QGIS mirror through a narrow bridge extension (fields_json on mirror
  upsert); Python and QGIS never hold divergent field sets.
- Specs validated host-side (pure-data tests) + bridge round-trip tests.

## T3 — Scalar factor layers are real QGIS rasters (§5) — CORE
- `FactorGridResult` → single-band float32 GeoTIFF (data mirror, keyed by
  data_revision ONLY) → `QgsRasterLayer` on BOTH the interactive canvas
  (mapstack) and the offscreen renderer →
  `QgsSingleBandPseudoColorRenderer` + `QgsColorRampShader` from a
  host-authored `ScalarStyleSpec`.
- ScalarStyleSpec supports: nodata transparency, unit, min/max, manual
  range, equal-interval / quantile / natural-breaks / explicit classes,
  continuous + classified ramps, reverse, opacity, colorbar labels;
  serialization into raster renderer XML; QgsProject reopen restores it.
- Styling NEVER rewrites scientific values: data mirror keyed by data
  revision; style changes re-apply renderer only (no GeoTIFF rewrite).
- Uncertainty (variance_grid → stddev) and fusion confidence render
  through the same scalar pipeline (FACTOR_UNCERTAINTY layers).
- RGBA mirror remains only as the documented fallback when the scalar QGIS
  path is unavailable (probe-gated, honest degradation).

## T4 — Geological Symbology V2 (§6)
- Style library V2 entries with renderer-XML bindings for: fault
  (normal/reverse/thrust/strike-slip/inferred + confidence), facies
  (categorized fills, hatch patterns, hierarchy, legend grouping),
  provenance/direction (arrow markers, directional line decorations),
  boundaries (shoreline/facies/interpolation/map-extent).
- Versioned style binding: style semantic id + revision recorded on layers;
  role-compatibility check (fault style cannot bind a shoreline layer);
  QGIS renderer XML + style DB export; UI editing stays QGIS-native
  (existing dialogs).

## T5 — Layer tree V7 + presentation state (§7–8)
- Existing system groups kept; factor groups produce all 6 children
  (input/grid/uncertainty/contour/polygon/QC) with stable ids; manual
  ordering, visibility, expanded state, stage visibility, user groups,
  system-group protection, drag/drop validation, XML roundtrip all hold
  (extend existing tests).
- `mapping_workspace/presentation.py`: `LayerPresentationState` (layer_id,
  group_id, role, visible, active, editable, dirty, raw_locked, stage_locked,
  maturity, freshness, stale_count, qc_error_count, missing, degraded,
  version) derived ONLY from existing domain/catalog/workflow state
  (memberships + dependency service + QA reports + catalog) — no new DB.
  Consumed by UI branches (cross-branch contract, 03-decisions D9).

## T6 — Incremental mirror / delta publish (§9)
- LayerContentToken / LayerStyleToken / LayerPlacementToken /
  LayerVisibilityToken formalized as per-layer revision ledger in the
  publish path; publish applies only changed ops.
- Canvas mirror path gains the feature-delta channel (same wire as the
  offscreen #932 delta); single-feature edit no longer re-ships the layer;
  style-only change reapplies renderer; visibility-only change touches
  visibility only; group move does not rebuild scientific layers.
- Benchmarks at 50/200/500/1000 layers with explicit budgets (07-perf).

## T7 — Stage workflows complete (§10–12)
- Stage 1: initial facies RAW + derived editable draft (exists) +
  well/seismic prediction overlays + confidence overlays (new) + evidence
  version + RAW lock + saved/reopen state.
- Stage 2: all constraint kinds as real QGIS vector layers with
  digitized-geometry SYNC BACK to `ConstraintLine.coordinates`
  (fingerprinted, versioned) + per-factor groups with all 6 children
  (grid scalar raster layer, classification polygons, uncertainty,
  contours, input, QC).
- Stage 3: evidence input set (exists) + integrated interpretation layer +
  integrated boundary creation + computational fusion entry (Fusion V2
  wired: likelihood/confidence/variance layers from evidence factors) +
  editable draft + stale propagation + extended QA + MapProduct assembly
  (payload-path bug fixed) + publish gate reachable; Phase-1 evidence
  untouched.
- Status-vocabulary bug fixed repo-wide (single constant).

## T8 — Layout / cartography V7 (§13–14)
- Component graph → QgsPrintLayout mapping extended: COLOR_BAR via
  QGIS-native legend bound to the scalar raster layer (same renderer XML ⇒
  screen/export consistency), GEOLOGICAL_LEGEND via native legend of
  categorized facies layer, WELL_LEGEND documented mapping, TITLE/SUBTITLE/
  DATASOURCE/TIME_CREDITS/NEATLINE/GRID/SCALE_BAR/NORTH_ARROW native,
  STAT_CHART/PROFILE/TIMESCALE as explicitly-documented hybrid boundary
  (composer fallback with engine reported — no silent drift).
- Cartographic QA rule set (§14 list) with issues localized to
  layer_id/feature_id/geometry-ref/rule/severity/reason; wired into stage
  QA action + publish gate.

## T9 — Performance (§15)
- Verified: 1000 layers, 100k vector features, 10k wells metadata,
  500×500×50 factor fusion, contour/polygon, layer tree, mirror delta,
  QGIS renderer, layout, save/reopen — with explicit budgets.
- Heavy ops off the GUI thread; cancellable where possible; UI knows the
  cancellation capability (probe semantics).

## T10 — Platform discipline
- No 100GB seismic anything (synthetic/small/medium interface checks only).
- All new capabilities probe/unavailable/degraded honest.
- No second GIS kernel; no second authority (MapDocument/catalog/tree).
- Docs 00–08 maintained; three review rounds; P0/P1 fixed with regressions.
