#include <pwb/workflow_runtime/run_orchestration.hpp>

#include <cctype>
#include <map>
#include <set>
#include <utility>

namespace pwb::workflow_runtime {

std::string begin_run(CatalogRepository& catalog, const RunSpec& spec) {
    return catalog.register_run(spec.operation, spec.input_version_ids,
                                spec.parameters, spec.generator_version,
                                "running", spec.domain_task_id,
                                spec.input_snapshot_hash, spec.actor);
}

void complete_run(CatalogRepository& catalog, const std::string& run_id) {
    catalog.update_run_status(run_id, "complete");
}

void fail_run(CatalogRepository& catalog, const std::string& run_id) noexcept {
    try {
        catalog.update_run_status(run_id, "failed");
    } catch (...) {
    }
}

void fail_run(CatalogRepository& catalog, const std::string& run_id,
              const Json& extra_parameters) noexcept {
    try {
        catalog.update_run_status(run_id, "failed", extra_parameters);
    } catch (...) {
        fail_run(catalog, run_id);
    }
}

void annotate_output_port(CatalogRepository& catalog,
                          const std::string& run_id,
                          const std::string& version_id,
                          const std::string& role) noexcept {
    if (run_id.empty() || version_id.empty()) return;
    try {
        catalog.set_run_ports(
            run_id, Json(),
            Json::array({{{"role", role}, {"version_id", version_id}}}));
    } catch (...) {
    }
}

void annotate_input_ports(
    CatalogRepository& catalog, const std::string& run_id,
    const std::vector<std::string>& version_ids, const std::string& role,
    const std::string& entity_type,
    const std::vector<std::string>& entity_ids) noexcept {
    if (run_id.empty() || version_ids.empty()) return;
    Json ports = Json::array();
    for (std::size_t ordinal = 0; ordinal < version_ids.size(); ++ordinal) {
        Json port = {{"role", role},
                     {"version_id", version_ids[ordinal]},
                     {"ordinal", ordinal}};
        if (!entity_type.empty() && ordinal < entity_ids.size()) {
            port["entity_type"] = entity_type;
            port["entity_id"] = entity_ids[ordinal];
        }
        ports.push_back(std::move(port));
    }
    try {
        catalog.set_run_ports(run_id, std::move(ports), Json());
    } catch (...) {
    }
}

std::vector<std::string> resolve_input_versions(
    CatalogRepository& catalog,
    const std::vector<std::string>& resource_ids) {
    std::vector<std::string> out;
    for (const std::string& rid : resource_ids) {
        const auto ref = catalog.resolve_legacy_resource(rid);
        if (ref.has_value()) out.push_back(ref->version_id);
    }
    return out;
}

// _versions_for_domain_tasks parity — propagates catalog errors (the
// `except Exception: return []` wrapper lives in the CALLER, e.g.
// compile_map_production._resolve_map_input_ids). Python dict insertion
// order for latest_complete: a sequence container, NOT std::map (which
// would sort by task id).
std::vector<std::string> versions_for_domain_tasks(
    const std::vector<std::string>& task_ids, CatalogRepository& catalog) {
    const std::set<std::string> wanted(task_ids.begin(), task_ids.end());
    if (wanted.empty()) return {};
    std::vector<std::pair<std::string, RunRecord>> latest_complete;
    std::map<std::string, RunRecord> latest_with_outputs;
    auto index_of = [&](const std::string& tid) -> std::size_t {
        for (std::size_t i = 0; i < latest_complete.size(); ++i) {
            if (latest_complete[i].first == tid) return i;
        }
        return latest_complete.size();
    };
    for (const RunRecord& run : catalog.list_runs()) {
        const std::string tid = run.domain_task_id.value_or("");
        if (!wanted.count(tid)) continue;
        std::string status = run.status;
        for (auto& c : status) {
            c = static_cast<char>(
                std::tolower(static_cast<unsigned char>(c)));
        }
        // _COMPLETE_RUN_STATUSES = {"complete", "completed"}
        if (status != "complete" && status != "completed") continue;
        const std::size_t slot = index_of(tid);
        if (slot == latest_complete.size()) {
            latest_complete.emplace_back(tid, run);
        } else {
            latest_complete[slot].second = run;
        }
        if (!run.output_version_ids.empty()) {
            latest_with_outputs[tid] = run;
        }
    }
    std::vector<std::string> out;
    std::set<std::string> seen;
    for (const auto& [tid, run] : latest_complete) {
        const auto with_out = latest_with_outputs.find(tid);
        const RunRecord& chosen_run =
            with_out != latest_with_outputs.end() ? with_out->second : run;
        const bool outputs = !chosen_run.output_version_ids.empty();
        const std::vector<std::string>& chosen =
            outputs ? chosen_run.output_version_ids
                    : chosen_run.input_version_ids;
        for (const std::string& vid : chosen) {
            if (seen.count(vid)) continue;
            if (outputs) {
                const auto ref = catalog.resolve_version(vid);
                // Withdrawn output must not enter a production run (H5-a).
                if (ref.has_value() && ref->trashed) continue;
            }
            seen.insert(vid);
            out.push_back(vid);
        }
    }
    return out;
}

}  // namespace pwb::workflow_runtime
