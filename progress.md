# Progress — QGIS Cartography Runtime V11

## Session 2026-09-12 (setup + state sync + audits + M1–M8)
- Worktree C:\Users\wangj.KEVIN\projects\paleo-workbench-qgis-runtime-v11,
  branch qgis-runtime-v11 off main 6c08fb7d. Submodules pinned
  (geo-viz-engine 08851951f via local clone; well-log-engine f845e7ab).
- GitHub synced: open PRs #1267/#1277 file-level ownership (findings +
  00-overlap-audit); #1278 map 8/8 decisions read, impl NOT started, spec
  file missing everywhere → V11 materializes it.
- Vendor build recovered at neutral paleo-qgis-build\qgis-vendor; conda
  paleo-qgis-deps intact; VS2022 toolchain OK. Worktree venv cp312
  (PySide6 6.11.2), bridge 0.7.0a0 built via PALEO_QGIS_REUSE_VENDOR=1.
- 4 parallel deep audits → .scratch/v11-audit/*.md + 01-current-qgis-runtime
  (defect register: 3 P0, 12 P1).
- M1 architecture docs (0642e367): 02-authority, 03-plan, 04-ordering.
- M2ordering+plan (9a2657fa): layer_order, LayerTreePlan, controller rewire,
  nested user groups, invalid-move ids, effective_home_group. 36 tests.
- M3 tree diff (0b65621c): keyed LCS + diff-driven reconcile + call-count
  structural tests. 22 tests.
- M4 native transaction (1cae67f2, bridge 0.7.0a0): begin/end window,
  tree_revision + runtime_facts counters, expand-preserving placements,
  tree_transaction wired into reconcile + mirror. 10 native tests.
- M5 echo gate (d6164860): revision-based stale drop (02 invariant 3).
- M6 five-target state (d4dc6b45): EditTargetSnapshot + divergent status.
- M7 stage fixes (9006c98f): rematerialize (D11), ghost prune (D13),
  factor titles (D2).
- M8 layout order (62157cc9): mirrorTreeOrderTopFirst (P0-1); flat
  top-first reversal + parity tests.
- M9 topology M0: spec docs/specs/topological-editing-migration-spec.md
  (agent assembly, 366 lines); crs_gate.py + pre-entry gate + guided fix
  (#1285); two-phase all-or-nothing flush (#1283); 14 tests.
- M10 lifecycle+scale (42146767, 1b228914): save-intent channel,
  changed_hints O(changed), raster ledger, single-mount fix, scale suite.
- M11 review round (40b8c2e6): R1–R4 parallel agents (P0×7: ghost-container
  drop, self/cycle recursion, unfiltered mount, skipped-drift, stale-hints
  loss, ledger poisoning, fast-path bypass) + R5 CRS / R6 fallback / R7
  scale / R8 final. Docs 05–08/10–14 complete (15 files).
- Final validation: 204 passed Python family + 39 passed native family.
- Incidents: sed over-reach self-recursion (probe4 hang, fixed); json.loads
  on dict in my test (teardown hang, fixed + C++ shutdown reset);
  gate-phase-1 abort semantics; layer-only declaration check.
- Pre-existing env: test_mapping_stage_ui multi-test AV (main too);
  authoring_ux registry-flags (owned by #1267).

## Next
- PHASE 9: save-intent buffer + feature-sig cache + raster ledger +
  lifecycle docs; PHASE 10 groups UI; PHASE 13 scale; PHASE 14 reviews;
  PHASE 15 docs tail + PR.
