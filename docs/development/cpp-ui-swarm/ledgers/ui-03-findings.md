# UI-03 core-data-preview — findings ledger

Slice owner: `feat/cpp-ui-core-data-preview` (worktree `cpp-ui-core-data-preview`).
State: agent partial output salvaged + completed by coordinator (the agent was
rate-limited before first compile; this ledger reflects the as-built state).

## Targets

- `pwb_ui_data_core` / `Pwb::UiDataCore` — Qt-free cores (`libs/ui_data_core`)
- `pwb_ui_data_qt` / `Pwb::UiDataQt` — Qt shells (`libs/ui_data_core/qt/`)

## File → terminal state

| Python source | State | C++ |
|---|---|---|
| pages/asset_table_model.py | ported (core) + qt shell **deferred** | asset_table_core.{hpp,cpp}; qt shell pending UI-06 consumer |
| pages/paged_asset_model.py | ported (core) + qt shell **deferred** | paged_asset_core.{hpp,cpp} |
| pages/data_view_models.py | ported | asset_view.{hpp,cpp} (AssetView/VersionView/LineageView + CatalogReadService seam + compute_catalog_row_overview) |
| pages/data_table_columns.py | ported | data_table_columns.hpp |
| pages/filter_index.py | ported | filter_index.{hpp,cpp} (FilterIndex/FilterQuery/CatalogCounts/vocab) |
| pages/preview_strategy.py | ported | preview_strategy.{hpp,cpp} |
| pages/preview_cache.py | ported | preview_cache.{hpp,cpp} |
| pages/preview_disk_cache.py | ported | preview_disk_cache.{hpp,cpp} |
| pages/preview_provider.py | ported | preview_provider.{hpp,cpp} + preview_types.hpp |
| pages/preview_worker.py | ported (core) + qt shell **deferred** | preview_worker.{hpp,cpp}; Qt worker pending |
| pages/preview_settings.py | ported (core) + qt shell **deferred** | preview_settings.hpp; QSettings store pending |
| pages/interchange_models.py | ported | interchange_models.{hpp,cpp} |
| pages/qc_helpers.py | ported | qc_helpers.{hpp,cpp} |
| pages/sequence_helpers.py | ported | sequence_helpers.{hpp,cpp} |
| pages/map_edit_commands.py | ported | map_edit_commands.{hpp,cpp} (EditCommand/Stack, Move/Vertex/Ring/PropertyChange/CreateFeature/Delete/Composite) |
| pages/map_edit_draft.py | ported (core+shell) | map_edit_draft.hpp (MapDraftCore) + qt/MapDraftManager |
| pages/map_edit_factory.py | ported | map_edit_factory.{hpp,cpp} |
| pages/map_edit_items.py | ported (core+shell) | map_edit_items.{hpp,cpp} (FeatureModel variant) + qt/{VertexHandle,FaciesPolygon,WellPoint,Line,Label}Item |
| pages/map_edit_snap.py | ported | map_edit_snap.{hpp,cpp} (MapSnapManager, cached candidates) |
| pages/map_edit_topology.py | ported | map_edit_topology.{hpp,cpp} + map_edit_geometry.{hpp,cpp} (geoviz api.py kernels + geometry_schema) |

Support headers: `json_util.hpp` (json coercion), `governance.hpp`
(governance_values/display), `tokens.hpp` (local token literals).

## Deferred (documented follow-up, not silent skips)

- `qt/` shells for `asset_table_model`, `paged_asset_model`,
  `preview_settings_store`, `preview_worker_qt` — CMakeLists references
  removed; the Qt-free cores they wrap are shipped. Consumers: UI-06 data
  pages (asset/paged models), UI-07 preview (worker/settings store).
  Follow-up: add these shells in whichever slice lands the consumer first.
- Oracle replay: no frozen fixture generated for this slice (agent died
  before the oracle round). `ui_data_core.smoke` covers headline semantics
  (31 checks). A frozen-oracle generator remains a follow-up if parity
  disputes surface.

## Session-2 (coordinator) fixes

- `asset_view.cpp`: StrongId→`.str()` throughout (AssetId/VersionId/RunId
  were used as std::string — file had never compiled).
- `filter_index.cpp`: same StrongId fix.
- `map_edit_commands.hpp`: missing `json_util.hpp` include.
- `map_edit_items.hpp`: `LineModel` missing `name` member (impl used it).
- `map_edit_topology.cpp`: `set_topology_status(const char*)` ambiguity —
  explicit `std::string_view`.
- `preview_worker.cpp`: `*view ? *view : …` → `*view ? **view : …`
  (shared_ptr deref confusion, both variant branches).
- Wrote `qt/` shells for `map_edit_items` (5 item classes delegating to
  FeatureModel) + `map_edit_draft_item` (MapDraftManager over MapDraftCore).
- Wrote `ui_data_core_tests/` (CMakeLists + smoke_test.cpp, 31 checks green).

## Verification

- `cmake --build … --target pwb_ui_data_core pwb_ui_data_qt ui_data_core.smoke`
  — clean build (linux-ninja, vendored QGIS SDK overrides).
- `ui_data_core.smoke` — 31 checks, 0 failures.
