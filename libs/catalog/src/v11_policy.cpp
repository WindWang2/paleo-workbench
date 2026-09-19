#include "pwb/catalog/v11_policy.hpp"

#include <algorithm>
#include <map>
#include <set>

namespace pwb::catalog {

namespace {
std::string py_repr(std::string_view text) {
    std::string out = "'";
    for (char c : text) {
        if (c == '\\' || c == '\'') out.push_back('\\');
        out.push_back(c);
    }
    out.push_back('\'');
    return out;
}

std::string posix_base_name(const std::string& rel) {
    auto slash = rel.find_last_of('/');
    return slash == std::string::npos ? rel : rel.substr(slash + 1);
}
}  // namespace

std::string default_retention_for_stage(domain::DataStage stage) {
    switch (stage) {
        case domain::DataStage::Raw: return "retain";
        case domain::DataStage::Intermediate: return "recomputable";
        case domain::DataStage::Derived: return "user";
        case domain::DataStage::Output: return "user";
    }
    return "retain";
}

domain::Result<std::vector<RunPort>> coerce_ports(const domain::Json& ports,
                                                  const std::string& direction) {
    std::vector<RunPort> out;
    if (ports.is_null()) return out;
    if (!ports.is_array()) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "port specs must be a list");
    }
    for (const auto& item : ports) {
        if (!item.is_object()) {
            return domain::DataError(domain::ErrorCode::InvalidArgument,
                                     "Invalid port spec: " + item.dump());
        }
        RunPort port;
        port.role = item.value("role", direction);
        if (item.contains("version_id") && item["version_id"].is_string()) {
            port.version_id = domain::VersionId(item["version_id"].get<std::string>());
        }
        port.ordinal = item.value("ordinal", 0);
        port.required = item.value("required", true);
        if (item.contains("entity_type") && item["entity_type"].is_string()) {
            port.entity_type = item["entity_type"].get<std::string>();
        }
        if (item.contains("entity_id") && item["entity_id"].is_string()) {
            port.entity_id = item["entity_id"].get<std::string>();
        }
        if (item.contains("note") && item["note"].is_string()) {
            port.note = item["note"].get<std::string>();
        }
        out.push_back(std::move(port));
    }
    return out;
}

domain::DataError apply_run_ports(
    DataRun* run, const DocumentIndex* index,
    const std::optional<std::vector<RunPort>>& input_ports,
    const std::optional<std::vector<RunPort>>& output_ports) {
    const std::size_t total = (input_ports ? input_ports->size() : run->input_ports.size()) +
                              (output_ports ? output_ports->size() : run->output_ports.size());
    if (static_cast<int>(total) > kMaxRunPorts) {
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "Run " + run->id.str() + " exceeds the port budget (" +
                std::to_string(total) + " > " + std::to_string(kMaxRunPorts) + ")");
    }
    if (index != nullptr) {
        domain::DataError port_error(domain::ErrorCode::Ok, "");
        auto check_ports = [&](const std::optional<std::vector<RunPort>>& list) {
            if (!list.has_value()) return;
            for (const auto& port : *list) {
                if (index->version(port.version_id.str()) == nullptr) {
                    port_error = domain::DataError(
                        domain::ErrorCode::InvalidArgument,
                        "Port references unknown version " + port.version_id.str());
                }
            }
        };
        check_ports(input_ports);
        check_ports(output_ports);
        if (!port_error.ok()) return port_error;
    }
    if (input_ports.has_value()) {
        run->input_ports = *input_ports;
        for (const auto& port : run->input_ports) {
            const auto& flat = run->input_version_ids;
            if (std::find(flat.begin(), flat.end(), port.version_id) == flat.end()) {
                run->input_version_ids.push_back(port.version_id);
            }
        }
    }
    if (output_ports.has_value()) {
        run->output_ports = *output_ports;
        for (const auto& port : run->output_ports) {
            const auto& flat = run->output_version_ids;
            if (std::find(flat.begin(), flat.end(), port.version_id) == flat.end()) {
                run->output_version_ids.push_back(port.version_id);
            }
        }
    }
    return domain::DataError(domain::ErrorCode::Ok, "");
}

RunPortsView ports_for_run(const DataRun& run) {
    RunPortsView view;
    if (!run.input_ports.empty()) {
        view.input = run.input_ports;
    } else {
        for (const auto& vid : run.input_version_ids) {
            RunPort port;
            port.role = "input";
            port.version_id = vid;
            port.required = true;
            view.input.push_back(port);
        }
    }
    if (!run.output_ports.empty()) {
        view.output = run.output_ports;
    } else {
        for (const auto& vid : run.output_version_ids) {
            RunPort port;
            port.role = "output";
            port.version_id = vid;
            port.required = true;
            view.output.push_back(port);
        }
    }
    return view;
}

std::vector<RunPort> inputs_by_role(const DataRun& run, const std::string& role) {
    std::vector<RunPort> out;
    for (const auto& port : ports_for_run(run).input) {
        if (port.role == role) out.push_back(port);
    }
    return out;
}

