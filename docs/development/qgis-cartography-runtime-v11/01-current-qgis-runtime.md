# 01 — Current QGIS Runtime (audit of main @ 6c08fb7d)

Sources: four full-read audits (`.scratch/v11-audit/{mapping-python,
mapping-workspace,ui-qgis-stack,native-bridge}.md` — worktree-local, with
file:line evidence). This document is the V11 baseline: what exists, what is
missing, and where each goal §5–§31 concern stands today.

## 1. Runtime topology

```
mapping_workspace/            domain semantics (roles, groups, stages, state)
  LayerGroupController        desired-tree build + incremental reconcile
  LayerTreeSnapshot           frozen pure-data tree model (no Qt)
mapping/qgis_mirror.py        snapshot → QGIS mirror publish (ledger + delta)
ui/qgis_stack/canvas_shim.py  Qt host for native QgisMapStack (one per canvas)
ui/qgis_stack/layer_tree_panel.py  native QgsLayerTreeView host + writeback
ui/workstation/composite_*    editing controller, document, attribute table
native/qgis_render_bridge     pybind11 ext → qgis_core/gui/analysis (vendor 4.2.0)
  map_stack_service.cpp       QgisMapStack: mirror layers, groups, tree view,
                              tools, snapping, layout export (~75 pybind methods)
  edit_tools.cpp              PwbVertexTool/MoveTool/SelectTool/MeasureTool
  geometry_service.cpp        21 single-geometry pure ops
```

Three layer-tree UI lineages coexist (D1-ui): the mapping-workspace native
tree (workstation), the fallback `LayerManagerPanel` QTreeWidget, and the
legacy `NativeLayerTree` (reversed-z-order model, old mapping page). V11
keeps ONE authority (native) and shrinks the others to fallbacks.

## 2. The four concepts today (goal §6)

| Concept | Current carrier | Problems |
|---|---|---|
| Layer identity | `doc_id` == `LayerRef.layer_id` == QGIS custom prop `pwb/doc_id`; groups via `kGroupIdProp` | Sound. Ghost memberships never pruned (D13-ws); ledger keyed by `id(stack)`+doc_id with weakref guard |
| Scientific role | `LayerRole` enum, 33 roles; membership records `LayerMembershipRecord` | QC/AID routing inconsistent stage-aware vs stage-None (D1-ws); registry gaps MAP_SYMBOL/PENDING_REVIEW_AREA (D14-ws) |
| Tree placement | `_placements`/`_group_orders`/`_root_order` positional dicts; desired tree rebuilt every sync | Within-group user order discarded for system/factor groups (D3-ws — biggest ordering defect); root-only user groups |
| Render/legend/layout order | group mode: tree walk; flat mode: `set_mirror_layer_order(seen)`; layout: `mirrorOrderTopFirst()` **root children only** | **Order-convention conflict** bottom-up vs top-first between native flat mode, fallback painter, and docstrings (no parity test); layout exports silently DROP grouped layers (native §7); canvas==tree==legend==layout guaranteed nowhere |

## 3. Ordering engine (goal §9/§10) — does not exist yet

- Default group order = declaration order of `SYSTEM_GROUP_TEMPLATES`
  (14 system groups, band ints 10..950 declared but only positionally
  consumed; `order` field feeds a dead helper).
- Within groups: bucket order = **flat snapshot order** (system groups),
  `FACTOR_CHILD_ORDER` rank for factor groups, `_group_orders` for user
  groups only. `_root_order` maintained but never read.
- No per-layer ordering keys anywhere (no rank/fractional key); insertion
  = list append; persistence = whole-list serialization.
- No band model for roles; no stage semantics in ordering; no user-override
  merge algebra beyond placement override; no temporary overlay band.

## 4. Tree reconcile (goal §12) — incremental but coarse

`LayerGroupController.reconcile` → `_apply_tree`:
1. `upsert_group` × G every sync (even no-op) — each does a full-tree
   `findGroupByGroupIdIn` + all-canvas sync (O(G×N)).
2. `_place_delta`: any membership change in a group re-moves **every**
   sibling + full subtree recursion; identical containers recurse.
