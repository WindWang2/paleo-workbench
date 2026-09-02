# Task Plan — QGIS Authoring Core (feat/qgis-authoring-core)

## Goal
Promote vendored QGIS from optional render adapter to the primary professional 2-D
cartographic authoring core of Paleo Workbench, while Paleo keeps project/data/version
authority (VectorEditSession, DataVersion, provenance).

## Current Phase
PHASE 2 — Code archaeology

## Phases
- [x] PHASE 0: Planning files created; worktree `../paleo-workbench-qgis-authoring`
      branch `feat/qgis-authoring-core` off `origin/main` (da1b9834)
- [ ] PHASE 1: Pre-read code (mapping/, ui/, native bridge, vendored QGIS, tests, ADRs)
- [ ] PHASE 2: Capability matrix in findings.md
- [ ] PHASE 3: P0 vertical slice
  - [ ] Unified QGIS runtime lifecycle owner
  - [ ] Revision-keyed layer mirror (no rebuild on pan/zoom)
  - [ ] Full QgsSymbol/SymbolLayer representation (multi-layer), no createSimple as main model
  - [ ] Renderers: single / categorized / graduated / rule-based (rule = P0)
  - [ ] Style serialization roundtrip (QGIS XML payload in project doc)
  - [ ] Legacy VectorStyle → QGIS renderer migration
  - [ ] Symbology GUI: QgsSymbolSelectorDialog + renderer widgets via bridge
- [ ] PHASE 4: P1
  - [ ] QgisGeometryService (union/split/buffer/... via QgsGeometry)
  - [ ] VectorEditSession integration (QGIS computes, Paleo commands record)
  - [ ] Style manager on QgsStyle (geological categories)
- [ ] PHASE 5: Tests (TDD) + visual regression fixtures
- [ ] PHASE 6: Local build + full validation loop (/loop until no P0/P1)
- [ ] PHASE 7: Adversarial review + fixes
- [ ] PHASE 8: Docs (ADR 0059) + commits + push + PR

## Decisions (locked by owner — do not revisit)
1. QGIS = official 2-D authoring core; fallback only for tests/headless/legacy.
2. Reuse vendored qgis_gui symbology widgets (no weak reimplementation).
3. QgsFeatureRenderer/QgsSymbol/QgsSymbolLayer/QgsTextFormat = authoritative style model;
   legacy VectorStyle kept only for compat/migration.
4. Geometry algorithms via QGIS; edit transaction authority stays in Paleo
   (VectorEditSession → DataVersion/provenance).

## Blocked Items
(none yet)

## Notes
- Build with PALEO_QGIS_BUILD_JOBS=2 (avoid OOM).
- Do not touch main working tree; all work in worktree.

---

# Task: Open Issues 清仓 + QGIS Workstation Convergence (2026-09-02)

## Base
- main @ 0e011bb5; worktree ../paleo-qgis-convergence, branch feat/qgis-workstation-convergence

## Phases
- [ ] A. Fix #1120–#1125, #1128 (lifecycle/layout/dock/data-flush) + #1127 tests
- [ ] B. CRS authority: LayerManagerPanel._publish must not hardcode EPSG:4326
- [ ] C. Layer properties / symbology / labeling into Composite (reuse MapLayerPropertiesDialog + bridge)
- [ ] D. split/merge via vector_operations (session commands); topology via TopologyService
- [ ] E. GeoTemplate field schemas (fault/facies/source/spreading/break/direction) + persistence
- [ ] F. Attribute table + identify results panels
- [ ] G. Per-layer snapping configuration dialog
- [ ] H. Map status bar in composite (CRS/scale/coords/renderer/edit/snap)
- [ ] I. Regression tests + 10k/50k/100k benchmark run
- [ ] J. Review loop (blocker=0, high=0) → push → PR

## Environment facts
- Test env: /opt/miniconda3/bin/python3.13 + PySide6 6.11.1, offscreen; wrapper ./run_env.sh
- qgis_render_bridge NOT built → fallback renderer active; all QGIS UI paths must probe & degrade
- Baseline failures on main: test_dock_title_bar (visibility assert + _dock attr race), test_composite_editing::test_shell_exposes_digitizing_toolbar — both touched by #1122 work
