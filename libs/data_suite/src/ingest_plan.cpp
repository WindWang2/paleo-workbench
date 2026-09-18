// build_ingest_plan (conv-26) — pure phase-1 port of
// paleo_workbench/resources/ingest_plan.py; see ingest_plan.hpp. The
// mutating phase-2 lives in ingest_exec.cpp.
//
// Path-string domains (Python parity): item/bundle/root paths are emitted
// and compared in their ORIGINAL generic-string form (`str(Path)` — Path
// equality is string equality after construction); only the duplicate
// matcher resolves, because ingest_plan.py resolves explicitly there.
// Path ORDER (sorted rglob, bundle members) follows PurePath part-wise
// comparison, not byte-wise whole-string order — primary selection depends
// on item order, so the part-wise order is contract.
#include "pwb/data/ingest_plan.hpp"

#include "pwb/catalog/models.hpp"
#include "pwb/domain/sha256.hpp"
#include "pwb/ingest/classifier.hpp"
#include "pwb/project/document.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <tuple>

namespace pwb::data {

namespace {

using domain::Json;

std::string lower_ascii(std::string text) {
    for (char& c : text) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    }
    return text;
}

// Path.suffix.lower() — extension WITH dot, "" when none.
std::string path_suffix(const fs::path& path) {
    return lower_ascii(path.extension().string());
}

// Path.stem — filename minus the last extension.
std::string path_stem(const fs::path& path) { return path.stem().string(); }

std::string generic_string(const fs::path& path) {
    return path.generic_string();
}

bool is_shapefile_member_extension(const std::string& suffix) {
    for (const char* ext : kShapefileMemberExtensions) {
        if (suffix == ext) return true;
    }
    return false;
}

bool is_candidate_file(const fs::path& path) {
    std::error_code ec;
    if (!fs::is_regular_file(path, ec) || ec) return false;
    const std::string name = path.filename().string();
    if (name.rfind("._", 0) == 0) return false;
    return fs::file_size(path, ec) > 0 && !ec;
}

std::vector<fs::path> sorted_tree_entries(const fs::path& root) {
    std::vector<fs::path> paths;
    std::error_code ec;
    for (const auto& entry : fs::recursive_directory_iterator(root, ec)) {
        paths.push_back(entry.path());
    }
    if (ec || paths.empty()) return paths;
    // Part-wise order: map from the component vector to the path index;
    // first occurrence wins ties (a single walk never duplicates paths).
    std::map<std::vector<std::string>, std::size_t> ordered;
    for (std::size_t i = 0; i < paths.size(); ++i) {
        std::vector<std::string> parts;
        for (const auto& part : paths[i]) parts.push_back(part.string());
        ordered.emplace(std::move(parts), i);
    }
    std::vector<fs::path> sorted;
    sorted.reserve(paths.size());
    for (const auto& [parts, index] : ordered) {
        (void)parts;
        sorted.push_back(paths[index]);
    }
    return sorted;
}

// Content bytes for classify_import_path sniffing (Python's bounded XML
// extractors read the file themselves; fixture-sized buffers suffice).
std::string read_sniff_bytes(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

std::string directory_hint(const fs::path& path) {
    const std::string parent = path.parent_path().filename().string();
    if (parent.empty() || parent == "." || parent == "/") return "";
    return parent;
}

// resolve().as_posix() parity: symlink-aware where the path exists, lexical
// normalization otherwise; "" when even lexicalization fails.
std::string resolved_posix(const fs::path& path) {
    std::error_code ec;
    fs::path canonical = fs::weakly_canonical(path, ec);
    if (ec || canonical.empty()) {
        canonical = fs::absolute(path, ec);
        if (ec) return "";
        canonical = canonical.lexically_normal();
    }
    return canonical.generic_string();
}

// ---- identity proposals (_propose_identities) ----------------------------

std::string well_name_of(const domain::Json& wells, const std::string& well_id) {
    if (wells.is_array()) {
        for (const auto& well : wells) {
            if (well.is_object() &&
                well.value("id", std::string()) == well_id) {
                return well.value("name", well_id);
            }
        }
    }
    return well_id;
}

void propose_well_identity(PlannedItem& item, const WellRegistry& registry,
                           const domain::Json& project_root) {
    // Header-based extraction follows the engine-missing fallback (see
    // header): name comes from the directory-hint chain, so confidence is
    // medium on a match and low otherwise — exactly the Python fallback
    // branch when the LAS/WITSML engines are unavailable.
    const std::string hint = directory_hint(item.path);
    const std::string name = !hint.empty() ? hint : path_stem(item.path);
    const ResolutionOutcome outcome =
        resolve_well(project_root, &registry, name);
    if (outcome.matched) {
        item.identity.entity_type = "well";
        item.identity.entity_id = outcome.well_id;
        item.identity.entity_name = name;
        item.identity.strategy = outcome.strategy;
        item.identity.confidence = "medium";
    } else if (outcome.ambiguous) {
        item.identity.entity_type = "well";
        item.identity.entity_name = name;
        item.identity.strategy = "ambiguous";
        item.identity.confidence = "low";
        const Json empty_wells = Json::array();
        const Json& wells = project_root.contains("wells") &&
                                    project_root["wells"].is_array()
                                ? project_root["wells"]
                                : empty_wells;
        for (const std::string& candidate : outcome.candidates) {
            Json entry = Json::object();
            entry["well_id"] = candidate;
            entry["name"] = well_name_of(wells, candidate);
            item.identity.candidates.push_back(std::move(entry));
        }
    } else {
        item.identity.entity_type = "well";
        item.identity.entity_name = name;
        item.identity.new_entity = true;
        item.identity.strategy = "directory_hint";
        item.identity.confidence = "low";
    }
}

void propose_survey_identity(PlannedItem& item, const SurveyRegistry& registry) {
    const std::string stem = path_stem(item.path);
    if (const SurveyRecord* survey = registry.by_key(stem)) {
        item.identity.entity_type = "seismic_survey";
        item.identity.entity_id = survey->id;
        item.identity.entity_name = survey->name;
        item.identity.strategy = "canonical_name";
        item.identity.confidence = "medium";
    } else {
        item.identity.entity_type = "seismic_survey";
        item.identity.entity_name = stem;
        item.identity.new_entity = true;
        item.identity.strategy = "file_stem";
        item.identity.confidence = "low";
    }
}

void propose_geological_identity(PlannedItem& item) {
    item.identity.entity_type = "geological_entity";
    item.identity.entity_name = path_stem(item.path);
    item.identity.new_entity = true;
    item.identity.strategy = "file_stem";
    item.identity.confidence = "low";
}

// ---- duplicate detection (_match_duplicates) ------------------------------

struct DuplicateIndexes {
    // sha -> (asset_id, version_id)
    std::map<std::string, std::pair<std::string, std::string>> sha_index;
    // resolved external path -> (asset_id, version_id)
    std::map<std::string, std::pair<std::string, std::string>> external_index;
    // (resolved source path, sha) -> (asset_id, version_id): the catalog's
    // own managed-RAW identity, one entry PER PAIR.
    std::map<std::pair<std::string, std::string>,
             std::pair<std::string, std::string>>
        identity_index;
    // version_id -> size (for same-size notes)
    std::map<std::string, std::optional<std::int64_t>> size_of;
};

DuplicateIndexes build_duplicate_indexes(const catalog::CatalogDocument& doc) {
    DuplicateIndexes indexes;
    for (const auto& version : doc.versions) {
        if (version.trashed) continue;
        indexes.size_of[version.id.str()] = version.size_bytes;
        if (!version.managed) {
            if (!version.path.empty()) {
                const std::string key = resolved_posix(
                    pwb::project::path_from_u8(version.path));
                if (!key.empty()) {
                    indexes.external_index.emplace(
                        key, std::make_pair(version.asset_id.str(),
                                            version.id.str()));
                }
            }
            continue;
        }
        if (version.stage != domain::DataStage::Raw) continue;
        if (version.sha256.has_value()) {
            indexes.sha_index.emplace(
                *version.sha256,
                std::make_pair(version.asset_id.str(), version.id.str()));
            if (version.source_uri.has_value()) {
                const std::string key = resolved_posix(
                    pwb::project::path_from_u8(*version.source_uri));
                if (!key.empty()) {
                    indexes.identity_index.emplace(
                        std::make_pair(key, *version.sha256),
                        std::make_pair(version.asset_id.str(),
                                        version.id.str()));
                }
            }
        }
    }
    return indexes;
}

bool same_size(const DuplicateIndexes& indexes, const std::string& version_id,
               const std::optional<std::int64_t>& size) {
    if (!size.has_value()) return false;
    auto it = indexes.size_of.find(version_id);
    return it != indexes.size_of.end() && it->second.has_value() &&
           *it->second == *size;
}

}  // namespace

std::string BundleSuggestion::primary_path() const {
    for (const std::string& member : member_paths) {
        if (path_suffix(fs::path(member)) == ".shp") return member;
    }
    return member_paths.empty() ? std::string() : member_paths.front();
}

std::vector<const PlannedItem*> IngestPlan::unresolved() const {
    std::vector<const PlannedItem*> found;
    for (const auto& item : items) {
        if (item.identity.strategy == "ambiguous") found.push_back(&item);
    }
    return found;
}

std::vector<const PlannedItem*> IngestPlan::duplicates() const {
    std::vector<const PlannedItem*> found;
    for (const auto& item : items) {
        if (!item.duplicate_of_version.empty()) found.push_back(&item);
    }
    return found;
}

Json IngestPlan::summary() const {
    Json summary = Json::object();
    summary["total"] = static_cast<std::int64_t>(items.size());
    summary["duplicates"] = static_cast<std::int64_t>(duplicates().size());
    summary["unresolved"] = static_cast<std::int64_t>(unresolved().size());
    std::int64_t bundles = 0;
    for (const auto& item : items) {
        if (item.bundle.has_value() &&
            item.bundle->primary_path() == generic_string(item.path)) {
            ++bundles;
        }
    }
    summary["bundles"] = bundles;
    return summary;
}

Json IngestPlan::to_json() const {
    Json nodes = Json::array();
    for (const auto& item : this->items) {
        Json node = Json::object();
        node["path"] = generic_string(item.path);
        node["type"] = item.type;
        node["format"] = item.format;
        node["size_bytes"] = item.size_bytes.has_value()
                                 ? Json(*item.size_bytes)
                                 : Json(nullptr);
        node["sha256"] = item.sha256.has_value() ? Json(*item.sha256)
                                                 : Json(nullptr);
        if (item.bundle.has_value()) {
            Json bundle = Json::object();
            bundle["member_paths"] = Json::array();
            for (const std::string& member : item.bundle->member_paths) {
                bundle["member_paths"].push_back(member);
            }
            bundle["kind"] = item.bundle->kind;
            node["bundle"] = std::move(bundle);
        } else {
            node["bundle"] = nullptr;
        }
        Json identity = Json::object();
        identity["entity_type"] = item.identity.entity_type;
        identity["entity_id"] = item.identity.entity_id.empty()
                                    ? Json(nullptr)
                                    : Json(item.identity.entity_id);
        identity["entity_name"] = item.identity.entity_name;
        identity["new_entity"] = item.identity.new_entity;
        identity["strategy"] = item.identity.strategy;
        identity["confidence"] = item.identity.confidence;
        identity["candidates"] = Json::array();
        for (const auto& candidate : item.identity.candidates) {
            identity["candidates"].push_back(candidate);
        }
        node["identity"] = std::move(identity);
        node["role"] = item.role;
        node["primary"] = item.primary;
        node["duplicate_of_version"] = item.duplicate_of_version.empty()
                                           ? Json(nullptr)
                                           : Json(item.duplicate_of_version);
        node["duplicate_of_asset"] = item.duplicate_of_asset.empty()
                                         ? Json(nullptr)
                                         : Json(item.duplicate_of_asset);
        node["decision"] = item.decision;
        node["note"] = item.note;
        nodes.push_back(std::move(node));
    }
    Json plan = Json::object();
    plan["root"] = generic_string(root);
    plan["items"] = std::move(nodes);
    plan["issues"] = Json::array();
    for (const std::string& issue : issues) plan["issues"].push_back(issue);
    return plan;
}

IngestPlan build_ingest_plan(const fs::path& root,
                             const project::ProjectDocument& project,
                             const IngestPlanOptions& options) {
    IngestPlan plan;
    plan.root = root;
    std::error_code ec;
    const bool root_is_dir = fs::is_directory(root, ec) && !ec;
    std::vector<fs::path> files;
    if (root_is_dir) {
        for (const fs::path& entry : sorted_tree_entries(root)) {
            if (is_candidate_file(entry)) files.push_back(entry);
        }
    } else if (is_candidate_file(root)) {
        files.push_back(root);
    }

    // ---- family grouping (shapefile) on the UNFILTERED candidate set -----
    std::map<std::pair<std::string, std::string>, std::vector<fs::path>>
        by_stem_dir;
    for (const fs::path& path : files) {
        if (is_shapefile_member_extension(path_suffix(path))) {
            by_stem_dir[{path.parent_path().string(), path_stem(path)}]
                .push_back(path);
        }
    }
    std::set<std::string> family_paths;
    std::map<std::string, BundleSuggestion> family_of;
    for (const auto& [dir_stem, members] : by_stem_dir) {
        (void)dir_stem;
        std::set<std::string> extensions;
        for (const fs::path& member : members) {
            extensions.insert(path_suffix(member));
        }
        bool has_shp = extensions.count(".shp") > 0;
        bool required = true;
        for (const char* ext : kShapefileRequired) {
            if (extensions.count(ext) == 0) required = false;
        }
        if (has_shp && required) {
            BundleSuggestion suggestion;
            // Members share the parent directory, so byte order over the
            // member strings equals PurePath part-wise order here.
            std::vector<fs::path> sorted_members = members;
            std::sort(sorted_members.begin(), sorted_members.end(),
                      [](const fs::path& a, const fs::path& b) {
                          return generic_string(a) < generic_string(b);
                      });
            for (const fs::path& member : sorted_members) {
                suggestion.member_paths.push_back(generic_string(member));
            }
            suggestion.kind = "shapefile_family";
            for (const fs::path& member : members) {
                family_of[generic_string(member)] = suggestion;
                family_paths.insert(generic_string(member));
            }
        }
    }

    if (options.preferred_only) {
        files.erase(std::remove_if(files.begin(), files.end(),
                                   [&](const fs::path& path) {
                                       const std::string key =
                                           generic_string(path);
                                       if (family_paths.count(key) > 0) {
                                           return false;
                                       }
                                       std::string ext = path_suffix(path);
                                       if (!ext.empty() && ext.front() == '.') {
                                           ext.erase(0, 1);
                                       }
                                       return !pwb::ingest::
                                           is_preferred_import_extension(ext);
                                   }),
                    files.end());
    }
    const std::size_t total = files.size();

    for (std::size_t index = 0; index < files.size(); ++index) {
        const fs::path& path = files[index];
        if (options.cancel && options.cancel()) {
            plan.issues.push_back("计划构建被取消（部分结果）");
            break;
        }
        if (options.progress) {
            options.progress(static_cast<int>(index),
                             static_cast<int>(total));
        }
        const std::string sniff = path_suffix(path) == ".xml"
                                      ? read_sniff_bytes(path)
                                      : std::string();
        const pwb::ingest::Classification classification =
            pwb::ingest::classify_import_path(path.string(), sniff);
        PlannedItem item;
        item.path = path;
        item.type = classification.type;
        item.format = classification.format;
        const std::string role = infer_role_for_type(
            classification.type, path_suffix(path),
            path.filename().string());
        item.role = role.empty() ? std::string("other") : role;
        if (classification.status != "indexed") {
            item.note = "classify status: " + classification.status;
        }
        std::error_code stat_ec;
        const std::uintmax_t size = fs::file_size(path, stat_ec);
        if (stat_ec) {
            plan.issues.push_back(path.filename().string() + ": stat failed");
            continue;
        }
        item.size_bytes = static_cast<std::int64_t>(size);
        auto family = family_of.find(generic_string(path));
        if (family != family_of.end()) {
            item.bundle = family->second;
            if (item.type == "unknown") item.type = "geojson";
        }
        if (*item.size_bytes > 0 &&
            static_cast<std::uintmax_t>(*item.size_bytes) <=
                kPlanHashLimitBytes) {
            if (auto digest = domain::Sha256::of_file(path)) {
                item.sha256 = *digest;
            } else {
                plan.issues.push_back(path.filename().string() +
                                      " 哈希失败");
            }
        }
        plan.items.push_back(std::move(item));
    }

    // ---- identity matching -----------------------------------------------
    const Json& root_json = project.root();
    const Json empty_array = Json::array();
    const Json& wells = root_json.contains("wells") &&
                                root_json["wells"].is_array()
                            ? root_json["wells"]
                            : empty_array;
    // One registry for the whole pass (Python rebuilds per item — a pure
    // read view, so hoisting is semantically identical).
    const WellRegistry well_registry(wells);
    const SurveyRegistry survey_registry(
        root_json.contains("seismic_surveys") &&
                root_json["seismic_surveys"].is_array()
            ? root_json["seismic_surveys"]
            : empty_array);
    for (auto& item : plan.items) {
        const bool well_bound_type =
            item.type == "well_log" || item.type == "well_head" ||
            item.type == "well_stratification" || item.type == "time_depth";
        const bool generic_role_chain =
            (item.role == "trajectory" || item.role == "tops" ||
             item.role == "time_depth" || item.role == "core") &&
            (item.type == "table" || item.type == "tabular" ||
             item.type == "spreadsheet" || item.type == "csv" ||
             item.type == "unknown");
        const bool survey_bound_type =
            item.type == "seismic" || item.type == "segy";
        if (well_bound_type || generic_role_chain) {
            propose_well_identity(item, well_registry, root_json);
        } else if (survey_bound_type) {
            propose_survey_identity(item, survey_registry);
        } else if (item.type == "horizon" || item.type == "fault" ||
                   item.type == "faults" ||
                   item.type == "well_stratification") {
            propose_geological_identity(item);
        } else {
            item.identity.entity_type = "";
            item.identity.strategy = "none";
        }
    }

    // ---- duplicate matching against the catalog ---------------------------
    if (options.catalog != nullptr) {
        const DuplicateIndexes indexes =
            build_duplicate_indexes(*options.catalog);
        for (auto& item : plan.items) {
            if (item.decision != "pending") continue;
            const std::string source_key = resolved_posix(item.path);
            std::pair<std::string, std::string> hit{"", ""};
            bool have_hit = false;
            if (item.sha256.has_value() && !source_key.empty()) {
                // Duplicate = same content AND same source location; same
                // content from a DIFFERENT source is a distinct RAW.
                auto it = indexes.identity_index.find(
                    {source_key, *item.sha256});
                if (it != indexes.identity_index.end()) {
                    hit = it->second;
                    have_hit = true;
                }
            }
            if (!have_hit && !source_key.empty()) {
                // External link at the same path: NOTE ONLY — content is
                // unverifiable for externals, the decision stays with the
                // caller. (Python also probes a managed-path index that it
                // never populates — dead branch, not carried.)
                auto external = indexes.external_index.find(source_key);
                if (external != indexes.external_index.end() &&
                    same_size(indexes, external->second.second,
                              item.size_bytes)) {
                    item.note = (item.note.empty() ? "" : item.note + " ") +
                                "同源外部引用 " + external->second.first +
                                "（内容未验证）";
                }
            }
            if (have_hit) {
                item.duplicate_of_asset = hit.first;
                item.duplicate_of_version = hit.second;
                item.decision = "skip";
                item.note = (item.note.empty() ? "" : item.note + " ") +
                            "内容与来源均与已导入 RAW 相同";
            }
        }
    }

    // ---- primary selection proposal ---------------------------------------
    std::set<std::tuple<std::string, std::string, std::string>> seen;
    for (auto& item : plan.items) {
        if (item.identity.entity_id.empty()) continue;
        if (item.decision != "pending") continue;
        const auto key = std::make_tuple(item.identity.entity_type,
                                         item.identity.entity_id, item.role);
        if (seen.count(key) == 0 &&
            asset_ids_for_entity(root_json, item.identity.entity_type,
                                 item.identity.entity_id, item.role)
                .empty()) {
            item.primary = true;
            seen.insert(key);
        }
    }
    return plan;
}

}  // namespace pwb::data
