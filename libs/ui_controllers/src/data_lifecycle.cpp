#include <pwb/ui_controllers/data_lifecycle.hpp>

#include <algorithm>
#include <chrono>
#include <filesystem>

#include <pwb/catalog/checksum.hpp>
#include <pwb/catalog/legacy_migration.hpp>
#include <pwb/project/paths.hpp>
#include <pwb/ui_shell/operation_registry.hpp>

namespace pwb::ui_controllers {

namespace {

std::string json_str(const domain::Json& object, const char* key) {
    if (!object.is_object()) return {};
    const auto it = object.find(key);
    if (it == object.end() || !it->is_string()) return {};
    return it->get<std::string>();
}

bool json_bool(const domain::Json& object, const char* key,
               bool fallback = false) {
    const auto it = object.find(key);
    return (it != object.end() && it->is_boolean()) ? it->get<bool>()
                                                    : fallback;
}

// ResourceItem → its persisted resources[] row (the companion-row shape
// upsert_legacy_resource consumes).
domain::Json resource_item_to_json(const ResourceItem& item) {
    domain::Json row = domain::Json::object();
    if (!item.id.empty()) row["id"] = item.id;
    row["name"] = item.name;
    row["path"] = item.path;
    if (!item.type.empty()) row["type"] = item.type;
    if (!item.format.empty()) row["format"] = item.format;
    if (item.crs) row["crs"] = *item.crs;
    row["status"] = item.status;
    row["tags"] = item.tags;
    row["source"] = item.source;
    row["parsed_summary"] = item.parsed_summary;
    if (item.checksum) row["checksum"] = *item.checksum;
    row["external"] = item.external;
    if (item.artifact_role) row["artifact_role"] = *item.artifact_role;
    return row;
}

ResourceItem json_to_resource_item(const domain::Json& row) {
    ResourceItem item;
    item.id = json_str(row, "id");
    item.name = json_str(row, "name");
    item.path = json_str(row, "path");
    item.type = json_str(row, "type");
    item.format = json_str(row, "format");
    if (const auto it = row.find("crs");
        it != row.end() && it->is_string())
        item.crs = it->get<std::string>();
    item.status = json_str(row, "status");
    if (item.status.empty()) item.status = "indexed";
    if (const auto it = row.find("tags"); it != row.end() && it->is_array())
        for (const auto& tag : *it)
            if (tag.is_string()) item.tags.push_back(tag.get<std::string>());
    item.source = json_str(row, "source");
    if (item.source.empty()) item.source = "local";
    if (const auto it = row.find("parsed_summary");
        it != row.end() && it->is_object())
        item.parsed_summary = *it;
    if (const auto it = row.find("checksum");
        it != row.end() && it->is_string())
        item.checksum = it->get<std::string>();
    item.external = json_bool(row, "external");
    if (const auto it = row.find("artifact_role");
        it != row.end() && it->is_string())
        item.artifact_role = it->get<std::string>();
    return item;
}

std::string stage_value(domain::DataStage stage) {
    switch (stage) {
        case domain::DataStage::Raw: return "raw";
        case domain::DataStage::Derived: return "derived";
        case domain::DataStage::Intermediate: return "intermediate";
        case domain::DataStage::Output: return "output";
    }
    return "raw";
}

}  // namespace

const ui_data_core::AssetObjectData& unwrap_asset(const AssetHandle& item) {
    static const ui_data_core::AssetObjectData kEmpty{GenericAsset{}};
    if (!item) return kEmpty;
    if (const auto* view = std::get_if<std::shared_ptr<AssetView>>(&*item);
        view != nullptr && *view && (*view)->raw_asset) {
        return *(*view)->raw_asset;
    }
    return *item;
}

AssetHandle unwrap_handle(const AssetHandle& item) {
    if (!item) return item;
    if (const auto* view = std::get_if<std::shared_ptr<AssetView>>(&*item);
        view != nullptr && *view && (*view)->raw_asset) {
        return (*view)->raw_asset;
    }
    return item;
}

DataLifecycleCore::DataLifecycleCore(
    DataPageApi page, CatalogRuntimeApi catalog_runtime,
    DataLifecycleServiceApi services, LifecycleDialogApi dialogs,
    UiJobRunner* catalog_job, UiJobRunner* verify_job,
    ui_shell::OperationRegistry* operations)
    : page_(std::move(page)),
      catalog_(std::move(catalog_runtime)),
      services_(std::move(services)),
      dialogs_(std::move(dialogs)),
      catalog_job_(catalog_job),
      verify_job_(verify_job),
      operations_(operations) {}

void DataLifecycleCore::set_status_(const std::string& text) const {
    if (page_.set_status) page_.set_status(text);
}
void DataLifecycleCore::refresh_() const {
    if (page_.refresh) page_.refresh();
}

domain::Json* DataLifecycleCore::project_root_() const {
    auto* doc = page_.document ? page_.document() : nullptr;
    return doc ? &doc->root() : nullptr;
}

domain::Json* DataLifecycleCore::resource_row_(int index) const {
    auto* root = project_root_();
    if (root == nullptr) return nullptr;
    const auto it = root->find("resources");
    if (it == root->end() || !it->is_array()) return nullptr;
    if (index < 0 || static_cast<std::size_t>(index) >= it->size())
        return nullptr;
    return &(*it)[index];
}

int DataLifecycleCore::resource_row_index_(
    const std::string& resource_id) const {
    auto* root = project_root_();
    if (root == nullptr) return -1;
    const auto it = root->find("resources");
    if (it == root->end() || !it->is_array()) return -1;
    for (std::size_t i = 0; i < it->size(); ++i) {
        if (json_str((*it)[i], "id") == resource_id)
            return static_cast<int>(i);
    }
    return -1;
}

std::vector<std::string> DataLifecycleCore::row_tags_(
    const domain::Json& row) {
    std::vector<std::string> tags;
    const auto it = row.find("tags");
    if (it != row.end() && it->is_array())
        for (const auto& tag : *it)
            if (tag.is_string()) tags.push_back(tag.get<std::string>());
    return tags;
}

void DataLifecycleCore::row_add_tag_(domain::Json& row,
                                     const std::string& tag) {
    auto& tags = row["tags"];
    if (!tags.is_array()) tags = domain::Json::array();
    for (const auto& existing : tags)
        if (existing.is_string() && existing.get<std::string>() == tag)
            return;
    tags.push_back(tag);
}

void DataLifecycleCore::row_remove_tag_(domain::Json& row,
                                        const std::string& tag) {
    auto it = row.find("tags");
    if (it == row.end() || !it->is_array()) return;
    for (auto jt = it->begin(); jt != it->end(); ++jt) {
        if (jt->is_string() && jt->get<std::string>() == tag) {
            it->erase(jt);
            return;
        }
    }
}

std::string DataLifecycleCore::resource_row_name_(
    const AssetHandle& item) const {
    const auto& data = unwrap_asset(item);
    if (const auto* resource = std::get_if<ResourceItem>(&data))
        return resource->name;
    if (const auto* asset =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&data))
        return (*asset)->name;
    if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&data))
        return ref->name;
    if (const auto* artifact = std::get_if<ExportArtifact>(&data))
        return artifact->id;
    return {};
}

// ---------------------------------------------------------------------------
// Catalog resolution
// ---------------------------------------------------------------------------

CatalogServiceApi* DataLifecycleCore::catalog_service() const {
    if (!catalog_.get_catalog_service) return nullptr;
    try {
        return catalog_.get_catalog_service();
    } catch (const std::exception&) {
        return nullptr;
    }
}

std::pair<CatalogServiceApi*, std::optional<catalog::DataVersionRef>>
DataLifecycleCore::catalog_bridge(const AssetHandle& item) const {
    const auto& data = unwrap_asset(item);
    const auto* resource = std::get_if<ResourceItem>(&data);
    if (resource == nullptr || !catalog_.get_catalog) return {nullptr, {}};
    try {
        auto* catalog = catalog_.get_catalog();
        if (catalog == nullptr) return {nullptr, {}};
        auto ref = catalog->resolve_legacy_resource(resource->id);
        if (!ref) return {nullptr, {}};
        auto* service = catalog_service();
        if (service == nullptr) return {nullptr, {}};
        return {service, ref};
    } catch (const std::exception&) {
        return {nullptr, {}};
    }
}

