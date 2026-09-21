#pragma once

// V14-DATA-LINEAGE (P4 product wiring) — closure_data_workspace.
//
// The composition module that turns the COMPLETED data-suite domain
// surface into product behavior on the UI-06 data workspace:
//   * populate_nav_tree  — NavTreeModel population from the live project
//     document (wells / seismic_surveys / geological_entities +
//     entity_asset_links), with the role seams bound to the REAL registry
//     (pwb::data::roles_for_entity_type / role_display — the "unported"
//     seams nav_tree_model.hpp documents now have a domain side).
//   * well_detail_slice + WellDetailHost — EntityDataView → the
//     ui_wellseis WellDataViewSlice the WellDetailPanel consumes, and a
//     host owning one RepositoryWorkspaceSource + EntityWorkspaceService
//     per open project (the panel's first producer).
//   * lineage_rows + delete_impact_summary — read-only lineage chains
//     (catalog::build_lineage_chain) and delete-impact advice text
//     (catalog::ImpactService) over the repository document.
//   * install_data_workspace — toolbar/ingest/nav-tree/well-detail wiring
//     (called from the PWB-V14-DATA-LINEAGE block in
//     closure_preview_install.cpp).
//
// Dependency note (single-writer honesty): the ingest execute path opens
// its own pwb::data::WritableSession over the project file — the same
// entry the store itself defers to (data_store.hpp notes the store keeps
// its own coordinator until it switches) — and saves the mutated
// document through that session's manager before returning.

#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_pages_data/ingest_plan_model.hpp>
#include <pwb/ui_pages_data/nav_tree_model.hpp>

namespace pwb::application {
class PwbDataStore;
}  // namespace pwb::application

namespace pwb::data {
class EntityWorkspaceService;
class RepositoryWorkspaceSource;
struct EntityDataView;
struct IngestPlan;
}  // namespace pwb::data

namespace pwb::ui_pages_data {
class NavTreeModel;
}  // namespace pwb::ui_pages_data

namespace pwb::ui_pages_data::qt {
class DataWorkspace;
class AssetSelectionBus;
class DataToolbar;
}  // namespace pwb::ui_pages_data::qt

namespace pwb::ui_wellseis {
struct WellDataViewSlice;
}  // namespace pwb::ui_wellseis

namespace pwb::ui_wellseis::qt {
class WellDetailPanel;
}  // namespace pwb::ui_wellseis::qt

class QWidget;

namespace pwb::app::v14_lineage {

// Store provider (the closure_preview Install::store shape — lazily
// re-read so a closed project surfaces as nullptr, never a stale store).
using StoreProvider =
    std::function<std::shared_ptr<pwb::application::PwbDataStore>()>;

// ---- 1. navigation tree ------------------------------------------------------

// Project document root → NavTreeModel view structs (schema.cpp field
// defaults mirrored: coordinate_status default "missing" → ⚠坐标 flag,
// spatial_scope default "workarea"). auxiliary_entities stay OUT: the
// nav model has no auxiliary-entity group (静态「辅助资料」leaf only).
pwb::ui_pages_data::NavProjectView build_nav_project_view(
    const domain::Json& project_root);

// Bind the role seams to the data-suite registry and populate `model`
// (model.build() must have run once — the Qt shell does that at
// construction). Role order/display come from
// pwb::data::roles_for_entity_type / role_display.
void populate_nav_tree(pwb::ui_pages_data::NavTreeModel& model,
                       const domain::Json& project_root);

// ---- 2. well detail ----------------------------------------------------------

// EntityDataView → the panel slice (catalog.entity_views.WellDataView).
// stage stays "" when the domain slice carries no stage (StaleLite keeps
// reason/pinned only) — honest degrade, never a fabricated stage.
pwb::ui_wellseis::WellDataViewSlice well_detail_slice(
    const pwb::data::EntityDataView& view);

// Owns one workspace service per open project and feeds the panel.
class WellDetailHost {
public:
    explicit WellDetailHost(pwb::ui_wellseis::qt::WellDetailPanel* panel);