std::vector<const DataRun*> runs_consuming(const CatalogDocument& document,
                                           const DocumentIndex& index,
                                           const std::optional<std::string>& role,
                                           const std::optional<std::string>& version_id) {
    (void)index;
    std::vector<const DataRun*> out;
    for (const auto& run : document.runs) {
        const bool has_ports = !run.input_ports.empty();
        if (!has_ports && version_id.has_value()) {
            const auto& flat = run.input_version_ids;
            if (std::find(flat.begin(), flat.end(), domain::VersionId(*version_id)) != flat.end()) {
                out.push_back(&run);
                continue;
            }
        }
        for (const auto& port : run.input_ports) {
            if (role.has_value() && port.role != *role) continue;
            if (version_id.has_value() && port.version_id.str() != *version_id) continue;
            out.push_back(&run);
            break;
        }
    }
    return out;
}

const std::vector<std::pair<std::string, std::string>>& operation_output_roles() {
    static const std::vector<std::pair<std::string, std::string>> kTable = {
        {"prediction", "prediction"},
        {"factor_map", "factor_grid"},
        {"factor_fusion", "fusion_result"},
        {"map_compile", "map_product"},
        {"time_depth_calibration", "calibrated_td"},
        {"stratigraphic_correlation", "correlation"},
        {"fault_interpretation", "interpretation"},
        {"horizon_interpretation", "interpretation"},
        {"qc", "qc_report"},
        {"export", "export"},
    };
    return kTable;
}

PortBackfillCounts migrate_run_ports(CatalogDocument* document,
                                     const DocumentIndex& index) {
    PortBackfillCounts counts;
    std::map<std::string, std::string> table(operation_output_roles().begin(),
                                              operation_output_roles().end());
    for (auto& run : document->runs) {
        if (!run.output_ports.empty()) continue;
        auto it = table.find(run.operation);
        if (it == table.end()) continue;
        std::vector<domain::VersionId> known;
        for (const auto& vid : run.output_version_ids) {
            if (index.version(vid.str()) != nullptr) known.push_back(vid);
        }
        if (known.empty()) continue;
        run.output_ports.clear();
        int ordinal = 0;
        for (const auto& vid : known) {
            RunPort port;
            port.role = it->second;
            port.version_id = vid;
            port.ordinal = ordinal++;
            run.output_ports.push_back(port);
        }
        counts.runs_annotated += 1;
        counts.ports_added += static_cast<int>(run.output_ports.size());
    }
    return counts;
}

domain::Result<BundleMemberPlan> plan_bundle_members(
    const std::vector<std::string>& source_rel_paths,
    const std::vector<VersionMember>& member_specs) {
    if (source_rel_paths.empty()) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "Bundle source directory is empty: <dir>");
    }
    if (static_cast<int>(source_rel_paths.size()) > kMaxBundleMembers) {
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "Bundle exceeds member budget (" +
                std::to_string(source_rel_paths.size()) + " > " +
                std::to_string(kMaxBundleMembers) +
                "); split the directory or import as separate assets");
    }
    std::map<std::string, VersionMember> spec_by_rel;
    for (const auto& spec : member_specs) {
        std::string rel = spec.rel_path;
        if (spec_by_rel.count(rel)) {
            return domain::DataError(domain::ErrorCode::InvalidArgument,
                                     "Duplicate member rel_path: " + rel);
        }
        spec_by_rel.emplace(rel, spec);
    }
    std::set<std::string> source(source_rel_paths.begin(), source_rel_paths.end());
    std::vector<std::string> unexpected;
    for (const auto& [rel, spec] : spec_by_rel) {
        (void)spec;
        if (!source.count(rel)) unexpected.push_back(rel);
    }
    if (!unexpected.empty()) {
        std::string listed = "[";
        for (std::size_t i = 0; i < unexpected.size(); ++i) {
            if (i) listed += ", ";
            listed += "'" + unexpected[i] + "'";
        }
        listed += "]";
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "Member specs reference missing files: " + listed);
    }
    std::set<std::string> used_names;
    std::map<std::string, std::string> auto_names;
    std::vector<std::string> sorted_paths(source.begin(), source.end());
    for (const auto& rel : sorted_paths) {
        auto spec = spec_by_rel.find(rel);
        if (spec != spec_by_rel.end()) {
            if (used_names.count(spec->second.name)) {
                return domain::DataError(domain::ErrorCode::InvalidArgument,
                                         "Duplicate member name " +
                                             py_repr(spec->second.name) + " in specs");
            }
            used_names.insert(spec->second.name);
            continue;
        }
        std::vector<std::string> candidates = {posix_base_name(rel), rel};
        bool assigned = false;
        for (const auto& candidate : candidates) {
            if (!candidate.empty() && !used_names.count(candidate)) {
                used_names.insert(candidate);
                auto_names[rel] = candidate;
                assigned = true;
                break;
            }
        }
        if (!assigned) {
            std::string base = posix_base_name(rel);
            int suffix = 2;
            while (used_names.count(base + "~" + std::to_string(suffix))) ++suffix;
            auto_names[rel] = base + "~" + std::to_string(suffix);
            used_names.insert(auto_names[rel]);
        }
    }
    BundleMemberPlan plan;
    for (const auto& rel : sorted_paths) {
        auto spec = spec_by_rel.find(rel);
        plan.names.emplace_back(rel, spec != spec_by_rel.end() ? spec->second.name
                                                              : auto_names[rel]);
    }
    return plan;
}