std::optional<CatalogRowTarget> DataLifecycleCore::catalog_row_target(
    const AssetHandle& item) const {
    const auto& data = unwrap_asset(item);
    if (std::get_if<ResourceItem>(&data) != nullptr) {
        const auto [service, ref] = catalog_bridge(item);
        if (service == nullptr || !ref) return std::nullopt;
        CatalogRowTarget target;
        target.service = service;
        target.asset_id = ref->asset_id;
        target.version_id = ref->version_id;
        target.name = resource_row_name_(item);
        return target;
    }
    if (const auto* asset =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&data);
        asset != nullptr && *asset != nullptr &&
        (*asset)->current_version_id) {
        auto* service = catalog_service();
        if (service == nullptr) return std::nullopt;
        CatalogRowTarget target;
        target.service = service;
        target.asset_id = (*asset)->id.str();
        target.version_id = (*asset)->current_version_id->str();
        target.name = (*asset)->name;
        return target;
    }
    if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&data);
        ref != nullptr && !ref->current_version_id.empty()) {
        auto* service = catalog_service();
        if (service == nullptr) return std::nullopt;
        CatalogRowTarget target;
        target.service = service;
        target.asset_id = ref->id;
        target.version_id = ref->current_version_id;
        target.name = ref->name;
        return target;
    }
    return std::nullopt;
}

std::optional<ui_data_core::CatalogEnricher>
DataLifecycleCore::catalog_enricher() const {
    auto* service = catalog_service();
    if (service == nullptr) return std::nullopt;
    try {
        return ui_data_core::CatalogEnricher(
            ui_data_core::compute_catalog_row_overview(*service));
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

std::vector<AssetView> DataLifecycleCore::catalog_only_rows(
    const ui_data_core::CatalogEnricher* enricher) const {
    auto* service = catalog_service();
    if (service == nullptr) return {};
    std::unordered_map<std::string, ui_data_core::CatalogRowOverview> overviews;
    try {
        if (enricher != nullptr && !enricher->overview_map().empty()) {
            overviews = enricher->overview_map();
        } else {
            overviews = ui_data_core::compute_catalog_row_overview(*service);
        }
    } catch (const std::exception&) {
        return {};
    }
    auto* root = project_root_();
    std::set<std::string> legacy_ids;
    std::set<std::string> artifact_version_ids;
    if (root != nullptr) {
        const auto res = root->find("resources");
        if (res != root->end() && res->is_array())
            for (const auto& row : *res)
                legacy_ids.insert(json_str(row, "id"));
        const auto art = root->find("export_artifacts");
        if (art != root->end() && art->is_array())
            for (const auto& row : *art) {
                const std::string vid = json_str(row, "catalog_version_id");
                if (!vid.empty()) artifact_version_ids.insert(vid);
            }
    }
    // version_id → asset_id map: artifacts register their version; the
    // catalog asset behind it must not also list as an orphan row.
    std::set<std::string> artifact_asset_ids;
    if (enricher != nullptr) {
        for (const auto& vid : artifact_version_ids) {
            const auto it = enricher->version_to_asset().find(vid);
            if (it != enricher->version_to_asset().end())
                artifact_asset_ids.insert(it->second);
        }
    }
    const auto root_dir =
        page_.preview_disk_project_root ? page_.preview_disk_project_root()
                                        : std::nullopt;
    std::vector<AssetView> rows;
    for (const auto& [asset_id, overview] : overviews) {
        if (overview.trashed) continue;
        if (legacy_ids.count(asset_id) || artifact_asset_ids.count(asset_id))
            continue;
        if (overview.legacy_resource_id &&
            legacy_ids.count(*overview.legacy_resource_id))
            continue;
        try {
            rows.push_back(ui_data_core::asset_view_from_catalog_overview(
                overview,
                root_dir ? &*root_dir : nullptr));
        } catch (const std::exception&) {
            continue;
        }
    }
    return rows;
}

bool DataLifecycleCore::update_governance_metadata(
    const std::string& asset_id, const domain::Json& patch) {
    auto* service = catalog_service();
    if (service == nullptr) {
        set_status_("治理信息需要活动数据目录");
        return false;
    }
    try {
        service->update_asset_metadata(asset_id, patch);
    } catch (const std::exception& exc) {
        set_status_(std::string("治理信息保存失败: ") + exc.what());
        return false;
    }
    refresh_();
    if (page_.update_inspector) page_.update_inspector();
    set_status_("已保存治理信息");
    return true;
}

std::optional<std::string> DataLifecycleCore::resolve_catalog_asset_id(
    const AssetHandle& item) const {
    const auto& data = unwrap_asset(item);
    if (std::get_if<ResourceItem>(&data) != nullptr) {
        const auto [service, ref] = catalog_bridge(item);
        (void)service;
        return ref ? std::optional<std::string>(ref->asset_id) : std::nullopt;
    }
    if (const auto* artifact = std::get_if<ExportArtifact>(&data)) {
        // The artifact's own id is NOT a catalog asset id — resolve only
        // through its registered catalog_version_id.
        if (!artifact->catalog_version_id) return std::nullopt;
        auto* service = catalog_service();
        if (service == nullptr) return std::nullopt;
        try {
            return std::optional<std::string>(
                service->get_version(*artifact->catalog_version_id)
                    .asset_id.str());
        } catch (const std::exception&) {
            return std::nullopt;
        }
    }
    if (const auto* asset =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&data)) {
        return (*asset)->id.str();
    }
    if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&data)) {
        return ref->id;
    }
    if (const auto* generic = std::get_if<GenericAsset>(&data)) {
        const auto id = json_str(generic->attrs, "id");
        if (!id.empty()) return id;
    }
    return std::nullopt;
}

// ---------------------------------------------------------------------------
// Remove / restore / rescan
// ---------------------------------------------------------------------------