3. First apply / force → one `apply_tree_placements(json)` batch call
   (the only batch API; O(N), one suppression window, one canvas sync —
   but ends with `expandAllNodes()` clobbering collapse state).

Failure semantics: exceptions re-raised (good); illegal drags rejected with
`on_invalid_move("","")` (ids dropped — generic message only) + forced
reconcile snap-back.

## 5. Native transaction (goal §13) — none public

- `SuppressGuard` + `RegistryBridgeDetach` + subtree detach/restore are all
  internal per-call. Python cannot open a suppression window across calls.
- 17 mutation sites each end in an identical all-canvas `syncCanvasLayers`
  loop → an N-layer publish causes N+G+3 full canvas-layer-set rebuilds.
- Echo callbacks coalesce via `QTimer::singleShot(0)` batch (schema-2 JSON)
  but only for USER edits; programmatic ops never echo (by design).
- No revision/token exposed for tree state; `tree_echo_suppressed` is the
  only observability; no way to know "echo silence = nothing vs suppressed".

## 6. Bidirectional sync (goal §14) — one-directional per op kind

- User tree edits → JSON events (`parse_tree_events`) →
  `observe_tree_nodes` (structure), `record_group_visibility_event`
  (visibility), rename/expand handlers. Validation via
  `movable_into_system_group`; factor cross-task drag wrongly accepted
  (D2b-ws); system rename silently reverted without notice (D13-ws).
- Programmatic → QGIS: no echo (SuppressGuard), but the Python-side
  `_publishing` flag guards only selection. No origin token; no revision
  counter; expand-state collisions keyed by project display name (D12-ws).

## 7. Active/edit/tool targets (goal §15) — five holders, known divergence

`tree selection` → `active_layer_changed` → `set_active_layer` +
`set_active_target` → `_apply_active_target`. Divergence (D2-ui): with a
session tool active on layer A, clicking session-less layer B keeps the
tool writing A's session while tree/status bar/tooltip present B.
`edit_target` vs `tool_target` vs `selection_layer` are not distinct
concepts in code. #1277 owns the session-commit-on-switch half; the
presentation/target-model split remains for V11.

## 8. Stages (goal §16) — union tree honored

`set_stage` changes: stage value, incremental group visibility (changed
only), default lock seeding, active-target reassignment, dock
recommendation (first entry), signals (tool profile, snapping repush,
readiness/freshness re-eval). It does NOT rebuild/re-upsert/reopen —
verified. Gap (D11-ws): newly-entered stage's empty groups don't
materialize until next composition sync; benign double set_stage via
echo loop.

## 9. Layer lifecycle / mirror (goal §17/§18)

- Host: `VectorLayer` (data_revision, selection, single session);
  session mutations journaled; `changes_since` returns None on unrecoverable
  span → consumers full-rebuild.
