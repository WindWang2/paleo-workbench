# 02 — Architecture (V14-DATA-LINEAGE)

## 1. Shape

This line CLOSES the gap between the existing authorities and the product, it does not build a
second one:

```
.paleo.json (project doc)                catalog.sqlite
  wells / surveys / domain entities        assets / versions / members
  entity_asset_links  ←─ new: ordinal      runs / ports / working copies
        │                                 lineage
        ▼                                        ▼
  role registry (NEW data_suite)      EntityWorkspaceService (NEW data_suite)
        │                                 well_index / survey_index / well_view
        ▼                                 role slots / missing / WC / stale
  entity domain ops (NEW data_suite)          │
  links_for_* / remove / prune                ▼
                                    product wiring (apps, NEW closure_data_workspace)
                                      nav tree population · well detail panel
                                      lineage explorer · impact preview · ingest plan UI
```

## 2. Source of truth / ownership / lifecycle (per new component)

| Component | SoT it reads | Owns | Lifecycle | Persistence |
|---|---|---|---|---|
| `data_suite/role_registry` | frozen table (roles.py parity) | nothing (pure) | static | none |
| `data_suite/entity_identity` (extended) | project JSON tree | nothing (mutates caller's tree) | per project session | via project save |
| `data_suite/entity_workspace` | project JSON + catalog (lazy SQL / snapshot) | nothing (read model) | constructed per project open, cheap | none |
| `catalog/manual_edit` (NEW small) | document | assembles DataRun only | per edit session | via service commit |
| `apps/closure_data_workspace` (NEW) | the above | UI wiring only | per window/project open | none |

Failure semantics: read models degrade honestly (unknown asset → `<未注册资产 id>` summary;
missing catalog → empty slots + unresolved surfacing), never throw to UI; mutations are
fail-closed with typed errors. Thread model: all new domain code is single-threaded
(called from GUI thread or worker with its own snapshot); the catalog core's single-writer
discipline is unchanged. Async: UI reads happen on worker snapshots; late results are guarded
by generation counters in the existing refresh path.

## 3. Multi-file well: the four semantics (how each maps)

1. **One well, many independent business assets** → N `DataAsset`s + N links
   (entity_type=well, role=well_log/trajectory/…, is_primary, **ordinal NEW**).
   NEVER one mega-bundle. Role registry documents cardinality (`0..1`/`0..N`),
   primary policy (`required_single` for well_head/time_depth/seismic_volume) and
   `ordered` (well_log ordering by ordinal).
2. **One logical version, many physical members** → existing `VersionMember` bundles
   (reused unchanged).
3. **Same asset, many versions** → existing version DAG + current pointer (reused).
4. **Algorithm/human derivation** → existing `DataRun` + ports; NEW manual_edit run
   registration closes the human-edit black hole.

## 4. EntityWorkspaceService (the core new read model)

Python-parity port of `catalog/entity_views.py` with the C++ scale path:

- `well_index(with_stale=false)`: O(W+L) over the project tree ONLY — zero catalog reads
  (structural test: a catalog source that throws proves it). `with_stale=true` opts into the
  impact pass (document snapshot — same cost class as Python; documented).
- `well_view(well_id)`: role slots from registry vocabulary (unknown roles → synthetic slot,
  never dropped); per-asset summaries via batched point lookups (`get_asset_models`,
  500-id chunks) + per-asset version counts/current via `queries_sql`; members sorted
  `(not is_primary, ordinal, name)`; bounded missing-source probe (first rung only);
  working copies filtered to the entity's assets; `entity_staleness` only when `with_stale`.
- `survey_index`/`survey_view`: same shape minus well-specific fields.
- Display slice conversion: `WellDataViewSlice` (ui_wellseis) — the panel DTO that already
  exists — is produced by an adapter, so the read model stays Qt-free.

Catalog access goes through a narrow interface (`WorkspaceCatalogSource`) with a concrete
implementation over `catalog::CatalogRepository` lazy SQL reads + service-core snapshot for
impact; tests implement fakes (also proving the no-catalog contract of the index layer).

## 5. Manual-edit provenance

`register_manual_edit_run`: validates source versions exist and are committed → assembles a
`DataRun` (operation `manual_edit`, typed input ports role=`manual_edit`, generator
`pwb-native/manual_edit`, parameters carry note/extra; author never fabricated — absent user
→ `unknown`) → registers through the service core → returns the run. `complete_manual_edit_run`
attaches output version ids (committed versions) and closes the run. Wired into the
`CatalogRuntimeApi` bag seams that exist but are unset (ui_controllers/catalog_api.hpp).

## 6. Lifecycle classes

The frozen decision table (`catalog/policies` artifact kinds) becomes REAL at the production
registration boundary (data_suite ingest exec + closure import funnel): when a registration
carries an `artifact_kind`, stage/retention/must-register follow the table, and the version
metadata records `lifecycle` (class + artifact kind). The frozen `v11_bundle` core is NOT
touched (oracle parity preserved); enrichment is caller-side, idempotent, and additive.
Explain surfaces the class; cleanup eligibility continues to consume retention as today.

## 7. Map/product usage seam (cross-line discipline)

`EntityWorkspaceService` exposes `asset_usage(asset_ids)` returning structured usage rows from
catalog data only (runs consuming/producing + entity links). QGIS-layer usage is NOT
implemented here; prompt-3's line consumes this seam or injects rows via the existing
`ImpactService::EntityLink` injection point. No QGIS headers enter data_suite.

## 8. Ingest plan product face

Domain: existing `data_suite/ingest_plan`/`ingest_exec` (reused verbatim — UI and agents call
the SAME API). UI: new Qt plan-review dialog (new files under `libs/ui_pages_data/qt/`) fed by
a Qt-free plan model (new `ingest_plan_model.hpp`) that wraps the domain plan for review
(decision flips, role/primary/ordinal edits, include/exclude, duplicate resolution) and
executes through `execute_ingest_plan` with progress + cancellation via the existing
JobCenter/generation guard pattern.

## 9. What this line deliberately does NOT do

- No second catalog/lineage store, no QGIS tree changes, no factor kernels, no layout engine.
- No edits to frozen-oracle hotspots leased by #1434 (context_menu.cpp, data_asset_table.*,
  ui_data_core, workflow_graph, mapping_kernel, ui_map, classifier.cpp, path_text_util.hpp).
- No new production Python. Python remains the frozen semantic oracle for ports.
- Composition root: reuse the existing `PwbDataStore` (ProjectManager+CatalogRepository+
  CommitCoordinator) path; `InstalledCatalogClosure` stays a tested module — installing it
  into MainWindow is deferred to the integration line to avoid shared-file churn (recorded in
  08-known-limitations).

## 10. Backward compatibility

- `ordinal` on links: schema-normalized default 0; old projects load/save unchanged;
  Python legacy ignores unknown JSON keys on its side (pydantic default config) — divergence
  documented.
- New metadata keys (`lifecycle`) are additive; unknown-key preservation already the norm.
- `future_schema` documents stay read-only (unchanged rule).
