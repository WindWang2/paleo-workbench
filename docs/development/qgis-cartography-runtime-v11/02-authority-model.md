# 02 — Authority Model (V11)

## 1. The one rule

```
QGIS Layer Tree = the ONLY runtime authority for layer structure,
order, visibility and canvas/legend/layout composition.
```

Paleo owns **intent** (domain semantics) and **truth** (science data):

| Concern | Owner | Carrier |
|---|---|---|
| Science data (features, fields) | Paleo | `user_vector_layers` (project truth) |
| Layer identity ↔ role ↔ membership | Paleo | `MappingWorkspaceState.memberships` |
| Desired tree (intent) | Paleo | `LayerTreePlan` (→ `LayerTreeSnapshot`) |
| Live tree (structure/order/vis) | **QGIS** | `QgsLayerTree` via bridge |
| Rendering, snapping, geometry | **QGIS** | qgis_core/gui/analysis via bridge |
| Stage/lock/maturity policy | Paleo | profiles, gates, `StageViewState` |
| Editing session semantics | Paleo session set + QGIS edit buffer | #1281/#1283 contracts |

## 2. The sync loop (observe → validate → persist intent → reconcile)

```
        ┌──────────────────────────── Python (Paleo) ───────────────────────────┐
        │  domain events ──► LayerTreePlan (desired)                            │
        │                         │                                             │
        │                         ▼                                             │
        │                  TreeDiff(current, desired)  ◄── tree_snapshot_json   │
        │                         │                           (observe)         │
        │                         ▼                                             │
        │            apply within BEGIN..END TREE UPDATE  ──────────────┐       │
        └───────────────────────────────────────────────────────────────┼──────┘
                                                                          ▼
        ┌──────────────────────────── C++ (QGIS) ──────────────────────────────┐
        │  deferred sync; one canvas refresh; one legend sync; no echo          │
        │  tree_revision++ on every mutation                                    │
        └──────────────────────────────────────────────────────────────────────┘
                ▲ user drags/checks/renames in QgsLayerTreeView
                │ echo batch (schema-2 JSON + revision + origin) ──► validate
                ▼                                                     │
        invalid → feedback (reason) + restore ◄────────────────────────┘
        valid   → observe_tree_nodes → persist intent (state.tree)
```

Invariants:
1. **Never** rebuild the whole tree on stage switch / composition sync;
   reconcile is always a minimal diff apply.
2. **Never** maintain a second mutable runtime tree; `LayerTreeSnapshot` is
   (a) pure description of desired intent, (b) projection of observed
   events, (c) persistence payload — never a live shadow updated by
   rendering code.
3. Programmatic applies carry an **origin token** (`pwb-py-<seq>`) and a
   **tree revision**; user echoes carry the revision at event time.
   Python drops echoes with `revision <= last_applied_revision` (echo
   suppression at the semantic level, not just a boolean flag).
4. Illegal user operations are **rejected with an actionable reason**
   (layer id + group id + rule id) and restored by an explicit reconcile —
   never a silent snap-back.
5. Canvas order == tree order == legend order == layout order — all four
   are read from the same tree walk (`layer_ids_top_first`), nowhere else.

## 3. Order-of-authority conflicts (resolution table)

| Conflict today | Resolution |
|---|---|
| `set_mirror_layer_order` (flat, root-only) vs group placements | Group mode wins; flat order API marked legacy, only valid inside a declared flat project (no groups) |
| Python `_publishing` flag vs C++ SuppressGuard | Both stay; V11 adds revision-based drop as the semantic guard (flag remains for selection) |
| `build_desired_tree` recomputes order from snapshot order (discards user order) | Desired order = order keys (persisted per node); snapshot order only seeds DEFAULT keys on first sight |
| Presentation stage-aware routing vs controller stage-None routing (D1-ws) | One routing function with explicit stage parameter; all callers pass the same value (the layer's creation stage, from membership record) |
| Layout map layers walk root children only | Fixed: full-tree depth-first walk (04/§5) |
| Fallback painter bottom-up vs native top-first | One named convention (top-first) + parity test; fallback painter reversed once to match |

## 4. Degradation contract

Bridge unavailable → **degraded mode is explicit and persistent**:
- a visible banner/state (not one-shot) lists exactly which surfaces are
  unavailable: groups, native editing, snapping, topology, layout export;
- stage group-visibility actions report "不可用（无 QGIS 桥）" instead of
  silently no-oping;
- basic browsing/export through the Python fallback remains;
- no capability is ever *simulated* (no fake groups, no fake snap-on).

## 5. Lifetime authority

- `QgsVectorLayer` mirror objects live and die with the QGIS project; the
  mirror ledger holds **weak** bookkeeping only (tokens), never geometry.
- Canvas/tree-view objects are owned by Qt hosts; the bridge reaps its
  tables on `destroyed` (existing pattern retained).
- The truth (`user_vector_layers`) is authoritative across reopen; the QGIS
  project XML envelope is presentational only (V10 decision, unchanged).
