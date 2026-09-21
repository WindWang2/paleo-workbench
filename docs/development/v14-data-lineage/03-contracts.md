# 03 — Contracts (new public APIs of this line)

## A. `pwb/data/role_registry.hpp` (data_suite, NEW)

```cpp
struct RoleDefinition {
    std::string_view role;                 // "well_log" ...
    std::vector<std::string_view> entity_types;
    std::string_view cardinality;          // "0..1" | "0..N"
    std::string_view primary_policy;       // none | optional | required_single
    bool ordered;                          // ordinal is meaningful
    std::string_view display;              // zh label
    std::string_view stage_default;        // "raw"
    std::vector<std::string_view> format_hints;
};
const RoleDefinition* role_definition(std::string_view role,
                                      std::string_view entity_type = {});
bool known_role(std::string_view role);
std::vector<std::string_view> roles_for_entity_type(std::string_view entity_type);
bool cardinality_allows_multiple(std::string_view role);
bool primary_required(std::string_view role);
// kWellRoles / kSurveyRoles / kGeologicalRoles ordered vocabularies (span views)
```

Semantics frozen to `paleo_workbench/project/roles.py` @ main: registry is guidance, NOT an
admission gate; unknown role → permissive fallback (`other`, `0..N`, `none`); scoped lookup
`(entity_type, role)` beats bare-role lookup; well vocabulary first for bare lookups.

## B. `pwb/data/entity_identity.hpp` (data_suite, EXTENDED — additive)

```cpp
// upsert gains ordinal (default 0); re-upsert keeps max(existing, given) ordering
// semantics: explicit ordinal >= 0 is stored; -1 = "leave unchanged".
LinkUpsert upsert_entity_asset_link(..., int ordinal = 0);

// NEW read ops (project/domain.py parity)
struct EntityLinkView {            // stable read view of one link row
    std::string id, entity_type, entity_id, asset_id, role;
    bool is_primary, unresolved;
    int ordinal;
    std::string note;
};
std::vector<EntityLinkView> links_for_entity(const domain::Json& root,
    std::string_view entity_type, std::string_view entity_id);
std::vector<EntityLinkView> links_for_asset(const domain::Json& root,
    std::string_view asset_id);
std::vector<std::pair<std::string, std::string>> entity_ids_for_asset(
    const domain::Json& root, std::string_view asset_id,
    std::string_view entity_type = "");

// NEW mutations (project/domain.py parity; mutate the tree, caller saves)
struct LinkPruneResult { int removed_links = 0; int pruned_wells = 0; };
int remove_links_for_asset(domain::Json& root, std::string_view asset_id);
LinkPruneResult remove_well_entity(domain::Json& root, std::string_view well_id);
LinkPruneResult remove_asset_links_and_prune_reference_wells(
    domain::Json& root, const std::vector<std::string>& asset_ids);
bool is_reference_well(const domain::Json& root, std::string_view well_id);
```

Prune rule (frozen): only wells touched by a removed link, only `spatial_scope ==
"reference"`, only when NO remaining link of any kind references them.

Project schema: `kEntityAssetLink` gains `{"ordinal", FieldType::Int, 0}` (normalize fills 0
on old docs; round-trip stable).

## C. `pwb/data/entity_workspace.hpp` (data_suite, NEW)

