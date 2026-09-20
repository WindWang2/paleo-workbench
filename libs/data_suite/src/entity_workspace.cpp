// Entity workspace read model — see entity_workspace.hpp. Every branch
// mirrors paleo_workbench/catalog/entity_views.py; deviations (the
// Qt-free rollups, related-run ids) are V14 additions recorded in
// docs/development/v14-data-lineage/03-contracts.md.
#include "pwb/data/entity_workspace.hpp"

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/impact.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/queries_sql.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/catalog/sqlite.hpp"
#include "pwb/data/role_registry.hpp"

#include <algorithm>
#include <chrono>
#include <system_error>

namespace pwb::data {

using domain::Json;

namespace {

// entity_views._slots_for_entity sort keys.
bool member_before(const AssetSummary& left, const AssetSummary& right) {
    if (left.is_primary != right.is_primary) return left.is_primary;
    if (left.ordinal != right.ordinal) return left.ordinal < right.ordinal;
    return left.name < right.name;
}

const Json* find_array(const Json& root, const char* key) {
    auto it = root.find(key);
    if (it == root.end() || !it->is_array()) return nullptr;
    return &*it;
}

std::string json_string(const Json& node, const char* key,
                        const char* default_value = "") {
    return node.value(key, std::string(default_value));
}

}  // namespace

// ---- EntityWorkspaceService -------------------------------------------------

EntityWorkspaceService::EntityWorkspaceService(const Json& project_root,
                                               WorkspaceCatalogSource* catalog)
    : project_root_(project_root), catalog_(catalog) {}

EntityWorkspaceService::EntityNode EntityWorkspaceService::find_entity(
    const char* section, const std::string& id) const {
    EntityNode node;
    const Json* entities = find_array(project_root_, section);
    if (entities == nullptr) return node;
    for (const auto& entity : *entities) {
        if (!entity.is_object()) continue;
        if (json_string(entity, "id") == id) {
            node.id = id;
            node.name = json_string(entity, "name");
            node.uwi = json_string(entity, "uwi");
            node.found = true;
            return node;
        }
    }
    return node;
}

std::vector<EntityIndexEntry> EntityWorkspaceService::well_index(
    bool with_stale) const {
    std::vector<EntityIndexEntry> entries;
    const Json* wells = find_array(project_root_, "wells");
    const Json* links = find_array(project_root_, "entity_asset_links");

    std::map<std::string, std::map<std::string, int>> per_well;
    std::map<std::string, int> unresolved;
    if (wells != nullptr) {
        for (const auto& well : *wells) {
            if (!well.is_object()) continue;
            const std::string id = json_string(well, "id");
            if (id.empty()) continue;
            per_well.emplace(id, std::map<std::string, int>());
            unresolved.emplace(id, 0);
        }
    }
    // asset → wells owning it (stale attribution pass).
    std::map<std::string, std::vector<std::string>> asset_to_wells;
    if (links != nullptr) {
        for (const auto& link : *links) {
            if (!link.is_object()) continue;
            if (json_string(link, "entity_type") != "well") continue;
            const std::string entity_id = json_string(link, "entity_id");
            if (per_well.find(entity_id) == per_well.end()) continue;
            const std::string role = json_string(link, "role");
            ++per_well[entity_id][role];
            if (link.value("unresolved", false)) ++unresolved[entity_id];
            asset_to_wells[json_string(link, "asset_id")].push_back(
                entity_id);
        }
    }

    // with_stale: attribute stale items onto wells through the nearest
    // changed ancestor's asset links (entity_views.well_index parity).
    std::map<std::string, int> stale_per_well;
    if (with_stale && catalog_ != nullptr && links != nullptr) {
        std::map<std::string, int> stale_by_asset;
        const std::vector<StaleLite> items = catalog_->downstream_stale_all();
        for (const auto& item : items) {
            const std::string& asset = item.nearest_changed_ancestor_asset_id
                                           .empty()
                                           ? item.asset_id
                                           : item.nearest_changed_ancestor_asset_id;
            ++stale_by_asset[asset];
        }
        for (const auto& [asset, count] : stale_by_asset) {
            for (const auto& well_id : asset_to_wells[asset]) {
                stale_per_well[well_id] += count;
            }
        }
    }

    if (wells == nullptr) return entries;
    entries.reserve(wells->size());
    for (const auto& well : *wells) {
        if (!well.is_object()) continue;
        const std::string id = json_string(well, "id");
        if (id.empty()) continue;
        EntityIndexEntry entry;
        entry.entity_id = id;
        entry.name = json_string(well, "name");
        entry.uwi = json_string(well, "uwi");
        auto fill = per_well.find(id);
        if (fill != per_well.end()) entry.role_fill = fill->second;
        entry.unresolved_count = unresolved.count(id) != 0
                                     ? unresolved.at(id)
                                     : 0;
        entry.stale_count =
            stale_per_well.count(id) != 0 ? stale_per_well.at(id) : 0;
        entries.push_back(std::move(entry));
    }
    return entries;
}

std::vector<EntityIndexEntry> EntityWorkspaceService::survey_index() const {
    std::vector<EntityIndexEntry> entries;
    const Json* surveys = find_array(project_root_, "seismic_surveys");
    const Json* links = find_array(project_root_, "entity_asset_links");

    std::map<std::string, std::map<std::string, int>> per_survey;
    if (surveys != nullptr) {
        for (const auto& survey : *surveys) {
            if (!survey.is_object()) continue;
            const std::string id = json_string(survey, "id");
            if (id.empty()) continue;
            per_survey.emplace(id, std::map<std::string, int>());
        }
    }
    if (links != nullptr) {
        for (const auto& link : *links) {
            if (!link.is_object()) continue;
            if (json_string(link, "entity_type") != "seismic_survey") {
                continue;
            }
            const std::string entity_id = json_string(link, "entity_id");
            if (per_survey.find(entity_id) == per_survey.end()) continue;
            ++per_survey[entity_id][json_string(link, "role")];
        }
    }

    if (surveys == nullptr) return entries;
    entries.reserve(surveys->size());
    for (const auto& survey : *surveys) {
        if (!survey.is_object()) continue;
        const std::string id = json_string(survey, "id");
        if (id.empty()) continue;
        EntityIndexEntry entry;
        entry.entity_id = id;
        entry.name = json_string(survey, "name");
        auto fill = per_survey.find(id);
        if (fill != per_survey.end()) entry.role_fill = fill->second;
        entries.push_back(std::move(entry));
    }
    return entries;
}

std::vector<RoleSlot> EntityWorkspaceService::slots_for_entity(
    const std::string& entity_type, const std::string& entity_id) const {
    // Registry vocabulary first (grouping order); unknown roles land in a
    // synthetic slot instead of being dropped silently.
    std::vector<RoleSlot> slots;
    std::map<std::string, std::size_t> slot_by_role;
    for (auto role : roles_for_entity_type(entity_type)) {
        RoleSlot slot;
        slot.role = std::string(role);
        slot.display = role_display(slot.role, entity_type);
        slot_by_role.emplace(slot.role, slots.size());
        slots.push_back(std::move(slot));
    }

    const std::vector<EntityLinkView> links =
        links_for_entity(project_root_, entity_type, entity_id);

    // Batched point lookups — never list_assets().
    std::vector<std::string> asset_ids;
    std::set<std::string> seen_ids;
    for (const auto& link : links) {
        if (seen_ids.insert(link.asset_id).second) {
            asset_ids.push_back(link.asset_id);
        }
    }
    std::map<std::string, AssetCatalogSummary> models;
    if (catalog_ != nullptr && !asset_ids.empty()) {
        models = catalog_->resolve_assets(asset_ids);
    }

    for (const auto& link : links) {
        auto slot_it = slot_by_role.find(link.role);
        if (slot_it == slot_by_role.end()) {
            RoleSlot slot;
            slot.role = link.role;
            slot.display = role_display(link.role, entity_type);
            slot_it = slot_by_role.emplace(link.role, slots.size()).first;
            slots.push_back(std::move(slot));
        }
        RoleSlot& slot = slots[slot_it->second];

        AssetSummary summary;
        summary.asset_id = link.asset_id;
        summary.role = link.role;
        summary.is_primary = link.is_primary;
        summary.ordinal = link.ordinal;
        auto model = models.find(link.asset_id);
        if (model == models.end()) {
            // Linked asset unknown to catalog — surface honestly.
            summary.name = "<未注册资产 " + link.asset_id + ">";
            summary.type = "unknown";
            summary.unresolved = true;
        } else {
            summary.name = model->second.name;
            summary.type = model->second.type;
            summary.unresolved = link.unresolved;
            summary.current_version_id = model->second.current_version_id;
            summary.version_count = model->second.version_count;
            summary.trashed = model->second.trashed;
            summary.stage = model->second.stage;
            summary.format = model->second.format;
            summary.bundle = model->second.bundle;
        }
        if (link.unresolved) {
            slot.unresolved.push_back(std::move(summary));
        } else {
            slot.members.push_back(std::move(summary));
        }
    }
    for (auto& slot : slots) {
        std::sort(slot.members.begin(), slot.members.end(), member_before);
        std::sort(slot.unresolved.begin(), slot.unresolved.end(),
                  [](const AssetSummary& l, const AssetSummary& r) {
                      return l.name < r.name;
                  });
    }
    return slots;
}

std::optional<EntityDataView> EntityWorkspaceService::entity_view(
    const char* section, const std::string& entity_type,
    const std::string& entity_id, bool with_stale) const {
    const EntityNode node = find_entity(section, entity_id);
    if (!node.found) return std::nullopt;

    EntityDataView view;
    view.entity_type = entity_type;
    view.entity_id = entity_id;
    view.name = node.name;
    view.uwi = node.uwi;
    view.role_slots = slots_for_entity(entity_type, entity_id);

    std::vector<std::string> member_asset_ids;
    for (const auto& slot : view.role_slots) {
        for (const auto& member : slot.members) {
            member_asset_ids.push_back(member.asset_id);
            if (member.stage == "intermediate") ++view.intermediate_count;
            else if (member.stage == "derived") ++view.derived_count;
            else if (member.stage == "output") ++view.output_count;
        }
    }

    if (catalog_ != nullptr) {
        // Bounded first-rung probe over the view's own member assets only
        // (F7 — the full find_missing_sources scan is O(all versions) and
        // must not run per expansion).
        view.missing_source_asset_ids =
            catalog_->probe_missing_sources(member_asset_ids);

        // Uncommitted edits on the entity's asset versions.
        std::set<std::string> entity_assets(member_asset_ids.begin(),
                                            member_asset_ids.end());
        for (const auto& copy : catalog_->list_working_copies()) {
            if (entity_assets.count(copy.asset_id) != 0) {
                view.uncommitted_edits.push_back(copy);
            }
        }

        view.related_run_ids = catalog_->related_runs(member_asset_ids);

        if (with_stale) {
            const std::vector<EntityLinkView> links = links_for_entity(
                project_root_, entity_type, entity_id);
            view.stale_items = catalog_->entity_staleness(links);
        }
    }
    return view;
}

std::optional<EntityDataView> EntityWorkspaceService::well_view(
    const std::string& well_id, bool with_stale) const {
    return entity_view("wells", "well", well_id, with_stale);
}

std::optional<EntityDataView> EntityWorkspaceService::survey_view(
    const std::string& survey_id) const {
    return entity_view("seismic_surveys", "seismic_survey", survey_id,
                       false);
}

// ---- RepositoryWorkspaceSource ----------------------------------------------

RepositoryWorkspaceSource::RepositoryWorkspaceSource(
    std::filesystem::path sqlite_path, std::filesystem::path project_dir)
    : sqlite_path_(std::move(sqlite_path)),
      project_dir_(std::move(project_dir)) {}

namespace {

// Opens the store read-only for the duration of one call (missing store /
// missing tables degrade to "empty" — queries_sql never throws).
catalog::Database open_read_only(const std::filesystem::path& path) {
    auto opened = catalog::Database::open(path,
                                          catalog::SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) return catalog::Database{};
    return std::move(opened.value());
}

}  // namespace

std::map<std::string, AssetCatalogSummary>
RepositoryWorkspaceSource::resolve_assets(
    const std::vector<std::string>& asset_ids) {
    std::map<std::string, AssetCatalogSummary> result;
    if (asset_ids.empty() || sqlite_path_.empty()) return result;
    catalog::Database db = open_read_only(sqlite_path_);
    if (!db.is_open()) return result;

    const std::vector<std::pair<std::string, catalog::DataAsset>> models =
        catalog::get_asset_models(db, asset_ids);
    const catalog::AssetVersionRollupMap rollups =
        catalog::asset_version_rollups_sql(db, asset_ids);

    for (const auto& [id, asset] : models) {
        AssetCatalogSummary summary;
        summary.name = asset.name;
        summary.type = asset.type;
        if (asset.current_version_id.has_value()) {
            summary.current_version_id = asset.current_version_id->str();
        }
        summary.trashed = asset.trashed;
        auto rollup = rollups.find(id);
        if (rollup != rollups.end()) {
            summary.version_count = rollup->second.version_count;
            summary.stage = rollup->second.current_stage;
            summary.format = rollup->second.current_format;
            summary.bundle = rollup->second.current_member_count > 0;
        }
        result.emplace(id, std::move(summary));
    }
    return result;
}

std::vector<WorkingCopyLite>
RepositoryWorkspaceSource::list_working_copies() {
    std::vector<WorkingCopyLite> result;
    if (sqlite_path_.empty()) return result;
    catalog::CatalogRepository repository(sqlite_path_);
    catalog::Database db = open_read_only(sqlite_path_);
    for (const auto& copy : repository.list_working_copies()) {
        WorkingCopyLite lite;
        lite.working_id = copy.working_id;
        lite.source_version_id = copy.source_version_id.str();
        lite.path = copy.path;
        lite.state = copy.state;
        // dirty_hint: cheap drift check against the recorded fingerprint
        // (mtime_ns; a missing file counts as dirty — the edit is not where
        // the registry expects it).
        lite.dirty_hint = !copy.payload_mtime_ns.has_value();
        if (copy.payload_mtime_ns.has_value()) {
            std::error_code ec;
            const auto mtime = std::filesystem::last_write_time(
                std::filesystem::path(copy.path), ec);
            if (ec) {
                lite.dirty_hint = true;
            } else {
                const auto nanos = std::chrono::duration_cast<
                    std::chrono::nanoseconds>(
                    mtime.time_since_epoch())
                    .count();
                lite.dirty_hint =
                    nanos != *copy.payload_mtime_ns;
            }
        }
        // Resolve the owning asset so the service can filter per entity
        // without a version→asset map (point lookup; bounded by copy count).
        if (db.is_open()) {
            auto version =
                catalog::get_version_model(db, copy.source_version_id.str());
            if (version.has_value()) {
                lite.asset_id = version->asset_id.str();
            }
        }
        result.push_back(std::move(lite));
    }
    return result;
}

std::vector<StaleLite> RepositoryWorkspaceSource::entity_staleness(
    const std::vector<EntityLinkView>& links) {
    std::vector<StaleLite> result;
    if (sqlite_path_.empty()) return result;
    std::set<std::string> asset_ids;
    for (const auto& link : links) {
        asset_ids.insert(link.asset_id);
    }
    // Full-document snapshot + bounded walk (opt-in cost class; Python's
    // impact pass pays the same). Missing/corrupt store → empty.
    catalog::CatalogRepository repository(sqlite_path_);
    auto document = repository.open_read_only();
    if (!document.is_ok()) return result;
    const catalog::CatalogDocument& doc = document.value();
    catalog::DocumentIndex index(doc);
    catalog::ImpactService impact(doc, index);
    for (const auto& item : impact.entity_staleness(asset_ids)) {
        StaleLite lite;
        lite.version_id = item.version_id;
        lite.asset_id = item.asset_id;
        lite.reason = item.reason;
        lite.pinned = item.pinned;
        lite.direct = item.direct;
        if (item.nearest_changed_ancestor.has_value()) {
            lite.nearest_changed_ancestor_asset_id =
                std::get<0>(*item.nearest_changed_ancestor);
        }
        result.push_back(std::move(lite));
    }
    return result;
}

std::vector<StaleLite> RepositoryWorkspaceSource::downstream_stale_all() {
    std::vector<StaleLite> result;
    if (sqlite_path_.empty()) return result;
    catalog::CatalogRepository repository(sqlite_path_);
    auto document = repository.open_read_only();
    if (!document.is_ok()) return result;
    const catalog::CatalogDocument& doc = document.value();
    catalog::DocumentIndex index(doc);
    catalog::ImpactService impact(doc, index);
    for (const auto& item : impact.downstream_stale()) {
        StaleLite lite;
        lite.version_id = item.version_id;
        lite.asset_id = item.asset_id;
        lite.reason = item.reason;
        lite.pinned = item.pinned;
        lite.direct = item.direct;
        if (item.nearest_changed_ancestor.has_value()) {
            lite.nearest_changed_ancestor_asset_id =
                std::get<0>(*item.nearest_changed_ancestor);
        }
        result.push_back(std::move(lite));
    }
    return result;
}

std::vector<std::string> RepositoryWorkspaceSource::related_runs(
    const std::vector<std::string>& asset_ids) {
    if (sqlite_path_.empty() || asset_ids.empty()) return {};
    catalog::Database db = open_read_only(sqlite_path_);
    if (!db.is_open()) return {};
    return catalog::run_ids_touching_assets(db, asset_ids);
}

std::vector<std::string> RepositoryWorkspaceSource::probe_missing_sources(
    const std::vector<std::string>& asset_ids) {
    // First-rung existence probe for the current versions of asset_ids
    // (mirrors sources._probe_path's cheap rungs: project-join + recorded
    // absolute) without the relocation/identity-hash rungs.
    std::vector<std::string> missing;
    if (sqlite_path_.empty() || project_dir_.empty()) return missing;
    catalog::Database db = open_read_only(sqlite_path_);
    if (!db.is_open()) return missing;

    const catalog::AssetVersionRollupMap rollups =
        catalog::asset_version_rollups_sql(db, asset_ids);
    const std::vector<std::pair<std::string, catalog::DataAsset>> models =
        catalog::get_asset_models(db, asset_ids);
    std::map<std::string, const catalog::DataAsset*> by_id;
    for (const auto& [id, asset] : models) by_id.emplace(id, &asset);

    for (const auto& asset_id : asset_ids) {
        auto model = by_id.find(asset_id);
        if (model == by_id.end()) continue;
        auto rollup = rollups.find(asset_id);
        if (rollup == rollups.end() || !rollup->second.has_current ||
            rollup->second.current_trashed) {
            continue;
        }
        std::filesystem::path candidate(rollup->second.current_path);
        if (rollup->second.current_managed) {
            candidate = project_dir_ / candidate;
        } else if (candidate.is_relative()) {
            candidate = project_dir_ / candidate;
        }
        std::error_code ec;
        if (!std::filesystem::exists(candidate, ec)) {
            missing.push_back(asset_id);
        }
    }
    return missing;
}

}  // namespace pwb::data