bool DataLifecycleCore::remove_assets(const std::vector<AssetHandle>& items) {
    std::set<std::string> target_ids;
    for (const auto& item : items) {
        const auto& data = unwrap_asset(item);
        if (const auto* resource = std::get_if<ResourceItem>(&data)) {
            if (!resource->id.empty()) target_ids.insert(resource->id);
        } else if (const auto* ref =
                       std::get_if<SqlCatalogAssetRef>(&data)) {
            if (!ref->id.empty()) target_ids.insert(ref->id);
        } else if (const auto* asset = std::get_if<
                       std::shared_ptr<const catalog::DataAsset>>(&data)) {
            if (!(*asset)->id.empty()) target_ids.insert((*asset)->id.str());
        } else if (const auto* artifact =
                       std::get_if<ExportArtifact>(&data)) {
            if (!artifact->id.empty()) target_ids.insert(artifact->id);
        }
    }
    std::set<std::string> domain_asset_ids = target_ids;
    std::vector<catalog::DataAsset> trashed_assets;
    int trashed_count = 0;
    int removed_count = 0;
    auto* service = catalog_service();
    auto* root = project_root_();

    // V13 W-C/W-F impact gate: only assets the catalog actually holds
    // (legacy-only rows carry no catalog impact); zero downstream impact
    // passes silently.
    if (service != nullptr && root != nullptr) {
        std::set<std::string> gate_ids;
        for (const auto& item : items) {
            const auto& data = unwrap_asset(item);
            if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&data)) {
                gate_ids.insert(ref->id);
            } else if (const auto* asset = std::get_if<
                           std::shared_ptr<const catalog::DataAsset>>(
                           &data)) {
                gate_ids.insert((*asset)->id.str());
            } else if (std::get_if<ResourceItem>(&data) != nullptr) {
                const auto [svc, ref] = catalog_bridge(item);
                if (ref) gate_ids.insert(ref->asset_id);
            }
        }
        try {
            std::set<std::string> filtered;
            for (const auto& id : gate_ids)
                if (service->asset_exists(id)) filtered.insert(id);
            gate_ids = std::move(filtered);
        } catch (const std::exception&) {
            gate_ids.clear();
        }
        if (!gate_ids.empty() && dialogs_.confirm_trash_impact) {
            std::vector<std::string> asset_names;
            for (const auto& item : items) {
                const std::string name = resource_row_name_(item);
                if (!name.empty()) asset_names.push_back(name);
            }
            const auto ws_it = root->find("mapping_workspace");
            const auto workspace =
                (ws_it != root->end() && ws_it->is_object())
                    ? *ws_it
                    : domain::Json::object();
            std::vector<std::string> sorted_ids(gate_ids.begin(),
                                                gate_ids.end());
            if (!dialogs_.confirm_trash_impact(*service, *root, sorted_ids,
                                               asset_names, workspace)) {
                set_status_("已取消移出（影响预览未确认）");
                return false;
            }
        }
    }

    // Catalog-only rows trash directly (SqlCatalogAssetRef + DataAsset).
    if (service != nullptr) {
        for (const auto& item : items) {
            const auto& data = unwrap_asset(item);
            std::string asset_id;
            if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&data)) {
                asset_id = ref->id;
            } else if (const auto* asset = std::get_if<
                           std::shared_ptr<const catalog::DataAsset>>(
                           &data)) {
                asset_id = (*asset)->id.str();
            } else {
                continue;
            }
            if (asset_id.empty()) continue;
            try {
                trashed_assets.push_back(
                    service->trash_asset(asset_id, "移出项目"));
                ++trashed_count;
                domain_asset_ids.insert(asset_id);
                target_ids.erase(asset_id);
            } catch (const std::exception& exc) {
                set_status_(std::string("移入回收站失败，未移除: ") +
                            exc.what());
                refresh_();
                return false;
            }
        }
    }

    // Bridged legacy rows: trash their catalog asset first (a catalog
    // trash failure aborts the whole removal — never a ghost).
    for (const auto& item : items) {
        const auto& data = unwrap_asset(item);
        if (std::get_if<ResourceItem>(&data) == nullptr) continue;
        const auto [service_for_ref, ref] = catalog_bridge(item);
        if (service_for_ref == nullptr || !ref) continue;
        try {
            trashed_assets.push_back(
                service_for_ref->trash_asset(ref->asset_id, "移出项目"));
            ++trashed_count;
            domain_asset_ids.insert(ref->asset_id);
        } catch (const std::exception& exc) {
            set_status_(std::string("移入回收站失败，未移除: ") + exc.what());
            refresh_();
            return false;
        }
    }

    if (root != nullptr) {
        std::size_t before_res = 0, before_art = 0;
        const auto res_it = root->find("resources");
        if (res_it != root->end() && res_it->is_array())
            before_res = res_it->size();
        const auto art_it = root->find("export_artifacts");
        if (art_it != root->end() && art_it->is_array())
            before_art = art_it->size();
        catalog::remove_legacy_resources_for_assets(root, trashed_assets);
        catalog::remove_legacy_resources_by_ids(
            root, {target_ids.begin(), target_ids.end()});
        std::size_t after_res = 0, after_art = 0;
        if (res_it != root->end() && res_it->is_array())
            after_res = res_it->size();
        const auto art_after = root->find("export_artifacts");
        if (art_after != root->end() && art_after->is_array())
            after_art = art_after->size();
        removed_count += static_cast<int>(before_res - after_res) +
                         static_cast<int>(before_art - after_art);
    }

    if (removed_count > 0 || trashed_count > 0) {
        std::pair<int, int> pruned{0, 0};
        if (root != nullptr && services_.prune_asset_links) {
            try {
                pruned = services_.prune_asset_links(*root, domain_asset_ids);
            } catch (const std::exception&) {
            }
        }
        if (page_.set_selected_asset) page_.set_selected_asset(nullptr);
        if ((pruned.first > 0 || pruned.second > 0) &&
            page_.refresh_domain_views) {
            page_.refresh_domain_views();
        } else {
            refresh_();
        }
        if (trashed_count > 0) {
            set_status_("已移至回收站 (" + std::to_string(trashed_count) +
                        " 项)");
        } else {
            set_status_("已移出项目 (" + std::to_string(removed_count) +
                        " 项)");
        }
        return true;
    }
    return false;
}

bool DataLifecycleCore::restore_selected_asset() {
    const AssetHandle item =
        page_.selected_asset ? page_.selected_asset() : nullptr;
    const auto& data = unwrap_asset(item);
    auto* root = project_root_();
    auto* service = catalog_service();
    if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&data)) {
        if (service == nullptr) {
            set_status_("该回收站项目无目录关联，无法还原");
            return false;
        }
        catalog::DataAsset asset;
        try {
            asset = service->restore_asset(ref->id);
        } catch (const std::exception& exc) {
            set_status_(std::string("还原失败: ") + exc.what());
            return false;
        }
        auto restored = resource_from_catalog_asset(*service, asset);
        if (root != nullptr && restored) {
            catalog::upsert_legacy_resource(
                root, resource_item_to_json(*restored));
        }
        return true;
    }
    const auto* resource = std::get_if<ResourceItem>(&data);
    if (resource == nullptr) {
        set_status_("请选择回收站中的数据项");
        return false;
    }
    if (service == nullptr) {
        set_status_("该回收站项目无目录关联，无法还原");
        return false;
    }
    // Trashed assets have no current version; the companion records the
    // catalog asset id directly in parsed_summary.
    std::string asset_id;
    if (resource->parsed_summary.is_object()) {
        const auto it = resource->parsed_summary.find("catalog_asset_id");
        if (it != resource->parsed_summary.end() && it->is_string())
            asset_id = it->get<std::string>();
    }
    if (asset_id.empty()) {
        const auto [svc, ref] = catalog_bridge(item);
        if (!ref) {
            set_status_("该回收站项目无目录关联，无法还原");
            return false;
        }
        asset_id = ref->asset_id;
    }
    catalog::DataAsset asset;
    try {
        asset = service->restore_asset(asset_id);
    } catch (const std::exception& exc) {
        set_status_(std::string("还原失败: ") + exc.what());
        return false;
    }
    auto restored = resource_from_catalog_asset(*service, asset);
    if (root != nullptr && restored) {
        catalog::upsert_legacy_resource(
            root, resource_item_to_json(*restored));
    }
    if (page_.set_selected_asset) page_.set_selected_asset(nullptr);
    refresh_();
    set_status_("已从回收站还原");
    return true;
}

RescanPrepared DataLifecycleCore::prepare_rescan() {
    RescanPrepared prepared;
    const AssetHandle item =
        page_.selected_asset ? page_.selected_asset() : nullptr;
    const auto& data = unwrap_asset(item);
    const auto* resource = std::get_if<ResourceItem>(&data);
    if (resource == nullptr || !page_.resolve_resource_path) {
        set_status_("请选择一个项目资源");
        return prepared;
    }
    prepared.resource_index = resource_row_index_(resource->id);
    prepared.path = page_.resolve_resource_path(*resource);
    prepared.project_path = page_.project_file_for_io
                                ? page_.project_file_for_io()
                                : std::nullopt;
    std::error_code ec;
    const bool exists = std::filesystem::exists(prepared.path, ec);
    if (ec || !exists) {
        // Unprobeable paths report as missing instead of raising (#882).
        if (auto* row = resource_row_(prepared.resource_index)) {
            (*row)["status"] = "missing";
            if (!(*row)["parsed_summary"].is_object())
                (*row)["parsed_summary"] = domain::Json::object();
            (*row)["parsed_summary"]["preview_warning"] = "文件不存在";
        }
        refresh_();
        if (page_.request_summary) page_.request_summary(*resource);
        set_status_("文件不存在");
        prepared.status = RescanStatus::missing;
        return prepared;
    }
    prepared.status = RescanStatus::ok;
    return prepared;
}

std::vector<ResourceItem> DataLifecycleCore::run_rescan(
    const std::filesystem::path& folder,
    const std::optional<std::filesystem::path>& project_path) const {
    if (!services_.scan_resources) return {};
    return services_.scan_resources(folder, project_path);
}

