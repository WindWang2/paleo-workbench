// Governance closure — see governance.hpp. All writes go through the two
// existing persistence authorities (project JSON via WritableSession,
// catalog.sqlite via catalog::open_catalog); reads take fresh best-effort
// snapshots so a governance view never serves a stale in-memory copy.
#include "pwb/data/governance.hpp"

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/impact.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/catalog/service_core.hpp"
#include "pwb/catalog/tags.hpp"
#include "pwb/catalog/trash_service.hpp"
#include "pwb/data/session.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <fstream>
#include <set>
#include <utility>

namespace pwb::data::governance {

namespace {

using domain::Json;

Json read_project_root(const fs::path& project_file) {
    Json root = Json::object();
    std::ifstream in(project_file);
    if (!in) return root;
    try {
        in >> root;
    } catch (const std::exception&) {
        return Json::object();
    }
    return root;
}

std::string strip_ascii_ws(const std::string& value) {
    const char* ws = " \t\r\n\f\v";
    const auto begin = value.find_first_not_of(ws);
    if (begin == std::string::npos) return {};
    const auto end = value.find_last_not_of(ws);
    return value.substr(begin, end - begin + 1);
}

const Json* entity_section(const Json& root, const std::string& entity_type) {
    const char* key = nullptr;
    if (entity_type == "well") {
        key = "wells";
    } else if (entity_type == "seismic_survey") {
        key = "seismic_surveys";
    } else if (entity_type == "geological_entity") {
        key = "geological_entities";
    } else if (entity_type == "auxiliary_entity") {
        key = "auxiliary_entities";
    }
    if (key == nullptr) return nullptr;
    const auto it = root.find(key);
    if (it == root.end() || !it->is_array()) return nullptr;
    return &*it;
}

catalog::TagSaveHook tag_save_hook(catalog::CatalogServiceCore& core) {
    return [&core]() { return core.save(); };
}

catalog::SaveHook core_save_hook(catalog::CatalogServiceCore& core) {
    return [&core](const catalog::DirtySet& dirty) {
        return core.save(dirty);
    };
}

std::vector<catalog::ImpactService::EntityLink> impact_entity_links(
    const Json& root) {
    std::vector<catalog::ImpactService::EntityLink> links;
    const auto it = root.find("entity_asset_links");
    if (it == root.end() || !it->is_array()) return links;
    for (const auto& node : *it) {
        if (!node.is_object()) continue;
        catalog::ImpactService::EntityLink link;
        link.entity_type = node.value("entity_type", std::string("well"));
        link.entity_id = node.value("entity_id", std::string());
        link.asset_id = node.value("asset_id", std::string());
        if (link.entity_id.empty() || link.asset_id.empty()) continue;
        links.push_back(std::move(link));
    }
    return links;
}

std::string tag_display(const catalog::Tag& tag) {
    return tag.display_name.has_value() && !tag.display_name->empty()
               ? *tag.display_name
               : tag.name;
}

}  // namespace

// ---- entity / link reads ---------------------------------------------------

std::vector<WellEntry> wells(const fs::path& project_file) {
    std::vector<WellEntry> result;
    const Json root = read_project_root(project_file);
    const auto it = root.find("wells");
    if (it == root.end() || !it->is_array()) return result;
    for (const auto& node : *it) {
        if (!node.is_object()) continue;
        WellEntry well;
        well.id = node.value("id", std::string());
        if (well.id.empty()) continue;  // unindexed nodes never list
        well.name = node.value("name", std::string());
        well.uwi = node.value("uwi", std::string());
        well.spatial_scope =
            node.value("spatial_scope", std::string("workarea"));
        result.push_back(std::move(well));
    }
    return result;
}

std::string entity_display_name(const fs::path& project_file,
                                std::string_view entity_type,
                                std::string_view entity_id) {
    const Json root = read_project_root(project_file);
    const Json* section =
        entity_section(root, std::string(entity_type));
    if (section == nullptr) return {};
    for (const auto& node : *section) {
        if (node.is_object() &&
            node.value("id", std::string()) == entity_id) {
            return node.value("name", std::string());
        }
    }
    return {};
}

std::vector<EntityLinkView> links_for_asset(const fs::path& project_file,
                                            std::string_view asset_id) {
    const Json root = read_project_root(project_file);
    return pwb::data::links_for_asset(root, asset_id);
}

bool asset_is_live(const fs::path& project_file,
                   const std::string& asset_id) {
    catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto document = repository.open_read_only();
    if (!document.is_ok()) return false;
    catalog::DocumentIndex index(document.value());
    const catalog::DataAsset* asset = index.asset(asset_id);
    return asset != nullptr && !asset->trashed;
}

// ---- link writes -----------------------------------------------------------

namespace {

// One WritableSession-scoped document mutation with a single atomic save.
// The session loads its own document copy; a failed save leaves the on-disk
// document untouched (the mutated copy dies with the session).
template <typename Mutate>
WriteOutcome with_document_saved(const fs::path& project_file,
                                 const char* what, Mutate&& mutate) {
    auto session = pwb::data::WritableSession::open(project_file);
    if (!session.is_ok()) {
        return WriteOutcome{
            false,
            "工程以只读/损坏状态打开，" + std::string(what) + "失败: " +
                session.error().message,
            {}};
    }
    WriteOutcome outcome = mutate(session.value().document().root());
    if (!outcome.ok) return outcome;  // validation refused — nothing saved
    const auto save = session.value().manager().save(
        session.value().document());
    if (!save.is_ok()) {
        return WriteOutcome{
            false, "工程文档保存失败（" + std::string(what) +
                       "未生效）: " + save.error().message,
            {}};
    }
    if (outcome.summary.empty()) outcome.summary = what;
    return outcome;
}

}  // namespace

WriteOutcome link_asset(const fs::path& project_file,
                        const std::string& entity_type,
                        const std::string& entity_id,
                        const std::string& asset_id,
                        const std::string& role, bool is_primary,
                        const std::string& note) {
    const std::string clean_role = strip_ascii_ws(role);
    if (clean_role.empty()) {
        return WriteOutcome{false, "角色不能为空（词汇来自角色注册表，也可自定义）", {}};
    }
    if (!asset_is_live(project_file, asset_id)) {
        return WriteOutcome{false,
                            "资产不存在或已在回收站，无法关联: " + asset_id,
                            {}};
    }
    return with_document_saved(
        project_file, "关联到实体", [&](Json& root) -> WriteOutcome {
            if (!pwb::data::entity_exists(root, entity_type, entity_id)) {
                return WriteOutcome{
                    false, "井/实体不存在于当前工程: " + entity_id, {}};
            }
            pwb::data::upsert_entity_asset_link(root, entity_type, entity_id,
                                                asset_id, clean_role,
                                                is_primary, false, note);
            WriteOutcome out;
            out.ok = true;
            out.summary = "已关联 " + asset_id + " → " + entity_id + "（" +
                          clean_role + (is_primary ? "，主数据）" : "）");
            return out;
        });
}

WriteOutcome unlink_asset(const fs::path& project_file,
                          const std::string& entity_type,
                          const std::string& entity_id,
                          const std::string& asset_id,
                          const std::string& role) {
    return with_document_saved(
        project_file, "解除关联", [&](Json& root) -> WriteOutcome {
            const int removed = pwb::data::remove_entity_asset_link(
                root, entity_type, entity_id, asset_id, role);
            if (removed == 0) {
                return WriteOutcome{
                    false, "链接不存在（可能已被移除）: " + entity_id + " / " +
                               asset_id + " / " + role,
                    {}};
            }
            WriteOutcome out;
            out.ok = true;
            out.summary = "已解除关联（" + std::to_string(removed) + " 条）";
            return out;
        });
}

WriteOutcome set_asset_link_role(const fs::path& project_file,
                                 const std::string& entity_type,
                                 const std::string& entity_id,
                                 const std::string& asset_id,
                                 const std::string& old_role,
                                 const std::string& new_role) {
    const std::string clean_new = strip_ascii_ws(new_role);
    if (clean_new.empty()) {
        return WriteOutcome{false, "新角色不能为空", {}};
    }
    return with_document_saved(
        project_file, "修改角色", [&](Json& root) -> WriteOutcome {
            const auto edit = pwb::data::set_link_role(
                root, entity_type, entity_id, asset_id, old_role, clean_new);
            switch (edit) {
                case pwb::data::LinkRoleEdit::Ok:
                    break;
                case pwb::data::LinkRoleEdit::NotFound:
                    return WriteOutcome{
                        false, "链接不存在（角色 " + old_role + " 未绑定）", {}};
                case pwb::data::LinkRoleEdit::Conflicts:
                    return WriteOutcome{
                        false,
                        "该资产在此实体上已有角色 " + clean_new +
                            " 的链接，拒绝重复（请先解除其一）",
                        {}};
            }
            WriteOutcome out;
            out.ok = true;
            out.summary = "角色已改为 " + clean_new;
            return out;
        });
}

// ---- tags ------------------------------------------------------------------

WriteOutcome add_tags(const fs::path& project_file,
                      const std::vector<std::string>& asset_ids,
                      const std::vector<std::string>& tag_names) {
    std::vector<std::string> names;
    for (const auto& raw : tag_names) {
        const std::string cleaned = strip_ascii_ws(raw);
        if (!cleaned.empty()) names.push_back(cleaned);
    }
    if (names.empty() || asset_ids.empty()) {
        return WriteOutcome{false, "标签名与资产都不能为空", {}};
    }
    auto opened = catalog::open_catalog(project_file, {});
    if (!opened.is_ok()) {
        return WriteOutcome{false,
                            "数据目录打开失败: " + opened.error().message, {}};
    }
    catalog::TagStore store(&opened.value().document(),
                            tag_save_hook(opened.value()));
    int applied = 0;
    std::vector<std::string> failures;
    for (const auto& name : names) {
        try {
            const auto result = store.bulk_add_tag(name, asset_ids, {});
            if (result.is_ok()) {
                ++applied;
            } else {
                failures.push_back(name + ": " + result.error().message);
            }
        } catch (const std::exception& exc) {
            failures.push_back(name + ": " + exc.what());
        }
    }
    if (!failures.empty()) {
        WriteOutcome out;
        out.ok = false;
        out.error = "标签写入失败（已成功 " + std::to_string(applied) +
                    " 个）: " +
                    [&] {
                        std::string joined;
                        for (const auto& failure : failures) {
                            if (!joined.empty()) joined += "; ";
                            joined += failure;
                        }
                        return joined;
                    }();
        return out;
    }
    WriteOutcome out;
    out.ok = true;
    out.summary = "已为 " + std::to_string(asset_ids.size()) + " 项资产添加 " +
                  std::to_string(applied) + " 个标签";
    return out;
}

WriteOutcome remove_tags(const fs::path& project_file,
                         const std::vector<std::string>& asset_ids,
                         const std::string& tag_name) {
    const std::string cleaned = strip_ascii_ws(tag_name);
    if (cleaned.empty() || asset_ids.empty()) {
        return WriteOutcome{false, "标签名与资产都不能为空", {}};
    }
    auto opened = catalog::open_catalog(project_file, {});
    if (!opened.is_ok()) {
        return WriteOutcome{false,
                            "数据目录打开失败: " + opened.error().message, {}};
    }
    catalog::TagStore store(&opened.value().document(),
                            tag_save_hook(opened.value()));
    try {
        const auto error =
            store.bulk_remove_tag(cleaned, asset_ids, {});
        if (error.code != domain::ErrorCode::Ok) {
            return WriteOutcome{false,
                                "标签移除失败: " + error.message, {}};
        }
    } catch (const std::exception& exc) {
        return WriteOutcome{false,
                            std::string("标签移除失败: ") + exc.what(), {}};
    }
    WriteOutcome out;
    out.ok = true;
    out.summary = "已从 " + std::to_string(asset_ids.size()) +
                  " 项资产移除标签 " + cleaned;
    return out;
}

std::vector<AssetTags> tags_for_assets(
    const fs::path& project_file,
    const std::vector<std::string>& asset_ids) {
    std::vector<AssetTags> result;
    result.reserve(asset_ids.size());
    for (const auto& id : asset_ids) result.push_back(AssetTags{id, {}});

    catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto document = repository.open_read_only();
    if (!document.is_ok()) return result;

    std::map<std::string, const catalog::Tag*> tags_by_id;
    for (const auto& tag : document.value().tags) {
        tags_by_id.emplace(tag.id, &tag);
    }
    std::map<std::string, std::size_t> slot_of;
    for (std::size_t i = 0; i < result.size(); ++i) {
        slot_of.emplace(result[i].asset_id, i);
    }
    for (const auto& [asset_id, tag_id] : document.value().asset_tags) {
        const auto slot = slot_of.find(asset_id);
        if (slot == slot_of.end()) continue;
        const auto tag = tags_by_id.find(tag_id);
        if (tag != tags_by_id.end()) {
            result[slot->second].tags.push_back(tag_display(*tag->second));
        }
    }
    return result;
}

std::vector<std::string> all_tag_names(const fs::path& project_file) {
    catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto document = repository.open_read_only();
    if (!document.is_ok()) return {};
    std::vector<std::string> names;
    names.reserve(document.value().tags.size());
    for (const auto& tag : document.value().tags) {
        names.push_back(tag_display(tag));
    }
    return names;
}

// ---- trash -----------------------------------------------------------------

std::vector<TrashedEntry> trashed_assets(const fs::path& project_file) {
    catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto document = repository.open_read_only();
    if (!document.is_ok()) return {};
    const catalog::CatalogDocument& doc = document.value();

    std::map<std::string, int> trashed_version_count;
    for (const auto& version : doc.versions) {
        if (version.trashed && !version.asset_id.empty()) {
            ++trashed_version_count[version.asset_id.str()];
        }
    }
    std::vector<TrashedEntry> result;
    for (const auto& asset : doc.assets) {
        if (!asset.trashed) continue;
        TrashedEntry entry;
        entry.asset_id = asset.id.str();
        entry.name = asset.name;
        entry.type = asset.type;
        entry.trashed_at = asset.trashed_at.value_or("");
        const auto count = trashed_version_count.find(entry.asset_id);
        entry.version_count =
            count != trashed_version_count.end() ? count->second : 0;
        // Reason lives on the version tombstones; surface the first one.
        for (const auto& version : doc.versions) {
            if (!version.trashed ||
                version.asset_id.str() != entry.asset_id) {
                continue;
            }
            const auto trash = version.metadata.find("trash");
            if (trash != version.metadata.end() && trash->is_object()) {
                const auto reason = trash->find("reason");
                if (reason != trash->end() && reason->is_string()) {
                    entry.reason = reason->get<std::string>();
                }
            }
            break;
        }
        result.push_back(std::move(entry));
    }
    return result;
}

WriteOutcome trash_assets(const fs::path& project_file,
                          const std::vector<std::string>& asset_ids,
                          const std::string& reason) {
    if (asset_ids.empty()) {
        return WriteOutcome{false, "没有要移入回收站的资产", {}};
    }
    auto opened = catalog::open_catalog(project_file, {});
    if (!opened.is_ok()) {
        return WriteOutcome{false,
                            "数据目录打开失败: " + opened.error().message, {}};
    }
    catalog::CatalogServiceCore& core = opened.value();

    int trashed = 0;
    for (const auto& asset_id : asset_ids) {
        // trash_asset/restore_asset 扫文档自身、忽略 index（trash_service
        // 的 (void)index 契约）——空索引即可，省去逐资产 O(N) 重建。
        const catalog::DocumentIndex index{};
        const auto error = catalog::trash_asset(
            &core.document(), index, project_file, asset_id,
            reason, core_save_hook(core));
        if (error.code != domain::ErrorCode::Ok) {
            core.invalidate_maps();
            WriteOutcome out;
            out.ok = trashed > 0;  // earlier assets stay trashed — honest
            out.error = "移入回收站失败（已移入 " + std::to_string(trashed) +
                        " 项）: " + error.message;
            return out;
        }
        core.invalidate_maps();
        ++trashed;
    }
    WriteOutcome out;
    out.ok = true;
    out.summary = "已移入回收站 " + std::to_string(trashed) + " 项（原始数据"
                  "保留在工程 artifacts/trash/，可恢复）";
    return out;
}

WriteOutcome restore_assets(const fs::path& project_file,
                            const std::vector<std::string>& asset_ids) {
    if (asset_ids.empty()) {
        return WriteOutcome{false, "没有要恢复的资产", {}};
    }
    auto opened = catalog::open_catalog(project_file, {});
    if (!opened.is_ok()) {
        return WriteOutcome{false,
                            "数据目录打开失败: " + opened.error().message, {}};
    }
    catalog::CatalogServiceCore& core = opened.value();

    int restored = 0;
    for (const auto& asset_id : asset_ids) {
        const catalog::DocumentIndex index{};
        const auto error = catalog::restore_asset(
            &core.document(), index, project_file, asset_id,
            core_save_hook(core));
        if (error.code != domain::ErrorCode::Ok) {
            core.invalidate_maps();
            WriteOutcome out;
            out.ok = restored > 0;
            out.error = "恢复失败（已恢复 " + std::to_string(restored) +
                        " 项）: " + error.message;
            return out;
        }
        core.invalidate_maps();
        ++restored;
    }
    WriteOutcome out;
    out.ok = true;
    out.summary = "已从回收站恢复 " + std::to_string(restored) +
                  " 项（关联关系保留，直接可解析）";
    return out;
}

// ---- delete impact ---------------------------------------------------------

ImpactFacts delete_impact_facts(
    const fs::path& project_file,
    const std::optional<std::string>& version_id,
    const std::optional<std::string>& asset_id) {
    ImpactFacts facts;
    catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto document = repository.open_read_only();
    if (!document.is_ok()) {
        facts.error = "目录库打开失败: " + document.error().message;
        return facts;
    }
    catalog::DocumentIndex index(document.value());
    catalog::ImpactService service(document.value(), index);
    const auto links = impact_entity_links(read_project_root(project_file));
    const auto impact = service.delete_impact(
        version_id, asset_id, links.empty() ? nullptr : &links);
    facts.ok = true;
    facts.affected_versions =
        static_cast<int>(impact.target_version_ids.size());
    facts.live_descendants =
        static_cast<int>(impact.live_descendants.size());
    facts.broken_edges = impact.broken_lineage_edges;
    facts.linked_entities =
        static_cast<int>(impact.linked_entities.size());
    facts.advice = impact.cascade_advice;
    return facts;
}

}  // namespace pwb::data::governance