    // (Re)bind the project: root JSON COPY (the service keeps a const&),
    // sqlite + project dir for the repository-backed source. Nullptr
    // root clears the binding (project closed → honest empty panel).
    void reconfigure(const domain::Json* project_root,
                     const std::filesystem::path& sqlite_path,
                     const std::filesystem::path& project_dir);

    // Build the with_stale=true view for one well and push it into the
    // panel. Returns false when the id is not a well in this project
    // (the panel is cleared — never a stale previous well).
    bool update(const std::string& well_id);

    bool bound() const { return service_ != nullptr; }

private:
    pwb::ui_wellseis::qt::WellDetailPanel* panel_ = nullptr;  // not owned
    std::optional<domain::Json> project_root_;
    std::unique_ptr<pwb::data::RepositoryWorkspaceSource> source_;
    std::unique_ptr<pwb::data::EntityWorkspaceService> service_;
};

// ---- 3. lineage / impact (read-only, repository document) ---------------------

struct LineageRow {
    int depth = 0;
    std::string asset_id;
    std::string asset_name;
    std::string stage;         // domain::DataStage value text
    std::string version_id;
    int version_number = 0;
    std::string path;
    std::string run_id;  // "" when no run produced the version
};

struct LineageQueryResult {
    bool ok = false;
    std::string error;
    std::string direction;  // "ancestors" | "descendants"
    int node_count = 0;
    bool truncated = false;
    std::vector<LineageRow> rows;  // pre-order flattening of the chain
};

// catalog::build_lineage_chain over a fresh read-only repository
// document + DocumentIndex (sqlite path derived from the project file).
LineageQueryResult lineage_rows(const std::filesystem::path& project_file,
                                const std::string& version_id,
                                const std::string& direction = "ancestors");

struct ImpactSummary {
    bool ok = false;
    std::string error;
    std::vector<std::string> lines;  // user-facing (Chinese) advice text
    int live_descendants = 0;
    int broken_edges = 0;
    int linked_entities = 0;
};

// catalog::ImpactService::delete_impact for one version (or asset when
// version_id is empty). Entity links come from the project document so
// the cascade advice covers entity↔asset bindings.
ImpactSummary delete_impact_summary(
    const std::filesystem::path& project_file,
    const std::optional<std::string>& version_id,
    const std::optional<std::string>& asset_id);

// ---- 4. workspace install ----------------------------------------------------

struct WorkspaceWiring {
    pwb::ui_pages_data::qt::DataToolbar* toolbar = nullptr;      // not owned
    pwb::ui_wellseis::qt::WellDetailPanel* well_detail = nullptr;  // not owned
    WellDetailHost* well_detail_host = nullptr;                  // child-owned
};

// Wire the product surfaces onto one workspace:
//   * DataToolbar (计划导入 button) inserted at the top — the toolbar
//     existed with zero hosts; the workspace layout is extended in place;
//   * WellDetailPanel into the workspace's well-detail slot + the host;
//   * bus assets_changed → nav-tree repopulation from the live store
//     document (+ host reconfigure) — rides the closure_preview refresh;
//   * nav tree entity_activated → well-detail update;
//   * toolbar plan_import_requested → folder pick → build_ingest_plan →
//     IngestPlanDialog → WritableSession execute + document save +
//     closure_preview::notify_project_store_changed() refresh.
// *refresh_notify* (optional): invoked after a successful folder ingest
// so the product can repaint (production passes
// closure_preview::notify_project_store_changed). Empty (tests) → the
// ingest result is simply returned to the caller.
WorkspaceWiring install_data_workspace(
    pwb::ui_pages_data::qt::DataWorkspace& workspace,
    pwb::ui_pages_data::qt::AssetSelectionBus* bus, StoreProvider store,
    QWidget* dialog_parent,
    std::function<void()> refresh_notify = {});

// Internal helper exposed for tests: the dialog Execute-callback body —
// open a WritableSession, apply the review rows onto the plan copy,
// execute, save the mutated document through the session's manager.
// Returns a user-facing (Chinese) summary; throws when the session
// cannot open (caller surfaces the message).
std::string execute_folder_ingest(
    const std::filesystem::path& project_file,
    const pwb::data::IngestPlan& plan,
    const std::vector<pwb::ui_pages_data::PlanItemRow>& rows);

}  // namespace pwb::app::v14_lineage
