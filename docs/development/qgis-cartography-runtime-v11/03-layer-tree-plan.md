# 03 — LayerTreePlan (V11)

## 1. Decision: evolve `LayerTreeSnapshot`, don't replace it

`LayerTreeSnapshot`/`GroupNode`/`LayerRef` (mapping_workspace/layer_tree.py)
stay the tree carrier: pure dataclasses, no Qt, three roles (desired intent /
observed projection / persistence). What V11 adds is the **plan layer** —
the policy that *produces* the desired snapshot — as a new pure module
`mapping_workspace/layer_tree_plan.py`. `LayerGroupController.build_desired_tree`
becomes a thin wrapper over the plan builder (same call sites, same tests).

## 2. Plan inputs (all pure data)

```python
@dataclass(frozen=True)
class LayerTreePlanInput:
    layer_records: tuple[PlanLayerRecord, ...]   # id, role, factor_task_id,
                                                 # constraint_kind, created_stage,
                                                 # display name, kind(raster/vector),
                                                 # science sub-order key
    stage: MappingStage | None                   # current stage (visibility only)
    user_placements: Mapping[str, str]           # layer_id → group_id override
    user_group_orders: Mapping[str, Sequence[str]]  # group_id → ordered layer ids
    user_groups: Mapping[str, str]               # group_id → name (user.*)
    root_order: Sequence[str]                    # loose root layer ids
    known_order_keys: Mapping[str, str]          # node id → persisted order key
    factor_titles: Mapping[str, str]
```

## 3. Plan output

A `LayerTreeSnapshot` whose every child (group or layer) additionally
carries an **order key** (04), plus a `LayerTreePlanFacts` side-car:

```python
@dataclass(frozen=True)
class LayerTreePlanFacts:
    default_keys: Mapping[str, str]    # node id → default (non-override) key
    override_keys: Mapping[str, str]   # node id → user-persisted key
    group_kinds: Mapping[str, str]     # group id → system|factor|user
    placement_rules: tuple[PlacementRule, ...]  # for validation + UI feedback
```

`LayerRef`/`GroupNode` gain `order_key: str = ""` (serialized; empty =
unkeyed legacy node → migration assigns deterministically).

## 4. Placement policy (who goes where)

Unchanged routing, now with ONE stage parameter everywhere (fixes D1-ws):
- factor family → `factor.<task_id>` (task mismatch = invalid target)
- QC/AID → creation-stage aux group (from membership record), not static home
- everything else → role home group (`SYSTEM_GROUP_TEMPLATES`)

### 4.1 Group capability matrix (goal §11)

| Group kind | Create | Delete | Rename | Move | Nest user groups inside | Layers nestable |
|---|---|---|---|---|---|---|
| system (`phase*`, `base.reference`, `legacy.unclassified`) | no (auto) | no | no (template title) | no (fixed band) | no | yes (layers only) |
| factor root `phase2.factors` | auto | no | no | no | no | no (groups only) |
| `factor.<task>` | auto per task | auto when task removed | via `factor_titles` sync | within factor root only | no | yes |
| user (`user.*`) | yes (any depth) | yes (children promoted) | yes | yes (into user group or root) | **yes (V11: nested user groups)** | yes |

V11 upgrades user groups from root-only to arbitrarily nestable:
- `create_user_group(name, parent_group_id="")`
- delete → children promoted one level up (groups and layers), never deleted
- rename → allowed for user.* only, echoed to QGIS
- move → user group into user group or root; never into system/factor groups
- system groups stay flat and fixed-band (scientific ordering is not a
  user-placeable thing)

## 5. Stage semantics inside the plan

Stage NEVER changes structure or order. It changes:
- which empty system groups are materialized (groups whose `stages` include
  the current stage are materialized even when empty — fixes D11-ws)
- effective group visibility (profile defaults + user overrides)
- default lock seeding
- recommended active target

The desired tree is stage-invariant; `LayerTreePlanInput.stage` feeds only
the visibility/lock projection (`apply_stage_visibility` path unchanged).

## 6. Reconciliation contract

```
desired = plan(input)                     # pure, deterministic
current = tree_from_nodes(observe())      # from bridge snapshot JSON
diff    = diff_trees(current, desired)    # 05-tree-diff
apply(diff) inside tree transaction       # 06-native-transaction
```

Determinism requirement (goal §10): `same input → same default tree` —
pinned by a test that builds the plan twice from identical inputs and
asserts equality including order keys, and a migration test that derives
keys from positional order with a fixed stride (no timestamps, no hashes).

## 7. Persistence (reopen)

`state.tree` (LayerTreeSnapshot dict) now includes order keys. Restore:
1. load memberships + tree dict (ids, keys)
2. plan input assembled; nodes lacking keys get deterministic defaults
3. reconcile (full placement — baselines cleared on reload, existing rule)
4. visibility/lock/expand projection + active target

Expand-state moves from QSettings(project display name) to the workspace
state (`GroupNode.expanded` becomes the consumed field — the vestigial
field becomes load-bearing, D9-ws resolved).