int DataLifecycleCore::find_rescan_match(
    const std::vector<ResourceItem>& scanned,
    const std::filesystem::path& path_resolved,
    const std::optional<std::filesystem::path>& project_path) const {
    for (std::size_t i = 0; i < scanned.size(); ++i) {
        try {
            fs::path item_path(scanned[i].path);
            if (!item_path.is_absolute() && project_path) {
                auto resolved = project::resolve_project_path(
                    scanned[i].path, *project_path);
                if (resolved.is_ok()) item_path = resolved.value();
            }
            std::error_code ec;
            const auto canonical = fs::weakly_canonical(item_path, ec);
            const auto want = fs::weakly_canonical(path_resolved, ec);
            if (!ec && canonical == want) return static_cast<int>(i);
        } catch (const std::exception&) {
            continue;
        }
    }
    return -1;
}

bool DataLifecycleCore::apply_rescan_result(
    int resource_index, const ResourceItem* updated) {
    if (updated == nullptr) {
        set_status_("重新扫描未找到文件");
        return false;
    }
    auto* row = resource_row_(resource_index);
    if (row == nullptr) {
        set_status_("重新扫描未找到文件");
        return false;
    }
    const std::string keep_type = json_str(*row, "type");
    const std::string keep_role = json_str(*row, "artifact_role");
    const auto keep_tags = row_tags_(*row);
    (*row)["name"] = updated->name;
    (*row)["path"] = updated->path;
    (*row)["format"] = updated->format;
    (*row)["status"] = updated->status;
    (*row)["source"] = updated->source;
    (*row)["parsed_summary"] = updated->parsed_summary;
    if (updated->checksum) (*row)["checksum"] = *updated->checksum;
    (*row)["external"] = updated->external;
    if (keep_type == updated->type || keep_type.empty()) {
        (*row)["type"] = updated->type;
        if (updated->artifact_role)
            (*row)["artifact_role"] = *updated->artifact_role;
        else if (!keep_role.empty())
            (*row)["artifact_role"] = keep_role;
    } else {
        // Type disagreement keeps the old classification AND the tags.
        if (!keep_type.empty()) (*row)["type"] = keep_type;
        if (!keep_role.empty()) (*row)["artifact_role"] = keep_role;
        (*row)["tags"] = keep_tags;
    }
    refresh_();
    if (page_.request_summary) page_.request_summary(*updated);
    set_status_("已重新扫描");
    return true;
}

bool DataLifecycleCore::rescan_selected_asset() {
    const auto prepared = prepare_rescan();
    if (prepared.status != RescanStatus::ok) {
        return prepared.status == RescanStatus::missing;
    }
    const auto scanned = run_rescan(prepared.path.parent_path(),
                                    prepared.project_path);
    std::error_code ec;
    const auto resolved = fs::weakly_canonical(prepared.path, ec);
    const int match = find_rescan_match(
        scanned, ec ? prepared.path : resolved, prepared.project_path);
    const ResourceItem* updated =
        match >= 0 ? &scanned[match] : nullptr;
    return apply_rescan_result(prepared.resource_index, updated);
}

// ---------------------------------------------------------------------------
// Catalog actions (worker-backed)
// ---------------------------------------------------------------------------

void DataLifecycleCore::run_catalog_action(
    const std::string& label, std::function<std::any()> fn,
    std::function<void(const std::any&)> on_result,
    std::function<void(const std::string&)> on_fail) {
    if (catalog_job_ == nullptr) {
        // Defensive fallback (page built before the job existed): run
        // synchronously, the Python `job is None` branch.
        try {
            on_result(fn());
        } catch (const std::exception& exc) {
            if (on_fail) {
                on_fail(exc.what());
            } else {
                set_status_(label + "失败: " + exc.what());
            }
        }
        return;
    }
    if (catalog_job_->is_running()) {
        set_status_(label + "：上一个数据操作仍在进行，请稍候…");
        return;
    }
    job::JobSpec spec;
    spec.kind = "io";
    spec.title = label;
    spec.run = [fn = std::move(fn)](job::JobContext&) -> std::any {
        return fn();
    };
    catalog_job_->start(
        std::move(spec),
        [this, label, on_result, on_fail](const UiJobOutcome& outcome) {
            if (outcome.state == job::JobState::failed) {
                if (on_fail) {
                    on_fail(outcome.error);
                } else {
                    set_status_(label + "失败: " + outcome.error);
                }
                return;
            }
            if (outcome.state == job::JobState::cancelled) return;
            on_result(outcome.result);
        });
    set_status_(label + "中…（大数据可能需要数秒）");
}

void DataLifecycleCore::create_derived_copy(const AssetHandle& item) {
    const auto target = catalog_row_target(item);
    if (!target) {
        set_status_("创建派生副本需要活动数据目录（数据未桥接）");
        return;
    }
    auto* service = target->service;
    const std::string asset_id = target->asset_id;
    const std::string version_id = target->version_id;
    const std::string name = target->name;
    const auto& data = unwrap_asset(item);
    if (std::get_if<ResourceItem>(&data) != nullptr) {
        // Legacy row: companion-style derived copy with a legacy re-surface.
        run_catalog_action(
            "创建派生副本",
            [this, item, service, asset_id, version_id]() -> std::any {
                catalog::DataVersionRef ref;
                ref.asset_id = asset_id;
                ref.version_id = version_id;
                auto derived = create_derived_via_catalog(item, service, ref);
                return derived ? std::any(*derived) : std::any();
            },
            [this, name](const std::any& result) {
                if (!result.has_value()) {
                    set_status_("创建派生副本失败: 无法解析源版本");
                    return;
                }
                const auto derived = std::any_cast<ResourceItem>(result);
                if (auto* root = project_root_()) {
                    catalog::upsert_legacy_resource(
                        root, resource_item_to_json(derived));
                }
                refresh_();
                if (page_.set_selected_asset) {
                    page_.set_selected_asset(
                        ui_data_core::make_asset_handle(derived));
                }
                set_status_("已从 ⊘ RAW 建立派生副本: " + derived.name);
            });
        return;
    }
    run_catalog_action(
        "创建派生副本",
        [service, version_id, name]() -> std::any {
            const auto source_version = service->get_version(version_id);
            const auto payload = service->resolve_path(source_version);
            if (!std::filesystem::is_regular_file(payload)) {
                return std::any();
            }
            return service->create_derived(
                payload, {source_version.id.str()}, name + "_derived",
                "derived_copy", "data_manager");
        },
        [this, name](const std::any& result) {
            if (!result.has_value()) {
                set_status_("创建派生副本失败: 无法解析源版本");
                return;
            }
            const auto& version =
                std::any_cast<catalog::DataVersion>(result);
            refresh_();
            set_status_("已建立派生副本: " + name + "_derived (v" +
                        std::to_string(version.version_number) + ")");
        });
}

std::optional<ResourceItem> DataLifecycleCore::create_derived_via_catalog(
    const AssetHandle& item, CatalogServiceApi* service,
    const std::optional<catalog::DataVersionRef>& ref_opt) {
    const auto& data = unwrap_asset(item);
    const auto* resource = std::get_if<ResourceItem>(&data);
    if (resource == nullptr) return std::nullopt;
    catalog::DataVersionRef ref;
    if (service == nullptr || !ref_opt) {
        const auto resolved = catalog_bridge(item);
        service = resolved.first;
        if (!resolved.second) return std::nullopt;
        ref = *resolved.second;
    } else {
        ref = *ref_opt;
    }
    if (service == nullptr) return std::nullopt;
    // Catalog failures RAISE — the caller surfaces them.
    const auto source_version = service->get_version(ref.version_id);
    const auto source_payload = service->resolve_path(source_version);
    if (!std::filesystem::is_regular_file(source_payload)) {
        return std::nullopt;
    }
    const auto version = service->create_derived(
        source_payload, {source_version.id.str()}, resource->name + "_derived",
        "derived_copy", "data_manager");
    const auto managed_path = service->resolve_path(version);
    const auto relativized = project::relativize_path(
        managed_path, service->project_path());
    ResourceItem companion;
    companion.name = resource->name + "_derived";
    companion.path = relativized.stored;
    companion.type = resource->type;
    companion.format = resource->format;
    companion.crs = resource->crs;
    companion.status = resource->status;
    companion.tags = resource->tags;
    companion.tags.insert(companion.tags.begin(), "派生");
    companion.source = "derived from " + resource->name;
    companion.parsed_summary = resource->parsed_summary.is_object()
                                   ? resource->parsed_summary
                                   : domain::Json::object();
    companion.parsed_summary["derived_from_id"] = resource->id;
    companion.parsed_summary["derived_from_name"] = resource->name;
    companion.parsed_summary["catalog_asset_id"] = version.asset_id.str();
    companion.parsed_summary["catalog_version_id"] = version.id.str();
    companion.checksum = version.sha256;
    companion.external = false;
    companion.artifact_role = "derived";
    return companion;
}

