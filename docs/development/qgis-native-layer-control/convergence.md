# QGIS-Native Layer Control Convergence — QgsProject/QgsLayerTree as the Single Control Plane

Status: active architecture (supersedes the V14 reconcile plane described in
`docs/development/qgis-v14-layer-control/`).

Branch: `feat/qgis-native-layer-control` · Baseline: `192422c60` (#1480).

## Authority model

```text
QgsProject (MapSession, one per session)
  └─ QgsLayerTreeRoot                      ← the layer tree (structure/order/
      ├─ QgsLayerTreeGroup                 grouping/visibility authority)
      │   • "pwb/group_id"   custom property  (machine identity)
      │   • "pwb/group_kind" custom property  ("system" | "user")
      │   • "pwb/expanded"   custom property  (expand persistence)
      └─ QgsLayerTreeLayer → QgsMapLayer registry
          • QGIS layer id == pwb/layer_id    (deterministic, assigned at
            admission; registry lookups are O(1))
                ↓
      QgsLayerTreeModel / QgsLayerTreeView  (native drag/rename/check)
                ↓
      QgsLayerTreeMapCanvasBridge → QgsMapCanvas  (single canvas writer)
                ↓
      persistence: <project>.artifacts/layer-tree.xml
        (QgsLayerTree::writeXml — the same serializer .qgs embeds)
```

What persists where:

| Data | Carrier |
|---|---|
| Tree structure, order, grouping, visibility, expanded | QGIS XML sidecar (`layer-tree.xml`) |
| Geological memberships (role/factor task/constraint kind/created stage/catalog lineage) | project document `mapping_workspace` (domain semantics QGIS cannot express) |
| Per-stage view states (visibility overlay/locks/opacity/active target) | project document `mapping_workspace` |
| Style/rendering/CRS/labeling | QGIS layer properties + QML sidecars (unchanged) |

## QGIS replacement matrix (deleted PWB abstractions)

| Retired abstraction | Was | Replaced by |
|---|---|---|
| `pwb::workspace::layer_order` (order-key engine: base-26 keys, LIS key assignment, rebalance) | Fractional string keys to minimize diff-persistence of order | Nothing — QGIS child order is integer indices persisted natively by the sidecar. Role-band vocabulary moved to `pwb::ui_composite::layer_ordering` (initial arrangement only) |
| `pwb::workspace::layer_tree` (`LayerTreeSnapshot`/`TreeNode`, `tree_from_nodes`, `flatten_for_render`) | The second tree: serializable domain copy of the QGIS tree | `QgsLayerTree` itself; persistence via `QgsLayerTree::writeXml/readXml`; one-shot legacy JSON migration inside `LayerTreeComposer::migrate_legacy_tree` |
| `pwb::workspace::layer_tree_diff` (keyed-LCS `diff_trees`) | Minimal op-set computation desired-tree → real-tree | Deleted — mutations go straight to real nodes (no desired tree to diff against) |
| `pwb::ui_composite::layer_tree_plan` (`build_plan`, desired-tree assembly, role-band merge, user-group tree builder) | Built the desired tree from templates + memberships + placements | `LayerTreeComposer`: template skeleton (`ensure_system_groups`, create-only) + home routing (`route_layer`, band-ordered for fresh builds) |
| `pwb::ui_composite::ILayerTreeStack` + `QgsLayerTreeStack` (op vocabulary applier, transaction window, revision/echo bookkeeping) | Second control plane hop: plan → ops → QGIS | `LayerTreeComposer::MutationGuard` keeps only the two proven protections (registry-bridge detach #1154, subtree-safe takeChild) + batched render suppression with one closing refresh. Revisions/echo-staleness deleted (no loop left to echo) |
| `LayerGroupController` reconcile half (`reconcile`/`apply_tree`/`observe_tree_nodes`/placement tables/order-key cache/user-group registry/`state.tree` write-back) | Incremental sync loop + save-time observation | Nothing — the live tree IS the result. Controller keeps only policy: membership lifecycle, stage view-state policy, routing queries (Qt-free) |
| `MapSession::syncCanvasLayers` | Second writer of the canvas layer set (parallel to `QgsLayerTreeMapCanvasBridge`) | Deleted; the bridge is the single canvas writer |
| `MappingWorkspaceState::tree` (JSON) | Persisted second tree | Sidecar; field kept read-compat for one-shot migration, cleared at `compose()` |
| workspace `layer_control_scale_test` (1000-layer key/diff scale) | Key-engine scale contracts | `platform.layer_tree_composer` 1000-layer compose + routing over the real QGIS tree |

## What survived, and why (QGIS has no equivalent)

* `pwb::ui_composite::layer_groups` — system-group templates, role → home
  routing, drag legality (`movable_into_system_group`), migration
  classification. Geological semantics, Qt-free, consumed by the composer.
* `pwb::ui_composite::layer_ordering` — role bands (initial scientific
  arrangement inside a container). After the first arrangement the real
  tree order is the truth; bands are never re-applied.
* `pwb::ui_composite::layer_stage_controller` — stage-switch policy
  (visibility policy, per-stage active target, no cross-stage
  inheritance). Executes through host-wired hooks onto the real tree.
* `pwb::workspace::{state,mutations,state_ops,source_usage}` — memberships,
  stage view states, catalog lineage, reverse usage queries (domain data,
  not tree geometry).
* `LayerTargets`/`layer_presentation` — edit-target invariants and row
  status language (probes read `QgsMapCanvas::currentLayer()` — the QGIS
  selection stays the authority).

## Lifecycle / performance contracts

* Stage switch (`LayerStageController::set_stage`): writes stage →
  `ensure_system_groups` (create-only) → one batched visibility push →
  target reassignment. Layer objects are never recreated.
* Every structural batch runs inside `MutationGuard`: registry bridge
  severed, canvas rendering suppressed, exactly one closing refresh
  (restores only what it suppressed — R2-13). Nested guards are safe
  (documented in layer_tree_composer.cpp).
* Layer removal: real QGIS removal (tree node + registry through the
  bridge); memberships drop through `unregister_layer`; no PWB-side
  dangling caches exist by construction.
* Session teardown (`MapSession::close`): tools unset → canvas layers
  cleared → bridge detached → layers removed → project destroyed.
* Migration carrier safety: the legacy `state.tree` survives `compose()`
  and is retired only after the FIRST successful sidecar write
  (`MainWindow::syncLayerControlOnSave`); a failed write keeps the
  document carrying the pre-migration tree, so the user's structure is
  never silently lost. The sidecar write itself is atomic (QSaveFile
  rename-commit, byte-count verified).
* User checkbox gestures on the native tree are recorded into the
  per-stage overlay through the tree MODEL's `dataChanged`
  (`visibilityChanged` is emitted per node with no relay to the root);
  programmatic batches are suppressed via
  `LayerTreeComposer::in_structural_batch`.
* Deterministic QGIS layer ids (`MapSession::assignDeterministicLayerId`):
  `layerById` resolves through the project registry O(1); sidecar layer
  references survive across sessions without an id remap; collisions keep
  the random id with the custom-property join as fallback.

## Known limits / follow-ups

* `native/qgis_render_bridge` (pybind product) still carries its own
  bridge-side tree vocabulary (`map_stack_service`); it is a separate
  product surface and out of this change's scope.
* `MappingWorkspaceState.tree` stays in the codec for legacy reads; the
  migration is one-shot per project (first open converts; the first
  SUCCESSFUL save writes the sidecar and retires the JSON tree).
* Layer-opacity gestures through the QGIS properties dialog are not yet
  recorded into `StageViewState.layer_opacity` (the mirror-stack panels
  that consumed it are display-only on the product path).
* `job_runtime.lifecycle` and `closure_science.core` are load flakes /
  pre-existing baseline failures on this host (A/B-verified against the
  baseline worktree; gcc-15 ICE and ld signal-11 appear intermittently
  under the 3-parallel-worktree build load — every build here used
  retry loops at -j<=4).
* Mirror-stack UI (`UnifiedMapCanvas`/`QgisCanvasShim`/`MirrorSnapshot`)
  is untouched here — it serves the no-QGIS fallback and composite
  document paths; its product-main-path usage is display-only.
