#pragma once

// UI-14 — catalog service seams for the root controllers.
//
// Python resolves two process-global objects per call:
//   * get_catalog()        — the CatalogPort adapter (legacy bridge index
//                            + batched writes);
//   * get_catalog_service() — the Core DataCatalogService (typed lifecycle:
//                            trash/restore/derived/materialize/working-copy/
//                            promote/tags/runs/maintenance).
// Neither high-level surface exists as one C++ object yet — the repository
// primitives (Pwb::Catalog), trash/payload fs ops, TagStore and the legacy
// projection kernels do — so the controllers take them as abstract seams.
// The concrete adapter (CatalogRepository + storage ops + TagStore
// composition) lands with the catalog-service slice; tests inject fakes.
//
// The read side reuses ui_data_core::CatalogReadService verbatim so the
// ported enricher kernels (compute_catalog_row_overview) run unmodified.

#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/catalog/models.hpp>
#include <pwb/catalog/refs.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/domain/stage.hpp>
#include <pwb/ui_data_core/asset_view.hpp>

namespace pwb::ui_controllers {

namespace fs = std::filesystem;

// DataCatalogService surface (service.py seam). Every "raise" path in
// Python throws here (domain::DataException or std::runtime_error); the
// controllers surface failures on the page status line, never silently.
class CatalogServiceApi : public ui_data_core::CatalogReadService {
public:
    ~CatalogServiceApi() override = default;

    // service.project_path — relativize_path anchor for stored paths.
    virtual const fs::path& project_path() const = 0;

    // service.get_version(version_id) — throws when unknown (the Python
    // attribute error paths the callers surface).
    virtual catalog::DataVersion get_version(
        const std::string& version_id) = 0;

    // maps._ensure_maps().asset_by_id membership — the remove-gate's "real
    // catalog asset" test (gate_ids are filtered to it).
    virtual bool asset_exists(const std::string& asset_id) = 0;

    // Trashed-asset listing for the 回收站 view (service.get_trashed_assets).
    virtual std::vector<catalog::DataAsset> get_trashed_assets() = 0;

    // ---- lifecycle writes (all one canonical transaction on the impl) --
    virtual catalog::DataAsset trash_asset(const std::string& asset_id,
                                           const std::string& reason) = 0;
    virtual catalog::DataAsset restore_asset(const std::string& asset_id) = 0;
    virtual catalog::DataVersion create_derived(
        const fs::path& source_path,
        const std::vector<std::string>& parent_version_ids,
        const std::string& name, const std::string& operation,
        const std::string& generator) = 0;
    virtual catalog::DataVersion materialize_external(
        const std::string& version_id,
        const std::optional<std::string>& run_id) = 0;
    virtual fs::path create_working_copy(const std::string& version_id) = 0;
    virtual catalog::DataVersion commit_working_copy(
        const fs::path& working_path, const std::string& asset_id,
        const std::optional<std::string>& name, domain::DataStage stage,
        const std::optional<std::string>& run_id) = 0;
    virtual catalog::DataVersion promote_version(
        const std::string& version_id, domain::DataStage to_stage,
        const std::optional<std::string>& reviewed_by,
        const std::optional<std::string>& note) = 0;
    virtual void update_asset_metadata(const std::string& asset_id,
                                       const domain::Json& patch) = 0;

    // ---- runs -------------------------------------------------------------
    virtual catalog::DataRun register_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const domain::Json& parameters) = 0;
    virtual void update_run_status(const std::string& run_id,
                                   const std::string& status) = 0;

    // ---- tags --------------------------------------------------------------
    virtual void add_tag(const std::string& name,
                         const std::optional<std::string>& asset_id,
                         const std::optional<std::string>& version_id) = 0;
    virtual void remove_tag(const std::string& name,
                            const std::optional<std::string>& asset_id,
                            const std::optional<std::string>& version_id) = 0;
    virtual void bulk_add_tag(const std::string& name,
                              const std::vector<std::string>& asset_ids) = 0;
    virtual void bulk_remove_tag(const std::string& name,
                                 const std::vector<std::string>& asset_ids) = 0;

    // service.verify_integrity(version_id) -> "verified|modified|missing|unknown".
    virtual std::string verify_integrity(const std::string& version_id) = 0;

    // ---- open-time maintenance surface (project_controller) ----------------
    virtual void warm_document() = 0;
    virtual void recover_working_copies() = 0;
    // migration.migrate_legacy_resources(resources_snapshot): the snapshot is
    // a frozen resources[] JSON array captured on the GUI thread.
    virtual void migrate_legacy_resources(const domain::Json& resources_snapshot) = 0;
    virtual void sweep_temp_on_open() = 0;
    virtual void ensure_index_ready() = 0;
    virtual void repair_ghost_runs() = 0;
    virtual void migrate_run_ports() = 0;
    virtual void rebase_artifact_paths() = 0;
    virtual void close() = 0;
};

