// Entity workspace read model (V14-DATA-LINEAGE) — the C++ port of
// paleo_workbench/catalog/entity_views.py (V11 §6.2).
//
// EntityWorkspaceService assembles WellDataView / SurveyDataView snapshots
// from the two existing authorities (project document entities/links +
// catalog assets/versions). It owns NO storage of its own — every query
// reads through to the authorities, so there is no second canonical copy
// to drift (data-fabric-v11/02 D5).
//
// Scale contract (11-scale): the well index is assembled from
// project.wells (≤10k) plus in-memory link aggregation — with_stale=false
// performs ZERO catalog reads (structural guarantee, asserted by tests
// with a throwing source). Expanding one well issues batched point
// lookups only (500-id chunked SQL; never list_assets()).
#pragma once


#include "pwb/data/entity_identity.hpp"

#include <filesystem>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::data {

// ---- catalog-facing data shapes -------------------------------------------

// What the catalog knows about one asset (lazily resolved; ""-valued
// fields when the current version is absent).
struct AssetCatalogSummary {
    std::string name;
    std::string type;
    std::string current_version_id;  // "" when the asset has no current
    int version_count = 0;
    bool trashed = false;
    bool bundle = false;             // current version has members
    std::string stage;               // current version stage ("" unknown)
    std::string format;              // current version format ("" unknown)
};

// One uncommitted working copy row (asset_id resolved by the source so the
// service can filter per entity without a version→asset map).
struct WorkingCopyLite {
    std::string working_id;
    std::string source_version_id;
    std::string asset_id;
    std::string path;
    std::string state;
    bool dirty_hint = false;
};

// Staleness item slice (catalog::StaleItem trimmed to what views render).
struct StaleLite {
    std::string version_id;
    std::string asset_id;
    std::string reason;
    bool pinned = false;
    bool direct = false;
    // Asset id of the nearest changed ancestor ("" when the trigger is
    // trash/unknown) — the well index maps stale counts onto wells through
    // this asset (entity_views.well_index parity).
    std::string nearest_changed_ancestor_asset_id;
};

// ---- view shapes ------------------------------------------------------------

// Lightweight asset view entry (identity + current version pointer).
struct AssetSummary {
    std::string asset_id;
    std::string name;
    std::string type;
    std::string role;
    bool is_primary = false;
    bool unresolved = false;
    bool trashed = false;
    bool bundle = false;
    int ordinal = 0;
    int version_count = 0;
    std::string current_version_id;
    std::string stage;
    std::string format;
};

// All assets bound to one (entity, role) pair, primary first.
struct RoleSlot {
    std::string role;
    std::string display;
    std::vector<AssetSummary> members;
    std::vector<AssetSummary> unresolved;
};

// One row of the light entity index (tree root layer).
struct EntityIndexEntry {
    std::string entity_id;
    std::string name;
    std::string uwi;
    std::map<std::string, int> role_fill;  // role → linked live asset count
    int unresolved_count = 0;
    int stale_count = 0;
};

// Full per-entity view (well or survey).
struct EntityDataView {
    std::string entity_type;  // "well" | "seismic_survey"
    std::string entity_id;
    std::string name;
    std::string uwi;
    std::vector<RoleSlot> role_slots;  // registry order; unknown roles appended
    std::vector<StaleLite> stale_items;  // only when with_stale
    std::vector<std::string> missing_source_asset_ids;
    std::vector<WorkingCopyLite> uncommitted_edits;
    // Workspace IA rollups (V14 additions over the Python shape):
    // Named stale_total (not stale_count) so it can never be confused with
    // EntityIndexEntry::stale_count — the field of the same name on the
    // sibling struct.
    int stale_total() const { return static_cast<int>(stale_items.size()); }
    int intermediate_count = 0;  // members whose current stage = intermediate
    int derived_count = 0;
    int output_count = 0;
    std::vector<std::string> related_run_ids;  // runs touching member assets
};

// ---- catalog seam ------------------------------------------------------------

// Narrow read seam the workspace consumes. Production: repository-backed
// (lazy SQL + document snapshot for staleness). Tests: fakes — including a
// THROWING fake that structurally proves the with_stale=false index layer
// never touches the catalog.
class WorkspaceCatalogSource {
public:
    virtual ~WorkspaceCatalogSource() = default;

