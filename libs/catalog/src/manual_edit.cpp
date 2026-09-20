// Manual-edit provenance — see manual_edit.hpp. Branches mirror
// paleo_workbench/catalog/lifecycle.py:1046-1122 (register/complete) and
// the _BUSINESS_ROLE_TO_PORT_ROLE table (:1026).
#include "pwb/catalog/manual_edit.hpp"

#include "pwb/catalog/refs.hpp"

#include <map>

namespace pwb::catalog {

namespace {

// lifecycle.py _BUSINESS_ROLE_TO_PORT_ROLE — open vocabulary, unknown
// roles pass through verbatim (port_role_for_business_role).
const std::map<std::string, std::string>& business_role_to_port_role() {
    static const std::map<std::string, std::string> table = {
        {"well_log", "well_logs"},
        {"trajectory", "trajectory"},
        {"tops", "tops"},
        {"time_depth", "time_depth"},
        {"seismic_volume", "seismic_volume"},
        {"horizon", "horizon"},
        {"fault", "faults"},
        {"interpretation", "interpretation"},
    };
    return table;
}

std::string trimmed(std::string_view text) {
    std::size_t begin = 0;
    while (begin < text.size() &&
           (text[begin] == ' ' || text[begin] == '\t')) {
        ++begin;
    }
    std::size_t end = text.size();
    while (end > begin &&
           (text[end - 1] == ' ' || text[end - 1] == '\t')) {
        --end;
    }
    return std::string(text.substr(begin, end - begin));
}

}  // namespace

std::string port_role_for_business_role(std::string_view business_role) {
    const std::string key = trimmed(business_role);
    if (key.empty()) return std::string();
    const auto& table = business_role_to_port_role();
    if (auto it = table.find(key); it != table.end()) return it->second;
    return key;
}

domain::Result<DataRun> build_manual_edit_run(const CatalogDocument& document,
                                              const ManualEditRequest& request) {
    DataRun run;
    run.id = domain::RunId(new_ref_id("run"));
    run.operation = std::string(kManualEditOperation);
    run.generator = std::string(kManualEditGenerator);
    run.status = "running";
    run.created_at = utc_now_iso();

    // Validation: every source id must reference a known version. There is
    // no "committed" flag on versions in this store — existence IS the
    // committed contract (immutable ids; working-copy payloads are never
    // registered as versions). Unknown ids fail closed with the id list.
    std::map<std::string, const DataVersion*> versions_by_id;
    for (const auto& version : document.versions) {
        versions_by_id.emplace(version.id.str(), &version);
    }
    std::vector<std::string> unknown;
    for (const auto& raw : request.source_version_ids) {
        if (raw.empty()) continue;  // lifecycle.py drops empty strings
        run.input_version_ids.push_back(domain::VersionId(raw));
        if (versions_by_id.find(raw) == versions_by_id.end()) {
            unknown.push_back(raw);
        }
    }
    if (!unknown.empty()) {
        std::string joined;
        for (const auto& id : unknown) {
            if (!joined.empty()) joined += ", ";
            joined += id;
        }
        return domain::DataError{domain::ErrorCode::NotFound,
                                 "manual_edit source version(s) not found: " +
                                     joined};
    }

    domain::Json parameters = domain::Json::object();
    parameters["entity_type"] = request.entity_type;
    parameters["entity_id"] = request.entity_id;
    parameters["business_role"] = request.business_role;
    parameters["as_new_asset"] = request.as_new_asset;
    if (!request.actor.empty()) parameters["actor"] = request.actor;
    if (!request.note.empty()) parameters["note"] = request.note;
    if (request.extra_parameters.is_object()) {
        for (auto it = request.extra_parameters.begin();
             it != request.extra_parameters.end(); ++it) {
            parameters[it.key()] = it.value();
        }
    }
    run.parameters = std::move(parameters);

    const std::string role =
        port_role_for_business_role(request.business_role);
    if (!role.empty()) {
        for (std::size_t i = 0; i < run.input_version_ids.size(); ++i) {
            RunPort port;
            port.direction = "input";
            port.role = role;
            port.version_id = run.input_version_ids[i];
            port.ordinal = static_cast<int>(i);
            port.required = true;
            run.input_ports.push_back(std::move(port));
        }
    }
    return run;
}

domain::Result<DataRun> apply_manual_edit_completion(
    const DataRun& run, const ManualEditCompletion& completion) {
    DataRun updated = run;

    std::vector<std::string> committed;
    for (const auto& raw : completion.committed_version_ids) {
        if (!raw.empty()) committed.push_back(raw);
    }
    if (committed.empty()) {
        // Compensation: no phantom RUNNING rows (lifecycle.py:1108).
        updated.status = "failed";
        return updated;
    }

    const std::string business_role =
        port_role_for_business_role(completion.business_role);
    if (!business_role.empty()) {
        // Output ports carry the MANUAL_EDIT role (lifecycle.py:1116 —
        // the business role only gates WHETHER ports are attached).
        updated.output_ports.clear();
        updated.output_version_ids.clear();
        for (std::size_t i = 0; i < committed.size(); ++i) {
            RunPort port;
            port.direction = "output";
            port.role = std::string("manual_edit");
            port.version_id = domain::VersionId(committed[i]);
            port.ordinal = static_cast<int>(i);
            port.required = true;
            updated.output_ports.push_back(std::move(port));
            updated.output_version_ids.push_back(
                domain::VersionId(committed[i]));
        }
    }
    updated.status = "complete";
    if (completion.failed_count != 0) {
        updated.parameters["failed_checkouts"] = completion.failed_count;
    }
    return updated;
}

}  // namespace pwb::catalog