// CatalogPort adapter surface (catalog.runtime.get_catalog()).
class CatalogPortApi {
public:
    virtual ~CatalogPortApi() = default;
    // adapter.document — _resolve_asset_version's assets/versions lookup.
    virtual const catalog::CatalogDocument& document() = 0;
    // adapter.resolve_path(version) — catalog-relative → absolute payload.
    virtual fs::path resolve_path(const catalog::DataVersion& version) = 0;
    // adapter.resolve_legacy_resource(legacy_id) -> DataVersionRef | None.
    virtual std::optional<catalog::DataVersionRef> resolve_legacy_resource(
        const std::string& legacy_id) = 0;
};

// Scoped canonical-write batch (adapter.batch_save() context manager).
// finish() == __exit__: commits the chunk; a false return drops that
// chunk's bridges from the registration receipt (D4 semantics).
class RegistrationBatch {
public:
    virtual ~RegistrationBatch() = default;
    virtual bool finish() = 0;
};

// Function-bag runtime seam: the catalog/lifecycle/domain-migration module
// functions the controllers call. std::function (not virtual) so tests and
// the integration adapter bind individual pieces — an unset std::function
// is a clean "unavailable" signal the controllers degrade on honestly.
struct CatalogRuntimeApi {
    std::function<CatalogPortApi*()> get_catalog;             // get_catalog()
    std::function<CatalogServiceApi*()> get_catalog_service;  // get_catalog_service()
    // DataCatalogService.open(target, lazy=True, sweep_temp=False) +
    // set_catalog(CoreCatalogAdapter(service)): installs the project's
    // catalog and returns the service (non-owning — runtime-owned).
    std::function<CatalogServiceApi*(const fs::path& target)> open_catalog;
    std::function<void()> reset_catalog;                       // reset_catalog()
    // seismic_lifecycle.shutdown_lifecycle(service) — cancel transcodes
    // before the handle closes (#1079).
    std::function<void(CatalogServiceApi*)> shutdown_lifecycle;
    // seismic_lifecycle.get_lifecycle_service(service) — resume interrupted
    // transcodes on open (#1223).
    std::function<void(CatalogServiceApi*)> resume_lifecycle;
    // catalog.batch_save() — bulk registration batch (nullptr → per-file).
    std::function<std::unique_ptr<RegistrationBatch>()> enter_batch;
    // catalog.lifecycle.register_resource_input(resource_row) -> ref | None.
    std::function<std::optional<catalog::DataVersionRef>(
        const domain::Json& resource_row)>
        register_resource_input;
    // catalog.lifecycle.register_manual_edit_run(...) -> run | None.
    std::function<std::optional<catalog::DataRun>(
        CatalogServiceApi* service,
        const std::vector<std::string>& source_version_ids,
        const std::optional<std::string>& note,
        const domain::Json& extra_parameters)>
        register_manual_edit_run;
    // catalog.lifecycle.complete_manual_edit_run(service, run_id, ids).
    std::function<void(CatalogServiceApi* service, const std::string& run_id,
                       const std::vector<std::string>& committed_version_ids)>
        complete_manual_edit_run;
    // catalog.lifecycle.register_persisted_factor_grids(project_root) -> bool
    // (true → caller must save the document again with the stored ids).
    std::function<bool(domain::Json& project_root)>
        register_persisted_factor_grids;
    // catalog.roles_backfill.backfill_role_primaries(project_root).
    std::function<void(domain::Json& project_root)> backfill_role_primaries;
    // catalog.domain_binding.stage_resources(project, resources_snapshot,
    // path_resolver, cancel) -> opaque staged payload (std::any — only the
    // migration bind consumes it).
    std::function<std::any(domain::Json& project_root,
                           const domain::Json& resources_snapshot,
                           const std::function<fs::path(std::string)>& resolver,
                           const std::function<bool()>& cancel_check)>
        stage_resources;
    // project.domain_migration.build_asset_id_mapping(service) ->
    // {legacy_resource_id: asset_id}.
    std::function<std::map<std::string, std::string>(CatalogServiceApi*)>
        build_asset_id_mapping;

    struct MigrationReport {
        bool migrated = false;
        int wells_created = 0, wells_updated = 0;
        int surveys_created = 0, surveys_updated = 0;
        int links_created = 0, links_updated = 0;
    };
    // project.domain_migration.migrate_project_to_workarea(document,
    // mapping, staged) — GUI-thread bind.
    std::function<MigrationReport(domain::Json& project_root,
                                  std::map<std::string, std::string> mapping,
                                  const std::any& staged)>
        migrate_project_to_workarea;

    // Session-cache teardown (_close_catalog's process-global clears):
    // factor_grid_artifacts.clear_session_caches + freshness.clear + plan_cache.
    std::function<void()> clear_session_caches;
};

}  // namespace pwb::ui_controllers