    // Batched asset summaries (missing ids simply absent from the map —
    // the service surfaces them as <未注册资产> unresolved rows).
    virtual std::map<std::string, AssetCatalogSummary> resolve_assets(
        const std::vector<std::string>& asset_ids) = 0;

    // Every working-copy row (live states; the service filters per entity).
    virtual std::vector<WorkingCopyLite> list_working_copies() = 0;

    // Bounded staleness scoped to the entity's linked assets (opt-in;
    // document-snapshot cost class — same as Python's impact pass).
    virtual std::vector<StaleLite> entity_staleness(
        const std::vector<EntityLinkView>& links) = 0;

    // The FULL live downstream-stale list (entity_views.well_index
    // attribution source). Same cost class as entity_staleness.
    virtual std::vector<StaleLite> downstream_stale_all() = 0;

    // Distinct run ids touching any version of the given assets.
    virtual std::vector<std::string> related_runs(
        const std::vector<std::string>& asset_ids) = 0;

    // First-rung existence probe over the CURRENT versions of asset_ids
    // (managed → project_dir/path; external → absolute or project-joined;
    // trashed / no-current skipped). Bounded to the given assets only.
    virtual std::vector<std::string> probe_missing_sources(
        const std::vector<std::string>& asset_ids) = 0;
};

// ---- the service ----------------------------------------------------------------

class EntityWorkspaceService {
public:
    // project_root: the .paleo.json tree (wells / seismic_surveys /
    // entity_asset_links). catalog: may be nullptr — views then surface
    // every linked asset as an unresolved <未注册资产> row (honest degrade,
    // never a crash).
    EntityWorkspaceService(const domain::Json& project_root,
                           WorkspaceCatalogSource* catalog);

    // One light entry per well — O(W+L) over the project tree.
    // with_stale=true opts into the impact pass (catalog reads).
    std::vector<EntityIndexEntry> well_index(bool with_stale = false) const;
    std::vector<EntityIndexEntry> survey_index() const;

    // Per-entity views; nullopt when the id is unknown.
    std::optional<EntityDataView> well_view(const std::string& well_id,
                                            bool with_stale = false) const;
    std::optional<EntityDataView> survey_view(
        const std::string& survey_id) const;

private:
    struct EntityNode {
        std::string id;
        std::string name;
        std::string uwi;
        bool found = false;
    };
    EntityNode find_entity(const char* section, const std::string& id) const;
    std::optional<EntityDataView> entity_view(const char* section,
                                              const std::string& entity_type,
                                              const std::string& entity_id,
                                              bool with_stale) const;
    std::vector<RoleSlot> slots_for_entity(
        const std::string& entity_type, const std::string& entity_id) const;

    const domain::Json& project_root_;
    WorkspaceCatalogSource* catalog_;
};

// Repository-backed production source: lazy SQL reads over catalog.sqlite
// (never list_assets(); 500-id chunked point lookups) + full-document
// snapshot only inside entity_staleness (opt-in). Missing store degrades
// to empty results — the service surfaces unresolved rows honestly.
class RepositoryWorkspaceSource final : public WorkspaceCatalogSource {
public:
    // project_dir: the directory containing catalog.sqlite's project file
    // (used by the managed-path probe). Both paths may be empty — every
    // read then degrades to empty.
    RepositoryWorkspaceSource(std::filesystem::path sqlite_path,
                              std::filesystem::path project_dir);

    std::map<std::string, AssetCatalogSummary> resolve_assets(
        const std::vector<std::string>& asset_ids) override;
    std::vector<WorkingCopyLite> list_working_copies() override;
    std::vector<StaleLite> entity_staleness(
        const std::vector<EntityLinkView>& links) override;
    std::vector<StaleLite> downstream_stale_all() override;
    std::vector<std::string> related_runs(
        const std::vector<std::string>& asset_ids) override;
    std::vector<std::string> probe_missing_sources(
        const std::vector<std::string>& asset_ids) override;

private:
    std::filesystem::path sqlite_path_;
    std::filesystem::path project_dir_;
};

}  // namespace pwb::data