void DataLifecycleCore::materialize_asset(const AssetHandle& item) {
    const auto& data = unwrap_asset(item);
    const auto* resource = std::get_if<ResourceItem>(&data);
    if (resource == nullptr) {
        set_status_("仅支持纳管 ResourceItem 数据");
        return;
    }
    const auto [service, ref] = catalog_bridge(item);
    if (service == nullptr || !ref) {
        set_status_("未连接数据目录，无法纳管");
        return;
    }
    if (!ref->external) {
        set_status_("该数据已是受管数据");
        return;
    }
    // Provenance first: the materialize run is booked before the copy so
    // the service can atomically attach the snapshot as its output.
    std::optional<std::string> run_id;
    try {
        const auto external_path =
            service->resolve_path(service->get_version(ref->version_id));
        domain::Json params = domain::Json::object();
        params["source"] = external_path.generic_string();
        const auto run = service->register_run(
            "materialize", {ref->version_id}, params);
        run_id = run.id.str();
    } catch (const std::exception&) {
        run_id = std::nullopt;
    }
    const std::string version_id = ref->version_id;
    const int resource_index = resource_row_index_(resource->id);
    run_catalog_action(
        "纳管",
        [service, version_id, run_id]() -> std::any {
            const auto version =
                service->materialize_external(version_id, run_id);
            return std::make_pair(version, service->resolve_path(version));
        },
        [this, service, resource_index](const std::any& result) {
            const auto& [version, managed_path] =
                std::any_cast<const std::pair<catalog::DataVersion,
                                              std::filesystem::path>&>(
                    result);
            const auto relativized = project::relativize_path(
                managed_path, service->project_path());
            std::string row_name;
            if (auto* row = resource_row_(resource_index)) {
                (*row)["external"] = false;
                (*row)["path"] = relativized.stored;
                if (version.sha256) (*row)["checksum"] = *version.sha256;
                row_name = json_str(*row, "name");
            }
            refresh_();
            set_status_("已纳管至项目: " + row_name);
        },
        [this, service, run_id](const std::string& message) {
            fail_booked_run_(service, run_id);
            set_status_("纳管失败: " + message);
        });
}

void DataLifecycleCore::new_version_from_asset(const AssetHandle& item) {
    const auto target = catalog_row_target(item);
    if (!target) {
        set_status_("新建版本需要活动数据目录（数据未桥接）");
        return;
    }
    auto* service = target->service;
    const std::string asset_id = target->asset_id;
    const std::string version_id = target->version_id;
    const std::string name = target->name;
    std::filesystem::path working_path;
    try {
        working_path = service->create_working_copy(version_id);
    } catch (const std::exception& exc) {
        set_status_(std::string("创建工作副本失败: ") + exc.what());
        return;
    }
    if (dialogs_.open_url) dialogs_.open_url(working_path);
    if (!dialogs_.new_version) return;
    const auto choice =
        dialogs_.new_version(name, domain::DataStage::Derived);
    if (!choice) {
        set_status_("已创建可编辑工作副本（未提交）: " +
                    working_path.generic_string());
        return;
    }
    // V13 audit fix: confirm the copy worker is idle BEFORE booking the
    // run — the refused branch never calls on_fail, so a pre-booked run
    // would leak as a phantom RUNNING row.
    if (catalog_job_ != nullptr && catalog_job_->is_running()) {
        set_status_("提交新版本：上一个数据操作仍在进行，请稍候（工作副本"
                    "保留，稍后可重试）");
        return;
    }
    std::optional<std::string> run_id;
    try {
        if (catalog_.register_manual_edit_run) {
            domain::Json extra = domain::Json::object();
            extra["stage"] = stage_value(choice->stage);
            const auto run = catalog_.register_manual_edit_run(
                service, {version_id},
                choice->version_name.empty()
                    ? std::nullopt
                    : std::optional<std::string>(choice->version_name),
                extra);
            if (run) run_id = run->id.str();
        }
    } catch (const std::exception&) {
        run_id = std::nullopt;
    }
    run_catalog_action(
        "提交新版本",
        [service, working_path, asset_id, choice, run_id]() -> std::any {
            return service->commit_working_copy(
                working_path, asset_id,
                choice->version_name.empty()
                    ? std::nullopt
                    : std::optional<std::string>(choice->version_name),
                choice->stage, run_id);
        },
        [this, service, run_id](const std::any& result) {
            const auto& version = std::any_cast<catalog::DataVersion>(result);
            if (run_id && catalog_.complete_manual_edit_run) {
                try {
                    catalog_.complete_manual_edit_run(service, *run_id,
                                                      {version.id.str()});
                } catch (const std::exception&) {
                }
            }
            refresh_();
            set_status_("已提交新版本: " + version.id.str() + " (v" +
                        std::to_string(version.version_number) + ", " +
                        stage_value(version.stage) + ")");
        },
        [this, service, run_id](const std::string& message) {
            fail_booked_run_(service, run_id);
            set_status_("提交新版本失败: " + message);
        });
}

void DataLifecycleCore::promote_asset(const AssetHandle& item) {
    const auto target = catalog_row_target(item);
    if (!target) {
        set_status_("提升为正式数据需要活动数据目录（数据未桥接）");
        return;
    }
    const std::string version_id = target->version_id;
    const std::string name = target->name;
    if (!dialogs_.promote) return;
    const auto choice = dialogs_.promote(name);
    if (!choice) return;
    auto* service = catalog_service();
    run_catalog_action(
        "提升为正式数据",
        [service, version_id, choice]() -> std::any {
            return service->promote_version(version_id, choice->stage,
                                            choice->reviewed_by,
                                            choice->note);
        },
        [this](const std::any& result) {
            const auto& version = std::any_cast<catalog::DataVersion>(result);
            refresh_();
            set_status_("已提升为正式数据: " + version.id.str() + " (v" +
                        std::to_string(version.version_number) + ")");
        });
}

// ---------------------------------------------------------------------------
// Delivery
// ---------------------------------------------------------------------------

