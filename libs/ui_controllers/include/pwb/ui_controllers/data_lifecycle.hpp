#pragma once

// UI-14 — DataLifecycleController Qt-free core
// (data_lifecycle_controller.py parity).
//
// Business orchestration for the Data Manager page: catalog bridge
// resolution, remove/trash/restore/rescan, derived/materialize/working-
// copy/promote/delivery actions, tag mirroring, integrity verification,
// trashed companions and chunked import registration. The page surface
// is DataPageApi; the catalog is CatalogServiceApi/CatalogPortApi behind
// CatalogRuntimeApi (per-call resolution — never cached across project
// switches); heavy work runs through the injected UiJobRunner pair
// (catalog_job + verify_job — page._catalog_copy_job/_verify_job parity).

#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/catalog/models.hpp>
#include <pwb/catalog/refs.hpp>
#include <pwb/ui_data_core/asset_view.hpp>
#include <pwb/ui_workers/integrity.hpp>

#include <pwb/ui_controllers/catalog_api.hpp>
#include <pwb/ui_controllers/host_api.hpp>
#include <pwb/ui_controllers/job_runner.hpp>

namespace pwb::ui_shell {
class OperationRegistry;
}

namespace pwb::ui_controllers {

// unwrap_asset parity: an AssetView handle unwraps to its raw_asset;
// every other handle is already the model object.
const ui_data_core::AssetObjectData& unwrap_asset(const AssetHandle& item);
AssetHandle unwrap_handle(const AssetHandle& item);

// _catalog_row_target parity: (service, asset_id, version_id, name) for
// both row shapes — bridged ResourceItems and catalog-only DataAsset rows.
struct CatalogRowTarget {
    CatalogServiceApi* service = nullptr;
    std::string asset_id;
    std::string version_id;
    std::string name;
};

// prepare_rescan's status vocabulary.
enum class RescanStatus { ok, missing, invalid };

struct RescanPrepared {
    RescanStatus status = RescanStatus::invalid;
    // The selected row's resource slice — the controller mutates it in
    // place through the page's Json document row index (resources are
    // Json rows; `resource_index` is the row's position in resources[]).
    int resource_index = -1;
    std::filesystem::path path;
    std::optional<std::filesystem::path> project_path;
};

// register_imported_resources receipt (ResourceItem.id → DataAsset.id).
using RegistrationReceipt = std::map<std::string, std::string>;

class DataLifecycleCore {
public:
    static constexpr int kRegistrationChunk = 500;

    DataLifecycleCore(DataPageApi page, CatalogRuntimeApi catalog_runtime,
                      DataLifecycleServiceApi services,
                      LifecycleDialogApi dialogs,
                      UiJobRunner* catalog_job, UiJobRunner* verify_job,
                      ui_shell::OperationRegistry* operations);

    // ---- catalog resolution (per-call, never cached) ----------------------
    CatalogServiceApi* catalog_service() const;
    // catalog_bridge(resource) → (service, ref|nullopt).
    std::pair<CatalogServiceApi*, std::optional<catalog::DataVersionRef>>
    catalog_bridge(const AssetHandle& item) const;
    std::optional<CatalogRowTarget> catalog_row_target(
        const AssetHandle& item) const;
    // catalog_enricher() → one overview pass over CURRENT catalog state.
    std::optional<ui_data_core::CatalogEnricher> catalog_enricher() const;
    // catalog_only_rows(enricher|nullopt).
    std::vector<AssetView> catalog_only_rows(
        const ui_data_core::CatalogEnricher* enricher = nullptr) const;

    bool update_governance_metadata(const std::string& asset_id,
                                    const domain::Json& patch);
    std::optional<std::string> resolve_catalog_asset_id(
        const AssetHandle& item) const;

    // ---- remove / restore / rescan -----------------------------------------
    bool remove_assets(const std::vector<AssetHandle>& items);
    bool restore_selected_asset();
    RescanPrepared prepare_rescan();
    std::vector<ResourceItem> run_rescan(
        const std::filesystem::path& folder,
        const std::optional<std::filesystem::path>& project_path) const;
    // find_rescan_match → the scanned row index (-1 → none).
    int find_rescan_match(const std::vector<ResourceItem>& scanned,
                          const std::filesystem::path& path_resolved,
                          const std::optional<std::filesystem::path>&
                              project_path) const;
    bool apply_rescan_result(int resource_index,
                             const ResourceItem* updated);
    bool rescan_selected_asset();

