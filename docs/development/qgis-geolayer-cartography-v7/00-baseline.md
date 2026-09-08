# 00 — Baseline (audit of main @ db21f6cf)

Goal: QGIS Geological Layer & Cartography Platform V7. All generic GIS
(layers, vector ops, geometry, rendering, layout) on QGIS; Paleo adds only
geological semantics/science/versions/QC. No second GIS kernel.

Evidence files (produced by four parallel deep audits, 2026-09-08):
- `audit-mapping.md` — mapping core: module inventory, Layer Authority
  Matrix, Geometry Operation Matrix, rendering/composer analysis.
- `audit-factor-workflow.md` — factor pipeline, FactorGridResult, RGBA
  mirror, constraints, stages, fusion, harness actions.
- `audit-qgis-stack.md` — complete bridge API surface, python wrappers,
  publish lifecycle, layout, raster status, 46 bridge-using test files.
- `audit-qgis-build.md` — build/run situation for the vendored QGIS +
  qgis_render_bridge on this Windows machine.

This file synthesizes them and registers the defect list that drives
implementation order.

## 1. Architecture as found (sound; extend, don't replace)

```
mapping_workspace (pure domain: LayerRole×33, ConstraintKind×11, 14 system
groups, 3 stages, freshness via Catalog lineage)   ← Paleo semantics
        ↓
MapLayer/MapDocument (mapping/layers.py) + LayerMembershipRecord
        ↓
immutable MapLayerSnapshot / MapRenderSnapshot seam
        ↓
two swappable canvas backends, identical contract:
  FallbackMapRenderBackend (QPainter+numpy)   QgisMapRenderBackend (bridge)
  + interactive native path: QgisCanvasShim → qgis_render_bridge.mapstack
    .QgisMapStack (doc-keyed mirror layers, native tree/groups, snapping,
    digitize tools, QgsProject XML envelope, transient QgsPrintLayout export)
```

Host keeps transaction authority everywhere (VectorEditSession + DataVersion
provenance); QGIS is only ever a mirror/renderer. This matches the goal's
architecture principle and is kept as the foundation.

Key existing capability (do not rebuild):
- Mirror API: `upsert_mirror_layer` (style-sig dedup, geometry-drift rebuild),
  `remove_mirror_layers_except`, `set_mirror_layer_order`, groups
  `upsert_group/apply_tree_placements`, tree echo schema 2, project XML
  envelope `map_qgis_project_xml`, native dialogs, snapping push, layout
  export (map/legend/scalebar/north/picture/label/shape + grid).
- Geometry bridge: 15 ops (`union, split_by_line, intersection, difference,
  symdifference, buffer, offset_curve, simplify, smooth, densify, make_valid,
  is_valid, multipart_to_singlepart, singlepart_to_multipart, clip`) —
  **only 3 used today** (union, split_by_line, make_valid).
