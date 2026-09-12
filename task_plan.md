# Task Plan — QGIS Cartography Runtime V11 (qgis-runtime-v11)

## Goal
Build the QGIS Cartography Runtime Control Plane V11: native layer tree as the
single runtime authority, formal layer ordering engine, minimal tree diff,
native tree transactions, bidirectional sync, active/edit/tool-target split,
stage union-tree semantics, mirror lifecycle, layout/legend consistency, and
topology editing M0 per #1278 spec (#1279–#1286 decisions). QGIS = 2D GIS
runtime; Paleo = geology semantics only. NO parallel GIS engine, NO qgis_app.

Worktree: C:\Users\wangj.KEVIN\projects\paleo-workbench-qgis-runtime-v11
Branch: qgis-runtime-v11 (off main 6c08fb7d)
Docs: docs/development/qgis-cartography-runtime-v11/

## Locked decisions
1. Base = main 6c08fb7d. PR #1267 (v10-review-fixes) and #1277
   (review-convergence) own their fixes — V11 MUST NOT duplicate them;
   00-overlap-audit.md records file-level ownership.
2. Parallel V11 lines to avoid: data-fabric-v11 (catalog/well/data page),
   workbench-ux-v11 (generic UI design system; stacked on #1277).
3. Topology: #1279–#1286 decision issues are the authority; the referenced
   docs/specs/topological-editing-migration-spec.md DID NOT EXIST on main or
   any branch — V11 materialized it (docs/specs/, assembly view).
4. Vendor QGIS build at C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor
   (survives); bridge rebuilt in worktree via PALEO_QGIS_REUSE_VENDOR=1.
5. Test recipe: PALEO_QGIS_BUILD_DIR=neutral vendor + PALEO_QGIS_CONDA_QT=1
   + QT_QPA_PLATFORM=offscreen; conftest auto-preps loader.
6. No CI waiting; local targeted verification. Windows/GitBash; explicit cd
   in every shell (background shells reset cwd to main checkout).

## Phases
- [x] PHASE 0: Setup — worktree + branch + submodules + venv + bridge 0.7.0a0
- [x] PHASE 1: State sync → 00-overlap-audit.md
- [x] PHASE 2: Deep audit → 01-current-qgis-runtime.md (4 parallel audits)
- [x] PHASE 3: Architecture 02-authority-model + 03-layer-tree-plan + 04-ordering
- [x] PHASE 4: Core runtime — layer_order + LayerTreePlan + controller rewire
      (9a2657fa; D1-ws/D3-ws closed; nested user groups; 36 tests)
- [x] PHASE 5: TreeDiff keyed-LCS + diff-driven reconcile + call-count tests
      (0b65621c; 1000层插入=1 move; 22 tests)
- [x] PHASE 6: Native tree transaction (bridge 0.7.0a0: begin/end window +
      tree_revision + runtime_facts counters) + echo gate (d6164860, 1cae67f2;
      10+8 native tests; 50 upserts=1 sync; 1000-layer publish=1 sync)
- [x] PHASE 7: Five-target edit state (d4dc6b45; EditTargetSnapshot +
      divergent status presentation; V10 review #1 semantics preserved)
- [x] PHASE 8: Stage fixes — empty-group materialization (D11-ws), ghost
      membership pruning (D13-ws), factor titles (D2-ws) (9006c98f)
- [x] PHASE 11: Layout/legend/tree one order source (62157cc9; P0-1 closed:
      mirrorTreeOrderTopFirst; flat top-first reversal + parity tests)
- [x] PHASE 12-M0: Topology spec materialized (docs/specs/) + CRS gate
      (#1285) + two-phase all-or-nothing Python save (#1283 partial)
- [ ] PHASE 9: Save-intent in-memory buffer + per-feature signature cache +
      raster ledger + lifecycle docs (09-mirror-lifecycle)
- [ ] PHASE 10: Nested groups UI polish + restore/reopen docs
- [ ] PHASE 13: Scale structural suite (13-scale)
- [ ] PHASE 14: 8 review rounds + P0/P1 fixes
- [ ] PHASE 15: Remaining docs 02–15 + milestone commits + PR + URL

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| vendor build thought lost (V7 worktree deleted) | 1 | neutral copy survives at paleo-qgis-build\qgis-vendor |
| uv install geoviz_common missing | 1 | geo-viz-engine submodule not inited; local clone + pin 08851951f |
| PySide6 6.8.3 vs conda Qt 6.11.2 mismatch | 1 | corrected to 6.11.2 |
| sed replace over-reached into own syncCanvasesAll impl | 1 | infinite recursion → probe4 hang; fixed + rebuilt |
| tree_transaction tests hung (teardown) | 1 | json.loads(dict) bug in MY test; C++ shutdown window reset added |
| worktree well-log-engine dirty on arrival | 1 | restored to pinned f845e7ab (not mine) |
| flush all-or-nothing: gate failure still committed others | 1 | phase-1 gate aborts whole save; fixed |
| CRS gate: layer-cleared decl still blocked by project CRS | 1 | layer-only declaration check per #1285 guided-fix semantics |

## Environment facts
- VS2022 cmake + MSVC 14.38; Qt6 = paleo-qgis-deps\Library (6.11.2)
- Vendor build: C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor
- Venv .venv cp312 (PySide6 6.11.2); bridge 0.7.0a0 built in worktree
- Pre-existing env failures: test_mapping_stage_ui multi-test AV (main too);
  test_authoring_ux registry-flags (owned by #1267/#1255)