std::optional<DataLifecycleCore::DeliveryPrepared>
DataLifecycleCore::prepare_delivery(const AssetHandle& item) {
    const auto& data = unwrap_asset(item);
    auto [service, ref] = std::get_if<ResourceItem>(&data) != nullptr
                              ? catalog_bridge(item)
                              : std::pair<CatalogServiceApi*,
                                          std::optional<
                                              catalog::DataVersionRef>>{
                                    nullptr, std::nullopt};
    std::optional<std::filesystem::path> source_path;
    if (const auto* resource = std::get_if<ResourceItem>(&data)) {
        if (page_.resolve_resource_path) {
            source_path = page_.resolve_resource_path(*resource);
        }
        if (service != nullptr && ref) {
            // Prefer the immutable managed snapshot the catalog version
            // references (#835); fall back to the legacy path only when
            // the managed payload is unavailable.
            try {
                const auto managed = service->resolve_path(
                    service->get_version(ref->version_id));
                if (std::filesystem::is_regular_file(managed))
                    source_path = managed;
            } catch (const std::exception&) {
            }
        }
        if ((!source_path ||
             !std::filesystem::is_regular_file(*source_path)) &&
            service != nullptr && ref) {
            try {
                source_path = service->resolve_path(
                    service->get_version(ref->version_id));
            } catch (const std::exception&) {
                source_path = std::nullopt;
            }
        }
    } else if (const auto* artifact = std::get_if<ExportArtifact>(&data)) {
        // record_export stores project-RELATIVE output paths; resolve
        // against the project dir (never CWD — review finding I1).
        fs::path rel(artifact->output_path);
        if (!rel.is_absolute()) {
            const auto project_file = page_.project_file_for_io
                                          ? page_.project_file_for_io()
                                          : std::nullopt;
            if (project_file) {
                auto resolved = project::resolve_project_path(
                    artifact->output_path, *project_file);
                source_path = resolved.is_ok() ? fs::path(resolved.value())
                                               : rel;
            } else {
                source_path = rel;
            }
        } else {
            source_path = rel;
        }
        if ((!source_path ||
             !std::filesystem::is_regular_file(*source_path)) &&
            service != nullptr && ref) {
            try {
                source_path = service->resolve_path(
                    service->get_version(ref->version_id));
            } catch (const std::exception&) {
                source_path = std::nullopt;
            }
        }
    } else {
        // Catalog-only row: resolve the current version's managed payload.
        service = catalog_service();
        const auto* asset =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&data);
        if (service != nullptr && asset != nullptr && *asset != nullptr &&
            (*asset)->current_version_id) {
            try {
                const auto version =
                    service->get_version((*asset)->current_version_id->str());
                source_path = service->resolve_path(version);
                catalog::DataVersionRef resolved_ref;
                resolved_ref.asset_id = (*asset)->id.str();
                resolved_ref.version_id = version.id.str();
                ref = resolved_ref;
            } catch (const std::exception&) {
                source_path = std::nullopt;
            }
        }
    }
    if (!source_path || !std::filesystem::is_regular_file(*source_path)) {
        set_status_("导出 / 交付失败: 源文件不存在");
        return std::nullopt;
    }
    if (!dialogs_.delivery) return std::nullopt;
    const auto project_file =
        page_.project_file_for_io ? page_.project_file_for_io()
                                  : std::nullopt;
    const fs::path suggested =
        services_.default_export_dir
            ? services_.default_export_dir(project_file) /
                  source_path->filename()
            : source_path->filename();
    const std::string asset_name = resource_row_name_(item);
    const auto destination = dialogs_.delivery(
        asset_name.empty() ? source_path->filename().string() : asset_name,
        suggested.generic_string());
    if (!destination) return std::nullopt;
    if (destination->empty()) {
        set_status_("导出 / 交付已取消");
        return std::nullopt;
    }
    DeliveryPrepared prepared;
    prepared.source_path = *source_path;
    prepared.destination = *destination;
    prepared.service = service;
    prepared.ref = ref;
    return prepared;
}

std::string DataLifecycleCore::run_delivery_copy(
    const std::filesystem::path& source,
    const std::filesystem::path& destination) const {
    std::error_code ec;
    std::filesystem::create_directories(destination.parent_path(), ec);
    // copyfile (not copy2): managed payloads carry the owner write bit
    // cleared as an in-repo accident guard — that guard is not a delivery
    // attribute; restore a writable mode explicitly (#835).
    std::filesystem::copy_file(
        source, destination, std::filesystem::copy_options::overwrite_existing,
        ec);
    if (ec) {
        throw std::runtime_error("copy failed: " + ec.message());
    }
    std::filesystem::permissions(
        destination,
        std::filesystem::perms::owner_read |
            std::filesystem::perms::owner_write |
            std::filesystem::perms::group_read |
            std::filesystem::perms::others_read,
        std::filesystem::perm_options::replace, ec);
    auto hash = catalog::sha256_file_or_none(destination);
    if (!hash) {
        throw std::runtime_error("delivery checksum failed");
    }
    return *hash;
}

void DataLifecycleCore::finish_delivery(
    const AssetHandle& item, const DeliveryPrepared& prepared,
    const std::string& checksum) {
    bool recorded = false;
    try {
        if (prepared.service != nullptr && prepared.ref) {
            domain::Json params = domain::Json::object();
            params["source_version_id"] = prepared.ref->version_id;
            params["exported_path"] = prepared.destination.generic_string();
            params["checksum"] = checksum;
            params["timestamp"] = domain::now_iso8601();
            params["format"] = prepared.source_path.extension().string();
            if (!params["format"].get<std::string>().empty() &&
                params["format"].get<std::string>().front() == '.') {
                params["format"] =
                    params["format"].get<std::string>().substr(1);
            }
            params["delivery_status"] = "exported";
            prepared.service->register_run(
                "delivery", {prepared.ref->version_id}, params);
            recorded = true;
        } else {
            const auto& data = unwrap_asset(item);
            if (const auto* artifact = std::get_if<ExportArtifact>(&data);
                artifact != nullptr && artifact->catalog_version_id) {
                auto* service = catalog_service();
                if (service != nullptr &&
                    version_exists_(service, *artifact->catalog_version_id)) {
                    domain::Json params = domain::Json::object();
                    params["source_version_id"] =
                        *artifact->catalog_version_id;
                    params["exported_path"] =
                        prepared.destination.generic_string();
                    params["checksum"] = checksum;
                    params["timestamp"] = domain::now_iso8601();
                    params["format"] =
                        prepared.source_path.extension().string();
                    params["delivery_status"] = "exported";
                    service->register_run(
                        "delivery", {*artifact->catalog_version_id}, params);
                    recorded = true;
                }
            }
        }
    } catch (const std::exception&) {
        recorded = false;
    }
    set_status_("已导出 / 交付: " +
                prepared.destination.filename().string() + " (" +
                (recorded ? "已记录交付元数据" : "未记录交付元数据") + ")");
}

void DataLifecycleCore::deliver_asset(const AssetHandle& item) {
    const auto prepared = prepare_delivery(item);
    if (!prepared) return;
    std::string checksum;
    try {
        checksum = run_delivery_copy(prepared->source_path,
                                     prepared->destination);
    } catch (const std::exception& exc) {
        set_status_(std::string("导出 / 交付失败: ") + exc.what());
        return;
    }
    finish_delivery(item, *prepared, checksum);
}

// ---------------------------------------------------------------------------
// Tags
// ---------------------------------------------------------------------------

void DataLifecycleCore::mirror_tag_to_catalog(
    const AssetHandle& item, const std::string& tag_name, bool add) {
    const auto [service, ref] = catalog_bridge(item);
    if (service == nullptr || !ref) return;
    try {
        if (add) {
            service->add_tag(tag_name, ref->asset_id, std::nullopt);
        } else {
            service->remove_tag(tag_name, ref->asset_id, std::nullopt);
        }
    } catch (const std::exception&) {
    }
}

void DataLifecycleCore::handle_tag_added(const AssetHandle& item,
                                         const std::string& tag_name) {
    const auto& data = unwrap_asset(item);
    if (const auto* asset =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&data)) {
        auto* service = catalog_service();
        if (service != nullptr) {
            try {
                service->add_tag(tag_name, (*asset)->id.str(), std::nullopt);
                refresh_();
                set_status_("已添加标签 #" + tag_name);
            } catch (const std::exception& exc) {
                set_status_(std::string("添加标签失败: ") + exc.what());
            }
        }
        return;
    }
    if (const auto* resource = std::get_if<ResourceItem>(&data)) {
        const int index = resource_row_index_(resource->id);
        auto* row = resource_row_(index);
        if (row == nullptr) return;
        const auto tags = row_tags_(*row);
        if (std::find(tags.begin(), tags.end(), tag_name) == tags.end()) {
            row_add_tag_(*row, tag_name);
            mirror_tag_to_catalog(item, tag_name, true);
            refresh_();
            set_status_("已添加标签 #" + tag_name);
        }
    }
}

void DataLifecycleCore::handle_tag_removed(
    const AssetHandle& item, const std::string& tag_name) {
    const auto& data = unwrap_asset(item);
    if (const auto* asset =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&data)) {
        auto* service = catalog_service();
        if (service != nullptr) {
            try {
                service->remove_tag(tag_name, (*asset)->id.str(), std::nullopt);
                refresh_();
                set_status_("已移除标签 #" + tag_name);
            } catch (const std::exception& exc) {
                set_status_(std::string("移除标签失败: ") + exc.what());
            }
        }
        return;
    }
    if (const auto* resource = std::get_if<ResourceItem>(&data)) {
        const int index = resource_row_index_(resource->id);
        auto* row = resource_row_(index);
        if (row == nullptr) return;
        const auto tags = row_tags_(*row);
        if (std::find(tags.begin(), tags.end(), tag_name) != tags.end()) {
            row_remove_tag_(*row, tag_name);
            mirror_tag_to_catalog(item, tag_name, false);
            refresh_();
            set_status_("已移除标签 #" + tag_name);
        }
    }
}