- Offscreen path already has true O(changed) feature deltas (#932).

## 2. The four matrices — headline results

### 2.1 Layer Authority (detail: audit-mapping.md §2)
- Two layer-type vocabularies never formally linked: runtime `LayerType`
  (layers.py:36) vs scientific `LayerRole` (33 values). Role lives only in
  `LayerMembershipRecord` metadata. No `GeologicalLayerSpec` that drives
  QgsFields/constraints/domains/defaults.
- Constraints: typed creation exists (V5 §22) but canvas geometry is never
  synced back to `ConstraintLine.coordinates` (engine input) — the digitized
  layer and the engine line diverge; constraints are unversioned
  (`constraints:current` ⇒ freshness UNKNOWN).
- Factor groups: only 2 of 6 intended children produced (FACTOR_INPUT,
  FACTOR_CONTOUR). FACTOR_GRID raster, FACTOR_CLASSIFICATION,
  FACTOR_UNCERTAINTY, FACTOR_QC have roles/styles/routing but no producer.
- `FACTOR_UNCERTAINTY`: variance_grid computed + persisted in npz artifact,
  never visualized anywhere.

### 2.2 Geometry Operations (detail: audit-mapping.md §3)
- Duplicates: 3 point-in-polygon ray-casters; 2 edge-stitching impls; 4
  spatial indexes; 5 extent builders; 2 geometry-repair entry points; 2
  clip-to-ring skeletons; 2 style vocabularies.
- Bridge geometry ops exist but are unused (buffer/clip/intersection/
  difference/densify/multipart↔single/is_valid/simplify/smooth/offset…).
- Scientific algorithms correctly custom (marching squares with saddle
  disambiguation; deterministic raster polygonization with majority-vote
  hole assignment; kriging/IDW; fusion) — stay in Paleo per goal §4.

### 2.3 Rendering (detail: audit-mapping.md §4.1, audit-qgis-stack.md §5)
- Vector: renderer XML authority (QgisStylePayload) + legacy VectorStyle
  fallback; native dialogs for editing. Good.
- Scalar factor grids: **RGBA-only** — Python pre-colorizes via LUT,
  `ScalarRasterMirrorCache` writes a 4-band Byte GeoTIFF (/vsimem), QGIS
  opens with default renderer. Scalar values NEVER reach QGIS. No
  QgsSingleBandPseudoColorRenderer / QgsColorRampShader anywhere.
- Interactive canvas has NO raster support at all (`qgis_mirror.py:41` skips
  non-vector layers).
- Uncertainty/confidence/stale overlays: absent.

### 2.4 Layout (detail: audit-qgis-stack.md §4, audit-mapping.md §4.2)
- Transient QgsPrintLayout export exists: map(+grid)/legend/scalebar/
  north_arrow/picture/label/shape. Composer graph (24 element types) maps
  partially; timescale/stat-charts/legend-tables/colorbar/inset force
  all-or-nothing `composer_fallback`.
- No COLOR_BAR native counterpart; legend/colorbar consistency with layer
  renderers therefore not guaranteed on the QGIS path.

## 3. Defect register (drives implementation order)

P0 (breaks scientific flows / contradicts goal):
1. Status-vocabulary bug: `FactorMapTask.status="complete"` but
   `stage_actions.py:331,462` and `readiness.py:247,282` filter
   `"completed"` — Phase-2 factor overlay, Phase-3 evidence listing, and
   readiness checks match nothing. Silent functional disable.
2. Stage-3 `assemble_map_product` action passes a directory
   (`.artifacts`) as the required payload FILE — assembly always fails.
3. Constraint geometry never synced back to `ConstraintLine.coordinates`:
   interpolation ignores what was digitized (empty coordinates).
4. Scalar factor grids cannot be rendered/styled in QGIS as data (RGBA
   mirror only) — goal §5 core task.

P1 (goal-required capabilities missing):
5. Interactive canvas skips raster layers entirely (qgis_mirror.py:41).
6. No single-band float raster mirror + pseudocolor renderer + ramp shader
   in bridge (needs new C++ surface + wire support).
7. Factor group children missing: grid/classification/uncertainty/QC
   producers (Stage-2 target: 6/6).
8. Uncertainty (variance_grid/fusion confidence) never visualized.
9. Fusion V2 complete+tested but zero production callers (Stage-3 has no
   computational fusion path).
10. Canvas mirror path re-ships full FeatureCollection per data update
    (truncate+re-add); delta channel exists only on offscreen path (goal §9).
11. 4 declared stage context actions unimplemented
    (toggle_prediction_confidence, factor_qc, compare_factor_versions,
    map_components).
12. Confidence overlays (WELL/SEISMIC_FACIES_CONFIDENCE) roles exist, no
    producer (Stage-1 target).
13. Layout: no native COLOR_BAR/GEOLOGICAL_LEGEND mapping; screen-vs-export
    style drift risk for scalar colorbars.
14. Generic geometry ops duplicated in Python while bridge ops go unused
    (goal §4: unify on QGIS).
15. `LayerType` ↔ `LayerRole` ↔ QgsFields never formally bound (goal §3:
    GeologicalLayerSpec V2).

P2 (quality/consistency, fix in passing):
16. `readiness._geometry_issue_count` naive while TopologyService exists.
17. 3 PIP ray-casters / 2 stitchers / 5 extent builders / 2 repair entries
    (consolidate where touched; scientific cores stay).
18. Two mirror registries (mapstack GeoJSON vs offscreen WKT) — document,
    keep (different roles), but share encoding where cheap.
19. Extended QA rule set (map_qa_rules) not wired into stage QA action;
    goal §14 adds cartographic QA rules anyway.

## 4. Environment / build baseline

- Machine: Windows 11, 32 GB RAM, VS2022 MSVC 14.38, cmake 4.4.2 + ninja
  1.13, conda 25.11.1; PySide6 6.11.2 (Qt 6.11.2.0) in both venvs.
- **No completed vendored QGIS build exists on this machine** (no Windows
  build ever; v5-era builds were WSL/Linux-only; WSL distros have none).
  Without the bridge, all `@pytest.mark.qgis` tests skip — the goal's QGIS
  verification would be unverifiable locally.
- Decision (see 03-decisions D1): build the vendor QGIS on Windows via a
  conda-forge prefix (qt6-main=6.11.2 matching PySide6 exactly, per ADR
  0059 ABI rule), `-j2`, into a neutral reusable path
  `C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor` so every worktree can
  later `PALEO_QGIS_REUSE_VENDOR=1`. Est. 1.5–4 h build + first-configure
  fixes (blockers B1–B6 in audit-qgis-build.md §5).
- Worktree venv: cp312.13, geoviz editables, pybind11/ninja/pytest-qt/
  pytest-timeout/setuptools installed. Submodules at pinned 40ebd168 /
  f845e7ab.

## 5. Baseline test status

Fast selection (`pytest tests -m "not slow"`, perf/e2e/lod_render_path
excluded, offscreen). Result recorded in `05-verification.md`; known
pre-existing failures inherited from main (documented in V6): integrity
tautology test, native map_edit version (env), native factor map (needs
native build), mapping_document_io malformed-coords. QGIS-marked tests skip
until the bridge is built.
