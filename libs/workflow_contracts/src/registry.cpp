#include <string>
#include <pwb/workflow_contracts/registry.hpp>

#include <algorithm>
#include <set>
#include <stdexcept>
#include <utility>

namespace pwb::workflow_contracts {

// modules.py — build_all_contracts(): the 14 declarations, embedded as
// frozen JSON (generated from the real Python model_dump; see
// tools/oracle/generate_workflow_contract_fixtures.py).
namespace {

// PWB-V14-DATA-LINEAGE: the frozen payload exceeds MSVC's per-line
// literal ceiling, so modules_data.inc now emits adjacent raw literals
// PWB-V14-DATA-LINEAGE: the frozen payload exceeds MSVC's per-line raw
// literal ceiling; modules_data.inc now emits several raw literals joined
// with '+', which needs a std::string initializer (adjacent literals
// cannot span lines).
const std::string kModulesJson =
#include "modules_data.inc"
    ;

}  // namespace

std::vector<DomainWorkflowContract> build_all_contracts() {
    const Json arr = Json::parse(kModulesJson);
    std::vector<DomainWorkflowContract> out;
    out.reserve(arr.size());
    for (const auto& c : arr)
        out.push_back(DomainWorkflowContract::from_json(c));
    return out;
}

// validation.py
namespace {

const std::set<std::string>& known_datarun_operations() {
    static const std::set<std::string> ops = {
        "factor_map",      "prediction",
        "export",          "horizon_interpretation",
        "map_compile",     "qc",
        "modeling",        "derived_copy",
        "delivery",        "stratigraphic_correlation",
        "fault_interpretation",
    };
    return ops;
}

const std::map<std::string, std::string>& contract_datarun_map() {
    static const std::map<std::string, std::string> m = {
        {"factor_interpolation", "factor_map"},
        {"facies_prediction", "prediction"},
        {"export", "export"},
        {"horizon_interpretation", "horizon_interpretation"},
        {"paleomap_compile", "map_compile"},
        {"quality_control", "qc"},
        {"geomodel_3d", "modeling"},
        {"well_correlation", "stratigraphic_correlation"},
        {"fault_interpretation", "fault_interpretation"},
    };
    return m;
}

bool contains(const std::vector<std::string>& v, const std::string& s) {
    return std::find(v.begin(), v.end(), s) != v.end();
}

}  // namespace

std::vector<std::string> validate_registry(
    const std::vector<DomainWorkflowContract>& contracts) {
    std::vector<std::string> issues;
    std::set<std::string> ids;
    std::map<std::string, const DomainWorkflowContract*> by_id;
    for (const auto& c : contracts) {
        ids.insert(c.id);
        by_id[c.id] = &c;
    }
    for (const auto& c : contracts) {
        for (const auto& up : c.upstream_contract_ids) {
            if (!ids.count(up))
                issues.push_back(c.id + ": unknown upstream " + up);
            else if (!contains(by_id[up]->downstream_contract_ids, c.id))
                // audit #848: edges must mirror or consumption is hidden
                issues.push_back(up + "->" + c.id +
                                 ": missing mirror downstream on " + up);
        }
        for (const auto& down : c.downstream_contract_ids) {
            if (!ids.count(down))
                issues.push_back(c.id + ": unknown downstream " + down);
            else if (!contains(by_id[down]->upstream_contract_ids, c.id))
                issues.push_back(c.id + "->" + down +
                                 ": missing mirror upstream on " + down);
        }
        for (const auto& op : c.datarun_operations)
            if (!op.empty() && !known_datarun_operations().count(op))
                issues.push_back(c.id +
                                 ": undeclared DataRun operation '" + op +
                                 "'");
        const auto it = contract_datarun_map().find(c.id);
        if (it != contract_datarun_map().end() &&
            !contains(c.datarun_operations, it->second))
            issues.push_back(c.id +
                             ": missing expected DataRun operation '" +
                             it->second + "'");
        for (const auto& p : c.parameters)
            if (p.certainty == Certainty::EXPERT_CONFIRMATION_REQUIRED &&
                !p.expert_question_id)
                issues.push_back(c.id + ": parameter " + p.id +
                                 " needs expert_question_id");
        for (const auto& q : c.expert_questions) {
            // (q.question or "").strip() — only ASCII/Unicode-space trim
            // matters; questions are frozen text.
            const auto first = q.question.find_first_not_of(" \t\n\v\f\r");
            if (first == std::string::npos)
                issues.push_back(c.id + ": empty expert question " + q.id);
            for (const auto& e : q.source_evidence)
                if (e.path.empty())
                    issues.push_back(c.id + "/" + q.id +
                                     ": evidence missing path");
        }
    }
    return issues;
}

// registry.py
WorkflowContractRegistry::WorkflowContractRegistry(
    std::optional<std::vector<DomainWorkflowContract>> contracts)
    : contracts_(contracts ? std::move(*contracts)
                           : build_all_contracts()) {
    for (std::size_t i = 0; i < contracts_.size(); ++i) {
        const auto& id = contracts_[i].id;
        if (by_id_.count(id))
            throw std::invalid_argument("duplicate contract id: " + id);
        by_id_[id] = i;
    }
    issues_ = validate_registry(contracts_);
}

const DomainWorkflowContract* WorkflowContractRegistry::get_contract(
    const std::string& contract_id) const {
    const auto it = by_id_.find(contract_id);
    return it == by_id_.end() ? nullptr : &contracts_[it->second];
}

std::vector<const DomainWorkflowContract*>
WorkflowContractRegistry::contracts_by_category(
    const std::string& category) const {
    std::vector<const DomainWorkflowContract*> out;
    for (const auto& c : contracts_)
        if (c.category == category) out.push_back(&c);
    return out;
}

std::vector<const DomainWorkflowContract*>
WorkflowContractRegistry::upstream(const std::string& contract_id) const {
    std::vector<const DomainWorkflowContract*> out;
    const DomainWorkflowContract* c = get_contract(contract_id);
    if (!c) return out;
    for (const auto& i : c->upstream_contract_ids) {
        const DomainWorkflowContract* u = get_contract(i);
        if (u) out.push_back(u);
    }
    return out;
}

std::vector<const DomainWorkflowContract*>
WorkflowContractRegistry::downstream(const std::string& contract_id) const {
    std::vector<const DomainWorkflowContract*> out;
    const DomainWorkflowContract* c = get_contract(contract_id);
    if (!c) return out;
    for (const auto& i : c->downstream_contract_ids) {
        const DomainWorkflowContract* d = get_contract(i);
        if (d) out.push_back(d);
    }
    return out;
}

std::vector<const ExpertConsultationQuestion*>
WorkflowContractRegistry::all_expert_questions() const {
    std::vector<const ExpertConsultationQuestion*> out;
    for (const auto& c : contracts_)
        for (const auto& q : c.expert_questions) out.push_back(&q);
    return out;
}

const std::vector<std::string>& WorkflowContractRegistry::p0_ids() {
    static const std::vector<std::string> ids = {
        "data_import",        "well_log_ingest",
        "well_log_visualization", "seismic_volume",
        "horizon_interpretation", "factor_interpolation",
        "facies_prediction",  "paleomap_compile",
        "quality_control",    "export",
    };
    return ids;
}

const WorkflowContractRegistry& get_default_registry() {
    // Function-local static: thread-safe init, same single-instance
    // observable semantics as the module-global _DEFAULT (D11).
    static const WorkflowContractRegistry reg;
    return reg;
}

}  // namespace pwb::workflow_contracts