bool DataLifecycleCore::version_exists_(
    CatalogServiceApi* service, const std::string& version_id) const {
    try {
        service->get_version(version_id);
        return true;
    } catch (const std::exception&) {
        return false;
    }
}

void DataLifecycleCore::fail_booked_run_(
    CatalogServiceApi* service,
    const std::optional<std::string>& run_id) const {
    if (service == nullptr || !run_id) return;
    try {
        service->update_run_status(*run_id, "failed");
    } catch (const std::exception&) {
    }
}

int DataLifecycleCore::bulk_apply_tag(
    const std::vector<AssetHandle>& items, const std::string& tag_name,
    bool add) {
    std::vector<const ResourceItem*> resources;
    std::vector<int> resource_indexes;
    std::vector<std::string> asset_ids;
    for (const auto& item : items) {
        const auto& data = unwrap_asset(item);
        if (const auto* resource = std::get_if<ResourceItem>(&data)) {
            resources.push_back(resource);
            resource_indexes.push_back(
                resource_row_index_(resource->id));
        } else if (const auto* ref =
                       std::get_if<SqlCatalogAssetRef>(&data)) {
            asset_ids.push_back(ref->id);
        }
    }
    // Catalog mirror first (best-effort, ONE canonical write) — collect
    // the bridged asset ids exactly like mirror_tag_to_catalog.
    last_tag_mirror_failed = false;
    auto* service = catalog_service();
    if (service != nullptr) {
        for (const auto& item : items) {
            const auto& data = unwrap_asset(item);
            if (std::get_if<ResourceItem>(&data) == nullptr) continue;
            const auto [svc, ref] = catalog_bridge(item);
            if (ref) asset_ids.push_back(ref->asset_id);
        }
    }
    if (!asset_ids.empty() && service != nullptr) {
        try {
            if (add) {
                service->bulk_add_tag(tag_name, asset_ids);
            } else {
                service->bulk_remove_tag(tag_name, asset_ids);
            }
        } catch (const std::exception&) {
            // A catalog failure never breaks the legacy tag action — but
            // it must stay VISIBLE (the status flag parity).
            last_tag_mirror_failed = true;
        }
    }
    int count = 0;
    for (std::size_t i = 0; i < resources.size(); ++i) {
        const int index = resource_indexes[i];
        auto* row = resource_row_(index);
        if (row == nullptr) continue;
        const auto tags = row_tags_(*row);
        const bool present =
            std::find(tags.begin(), tags.end(), tag_name) != tags.end();
        if (add && !present) {
            row_add_tag_(*row, tag_name);
            ++count;
        } else if (!add && present) {
            row_remove_tag_(*row, tag_name);
            ++count;
        }
    }
    if (resources.empty()) count = static_cast<int>(asset_ids.size());
    return count;
}

bool DataLifecycleCore::set_version_tag(const std::string& version_id,
                                        const std::string& tag_name,
                                        bool add) {
    auto* service = catalog_service();
    if (service == nullptr) return false;
    try {
        if (add) {
            service->add_tag(tag_name, std::nullopt, version_id);
        } else {
            service->remove_tag(tag_name, std::nullopt, version_id);
        }
        return true;
    } catch (const std::exception&) {
        return false;
    }
}

void DataLifecycleCore::prompt_add_tag_to_assets(
    const std::vector<AssetHandle>& items) {
    if (!dialogs_.tag_input) return;
    const auto tag = dialogs_.tag_input("添加标签", "请输入标签名称:");
    if (!tag || tag->empty()) return;
    const int count = bulk_apply_tag(items, *tag, true);
    if (count > 0) {
        refresh_();
        set_status_("已为 " + std::to_string(count) + " 项数据添加标签 #" +
                    *tag);
    }
}

void DataLifecycleCore::prompt_remove_tag_from_assets(
    const std::vector<AssetHandle>& items) {
    std::set<std::string> all_tags;
    for (const auto& item : items) {
        const auto& data = unwrap_asset(item);
        if (const auto* resource = std::get_if<ResourceItem>(&data)) {
            const auto tags = row_tags_(
                resource_row_(resource_row_index_(resource->id))
                    ? *resource_row_(resource_row_index_(resource->id))
                    : domain::Json::object());
            all_tags.insert(tags.begin(), tags.end());
        }
    }
    if (all_tags.empty()) {
        set_status_("选中数据无可用标签");
        return;
    }
    if (!dialogs_.tag_input) return;
    const auto tag = dialogs_.tag_input("批量移除标签",
                                        "请输入要移除的标签名称:");
    if (!tag || tag->empty()) return;
    const int count = bulk_apply_tag(items, *tag, false);
    if (count > 0) {
        refresh_();
        set_status_("已从 " + std::to_string(count) + " 项数据移除标签 #" +
                    *tag);
    }
}

// ---------------------------------------------------------------------------
// Integrity verification
// ---------------------------------------------------------------------------

std::pair<CatalogServiceApi*, std::map<std::string, std::string>>
DataLifecycleCore::bridged_version_map(
    const std::vector<AssetHandle>& items) const {
    auto* service = catalog_service();
    if (service == nullptr) return {nullptr, {}};
    std::map<std::string, std::string> bridged;
    for (const auto& item : items) {
        const auto& data = unwrap_asset(item);
        if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&data)) {
            if (!ref->current_version_id.empty())
                bridged[ref->id] = ref->current_version_id;
            continue;
        }
        const auto [svc, version_ref] = catalog_bridge(item);
        if (version_ref &&
            std::get_if<ResourceItem>(&data) != nullptr) {
            bridged[std::get_if<ResourceItem>(&data)->id] =
                version_ref->version_id;
        }
    }
    if (bridged.empty()) return {nullptr, {}};
    return {service, bridged};
}

void DataLifecycleCore::verify_assets(
    const std::vector<AssetHandle>& items) {
    if (items.empty()) {
        set_status_("没有可校验的数据资产");
        return;
    }
    if (verify_job_ != nullptr && verify_job_->is_running()) {
        verify_job_->cancel();
        set_status_("正在取消校验...");
        return;
    }
    const auto [service, bridged] = bridged_version_map(items);
    // View conversion through the real adapter (IntegrityWorker's items
    // read the same fields asset_view_from_object produces).
    ui_workers::IntegrityInput input;
    for (const auto& item : items) {
        ui_workers::IntegrityAssetSlice slice;
        const auto& data = unwrap_asset(item);
        try {
            const auto view = ui_data_core::asset_view_from_object(
                unwrap_handle(item));
            slice.id = view.id;
            slice.name = view.name;
            slice.path = view.path;
            slice.managed = view.managed;
            slice.checksum = view.checksum;
        } catch (const std::exception&) {
            if (const auto* resource = std::get_if<ResourceItem>(&data)) {
                slice.id = resource->id;
                slice.name = resource->name;
                slice.path = resource->path;
                slice.checksum = resource->checksum;
                slice.managed = !resource->external;
            }
        }
        (void)data;
        if (slice.id.empty()) continue;
        input.assets.push_back(std::move(slice));
    }
    const auto root_dir =
        page_.preview_disk_project_root ? page_.preview_disk_project_root()
                                        : std::nullopt;
    input.project_root = root_dir ? root_dir->generic_string() : "";
    input.bridged_versions = bridged;
    if (service != nullptr) {
        input.verify_fn = [service](const std::string& version_id) {
            return service->verify_integrity(version_id);
        };
    }
    // Operation-registry booking (D4): the shell's registry when bound,
    // none otherwise (test/offline).
    std::string op_id;
    if (operations_ != nullptr) {
        op_id = "verify:" + std::to_string(
                                std::chrono::steady_clock::now()
                                    .time_since_epoch()
                                    .count());
        operations_->begin(op_id, "完整性校验",
                           std::to_string(items.size()) + " 项资产",
                           /*cancellable=*/true,
                           static_cast<int>(items.size()));
        operations_->update(op_id, std::nullopt, std::nullopt, "SHA-256");
        operations_->set_cancel(op_id, [this] {
            if (verify_job_ != nullptr) verify_job_->cancel();
        });
    }
    // The report is consumed on the OWNER thread inside on_finished —
    // spec callbacks are worker-side (job_contract: they run before the
    // terminal state lands, off the GUI thread). A cancelled run lands
    // JobState::cancelled WITH the partial report in outcome.result.
    auto spec = ui_workers::make_integrity_job_spec(std::move(input));
    const auto finish = [this, op_id](const UiJobOutcome& outcome) {
        if (operations_ != nullptr) {
            if (outcome.state == job::JobState::failed) {
                operations_->finish(op_id, ui_shell::OperationState::Failed,
                                    outcome.error);
            } else if (const auto* report =
                           outcome.try_result<
                               ui_workers::IntegrityCheckReport>()) {
                if (outcome.state == job::JobState::cancelled) {
                    operations_->finish(op_id,
                                        ui_shell::OperationState::Cancelled,
                                        std::nullopt,
                                        report->summary_text());
                } else if (report->missing_count > 0 ||
                           report->modified_count > 0 ||
                           report->unknown_count > 0) {
                    operations_->finish(op_id, ui_shell::OperationState::Warning,
                                        std::nullopt, report->summary_text());
                } else {
                    operations_->finish(op_id,
                                        ui_shell::OperationState::Completed,
                                        std::nullopt,
                                        report->summary_text());
                }
            } else {
                operations_->finish(op_id, ui_shell::OperationState::Cancelled);
            }
        }
        if (page_.set_verify_running) page_.set_verify_running(false);
    };
    if (verify_job_ == nullptr) {
        // No worker wired: run synchronously (InlineJobRunner delivers the
        // outcome in-line — the same contract, one thread).
        InlineJobRunner inline_runner;
        inline_runner.start(std::move(spec), finish);
        return;
    }
    verify_job_->start(
        std::move(spec), finish,
        [this, op_id](double /*ratio*/, const std::string& message) {
            if (operations_ != nullptr) {
                operations_->update(
                    op_id, std::nullopt, std::nullopt,
                    message.empty() ? std::optional<std::string>("SHA-256")
                                    : "SHA-256 · " + message);
            }
        });
    if (page_.set_verify_running) page_.set_verify_running(true);
    set_status_("正在后台校验 " + std::to_string(items.size()) +
                " 项数据资产完整性...");
}

