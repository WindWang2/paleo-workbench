// CONV-23 — workflow/contracts/{registry,modules,validation}.py port.
#pragma once

#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/workflow_contracts/models.hpp>

namespace pwb::workflow_contracts {

// modules.py — the 14 declarations parsed from the generated
// modules_data.inc (data frozen from the real Python output; D3).
std::vector<DomainWorkflowContract> build_all_contracts();

// validation.py
std::vector<std::string>
validate_registry(const std::vector<DomainWorkflowContract>& contracts);

// registry.py — in-memory registry; construction validates eagerly and
// rejects duplicate ids with Python's ValueError message. A nullopt
// contract list means "build_all_contracts()" (Python's None default).
class WorkflowContractRegistry {
public:
    explicit WorkflowContractRegistry(
        std::optional<std::vector<DomainWorkflowContract>> contracts =
            std::nullopt);

    const std::vector<DomainWorkflowContract>& list_contracts() const {
        return contracts_;
    }
    const DomainWorkflowContract* get_contract(
        const std::string& contract_id) const;
    std::vector<const DomainWorkflowContract*> contracts_by_category(
        const std::string& category) const;
    std::vector<const DomainWorkflowContract*> upstream(
        const std::string& contract_id) const;
    std::vector<const DomainWorkflowContract*> downstream(
        const std::string& contract_id) const;
    std::vector<const ExpertConsultationQuestion*> all_expert_questions()
        const;
    const std::vector<std::string>& validation_issues() const {
        return issues_;
    }
    static const std::vector<std::string>& p0_ids();

private:
    // insertion-ordered storage + id index (dict.values() order semantics)
    std::vector<DomainWorkflowContract> contracts_;
    std::map<std::string, std::size_t> by_id_;
    std::vector<std::string> issues_;
};

// Default-constructed registry builds from build_all_contracts().
const WorkflowContractRegistry& get_default_registry();

}  // namespace pwb::workflow_contracts
