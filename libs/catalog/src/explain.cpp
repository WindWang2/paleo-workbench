#include "pwb/catalog/explain.hpp"

#include <algorithm>
#include <set>

namespace pwb::catalog {

namespace {
domain::Json run_port_to_json(const RunPort& port) {
    // RunPort.model_dump(): declared field order.
    domain::Json out = domain::Json::object();
    out["role"] = port.role;
    out["version_id"] = port.version_id.str();
    out["ordinal"] = port.ordinal;
    out["required"] = port.required;
    out["entity_type"] = port.entity_type;
    out["entity_id"] = port.entity_id;
    out["note"] = port.note;
    return out;
}
}  // namespace

domain::Json VersionExplanation::to_dict() const {
    domain::Json out = domain::Json::object();
    out["version_id"] = version_id;
    out["asset_id"] = asset_id;
    out["asset_name"] = asset_name;
    out["asset_type"] = asset_type;
    out["stage"] = stage;
    out["bundle"] = bundle;
    out["member_count"] = member_count;
    out["producing_run_id"] = producing_run_id.has_value()
                                  ? domain::Json(*producing_run_id)
                                  : domain::Json();
    out["operation"] =
        operation.has_value() ? domain::Json(*operation) : domain::Json();
    out["generator"] = generator;
    out["model_ref"] = model_ref.is_null() ? domain::Json() : model_ref;
    out["parameters"] = parameters;
    out["created_at"] = created_at;
    out["input_ports"] = input_ports;
    out["output_ports"] = output_ports;
    domain::Json parents = domain::Json::array();
    for (const auto& id : parent_version_ids) parents.push_back(id);
    out["parent_version_ids"] = parents;
    out["typed_lineage"] = typed_lineage;
    domain::Json entity_rows = domain::Json::array();
    for (const auto& [type, id] : entities) {
        domain::Json row = domain::Json::object();
        row["entity_type"] = type;
        row["entity_id"] = id;
        entity_rows.push_back(std::move(row));
    }
    out["entities"] = entity_rows;
    domain::Json downstream = domain::Json::array();
    for (const auto& id : downstream_version_ids) downstream.push_back(id);
    out["downstream_version_ids"] = downstream;
    domain::Json runs = domain::Json::array();
    for (const auto& id : downstream_run_ids) runs.push_back(id);
    out["downstream_run_ids"] = runs;
    out["deletable"] = deletable;
    domain::Json blockers = domain::Json::array();
    for (const auto& blocker : delete_blockers) blockers.push_back(blocker);
    out["delete_blockers"] = blockers;
    out["regenerable"] = regenerable;
    out["stale"] = stale;
    out["stale_reason"] = stale_reason;
    out["pinned"] = pinned;
    out["integrity_status"] = integrity_status;
    return out;
}

domain::Result<VersionExplanation> ExplainService::explain_version(
    const std::string& version_id,
    const std::vector<ImpactService::EntityLink>* entity_links,
    bool live_working_copy) {
    const DataVersion* version = index_.version(version_id);
    if (version == nullptr) {
        return domain::DataError(domain::ErrorCode::NotFound,
                                 "Unknown version: " + version_id);
    }
    const DataAsset* asset = index_.asset(version->asset_id.str());
    if (asset == nullptr) {
        return domain::DataError(domain::ErrorCode::NotFound,
                                 "Unknown asset: " + version->asset_id.str());
    }
    VersionExplanation explanation;
    explanation.version_id = version->id.str();
    explanation.asset_id = asset->id.str();
    explanation.asset_name = asset->name;
    explanation.asset_type = asset->type;
    explanation.stage = std::string(domain::to_string(version->stage));
    explanation.bundle = !version->members.empty();
    explanation.member_count = static_cast<int>(version->members.size());
    explanation.created_at = version->created_at;
    for (const auto& parent : version->parent_version_ids) {
        explanation.parent_version_ids.push_back(parent.str());
    }
    explanation.pinned = is_pinned(*version);

    // --- provenance --------------------------------------------------------
    const DataRun* run =
        version->run_id ? index_.run(version->run_id->str()) : nullptr;
    if (run != nullptr) {
        explanation.producing_run_id = run->id.str();
        explanation.operation = run->operation;
        explanation.generator = run->generator;
        explanation.model_ref = run->model_ref.value_or(domain::Json());
        explanation.parameters = run->parameters;
        RunPortsView ports = ports_for_run(*run);
        explanation.typed_lineage =
            !run->input_ports.empty() || !run->output_ports.empty();
        for (const auto& port : ports.input) {
            explanation.input_ports.push_back(run_port_to_json(port));
        }
        for (const auto& port : ports.output) {
            explanation.output_ports.push_back(run_port_to_json(port));
        }
    }
    explanation.regenerable = run != nullptr;

    // --- upstream closure (entity context rides the lineage) ----------------
    UpstreamImpact upstream = impact_.upstream_impact(version_id);

    if (entity_links != nullptr) {
        // Own asset first, then the ancestor closure's assets: results
        // usually carry no direct link — their wells/surveys answer through
        // lineage (goal §15 "which well/survey?").
        std::vector<std::string> ancestor_assets = upstream.ancestor_asset_ids;
        if (std::find(ancestor_assets.begin(), ancestor_assets.end(),
                      version->asset_id.str()) == ancestor_assets.end()) {
            ancestor_assets.push_back(version->asset_id.str());
        }
        std::set<std::pair<std::string, std::string>> seen_entities;
        for (const auto& related_asset : ancestor_assets) {
            for (const auto& link : *entity_links) {
                if (link.asset_id != related_asset) continue;
                auto key = std::make_pair(link.entity_type, link.entity_id);
                if (seen_entities.insert(key).second) {
                    explanation.entities.push_back(key);
                }
            }
        }
    }

    // --- downstream usage ----------------------------------------------------
    for (const auto& run_iter : document_.runs) {
        const auto& inputs = run_iter.input_version_ids;
        if (std::find(inputs.begin(), inputs.end(), version->id) != inputs.end()) {
            explanation.downstream_run_ids.push_back(run_iter.id.str());
            for (const auto& output : run_iter.output_version_ids) {
                if (!(output == version->id) &&
                    std::find(explanation.downstream_version_ids.begin(),
                              explanation.downstream_version_ids.end(),
                              output.str()) ==
                        explanation.downstream_version_ids.end()) {
                    explanation.downstream_version_ids.push_back(output.str());
                }
            }
        }
    }
    if (const auto* children = index_.children_of(version_id)) {
        for (const DataVersion* child : *children) {
            if (std::find(explanation.downstream_version_ids.begin(),
                          explanation.downstream_version_ids.end(),
                          child->id.str()) ==
                explanation.downstream_version_ids.end()) {
                explanation.downstream_version_ids.push_back(child->id.str());
            }
        }
    }

    // --- lifecycle answers -----------------------------------------------------
    CleanupEligibility eligibility = cleanup_eligibility(
        document_, index_, version_id, live_working_copy);
    explanation.deletable = eligibility.eligible;
    explanation.delete_blockers = eligibility.blockers;

    auto [stale, stale_reason] = impact_.is_stale(version_id);
    if (stale) {
        explanation.stale = true;
        explanation.stale_reason =
            stale_reason + (explanation.pinned ? "该下游版本被 pin 固定在旧输入。"
                                               : "建议重算。");
    }
    return explanation;
}

domain::Json ExplainService::explain_asset(
    const std::string& asset_id,
    const std::vector<ImpactService::EntityLink>* entity_links,
    bool live_working_copy) {
    const DataAsset* asset = index_.asset(asset_id);
    if (asset == nullptr) return domain::Json();
    std::vector<const DataVersion*> versions;
    if (const auto* list = index_.versions_of_asset(asset_id)) versions = *list;
    std::optional<std::string> current_id;
    if (asset->current_version_id.has_value()) {
        current_id = asset->current_version_id->str();
    } else if (!versions.empty()) {
        current_id = versions.back()->id.str();
    }
    domain::Json current;
    if (current_id.has_value()) {
        auto explanation = explain_version(*current_id, entity_links, live_working_copy);
        if (explanation.is_ok()) current = explanation.value().to_dict();
    }
    domain::Json roles = domain::Json::array();
    if (entity_links != nullptr) {
        for (const auto& link : *entity_links) {
            if (link.asset_id != asset_id) continue;
            domain::Json row = domain::Json::object();
            row["entity_type"] = link.entity_type;
            row["entity_id"] = link.entity_id;
            roles.push_back(std::move(row));
        }
    }
    domain::Json out = domain::Json::object();
    out["asset_id"] = asset->id.str();
    out["name"] = asset->name;
    out["type"] = asset->type;
    out["version_count"] = versions.size();
    out["current_version_id"] =
        current_id.has_value() ? domain::Json(*current_id) : domain::Json();
    out["current"] = current.is_null() ? domain::Json() : current;
    out["roles"] = roles;
    out["trashed"] = asset->trashed;
    return out;
}

}  // namespace pwb::catalog
