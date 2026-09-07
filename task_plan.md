# Task Plan — QGIS Geological Layer & Cartography Platform V7 (feat/qgis-geolayer-cartography-v7)

## Goal
Establish Paleo Workbench's QGIS geological layer & professional cartography
platform. Generic GIS (layers, vector ops, geometry, rendering, layout) must be
built on QGIS; Paleo only adds geological semantics, science, factor maps,
compilation, versioning, QC, product lifecycle. NO parallel generic-GIS stack.

Primary rules:
- Evidence before modification; find existing authority before creating new.
- Reuse QGIS/existing services; no second GIS kernel.
- Every capability has probe/unavailable/degraded semantics; no fake success,
  no silent fallback, no swallowed exceptions.
- Public-contract changes migrate ALL in-repo callers + tests.
- HARD EXCLUSION: no 100GB seismic support/benchmark/optimization.

## Current Phase
PHASE 2/3 — implementation (P0 fixes → GeologicalLayerSpec)
PHASE 1 — DONE (audit-*.md + 00..03 docs committed)

## Phases
- [x] PHASE 0: Setup — worktree `.worktrees/qgis-geolayer-cartography-v7`,
      branch `feat/qgis-geolayer-cartography-v7` off main (db21f6cf);
      submodules geo-viz-engine (40ebd168) + well-log-engine (f845e7ab);
      uv venv cp312 + geoviz editables; baseline test run (pending baseline)
- [x] PHASE 1: Deep audit (§2) — mapping/mapping_workspace/workflow factor+map/
      ui.qgis_stack/native qgis_render_bridge/composer; 4 matrices
      (Layer Authority, Geometry Operation, Rendering, Layout) → 00-baseline.md
- [ ] PHASE 2: GeologicalLayerSpec V2 (§3) — QGIS-driven layer spec covering
      15 roles; QgsFields/constraints/domains/defaults mapping; single authority
- [ ] PHASE 3: Vector spatial ops on QGIS (§4) — buffer/clip/intersect/union/
      difference/dissolve/multi<->single/simplify/densify/validate/repair/
      polygonize/linemerge/spatial index/CRS/area-length/nearest/PIP/topology
- [ ] PHASE 4: QGIS raster/scalar factor layers (§5) — FactorGridResult →
      scalar raster → single-band pseudocolor renderer, ramps, nodata/unit/
      ranges/modes/reverse/opacity/uncertainty/provenance, serialization,
      project reopen; styling never rewrites science values
- [ ] PHASE 5: Geological Symbology V2 (§6) — fault/facies/provenance/boundary
      styles, QGIS renderer XML/style DB, versioned binding, role compat check
- [ ] PHASE 6: Layer Tree V7 (§7) + LayerPresentationState (§8) — system
      groups, factor nested groups, stable ids, ordering, protection,
      roundtrip; presentation state from existing domains
- [ ] PHASE 7: Incremental QGIS mirror / delta publish (§9) — content/style/
      placement/visibility tokens; no-op ≈ O(changed); benchmarks 50/200/500/1000
- [ ] PHASE 8: Stage workflows (§10–12) — Stage1 facies RAW/draft/overlays/
      lock; Stage2 constraint QGIS layers + factor products group; Stage3
      integrated compilation + QA + publish gate
- [ ] PHASE 9: QGIS Layout/Cartography V7 (§13) + cartographic QA (§14) —
      component graph → QgsPrintLayout; 13+ item kinds; screen=export parity;
      QA rules with layer/feature/rule/severity localization
- [ ] PHASE 10: Performance (§15) — 1000 layers/100k features/10k wells/
      500×500×50 fusion/contour/mirror/renderer/layout/save-reopen; off-GUI
      thread + cancellation capability
- [ ] PHASE 11: 3 review rounds (§19) + P0/P1 fixes + regression tests
- [ ] PHASE 12: Docs 00–08, atomic commits, PR to main (§20)

## Decisions (locked)
1. Build on QGIS as the only generic-GIS authority; Paleo = geology only.
2. No 100GB seismic (synthetic/small/medium interface checks only).
3. Resource: reuse vendored QGIS build; -j2 C++ compiles, serial heavy tests,
   bounded benchmarks with explicit size/memory caps.
4. Windows/GitBash; worktree-local .venv (root .venv points at main checkout —
   never use it).
5. Don't touch ui/workstation, ui/components, qgis_render_bridge/edit_tools.*
   (owned by parallel QGIS Authoring branch) except via narrow adapters;
   record cross-branch contracts.

## Blocked Items
(none)

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| well-log-engine clone --reference failed (shallow ref) | 1 | plain local clone, checkout pinned f845e7ab — OK |

## Environment facts
- Worktree: C:\Users\wangj.KEVIN\projects\paleo-workbench\.worktrees\qgis-geolayer-cartography-v7
- Parallel worktree exists: .worktrees/workstation-ux-v7 (feat/workstation-ux-v7) — avoid C++ file collisions (esp. qgis_render_bridge/edit_tools)
- Submodules: geo-viz-engine 40ebd168, well-log-engine f845e7ab (NOT third_party/gdal|proj — vendored builds only)
- venv: .venv (cp312.13) with geoviz editables OK
- Pre-existing main failures (from V6 session, NOT to fix silently): test_integrity_guard tautologies, test_native_backend map_edit version (env), test_native_factor_map (needs native build), test_mapping_document_io malformed-coords, hard crash test_lod_render_path (Windows)
