# 00 — Overlap Audit (QGIS Cartography Runtime V11)

Base SHA: `6c08fb7d` (origin/main, 2026-09-12)
Branch: `qgis-runtime-v11`

This audit fixes the ownership boundaries V11 must respect. Two open PRs and
two parallel V11 lines already own specific fixes/areas; V11 builds the
runtime control plane AROUND them, never re-implementing their content.

## 1. Open PR #1267 `v10-review-fixes` (mergeable)

Fixes: #1255 (action_registry tool ids), #1256 (icons + checked vocab),
#1258 (vertex_delete_rejected shim consumer), #1259 (multi-select single
undo unit), #1260 (provider_writable honors bridge supports_editing),
#1261 (perf gates), #1262 (health probe fallback + transform_available),
#1264 (ring/part refresh topo counts), #1265 (loader non-Windows crash),
#1263 (paths.py hardcoded dev path).

Owned changes (files V11 must not duplicate):
- `native/qgis_render_bridge/src/map_stack_service.{cpp,hpp}` — adds
  `invalidateLocators(layer)` used by delta AND full truncate+add paths
  (#1257 stale point-locator fix); null-guard on `dataProvider()`.
- `paleo_workbench/mapping/{action_registry,tool_availability,tool_context,
  vector_layer}.py`, `qgis_runtime/{health,paths}.py`,
  `ui/qgis_stack/canvas_shim.py`, `ui/workstation/composite_{document,
  editing}.py`, `ui/map_action_controller.py`, 5 icons,
  `scripts/run_qgis_env.py`, tests (test_v10_* additions).

V11 consequence: when touching the same files (likely: map_stack_service,
canvas_shim, composite_editing, tool_context), V11 changes must be written
against MAIN semantics and re-apply cleanly after #1267 merges; V11 must NOT
re-fix #1255–#1264. V11's own locator invalidation needs (batch tree
transactions) will REUSE #1267's `invalidateLocators` seam by name once
merged; until then V11 does not touch that concern.

## 2. Open PR #1277 `review-convergence-20260912` (mergeable, main+3 commits)

Fixes: #1268 (switch-layer commits previous session), #1269 (paged asset
materialization), #1270 (sand-ratio unit), #1271 (fusion freeze pins),
#1272 (mirror delta full-collection dumps + attribute table 100k), #1274
(theme lambda lifetime), #1275 (interpolation honesty), #1276 (snapping
push honesty: `set_snapping_config` returning False disables + notifies).

Owned changes:
- `qgis_mirror.py` — delta-succeeded path ships `_EMPTY_FEATURE_COLLECTION`
  (no full dumps on delta path); failed-delta retry and TypeError retry
  re-serialize and full-ship; ledger semantics unchanged.
- `map_stack_service.cpp` — refuse-empty-truncate guard (delta not applied
  + empty geojson → throw, host full-ships).
- `composite_editing.py` — `editable` metadata now honest via
  `can_edit_layer` (#1273); snapping push honesty.
- `composite_attribute_table.py` (differential + sort), `stage_actions.py`,
  catalog db/service, pipeline, factor_{fusion,interpolation,units},
  integrated_compilation, interpolation_evaluation, well_identity_adapter,
  data_page, loader, canvas_shim, qgis_style, stage_vocabulary,
  run_qgis_env + tests.

V11 consequence: the mirror single-feature serialization optimization for
the DELTA-SUCCEEDED path is OWNED by #1277. V11's remaining mirror work
(§09): per-feature signature recomputation O(N) per publish, raster ledger
absence, fields_sig/role tokens, post-commit alignment per #1283 (ledger
freeze during session set, committed* writeback channel, no re-ship after
commit). V11 does NOT redo the empty-collection-ship trick.

## 3. Open issues NOT owned by either PR

- #1230 (CI slow-family gating) — out of V11 scope (no CI work).
- #1266 (V10 tautology guard red: 4 V10 test files) — test-hygiene debt on
  files V11 will extend; V11 must not add tautological assertions and
  SHOULD avoid worsening it; full fix not owned by V11.
- #1263/#1265 remainder — #1267 owns the code fixes; V11 leaves them.

## 4. Parallel V11 lines (do not enter)

- `data-fabric-v11` (worktree locked @ main): catalog schema, well
  multi-file model, Data Fabric, `ui/pages/data_page.py`.
- `workbench-ux-v11` (stacked on #1277): generic UI design system, dock
  framework, shared components. V11 UI work is QGIS-presentation-specific
  (layer panel badges, tree sync UX) and reuses their components; no
  generic design-system edits.

## 5. Topology roadmap #1278 — implementation NOT started

- All 8 decision issues (#1279–#1286) are closed; the referenced
  `docs/specs/topological-editing-migration-spec.md` exists on NO branch
  (verified across all remote refs) — the spec deliverable never landed.
- Current native state confirms zero topology implementation:
  no `addTopologicalPoints` anywhere, `splitFeatures` non-topological
  (geometry_service.cpp:79-81), no avoid-intersections layers, no
  cross-layer C++ ops, no vertex box-select (audit: native-bridge.md).
- V11 materializes the spec from the decision issues (assembly view;
  decisions remain the authority) and implements milestones from M0
  forward per its §8, within this goal's budget.

## 6. V10 docs baseline (already merged, do not restate)

- `docs/development/qgis-native-vector-authoring-v10/00..11` — editing
  flow, tool matrix, snapping/topology, undo/transaction, performance,
  verification, review findings, known limitations.
- `docs/development/qgis-spatial-layer-foundation-v10/`,
  `qgis-authoring-ux-v10/` — layer platform + UX matrices.

## 7. Verdict

No overlap conflict blocks V11: every fix in #1267/#1277 is a point fix on
paths V11 evolves but does not need to re-fix. V11 commits must be authored
to merge after both PRs (expect small textual conflicts in
`map_stack_service.cpp`, `qgis_mirror.py`, `canvas_shim.py`,
`composite_editing.py` — acceptable; resolution favors the semantic union).
