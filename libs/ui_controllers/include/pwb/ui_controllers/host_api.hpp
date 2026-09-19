#pragma once

// UI-14 — host surface seams: the page/window objects the controllers
// read and the dialogs they open. Everything arrives as std::function —
// an unset function is Python's getattr(..., None): a no-op surface the
// orchestration tolerates, never a crash. The Qt shell binds the real
// pages/dialogs; tests inject fakes.

#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/domain/stage.hpp>
#include <pwb/project/document.hpp>
#include <pwb/ui_data_core/asset_view.hpp>

#include <pwb/ui_controllers/catalog_api.hpp>

namespace pwb::ui_controllers {

namespace fs = std::filesystem;
using ui_data_core::AssetHandle;
using ui_data_core::AssetView;
using ui_data_core::ExportArtifact;
using ui_data_core::GenericAsset;
using ui_data_core::ResourceItem;
using ui_data_core::SqlCatalogAssetRef;

// The DataPage surface (page.* attribute parity). document() returns the
// live project pointer (may be nullptr before first open).
struct DataPageApi {
    std::function<project::ProjectDocument*()> document;
    // page._selected_asset / page._set_selected_asset(item) — nullptr clears.
    std::function<AssetHandle()> selected_asset;
    std::function<void(const AssetHandle&)> set_selected_asset;
    std::function<void(const std::string&)> set_status;
    std::function<void()> refresh;
    std::function<void()> refresh_domain_views;
    std::function<void()> update_inspector;
    std::function<void(const ResourceItem&)> request_summary;
    std::function<fs::path(const ResourceItem&)> resolve_resource_path;
    std::function<std::optional<fs::path>()> project_file_for_io;
    std::function<std::optional<fs::path>()> preview_disk_project_root;
    // data_toolbar.set_verify_running(bool).
    std::function<void(bool)> set_verify_running;
};

// Dialog/host-file seams the lifecycle actions open. Every choice DTO
// returns nullopt on cancel — the dialog widget itself lives in the Qt
// shell (thin wrappers over QMessageBox/QDialog/QDesktopServices).
struct NewVersionChoice {
    domain::DataStage stage = domain::DataStage::Derived;
    std::string version_name;  // "" → default naming
};
struct PromoteChoice {
    domain::DataStage stage = domain::DataStage::Output;
    std::optional<std::string> reviewed_by;
    std::optional<std::string> note;
};
struct LifecycleDialogApi {
    std::function<std::optional<NewVersionChoice>(
        const std::string& asset_name, domain::DataStage default_stage)>
        new_version;
    std::function<std::optional<PromoteChoice>(const std::string& asset_name)>
        promote;
    std::function<std::optional<fs::path>(
        const std::string& asset_name, const std::string& suggested_path)>
        delivery;
    // TagInputDialog — (title, label) → tag name | nullopt.
    std::function<std::optional<std::string>(
        const std::string& title, const std::string& label)>
        tag_input;
    // confirm_trash_impact — the V13 impact gate (ui_review dialog).
    std::function<bool(
        CatalogServiceApi& service, domain::Json& project_root,
        const std::vector<std::string>& asset_ids,
        const std::vector<std::string>& asset_names,
        const domain::Json& mapping_workspace)>
        confirm_trash_impact;
    // QDesktopServices.openUrl(QUrl.fromLocalFile(path)).
    std::function<void(const fs::path&)> open_url;
};

// Module-level services the lifecycle controller calls (scanner/export/
// domain kernels not yet ported as Pwb services).
struct DataLifecycleServiceApi {
    // resources.scanner.scan_resources(folder, project_path=…) — worker.
    std::function<std::vector<ResourceItem>(
        const fs::path& folder, const std::optional<fs::path>& project_path)>
        scan_resources;
    // resources.export_service.default_export_dir(project_file).
    std::function<fs::path(const std::optional<fs::path>& project_file)>
        default_export_dir;
    // project.domain.remove_asset_links_and_prune_reference_wells →
    // (removed_links, removed_wells).
    std::function<std::pair<int, int>(
        domain::Json& project_root, const std::set<std::string>& asset_ids)>
        prune_asset_links;
};

}  // namespace pwb::ui_controllers
