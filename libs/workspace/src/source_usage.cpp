// V14 source usage reverse query — port of source_usage.py (see
// source_usage.hpp).
#include "pwb/workspace/source_usage.hpp"

#include <tuple>

namespace pwb::workspace {

namespace {

// str(value or ""): absent/null/"" -> ""; strings kept; other scalars
// stringified via dump (closest honest mapping of Python str()).
std::string str_or_empty(const domain::Json& parent, const char* key) {
    if (!parent.is_object()) return "";
    auto it = parent.find(key);
    if (it == parent.end() || it->is_null()) return "";
    if (it->is_string()) return it->get<std::string>();
    if (it->is_number_integer()) return std::to_string(it->get<long long>());
    if (it->is_number_float()) return it->dump();
    if (it->is_boolean()) return it->get<bool>() ? "True" : "False";
    return "";
}

bool run_consumes(const UsageCatalog& catalog, const std::string& run_id,
                  const std::string& version_id) {
    const auto inputs = catalog.run_input_version_ids(run_id);
    if (!inputs.has_value()) return false;
    return std::find(inputs->begin(), inputs->end(), version_id) !=
           inputs->end();
}

std::vector<RunSummary> runs_consuming(const UsageCatalog& catalog,
                                       const std::string& version_id) {
    try {
        return catalog.runs_consuming(version_id);
    } catch (...) {
        return {};  // Python: except Exception -> []
    }
}

std::vector<std::string> versions_of_asset(const UsageCatalog& catalog,
                                           const std::string& asset_id) {
    try {
        return catalog.versions_of_asset(asset_id);
    } catch (...) {
        return {};  // Python: except Exception -> []
    }
}

}  // namespace

VersionUsageReport usages_of_version(
    const std::string& version_id, const MappingWorkspaceState* workspace,
    const domain::Json* project_root, const UsageCatalog* catalog,
    bool include_runs) {
    VersionUsageReport report;
    const std::string vid = version_id;
    if (vid.empty()) return report;
    auto& usages = report.usages;
    if (workspace != nullptr) {
        for (const auto& [layer_id, record] : workspace->memberships) {
            if (record.source_version_id != vid) continue;
            VersionUsage usage;
            usage.kind = std::string(kUsageLayer);
            usage.ref_id = layer_id;
            usage.label = "图层 " + layer_id;
            usage.version_id = vid;
            usage.stage = record.created_stage;
            usage.role = record.role;
            usages.push_back(std::move(usage));
        }
    }
    if (project_root != nullptr && project_root->is_object()) {
        if (project_root->contains("factor_map_tasks") &&
            (*project_root)["factor_map_tasks"].is_array()) {
            for (const auto& task : (*project_root)["factor_map_tasks"]) {
                if (str_or_empty(task, "grid_artifact_version_id") != vid) {
                    continue;
                }
                VersionUsage usage;
                usage.kind = std::string(kUsageFactorGrid);
                usage.ref_id = str_or_empty(task, "id");
                const std::string name = str_or_empty(task, "name");
                usage.label = name.empty() ? usage.ref_id : name;
                usage.version_id = vid;
                usage.role = "factor_grid";
                usages.push_back(std::move(usage));
            }
        }
        if (project_root->contains("compilation_input_sets") &&
            (*project_root)["compilation_input_sets"].is_array()) {
            for (const auto& raw : (*project_root)["compilation_input_sets"]) {
                if (!raw.is_object()) continue;
                const std::string set_id = str_or_empty(raw, "id");
                const std::string set_name = str_or_empty(raw, "name");
                const bool frozen = raw.value("frozen", false);
                if (!raw.contains("entries") || !raw["entries"].is_array()) {
                    continue;
                }
                for (const auto& entry : raw["entries"]) {
                    if (!entry.is_object()) continue;
                    if (str_or_empty(entry, "pinned_version_id") != vid) {
                        continue;
                    }
                    VersionUsage usage;
                    usage.kind = std::string(kUsageCompilationInput);
                    usage.ref_id = set_id;
                    usage.label = set_name.empty() ? set_id : set_name;
                    usage.version_id = vid;
                    usage.status = frozen ? "frozen" : "draft";
                    usages.push_back(std::move(usage));
                }
            }
        }
        if (project_root->contains("map_products") &&
            (*project_root)["map_products"].is_array()) {
            for (const auto& record : (*project_root)["map_products"]) {
                const std::string output_vid =
                    str_or_empty(record, "output_version_id");
                const std::string ref_id = str_or_empty(record, "id");
                const std::string product_name =
                    str_or_empty(record, "product_name");
                const std::string label =
                    product_name.empty() ? ref_id : product_name;
                const std::string lifecycle =
                    str_or_empty(record, "lifecycle");
                if (output_vid == vid) {
                    VersionUsage usage;
                    usage.kind = std::string(kUsageMapProductOutput);
                    usage.ref_id = ref_id;
                    usage.label = label;
                    usage.version_id = vid;
                    usage.status = lifecycle;
                    usages.push_back(std::move(usage));
                    continue;
                }
                const std::string run_id = str_or_empty(record, "run_id");
                if (!run_id.empty() && catalog != nullptr &&
                    run_consumes(*catalog, run_id, vid)) {
                    VersionUsage usage;
                    usage.kind = std::string(kUsageMapProductInput);
                    usage.ref_id = ref_id;
                    usage.label = label;
                    usage.version_id = vid;
                    usage.status = lifecycle;
                    usages.push_back(std::move(usage));
                }
            }
        }
    }
    if (include_runs && catalog != nullptr) {
        const std::vector<RunSummary> runs =
            runs_consuming(*catalog, vid);
        for (std::size_t index = 0; index < runs.size(); ++index) {
            if (index >= kMaxRunUsageEntries) {
                report.truncated = true;
                break;
            }
            VersionUsage usage;
            usage.kind = std::string(kUsageRunInput);
            usage.ref_id = runs[index].id;
            usage.label = "run " + runs[index].operation;
            usage.version_id = vid;
            usage.status = runs[index].status;
            usages.push_back(std::move(usage));
        }
    }
    return report;
}

VersionUsageReport usages_of_asset(const std::string& asset_id,
                                   const MappingWorkspaceState* workspace,
                                   const domain::Json* project_root,
                                   const UsageCatalog* catalog) {
    VersionUsageReport report;
    const std::string aid = asset_id;
    if (aid.empty()) return report;
    auto& usages = report.usages;
    std::vector<std::tuple<std::string, std::string, std::string>> seen;
    auto already_seen =
        [&seen](const std::string& kind, const std::string& ref_id,
                const std::string& version_id) {
            const std::tuple<std::string, std::string, std::string> key(
                kind, ref_id, version_id);
            if (std::find(seen.begin(), seen.end(), key) != seen.end()) {
                return true;
            }
            seen.push_back(key);
            return false;
        };
    if (catalog != nullptr) {
        // Versions of an asset are usually single-digit to a few dozen.
        for (const std::string& version_id :
             versions_of_asset(*catalog, aid)) {
            VersionUsageReport per_version = usages_of_version(
                version_id, workspace, project_root, catalog, false);
            for (auto& usage : per_version.usages) {
                if (!already_seen(usage.kind, usage.ref_id,
                                  usage.version_id)) {
                    usages.push_back(std::move(usage));
                }
            }
        }
    }
    if (workspace != nullptr) {
        for (const auto& [layer_id, record] : workspace->memberships) {
            if (record.source_asset_id != aid) continue;
            if (already_seen(std::string(kUsageLayer), layer_id,
                             record.source_version_id)) {
                continue;
            }
            VersionUsage usage;
            usage.kind = std::string(kUsageLayer);
            usage.ref_id = layer_id;
            usage.label = "图层 " + layer_id;
            usage.version_id = record.source_version_id;
            usage.stage = record.created_stage;
            usage.role = record.role;
            usages.push_back(std::move(usage));
        }
    }
    if (project_root != nullptr && project_root->is_object() &&
        project_root->contains("compilation_input_sets") &&
        (*project_root)["compilation_input_sets"].is_array()) {
        for (const auto& raw : (*project_root)["compilation_input_sets"]) {
            if (!raw.is_object()) continue;
            if (!raw.contains("entries") || !raw["entries"].is_array()) {
                continue;
            }
            for (const auto& entry : raw["entries"]) {
                if (!entry.is_object()) continue;
                if (str_or_empty(entry, "resolved_asset_id") != aid) {
                    continue;
                }
                const std::string set_id = str_or_empty(raw, "id");
                const std::string pinned =
                    str_or_empty(entry, "pinned_version_id");
                if (already_seen(std::string(kUsageCompilationInput),
                                 set_id, pinned)) {
                    continue;
                }
                VersionUsage usage;
                usage.kind = std::string(kUsageCompilationInput);
                usage.ref_id = set_id;
                const std::string set_name = str_or_empty(raw, "name");
                usage.label = set_name.empty() ? set_id : set_name;
                usage.version_id = pinned;
                usage.status =
                    raw.value("frozen", false) ? "frozen" : "draft";
                usages.push_back(std::move(usage));
            }
        }
    }
    return report;
}

std::map<std::string, std::size_t> usage_counts(
    const VersionUsageReport& report) {
    std::map<std::string, std::size_t> counts;
    for (const VersionUsage& usage : report.usages) {
        ++counts[usage.kind];
    }
    return counts;
}

}  // namespace pwb::workspace
