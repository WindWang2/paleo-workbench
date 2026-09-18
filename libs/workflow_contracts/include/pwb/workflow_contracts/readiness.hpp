// CONV-23 — workflow/contracts/readiness.py port.
//
// Metadata-only evaluation: the Python project argument is duck-typed
// (getattr chains over resources/tasks/docs). Here it is a ProjectView —
// each member a Json array/object in the same attribute shape the Python
// getattr chains read. Dict-valued leaves (task.parameters, doc.view_state)
// stay Json objects — production models store plain dicts there (D4).
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <pwb/workflow_contracts/models.hpp>
#include <pwb/workflow_contracts/registry.hpp>

namespace pwb::workflow_contracts {

// Duck-typed project surface — missing members = Json(null) which reads as
// Python's ``getattr(project, "x", None) or []`` → empty.
struct ProjectView {
    Json resources;                    // [{type, status, path}, ...]
    Json factor_map_tasks;             // [{status, parameters{...},
                                       //   target_horizon, adapter_kind}]
    Json paleomap_documents;           // [{linked_target_horizon,
                                       //   view_state{is_demo_draft}}]
    Json stratigraphy;                 // {target_horizon}
    Json correlation_interpretations;  // [{depth_domains | depth_domain}]
    Json prediction_tasks;             // [{adapter_kind}]
    Json export_artifacts;             // presence list
    Json meta;                         // {project_root}

    static ProjectView from_json(const Json& j);
};

// Catalog production-model seam (D5): nullptr probe == Python's
// ``svc is None`` (catalog service unconfigured → "目录未连接");
// a probe returning nullopt == find_production_model() → None;
// a throwing probe == catalog read failure → catalog_read_error.
struct ProductionModelProbe {
    virtual ~ProductionModelProbe() = default;
    virtual std::optional<Json>
    find_production_model(const std::string& capability) const = 0;
};

constexpr const char* kCapabilityFacies = "facies";

struct ReadinessReport {
    std::string contract_id;
    ReadinessStatus status = ReadinessStatus::UNKNOWN;
    std::vector<ReadinessReason> reasons;
    ImplementationStatus implementation_status =
        ImplementationStatus::PARTIAL;
    std::string freshness_note = "freshness_owned_by_stage9";
    Json to_dict() const;
};

ReadinessReport evaluate_contract_readiness(
    const ProjectView& project, const DomainWorkflowContract& contract,
    const ProductionModelProbe* catalog = nullptr);

ReadinessReport evaluate_readiness(
    const ProjectView& project, const std::string& contract_id,
    const WorkflowContractRegistry* registry = nullptr,
    const ProductionModelProbe* catalog = nullptr);

class WorkflowReadinessEvaluator {
public:
    explicit WorkflowReadinessEvaluator(
        const WorkflowContractRegistry* registry = nullptr)
        : registry_(registry ? registry : &get_default_registry()) {}

    ReadinessReport evaluate(const ProjectView& project,
                             const std::string& contract_id,
                             const ProductionModelProbe* catalog =
                                 nullptr) const {
        return evaluate_readiness(project, contract_id, registry_,
                                  catalog);
    }

    std::vector<ReadinessReport>
    evaluate_all(const ProjectView& project,
                 const ProductionModelProbe* catalog = nullptr) const {
        std::vector<ReadinessReport> out;
        for (const auto& c : registry_->list_contracts())
            out.push_back(
                evaluate_contract_readiness(project, c, catalog));
        return out;
    }

private:
    const WorkflowContractRegistry* registry_;
};

}  // namespace pwb::workflow_contracts
