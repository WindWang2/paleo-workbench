# 00 — Baseline (V14-DATA-LINEAGE)

Execution date: 2026-09-20. Base SHA: `412d8baf22a6a928c860e2e3d6c1108a9c035c78` (origin/main).

## Repository state at start

- main = `412d8baf` (merge of #1433 mapping-authoring closure wave line 08).
- Single open PR: **#1434** (`fix/open-issues-batch`) — workflow_graph CONV-25 semantics,
  curve_expr/polygonization fixes, QGIS mirror/export perf, table/filter perf, hygiene, CI env.
  Still open at execution time → its changed files are treated as parallel leases (see 01-overlap-audit).
- Relevant merged PRs absorbed into the base: #1414 (catalog/project closure, line 01),
  #1415 (workflow closure), #1418 (science + prediction provenance), #1421 (product integration, line 12),
  #1426 (unified data page/preview, line 04), #1433 (mapping authoring, line 08).

## Capability matrix (audited file-by-file, not from old docs)

Legend: ✅ C++ production · 🟡 C++ exists but unwired/test-only · ❌ missing (Python-only or nowhere)

| Capability | C++ model | persistence | production wiring | UI | tests | gap |
|---|---|---|---|---|---|---|
| multi-file well (entity + role links) | ✅ `data_suite/entity_identity` (WellRegistry, resolve_well, upsert link, single-primary) | 🟡 links in `.paleo.json` (`libs/project/schema.cpp` kEntityAssetLink); **no `ordinal` field** | 🟡 `NavTreeModel` models wells→roles→assets but **no producer calls `set_project`** | 🟡 nav tree skeleton only; flat asset table wired | ✅ ingest_plan/entity identity tests | link ordinal, role registry cardinality, entity domain ops, entity view producer |
| compound version (VersionMember bundle) | ✅ `catalog/v11_bundle` (members, per-member hash, aggregate hash, all-or-nothing place, bundle WC) | ✅ `version_members` table | ✅ via service core | ❌ member-level UI absent | ✅ oracle suite | member-level explain |
| same-asset multi-version lineage | ✅ `parent_version_ids` DAG + `lineage` table + child index | ✅ | ✅ | 🟡 lineage column text only | ✅ | successor/branch pointers (deferred) |
| run/provenance (DataRun, typed ports) | ✅ `catalog/models` DataRun/RunPort, ports invariants (`v11_policy`) | ✅ `runs`/`run_ports` | 🟡 v3 run lifecycle via `data_suite/CommitCoordinator`; **typed business registrations missing** (manual_edit etc. — runtime bag seams declared UNSET) | ❌ | ✅ run lifecycle/recovery | manual_edit run registration |
| working copy lifecycle | ✅ `catalog/working_copy` R5 state machine + crash recovery + CAS | ✅ `working_copies` | ✅ service core | 🟡 grant seam in main_window | ✅ deep suite | entity view surfacing |
| intermediate lifecycle classes | ✅ pure decision table `catalog/policies` (ephemeral/cache/intermediate/derived/output) + retention classes `v11_policy` | 🟡 retention in version metadata | ❌ **decision table consulted by nobody at registration** | ❌ | ✅ policy tests | wiring into production registration |
| lineage graph | ✅ `catalog/lineage_graph` (BFS, cycle-safe, truncated flag) | — | 🟡 | 🟡 review-lineage dialog (09) | ✅ | — |
| impact/stale | ✅ `catalog/impact` (downstream_stale, entity_staleness, delete_impact, bounded) | — | ❌ zero product consumers | 🟡 `show_downstream_impact` zero callers | ✅ | product wiring |
| explain | ✅ `catalog/explain` (version/asset, lifecycle answers) | — | ❌ zero product consumers | ❌ | ✅ | product wiring; integrity_status never computed |
| ingest plan | ✅ `data_suite/ingest_plan` + `ingest_exec` (scan→classify→family→identity→role→dup→decision→execute) | — | ❌ **no product caller** (`plan_import_requested` signal unconsumed) | ❌ toolbar buttons only | ✅ oracle | plan review UI + wiring |
| entity workspace views | ❌ Python `catalog/entity_views.py` (EntityViewService) — **not ported**; `ui_wellseis/WellDataViewSlice` display DTO exists with **no producer** | — | ❌ | 🟡 WellDetailPanel exists, never fed | ❌ | the core gap of this line |
| entity domain ops (remove/prune) | ❌ Python `project/domain.py` `remove_well_entity`, `remove_asset_links_and_prune_reference_wells`, `links_for_*` — not ported (unset `prune_asset_links` seam in host_api) | — | ❌ | ❌ | ❌ | port |
| role registry | ❌ Python `project/roles.py` (ROLE_DEFINITIONS_BY_TYPE, cardinality, primary_policy, ordered) — only `infer_role_for_type` subset ported | — | ❌ NavTreeModel role fns documented "unported" | ❌ | ❌ | port |
| composition-root catalog closure | ✅ `apps/closure_catalog_service/install` (line 01) | — | ❌ **no MainWindow/AppContext consumer** (line 12 landed other wiring) | — | ✅ closure test | install or bypass decision (02-architecture §6) |

## Key structural facts

- Two authorities: `catalog.sqlite` (assets/versions/runs/WC; schema v5) and `.paleo.json`
  (wells/surveys/domain entities/`entity_asset_links`). Entity views must READ BOTH and own nothing.
- Scale path: `catalog/queries_sql` lazy SQL reads (500-id chunks) + `paged_sql`; document
  materialization is the heavy path used by impact/explain (bounded, opt-in).
- Error-message byte parity with Python is a frozen contract in `libs/catalog` — new domain code
  must not alter frozen message paths; new features get their own messages.
- Build on this machine: Windows/MSVC/Ninja, Qt 6.8.0 at `C:/deps/Qt`. POSIX resource gate
  unavailable (`invoke-resource-gate.sh` exits 77 on win32); `Invoke-ResourceGate.ps1` is the
  Windows equivalent. Discipline: `-j4` ceiling, isolated `build/` per worktree.