```cpp
struct AssetSummary {              // entity_views.AssetSummary parity
    std::string asset_id, name, type, role;
    bool is_primary = false, unresolved = false, trashed = false, bundle = false;
    int ordinal = 0, version_count = 0;
    std::string current_version_id;   // "" when none
    std::string stage, format;
};
struct RoleSlot { std::string role, display;
    std::vector<AssetSummary> members, unresolved; };
struct WorkingCopyLite { std::string working_id, source_version_id, path, state;
    bool dirty_hint = false; };
struct StaleLite { std::string version_id, asset_id, reason; bool pinned; };
struct EntityIndexEntry { std::string entity_id, name, uwi;
    std::map<std::string,int> role_fill; int unresolved_count = 0, stale_count = 0; };
struct EntityDataView {
    std::string entity_id, name, uwi;
    std::vector<RoleSlot> slots;                 // registry order, unknown roles appended
    std::vector<StaleLite> stale_items;          // only when with_stale
    std::vector<std::string> missing_source_asset_ids;
    std::vector<WorkingCopyLite> uncommitted_edits;
    // + stage-classified rollups for the workspace IA:
    int intermediate_count = 0, derived_count = 0, output_count = 0;
    std::vector<std::string> related_run_ids;    // runs producing/consuming member assets
};

// Narrow catalog seam (test-fakeable; proves the index layer's zero-catalog contract)
class WorkspaceCatalogSource {
public:
    virtual ~WorkspaceCatalogSource() = default;
    virtual std::map<std::string, AssetCatalogSummary> resolve_assets(
        const std::vector<std::string>& asset_ids) = 0;       // 500-id batches inside
    virtual std::vector<WorkingCopyLite> list_working_copies() = 0;
    virtual std::vector<StaleLite> entity_staleness(
        std::string_view entity_type, std::string_view entity_id,
        const std::vector<EntityLinkView>& links) = 0;        // bounded, opt-in
    virtual std::vector<std::string> related_runs(
        const std::vector<std::string>& asset_ids) = 0;
};
struct AssetCatalogSummary { std::string name, type, current_version_id;
    int version_count = 0; bool trashed = false, bundle = false;
    std::string stage, format; };                              // ""-valued when unknown

class EntityWorkspaceService {            // read-only; owns nothing
    EntityWorkspaceService(const domain::Json& project_root,
                           WorkspaceCatalogSource* catalog);   // null → unresolved-only views
    std::vector<EntityIndexEntry> well_index(bool with_stale = false) const;
    std::vector<EntityIndexEntry> survey_index() const;
    std::optional<EntityDataView> well_view(std::string_view well_id,
                                            bool with_stale = false) const;
    std::optional<EntityDataView> survey_view(std::string_view survey_id) const;
};

// Repository-backed concrete source (lazy SQL reads; document snapshot only for staleness)
class RepositoryWorkspaceSource final : public WorkspaceCatalogSource { ... };
```

Sorting contract: members `(not is_primary, ordinal, name)`; unresolved by name.
Unknown-role links land in a synthetic slot (never dropped). Unknown assets surface as
`<未注册资产 {id}>` unresolved summaries. Missing-source probe: managed → project_dir/path;
external → absolute or project_dir-joined; trashed/current-less assets skipped.

## D. `pwb/catalog/manual_edit.hpp` (catalog, NEW small)

```cpp
struct ManualEditRunInput { std::vector<std::string> source_version_ids;
    std::string note; domain::Json extra_parameters = Json::object(); };
// Pure assembly over the document: validates ids (committed, live), builds DataRun
// {operation="manual_edit", generator="pwb-native/manual_edit", input ports
// (role="manual_edit", entity refs from caller), parameters={note, extra, user:"unknown"}},
// status="running". Returns error string when a source id is unknown/uncommitted.
domain::Result<catalog::DataRun> build_manual_edit_run(
    const catalog::CatalogDocument& document, const ManualEditRunInput& input);
// Mutation halves live on the service/closure layer (register + complete).
```

## E. Lifecycle enrichment (data_suite ingest exec + closure import funnel)

When a registration request carries `artifact_kind`:
`lifecycle_for_artifact(kind)` (delegates to the frozen `catalog::artifact_policy_for`) →
`{stage, retention_class, must_register, lifecycle_class}`; enforcement: `must_register=false`
kinds are refused by the managed-import funnel (honest error, no tempfile catalogization);
registered versions get `metadata["lifecycle"] = {class, artifact_kind, retention_class}`.
Idempotent: existing metadata wins (no rewrite).

## F. Product seams (apps, NEW `closure_data_workspace.*`)

- `populate_nav_tree(NavTreeModel&, project doc, role registry)` — fills `NavProjectView`
  (wells/surveys/geo entities/links incl. role order/display fns from the registry).
- `WellDetailHost` — converts `EntityDataView` → `ui_wellseis::WellDataViewSlice` and feeds
  the existing `WellDetailPanel` on entity selection.
- Lineage explorer enablement: apps-level action over the existing
  `ui_review::LineageExplorerDialog` + `ICatalogApi` (09-line dialog, reused).
- Impact preview: `DataDetailPanel::show_downstream_impact` fed via
  `ImpactService::delete_impact` through the closure adapter.
- Ingest plan: `IngestPlanDialog` (new qt file) over the Qt-free `IngestPlanReviewModel`
  (new core file) → `build_ingest_plan`/`execute_ingest_plan`.