    // ---- catalog actions (worker-backed, #931) ------------------------------
    void run_catalog_action(
        const std::string& label, std::function<std::any()> fn,
        std::function<void(const std::any&)> on_result,
        std::function<void(const std::string&)> on_fail = nullptr);
    void create_derived_copy(const AssetHandle& item);
    std::optional<ResourceItem> create_derived_via_catalog(
        const AssetHandle& item,
        CatalogServiceApi* service = nullptr,
        const std::optional<catalog::DataVersionRef>& ref = std::nullopt);
    void materialize_asset(const AssetHandle& item);
    void new_version_from_asset(const AssetHandle& item);
    void promote_asset(const AssetHandle& item);

    // ---- delivery ------------------------------------------------------------
    struct DeliveryPrepared {
        std::filesystem::path source_path;
        std::filesystem::path destination;
        CatalogServiceApi* service = nullptr;
        std::optional<catalog::DataVersionRef> ref;
    };
    std::optional<DeliveryPrepared> prepare_delivery(const AssetHandle& item);
    // worker half: copy + chmod 0644 + sha256.
    std::string run_delivery_copy(const std::filesystem::path& source,
                                  const std::filesystem::path& destination) const;
    void finish_delivery(const AssetHandle& item,
                         const DeliveryPrepared& prepared,
                         const std::string& checksum);
    void deliver_asset(const AssetHandle& item);

    // ---- tags -------------------------------------------------------------------
    void mirror_tag_to_catalog(const AssetHandle& item,
                               const std::string& tag_name, bool add);
    void handle_tag_added(const AssetHandle& item, const std::string& tag_name);
    void handle_tag_removed(const AssetHandle& item,
                            const std::string& tag_name);
    int bulk_apply_tag(const std::vector<AssetHandle>& items,
                       const std::string& tag_name, bool add);
    bool set_version_tag(const std::string& version_id,
                         const std::string& tag_name, bool add);
    void prompt_add_tag_to_assets(const std::vector<AssetHandle>& items);
    void prompt_remove_tag_from_assets(const std::vector<AssetHandle>& items);

    // ---- integrity ----------------------------------------------------------------
    std::pair<CatalogServiceApi*, std::map<std::string, std::string>>
    bridged_version_map(const std::vector<AssetHandle>& items) const;
    void verify_assets(const std::vector<AssetHandle>& items);

    // ---- trash companions + registration ---------------------------------------
    std::vector<ResourceItem> trashed_companions();
    std::optional<ResourceItem> resource_from_catalog_asset(
        CatalogServiceApi& service, const catalog::DataAsset& asset,
        bool trashed = false) const;
    RegistrationReceipt register_imported_resources(
        const std::vector<ResourceItem>& resources,
        std::function<void(int, int)> progress = nullptr,
        std::function<bool()> cancel_check = nullptr);

    // Outcome surfaces (Python attribute parity).
    std::vector<std::string> last_registration_failures;
    bool last_tag_mirror_failed = false;

private:
    // Json resources[] row access — the live document rows the Python
    // pydantic ResourceItem objects were. Edits land in place.
    domain::Json* resource_row_(int index) const;
    int resource_row_index_(const std::string& resource_id) const;
    void set_status_(const std::string& text) const;
    void refresh_() const;
    void fail_booked_run_(CatalogServiceApi* service,
                        const std::optional<std::string>& run_id) const;
    bool version_exists_(CatalogServiceApi* service,
                         const std::string& version_id) const;
    // resource.tags mutation on the Json row (the legacy side of tags).
    static std::vector<std::string> row_tags_(const domain::Json& row);
    static void row_add_tag_(domain::Json& row, const std::string& tag);
    static void row_remove_tag_(domain::Json& row, const std::string& tag);
    // The document root; nullptr when no document is open.
    domain::Json* project_root_() const;
    std::string resource_row_name_(const AssetHandle& item) const;

    DataPageApi page_;
    CatalogRuntimeApi catalog_;
    DataLifecycleServiceApi services_;
    LifecycleDialogApi dialogs_;
    UiJobRunner* catalog_job_;  // page._catalog_copy_job parity
    UiJobRunner* verify_job_;   // page._verify_job parity
    ui_shell::OperationRegistry* operations_;  // may be nullptr
};

}  // namespace pwb::ui_controllers