- Mirror ledger `(id(stack), doc_id) → _LedgerEntry` (7 tokens). Delta
  channel exists (delete+re-add by `__pwb_fid`, base-revision guarded).
  On main, full FeatureCollection is serialized on every non-delta publish
  and per-feature signatures recomputed O(N) — **#1277 owns the
  delta-succeeded empty-ship optimization**; V11 owns: per-feature
  signature O(changed), raster ledger (absent today — rasters re-upsert
  every publish), fields/role tokens, post-commit alignment (#1283).
- Failure hole on main (failed upsert prunes healthy mirror) — **#1277
  owns the failed-delta retry fix**; V11 must not duplicate.
- Full-ship path does not invalidate point locators on main — **#1267
  owns `invalidateLocators`**; V11 reuses the seam.
- Lifecycle transitions not modeled: rename → mirror rename is by
  name-diff; `replace source`/`schema change` force full reship (defensible);
  no `restore` after removal.

## 10. Native editing & topology (goal §20/§21) — pre-M0

Present: vertex tool (single-vertex drag/insert/delete + hover markers +
snap indicator + min-vertex guard + zero-displacement suppression), move
tool, digitize tool (QgsMapToolDigitizeFeature + CAD dock hidden + 30ms
progress throttle + CRS-drift rejection), select, identify, measure,
snapping config push (types/modes/per-layer/intersection + locator
pre-warm + probe), highlights, `setTopologicalEditing` project flag push.

Absent (the #1278 M0–M5 gap list): no `addTopologicalPoints`; split
non-topological (`splitGeometry(topological=false)`); no
avoid-intersections; no tracing; no multi-vertex box select; no
all-layers vertex scope; no undo/redo bridge (Python journal is the only
undo); no `committed*` signal channel; no beforeCommitChanges gate; no
QgsGeometryCheck exposure; no topology inspector. Edit authority today =
Python session journal + TopologyService (the system #1281 retires).

## 11. Layout/legend (goal §19)

`layout_export` builds a transient QgsPrintLayout from the stack;
map layers = `mirrorOrderTopFirst()` reversed = **root order only —
grouped layers silently absent**. Legend item = manual sync + optional
`filter_layers`. Production composition panel passes no stack → always
falls back to the Python composer engine (z_index order). Legend order ==
tree root order only by construction of that walk; fallback composer and
native layout disagree on source-of-truth.

## 12. Scale (goal §25/§26) — known O(N²) hot paths

factor sort `known_ids.index` (ws:274); `_place_delta` sibling fan-out;
`upsert_group` × G per sync (O(G×N) C++ finds + G canvas syncs);
`_group_summaries` O(G×M) per decorations push; presentation per-layer
profile rebuild O(N×G); panel `_layers.index` idioms; per-state_changed
row-indicator JSON bridge calls O(N)/op; fallback full tree rebuild on
reorder. Mitigations that exist: `apply_tree_placements` batch O(N),
changed-only visibility, ledger no-op skip, 120ms publish debounce.

## 13. Restore/reopen (goal §27)

Saved: stage, per-stage view state (visibility/locks/opacity/active),
memberships (role/task/kind/stage/version), full tree dict, maturity,
compilation input set, QGIS project XML envelope (styles + tree),
user_vector_layers truth. Restored via stable ids throughout. Gaps:
expand prefs keyed by project display name (QSettings); factor group
titles from raw task ids (sync_factor_titles dead); within-group order
lost for system/factor groups (D3-ws); ghost memberships inflate counts.

## 14. Fallback (goal §28)

Honest at load: exception guard → UnifiedMapCanvas, "unavailable"
capability mode feeds the same evaluator, degraded status message at
project open. Gaps: degraded notice one-shot; stage group visibility
silently no-ops in fallback; fallback tree = parallel QTreeWidget with
full rebuild on reorder.

## 15. Defect register (V11 scope, deduplicated vs PR-owned)

P0-class:
1. Layout exports drop grouped layers (root-only walk) — data loss in
   final deliverable (goal §19).
2. Order-convention conflict bottom-up vs top-first — either native
   canvas or fallback paints wrong stacking; no parity test.
3. Per-op all-canvas sync storms (N+G+3 syncs per publish) — structural
   scale blocker (goal §13/§25).

P1-class:
4. Within-group reorder loss for system/factor groups (goal §9/§10).
5. Active/edit/tool-target divergence (goal §15).
6. O(N²) hot paths above (goal §25/§26).
7. `apply_tree_placements` expandAll clobbers collapse state.
8. applyProjectXml swallows placement failures (S1-native).
9. `on_invalid_move("","")` drops ids — no actionable feedback.
10. New-stage empty groups don't materialize (D11-ws).
11. Mirror raster ledger absent (re-upsert every publish).
12. canvasOrThrow reinterpret-casts unknown addresses (T4-native).

P2-class: dead APIs (`set_group_visible`, `snapshot_bridge_tree`,
`RoleRule`, `profile_group_order`, `flatten_for_render`); vestigial
persisted fields (`GroupNode.expanded/locked/visible`, `LayerRef.note`);
QSettings project-name keying; ghost memberships; registry gaps
(MAP_SYMBOL/PENDING_REVIEW_AREA specs); sync_factor_titles dead; scale-
range convention split (T2-native); upsert 17-arg wire (T1-native).
