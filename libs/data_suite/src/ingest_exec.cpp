// execute_ingest_plan (conv-26) — see ingest_exec.hpp.
#include "pwb/data/ingest_exec.hpp"

#include "path_text_util.hpp"

#include "pwb/catalog/dedup.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/ids.hpp"
#include "pwb/project/document.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <map>
#include <set>
#include <utility>

namespace pwb::data {

namespace {

using domain::Json;
namespace fs = std::filesystem;
using util::lower_ascii;

std::string path_suffix_of(const fs::path& path) {
    return util::path_suffix(path);
}

using util::resolved_posix;

// The fresh version directory a failed transaction rolls back (shared CAS
// blobs are never touched — only GC removes those).
void remove_staged_version_dir(const fs::path& project_file,
                               const std::string& rel_path) {
    if (rel_path.empty()) return;
    std::error_code ec;
    const fs::path version_dir =
        fs::path(rel_path).parent_path();
    if (version_dir.empty()) return;
    const fs::path absolute =
        project::project_dir_for(project_file) / version_dir;
    fs::remove_all(absolute, ec);
}

// ---- entity creation helpers (project JSON tree) --------------------------

Json make_well_node(const std::string& name, const std::string& spatial_scope,
                    const std::string& stamp) {
    Json well = Json::object();
    well["id"] = domain::make_id("well_");
    well["name"] = name;
    well["uwi"] = "";
    well["aliases"] = Json::array();
    well["surface_x"] = nullptr;
    well["surface_y"] = nullptr;
    well["surface_z"] = nullptr;
    well["source_crs"] = "";
    well["project_x"] = nullptr;
    well["project_y"] = nullptr;
    well["coordinate_status"] = "missing";
    well["kb"] = nullptr;
    well["td"] = nullptr;
    well["status"] = "active";
    well["spatial_scope"] = spatial_scope;
    well["tags"] = Json::array();
    well["metadata"] = Json::object();
    well["created_at"] = stamp;
    well["updated_at"] = stamp;
    return well;
}

Json& array_section(Json& root, const char* key) {
    auto section = root.find(key);
    if (section == root.end() || !section->is_array()) {
        root[key] = Json::array();
        return root[key];
    }
    return *section;
}

std::string normalized_name_of(const Json& node) {
    return normalize_well_name(node.value("name", std::string()));
}

}  // namespace

Json IngestExecuteReport::to_json() const {
    Json report = Json::object();
    report["imported_version_ids"] = Json::array();
    for (const std::string& id : imported_version_ids) {
        report["imported_version_ids"].push_back(id);
    }
    report["asset_id_by_path"] = Json::object();
    for (const auto& [path, asset] : asset_id_by_path) {
        report["asset_id_by_path"][path] = asset;
    }
    report["bound_links"] = bound_links;
    report["created_entities"] = created_entities;
    report["skipped"] = Json::array();
    for (const std::string& path : skipped) report["skipped"].push_back(path);
    report["issues"] = Json::array();
    for (const std::string& issue : issues) report["issues"].push_back(issue);
    report["cancelled"] = cancelled;
    return report;
}

IngestExecuteReport execute_ingest_plan(const IngestPlan& plan,
                                        WritableSession& session,
                                        const IngestExecuteOptions& options) {
    IngestExecuteReport report;
    const fs::path project_file = session.project_file();

    // Open the store read-write (create-on-demand) and snapshot the live
    // managed-RAW identity pairs for per-item O(1) idempotency lookups.
    auto document_result = session.repository().open_read_write();
    if (!document_result.is_ok()) {
        report.issues.push_back("catalog open failed: " +
                                document_result.error().message);
        return report;
    }
    catalog::CatalogDocument catalog_doc = std::move(document_result.value());
    std::map<std::pair<std::string, std::string>, std::string> registered_pairs;
    for (const auto& version : catalog_doc.versions) {
        if (!version.trashed && version.managed &&
            version.stage == domain::DataStage::Raw &&
            version.sha256.has_value() && version.source_uri.has_value()) {
            const std::string key = resolved_posix(
                project::path_from_u8(*version.source_uri));
            if (!key.empty()) {
                registered_pairs.emplace(
                    std::make_pair(key, *version.sha256),
                    version.asset_id.str());
            }
        }
    }

    std::vector<const PlannedItem*> pending;
    for (const auto& item : plan.items) {
        if (options.execute_unconfirmed) {
            if (item.decision == "accept" || item.decision == "pending" ||
                item.decision == "skip" || item.decision == "as_new_version") {
                pending.push_back(&item);
            }
        } else {
            // Confirmed mode: accept/as_new_version execute; explicit skips
            // are recorded in report.skipped (never registered); pending
            // NEVER executes without execute_unconfirmed.
            if (item.decision == "accept" || item.decision == "skip" ||
                item.decision == "as_new_version") {
                pending.push_back(&item);
            }
        }
    }
    const std::size_t total = pending.size();
    std::size_t done = 0;
    // (item, asset_id) pairs staged for the binding phase.
    std::vector<std::pair<const PlannedItem*, std::string>> staged_bindings;
    staged_bindings.reserve(pending.size());
    const int chunk_size = std::max(1, options.chunk_size);

    for (std::size_t start = 0; start < pending.size(); start += chunk_size) {
        if (options.cancel && options.cancel()) {
            report.cancelled = true;
            break;
        }
        const std::size_t end = std::min(start + chunk_size, pending.size());
        for (std::size_t i = start; i < end; ++i) {
            const PlannedItem& item = *pending[i];
            ++done;
            if (options.progress) {
                options.progress(static_cast<int>(done),
                                 static_cast<int>(total));
            }
            if (item.decision == "skip") {
                report.skipped.push_back(item.path.generic_string());
                if (!item.duplicate_of_asset.empty()) {
                    report.asset_id_by_path[item.path.generic_string()] =
                        item.duplicate_of_asset;
                    staged_bindings.emplace_back(&item,
                                                 item.duplicate_of_asset);
                }
                continue;
            }
            // Idempotency: an interrupted earlier execution may have
            // imported this very (source, content) already. as_new_version
            // deliberately bypasses it — re-registering content as a new
            // asset is that decision's whole point.
            std::string existing;
            if (item.sha256.has_value() &&
                item.decision != "as_new_version") {
                const std::string key = resolved_posix(item.path);
                if (!key.empty()) {
                    auto hit = registered_pairs.find({key, *item.sha256});
                    if (hit != registered_pairs.end()) existing = hit->second;
                }
            }
            if (!existing.empty()) {
                report.skipped.push_back(item.path.generic_string());
                report.asset_id_by_path[item.path.generic_string()] = existing;
                staged_bindings.emplace_back(&item, existing);
                continue;
            }

            // ---- import_raw (managed RAW snapshot + CAS dedup) ----------
            const std::string asset_id = domain::make_id("asset_");
            const std::string version_id = domain::make_id("ver_");
            auto placed = catalog::place_managed_file(
                item.path, project_file, domain::DataStage::Raw, asset_id,
                version_id,
                catalog::PlaceManagedOptions{
                    .keep_source = true,
                    .known_sha256 = item.sha256,
                    .register_blob = true,
                });
            if (!placed.is_ok()) {
                report.issues.push_back(
                    item.path.filename().string() + ": 导入失败 DataError: " +
                    placed.error().message);
                continue;
            }
            const std::string now = domain::now_iso8601();
            catalog::DataAsset asset;
            asset.id = domain::AssetId(asset_id);
            asset.name = item.path.filename().string();
            asset.type = item.type.empty() ? std::string("unknown") : item.type;
            asset.description = "";
            asset.metadata = Json::object();
            if (!item.format.empty()) {
                asset.metadata["format"] = item.format;
            }
            asset.created_at = now;
            asset.updated_at = now;

            catalog::DataVersion version;
            version.id = domain::VersionId(version_id);
            version.asset_id = asset.id;
            version.version_number = 1;
            version.stage = domain::DataStage::Raw;
            version.managed = true;
            version.path = placed.value().rel_path;
            version.source_uri = resolved_posix(item.path);
            version.format = item.format;
            version.size_bytes = placed.value().size_bytes;
            version.sha256 = placed.value().sha256;
            version.run_id = std::nullopt;
            version.metadata = Json::object();
            version.created_at = now;

            const auto commit_error =
                session.repository().import_raw_transaction(asset, version);
            if (commit_error.code != domain::ErrorCode::Ok) {
                remove_staged_version_dir(project_file,
                                          placed.value().rel_path);
                report.issues.push_back(
                    item.path.filename().string() + ": 导入失败 DataError: " +
                    commit_error.message);
                continue;
            }
            report.imported_version_ids.push_back(version.id.str());
            report.asset_id_by_path[item.path.generic_string()] = asset_id;
            if (version.sha256.has_value()) {
                const std::string key = resolved_posix(item.path);
                if (!key.empty()) {
                    registered_pairs.emplace(
                        std::make_pair(key, *version.sha256), asset_id);
                }
            }
            staged_bindings.emplace_back(&item, asset_id);
        }
    }

    if (options.bind && !staged_bindings.empty()) {
        Json& root = session.document().root();
        const std::string stamp = domain::now_iso8601();
        // ---- survey + geological binding --------------------------------
        for (const auto& [item, asset_id] : staged_bindings) {
            const IdentityProposal& identity = item->identity;
            if (identity.entity_type == "seismic_survey") {
                Json& surveys = array_section(root, "seismic_surveys");
                const std::string normalized =
                    normalize_well_name(identity.entity_name);
                std::string survey_id;
                Json* matched = nullptr;
                if (!normalized.empty()) {
                    for (auto& node : surveys) {
                        if (node.is_object() &&
                            normalized_name_of(node) == normalized) {
                            survey_id = node.value("id", std::string());
                            matched = &node;
                            break;
                        }
                    }
                }
                if (survey_id.empty()) {
                    if (!identity.new_entity) {
                        report.issues.push_back(
                            "调查 '" + identity.entity_name +
                            "' 未匹配且未标记新建，跳过绑定");
                        continue;
                    }
                    Json node = Json::object();
                    node["id"] = domain::make_id("svy_");
                    node["name"] = identity.entity_name;
                    node["survey_type"] = "3d";
                    node["crs"] = "";
                    node["extent"] = Json::array();
                    node["inline_range"] = Json::array();
                    node["crossline_range"] = Json::array();
                    node["n_samples"] = nullptr;
                    node["dt_ms"] = nullptr;
                    node["t0_ms"] = nullptr;
                    node["metadata"] = Json::object();
                    node["created_at"] = "";
                    node["updated_at"] = "";
                    survey_id = node["id"].get<std::string>();
                    surveys.push_back(std::move(node));
                    matched = &surveys.back();
                    ++report.created_entities;
                }
                // _stamp parity: created_at filled when empty, updated_at
                // always (the binding pass touched this survey).
                if (matched != nullptr) {
                    if (matched->value("created_at", std::string()).empty()) {
                        (*matched)["created_at"] = stamp;
                    }
                    (*matched)["updated_at"] = stamp;
                }
                const auto upsert = upsert_entity_asset_link(
                    root, "seismic_survey", survey_id, asset_id,
                    "seismic_volume", true);
                report.bound_links += upsert.created ? 1 : 0;
            } else if (identity.entity_type == "geological_entity") {
                static const std::map<std::string,
                                      std::tuple<const char*, const char*,
                                                 const char*>>
                    kinds = {
                        {"horizon", {"geological", "horizon", "horizon"}},
                        {"fault", {"geological", "fault", "fault"}},
                        {"faults", {"geological", "fault", "fault"}},
                        {"well_stratification",
                         {"geological", "tops", "tops"}},
                    };
                std::string kind = "geological", entity_kind = item->type,
                            role = "other";
                auto mapping = kinds.find(item->type);
                if (mapping != kinds.end()) {
                    std::tie(kind, entity_kind, role) = mapping->second;
                }
                const std::string normalized =
                    normalize_well_name(identity.entity_name);
                Json& entities =
                    array_section(root, "geological_entities");
                const Json* entity = nullptr;
                for (const auto& node : entities) {
                    if (node.is_object() &&
                        node.value("kind", std::string()) == kind &&
                        normalize_well_name(
                            node.value("name", std::string())) ==
                            normalized) {
                        entity = &node;
                        break;
                    }
                }
                std::string entity_id;
                if (entity == nullptr) {
                    Json node = Json::object();
                    node["id"] = domain::make_id("ent_");
                    node["kind"] = kind;
                    node["name"] = identity.entity_name;
                    node["entity_kind"] = entity_kind;
                    node["description"] = "";
                    node["metadata"] = Json::object();
                    node["created_at"] = "";
                    node["updated_at"] = "";
                    entities.push_back(std::move(node));
                    ++report.created_entities;
                    entity_id =
                        entities.back().value("id", std::string());
                } else {
                    entity_id = entity->value("id", std::string());
                }
                const auto upsert = upsert_entity_asset_link(
                    root, "geological_entity", entity_id, asset_id, role,
                    true);
                report.bound_links += upsert.created ? 1 : 0;
            }
        }

        // ---- well binding (scope-grouped, Python _bind_plan_items order) --
        // Groups iterate in insertion order; within a group the known-id
        // links land first, then the unresolved create/link pass — the
        // link ARRAY order is observable (project JSON) and frozen by the
        // oracle, so the structure mirrors Python exactly.
        struct WellEntry {
            const PlannedItem* item;
            std::string asset_id;
            bool has_well_id;
        };
        std::vector<WellEntry> well_entries;
        for (const auto& [item, asset_id] : staged_bindings) {
            if (item->identity.entity_type != "well") continue;
            if (!item->identity.entity_id.empty()) {
                well_entries.push_back({item, asset_id, true});
            } else if (item->identity.new_entity) {
                well_entries.push_back({item, asset_id, false});
            }
        }
        // Insertion-ordered (scope, role) groups — Python dicts preserve
        // first-seen order and the link array order is observable.
        std::vector<std::pair<std::pair<std::string, std::string>,
                              std::vector<WellEntry>>>
            groups;
        for (const WellEntry& entry : well_entries) {
            const std::string scope =
                path_suffix_of(entry.item->path) == ".xml" ? "reference" : "";
            const std::string role =
                entry.item->role.empty() ? "well_log" : entry.item->role;
            const auto key = std::make_pair(scope, role);
            auto it = std::find_if(groups.begin(), groups.end(),
                                   [&key](const auto& group) {
                                       return group.first == key;
                                   });
            if (it == groups.end()) {
                groups.push_back({key, {}});
                it = groups.end() - 1;
            }
            it->second.push_back(entry);
        }
        for (const auto& [scope_role, entries] : groups) {
            const std::string& scope = scope_role.first;
            // Scoped registry: wells of that spatial scope only.
            Json& wells = array_section(root, "wells");
            WellRegistry registry;
            for (const auto& node : wells) {
                if (!scope.empty() &&
                    node.value("spatial_scope", std::string("workarea")) !=
                        scope) {
                    continue;
                }
                WellRecord record;
                record.id = node.value("id", std::string());
                record.name = node.value("name", std::string());
                record.uwi = node.value("uwi", std::string());
                registry.add(std::move(record));
            }
            // Known-id links first (bind_well_extracts' fast path).
            for (const WellEntry& entry : entries) {
                if (!entry.has_well_id) continue;
                const auto upsert = upsert_entity_asset_link(
                    root, "well", entry.item->identity.entity_id,
                    entry.asset_id,
                    entry.item->role.empty() ? "other" : entry.item->role,
                    false);
                report.bound_links += upsert.created ? 1 : 0;
            }
            // Pass A: scoped resolve; create the missing wells. Every
            // processed well is _stamp'ed (updated_at always, created_at
            // filled when empty) like bind_well_extracts.
            for (const WellEntry& entry : entries) {
                if (entry.has_well_id) continue;
                const std::string name =
                    !entry.item->identity.entity_name.empty()
                        ? entry.item->identity.entity_name
                        : entry.item->path.stem().string();
                const ResolutionOutcome outcome =
                    resolve_well(root, &registry, name);
                if (outcome.matched) {
                    for (auto& node : wells) {
                        if (node.value("id", std::string()) ==
                            outcome.well_id) {
                            if (!scope.empty()) {
                                node["spatial_scope"] = scope;
                            }
                            if (node.value("created_at", std::string())
                                    .empty()) {
                                node["created_at"] = stamp;
                            }
                            node["updated_at"] = stamp;
                            break;
                        }
                    }
                } else if (!outcome.ambiguous) {
                    Json well = make_well_node(name, "workarea", stamp);
                    if (!scope.empty()) well["spatial_scope"] = scope;
                    const std::string well_id =
                        well["id"].get<std::string>();
                    wells.push_back(std::move(well));
                    WellRecord record;
                    record.id = well_id;
                    record.name = name;
                    registry.add(std::move(record));
                    ++report.created_entities;
                }
            }
            // Pass B: unscoped resolution → link (or honest issue). One
            // registry for the whole group — rebuilt once after pass A so
            // the wells it created are visible (never per entry; V6 §6).
            WellRegistry full_registry;
            for (const auto& node : wells) {
                WellRecord record;
                record.id = node.value("id", std::string());
                record.name = node.value("name", std::string());
                record.uwi = node.value("uwi", std::string());
                full_registry.add(std::move(record));
            }
            for (const WellEntry& entry : entries) {
                if (entry.has_well_id) continue;
                const std::string name =
                    !entry.item->identity.entity_name.empty()
                        ? entry.item->identity.entity_name
                        : entry.item->path.stem().string();
                const std::string role =
                    entry.item->role.empty() ? "well_log" : entry.item->role;
                const ResolutionOutcome outcome =
                    resolve_well(root, &full_registry, name);
                if (outcome.matched && !outcome.well_id.empty()) {
                    const auto upsert = upsert_entity_asset_link(
                        root, "well", outcome.well_id, entry.asset_id, role,
                        false);
                    report.bound_links += upsert.created ? 1 : 0;
                } else {
                    report.issues.push_back(
                        name + ": 井身份无法确定，资产 " + entry.asset_id +
                        " 未绑定");
                }
            }
        }

        // ---- primary selection ------------------------------------------
        for (const auto& [item, asset_id] : staged_bindings) {
            if (!item->primary) continue;
            const IdentityProposal& identity = item->identity;
            if (identity.entity_type == "well" &&
                !identity.entity_id.empty()) {
                upsert_entity_asset_link(
                    root, "well", identity.entity_id, asset_id,
                    item->role.empty() ? "other" : item->role, true);
            } else if (identity.entity_type == "seismic_survey" &&
                       !identity.entity_id.empty()) {
                upsert_entity_asset_link(
                    root, "seismic_survey", identity.entity_id, asset_id,
                    item->role.empty() ? "seismic_volume" : item->role,
                    true);
            }
        }
    }
    return report;
}

}  // namespace pwb::data
