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