// ---------------------------------------------------------------------------
// Trashed companions + registration
// ---------------------------------------------------------------------------

std::vector<ResourceItem> DataLifecycleCore::trashed_companions() {
    auto* service = catalog_service();
    if (service == nullptr) return {};
    std::vector<catalog::DataAsset> assets;
    try {
        assets = service->get_trashed_assets();
    } catch (const std::exception&) {
        return {};
    }
    std::vector<ResourceItem> companions;
    for (const auto& asset : assets) {
        auto item = resource_from_catalog_asset(*service, asset,
                                                /*trashed=*/true);
        if (item) companions.push_back(std::move(*item));
    }
    return companions;
}

std::optional<ResourceItem> DataLifecycleCore::resource_from_catalog_asset(
    CatalogServiceApi& service, const catalog::DataAsset& asset,
    bool trashed) const {
    try {
        std::optional<catalog::DataVersion> version;
        if (asset.current_version_id) {
            version = service.get_version(asset.current_version_id->str());
        }
        std::optional<std::filesystem::path> payload;
        if (version) payload = service.resolve_path(*version);
        std::string stored_path = asset.id.str();
        if (payload) {
            stored_path = project::relativize_path(
                *payload, service.project_path())
                              .stored;
        }
        domain::Json summary =
            asset.metadata.is_object() ? asset.metadata
                                       : domain::Json::object();
        if (trashed) summary["catalog_trashed"] = true;
        summary["catalog_asset_id"] = asset.id.str();
        if (version) summary["catalog_version_id"] = version->id.str();
        std::vector<std::string> tags;
        const auto meta_it = asset.metadata.find("legacy_tags");
        if (meta_it != asset.metadata.end() && meta_it->is_array()) {
            for (const auto& tag : *meta_it)
                if (tag.is_string()) tags.push_back(tag.get<std::string>());
        }
        if (tags.empty()) {
            try {
                // document.asset_tags parity: (asset_id, tag_id) pairs →
                // display_name/name of the tag rows.
                std::map<std::string, const catalog::Tag*> by_id;
                for (const auto& tag : service.document().tags)
                    by_id.emplace(tag.id, &tag);
                for (const auto& [asset_id, tag_id] :
                     service.document().asset_tags) {
                    if (asset_id != asset.id.str()) continue;
                    const auto it = by_id.find(tag_id);
                    if (it != by_id.end()) {
                        tags.push_back(it->second->display_name
                                           ? *it->second->display_name
                                           : it->second->name);
                    }
                }
            } catch (const std::exception&) {
                tags.clear();
            }
        }
        ResourceItem item;
        item.id = asset.legacy_resource_id ? *asset.legacy_resource_id
                                           : asset.id.str();
        item.name = asset.name;
        item.path = stored_path;
        item.type = asset.type;
        item.format = version ? version->format : "";
        item.checksum = version ? version->sha256 : std::nullopt;
        item.external = version ? !version->managed : false;
        const auto role_it = asset.metadata.find("artifact_role");
        item.artifact_role =
            (role_it != asset.metadata.end() && role_it->is_string())
                ? std::optional<std::string>(role_it->get<std::string>())
                : (version && version->stage == domain::DataStage::Output
                       ? std::optional<std::string>("output")
                       : std::optional<std::string>("input"));
        item.tags = std::move(tags);
        const bool exists =
            payload && std::filesystem::is_regular_file(*payload);
        item.status = exists ? "indexed" : "missing";
        const auto src_it = asset.metadata.find("source");
        item.source = (src_it != asset.metadata.end() && src_it->is_string())
                          ? src_it->get<std::string>()
                          : "catalog";
        item.parsed_summary = std::move(summary);
        return item;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

RegistrationReceipt DataLifecycleCore::register_imported_resources(
    const std::vector<ResourceItem>& resources,
    std::function<void(int, int)> progress,
    std::function<bool()> cancel_check) {
    last_registration_failures.clear();
    RegistrationReceipt registered;
    if (!catalog_.register_resource_input) {
        last_registration_failures.push_back(
            "catalog lifecycle unavailable");
        return registered;
    }
    const int total = static_cast<int>(resources.size());
    for (int start = 0; start < total; start += kRegistrationChunk) {
        if (cancel_check && cancel_check()) break;
        RegistrationReceipt chunk_ids;
        // One canonical transaction per chunk (batch_save parity); a
        // missing batch falls back to per-file writes honestly.
        std::unique_ptr<RegistrationBatch> batch;
        if (catalog_.enter_batch) {
            try {
                batch = catalog_.enter_batch();
            } catch (const std::exception&) {
                batch = nullptr;
            }
        }
        bool committed = true;
        const int end =
            std::min(total, start + kRegistrationChunk);
        for (int i = start; i < end; ++i) {
            if (cancel_check && cancel_check()) break;
            const auto& resource = resources[i];
            try {
                const auto ref = catalog_.register_resource_input(
                    resource_item_to_json(resource));
                if (ref) chunk_ids[resource.id] = ref->asset_id;
            } catch (const std::exception& exc) {
                last_registration_failures.push_back(
                    resource.name + " (" + resource.id + "): " +
                    exc.what());
            }
        }
        if (batch != nullptr) {
            try {
                committed = batch->finish();
            } catch (const std::exception& exc) {
                committed = false;
                last_registration_failures.push_back(
                    std::string("批提交失败: ") + exc.what());
            }
        }
        // Only THIS chunk's registrations are lost on a failed commit —
        // earlier committed chunks stay in the receipt.
        if (committed) {
            registered.merge(chunk_ids);
            for (const auto& [id, asset] : chunk_ids)
                registered[id] = asset;
        }
        if (progress) {
            try {
                // The ACTUAL registered count — a cancel inside the chunk
                // commits a partial batch; progress must never claim
                // skipped resources.
                progress(static_cast<int>(registered.size()), total);
            } catch (const std::exception&) {
            }
        }
    }
    return registered;
}

}  // namespace pwb::ui_controllers