bool is_pinned(const DataVersion& version) {
    return version.metadata.is_object() && version.metadata.contains("pin") &&
           version.metadata["pin"].is_object() && !version.metadata["pin"].empty();
}

void apply_pin(DataVersion* version, const std::string& reason,
               const std::string& pinned_at_iso) {
    if (!version->metadata.is_object()) version->metadata = domain::Json::object();
    domain::Json pin = domain::Json::object();
    pin["reason"] = reason;
    pin["pinned_at"] = pinned_at_iso;
    version->metadata["pin"] = std::move(pin);
}

void apply_unpin(DataVersion* version) {
    if (version->metadata.is_object() && version->metadata.contains("pin")) {
        version->metadata.erase("pin");
    }
}

domain::DataError validate_retention_class(const std::string& retention_class) {
    for (std::string_view allowed : kRetentionClasses) {
        if (retention_class == allowed) return domain::DataError(domain::ErrorCode::Ok, "");
    }
    std::string expected = "(";
    for (std::size_t i = 0; i < std::size(kRetentionClasses); ++i) {
        if (i) expected += ", ";
        expected += "'" + std::string(kRetentionClasses[i]) + "'";
    }
    expected += ")";
    // Python: f"Unknown retention class {rc!r}; expected one of {tuple}"
    return domain::DataError(domain::ErrorCode::InvalidArgument,
                             "Unknown retention class " + py_repr(retention_class) +
                                 "; expected one of " + expected);
}

std::string retention_class_of(const DataVersion& version) {
    if (version.metadata.is_object() && version.metadata.contains("retention_class")) {
        const auto& stored = version.metadata["retention_class"];
        if (stored.is_string()) {
            const std::string value = stored.get<std::string>();
            for (std::string_view allowed : kRetentionClasses) {
                if (value == allowed) return value;
            }
            if (!value.empty()) return "retain";  // unknown → conservative
        }
    }
    return default_retention_for_stage(version.stage);
}

CleanupEligibility cleanup_eligibility(const CatalogDocument& document,
                                        const DocumentIndex& index,
                                        const std::string& version_id,
                                        bool live_working_copy) {
    CleanupEligibility out;
    out.version_id = version_id;
    const DataVersion* version = index.version(version_id);
    if (version == nullptr) return out;
    out.retention_class = retention_class_of(*version);
    if (out.retention_class == "retain" || out.retention_class == "user") {
        out.blockers.push_back("retention_class=" + out.retention_class);
    }
    if (version->stage == domain::DataStage::Raw) {
        out.blockers.push_back("raw_stage");
    }
    if (is_pinned(*version)) {
        out.blockers.push_back("pinned");
    }
    int live_children = 0;
    if (const auto* children = index.children_of(version_id)) {
        for (const DataVersion* child : *children) {
            if (!child->trashed) ++live_children;
        }
    }
    out.downstream_count = live_children;
    if (live_children > 0) {
        out.blockers.push_back("downstream_versions=" + std::to_string(live_children));
    }
    if (live_working_copy) {
        out.blockers.push_back("live_working_copy");
    }
    if (version->trashed) {
        out.blockers.push_back("already_trashed");
    }
    out.eligible = out.blockers.empty();
    (void)document;
    return out;
}

domain::Json version_lifecycle_status(const CatalogDocument& document,
                                       const DocumentIndex& index,
                                       const std::string& version_id,
                                       bool live_working_copy) {
    const DataVersion* version = index.version(version_id);
    if (version == nullptr) return domain::Json();
    const DataRun* producing =
        version->run_id ? index.run(version->run_id->str()) : nullptr;
    int dependent_runs = 0;
    for (const auto& run : document.runs) {
        const auto& flat = run.input_version_ids;
        if (std::find(flat.begin(), flat.end(), version->id) != flat.end()) {
            ++dependent_runs;
        }
    }
    int downstream = 0;
    if (const auto* children = index.children_of(version_id)) {
        downstream = static_cast<int>(children->size());
    }
    domain::Json out = domain::Json::object();
    out["version_id"] = version_id;
    out["asset_id"] = version->asset_id.str();
    out["stage"] = std::string(domain::to_string(version->stage));
    out["bundle"] = !version->members.empty();
    out["member_count"] = version->members.size();
    out["retention_class"] = retention_class_of(*version);
    out["pinned"] = is_pinned(*version);
    out["trashed"] = version->trashed;
    out["live_working_copy"] = live_working_copy;
    out["producing_run_id"] = version->run_id.has_value()
                                  ? domain::Json(version->run_id->str())
                                  : domain::Json();
    out["producing_operation"] =
        producing != nullptr ? domain::Json(producing->operation) : domain::Json();
    out["recomputable"] = producing != nullptr;
    out["dependent_run_count"] = dependent_runs;
    out["downstream_count"] = downstream;
    return out;
}

}  // namespace pwb::catalog
