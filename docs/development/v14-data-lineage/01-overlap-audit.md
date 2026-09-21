# 01 — Overlap audit (execution-time main + parallel leases)

## Open PR #1434 (still open at start; treated as parallel lease)

Its changed files (from `gh pr view 1434 --json files`) group into:

| Group | Paths | This line's stance |
|---|---|---|
| Table/filter perf | `libs/ui_data_core/**` (asset_table_core, filter_index, preview_cache, json_util, asset_view), `libs/ui_pages_data/src/qt/data_asset_table.{hpp,cpp}`, `libs/ui_pages_data/src/context_menu.cpp`, `libs/ui_pages_preview/table_preview_model.*` | **Avoid entirely.** No edits to these files. New entity-tree/lineage/ingest UI lands in NEW files or in non-leased files (`data_workspace.*`, new `qt/` dialogs). |
| workflow_graph CONV-25 | `libs/workflow_graph/**`, fixtures | avoid |
| mapping/polygonization | `libs/mapping_kernel/**` | avoid |
| QGIS mirror/export perf | `libs/ui_map/**`, `libs/ui_widgets/{object_table,qgis/*}` | avoid |
| Text/hygiene | `libs/domain/text.*`, `libs/data_suite/src/path_text_util.hpp`, `libs/well_science/curve_expr`, `libs/factor_host/semantics`, `libs/ingest/src/classifier.cpp` | **`classifier.cpp` and `path_text_util.hpp` touch my ownership area** — this line does NOT modify them; role inference consumes classifier output read-only. |
| CI env | `.github/workflows/*`, `tests/conftest.py`, several python tests | avoid; local verification only |
| Python harness | `paleo_workbench/harness/actions/data_lineage.py` | read-only oracle reference |

Overlap matrix vs my owned paths: `libs/ui_pages_data/src/context_menu.cpp` +
`qt/data_asset_table.*` are the ONLY intersecting files → zero-edit rule there.
`libs/data_suite/**`, `libs/catalog/**`, `libs/project/**` are exclusively mine among open PRs.

## Sibling lines (prompts 2–5, same wave)

No leases present in `$(git-common-dir)/paleo-v14-parallel/leases/` besides mine at start.
Discipline for when they appear:

- Prompt 2 (shell/UI): I expose read models/commands through existing seams
  (`NavTreeModel`, `WellDataViewSlice`, `AssetSelectionBus`); no catalog-JSON coupling requested.
- Prompt 3 (QGIS): map-usage queries go through a data-facing seam only (see 02-architecture §7);
  never the QGIS layer tree.
- Prompt 4 (factor): run/version registration via the existing `CommitCoordinator`/catalog APIs;
  algorithm cores never write catalog DB directly.
- Prompt 5 (compilation): export provenance via `DataRun` registration APIs only.

Shared files (root `CMakeLists.txt`, `main_window.cpp`, `app_shell.cpp`): additive named
`BEGIN/END PWB-V14-DATA-LINEAGE` blocks only; bulk shared-file churn deferred to the end of the
line and minimized.

## Merged-PR absorption check

#1414/#1426/#1433 results are IN the base (`412d8baf`) — audited directly, not re-implemented:
- catalog closure adapters exist (`apps/closure_catalog_service.{hpp,cpp}`, 1886 lines) — reused as-is.
- unified data page (viz_e install, AssetSelectionBus, parser-registry preview) — reused as the host
  for this line's entity tree population and new panels.
- `NavTreeModel` role seams (`RoleOrderFn`/`RoleDisplayFn`) — this line supplies the producers.

## Conclusion

The prompt's claimed gaps were re-verified against execution-time main before implementation:
entity workspace views, role registry, entity domain ops, link ordinal, manual_edit runs,
lifecycle-class wiring, ingest plan UI, nav-tree/lineage/impact product wiring are ALL still
missing on `412d8baf`. Compound bundles, working copies, lineage/impact/explain cores,
ingest plan domain — already exist and are REUSED, not rebuilt.
