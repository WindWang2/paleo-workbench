// CONV-34 — see header for provenance; mirrors
// paleo_workbench/runtime/governance.py.

#include "pwb/job_runtime/governance.hpp"

#include <algorithm>

namespace pwb::job {
namespace {

// AdmissionLease wrapping a ResourceLease for the scheduler protocol:
// release() is called exactly once by the scheduler; ResourceLease
// release is idempotent so the destructor/scheduler ordering is safe.
class GovernorLease final : public AdmissionLease {
public:
    explicit GovernorLease(std::unique_ptr<ResourceLease> inner)
        : inner_(std::move(inner)) {}
    void release() override { inner_.reset(); }

private:
    std::unique_ptr<ResourceLease> inner_;
};

[[nodiscard]] JobCategory parse_category(std::string_view id) {
    // Wire-id -> enum; unknown ids raise std::invalid_argument like
    // Python's TaskCategory(value) ValueError (clamp_workers catches).
    static constexpr std::pair<std::string_view, JobCategory> kMap[] = {
        {"interactive.render", JobCategory::interactive_render},
        {"interactive.query", JobCategory::interactive_query},
        {"preview", JobCategory::preview},
        {"background.io", JobCategory::background_io},
        {"background.compute", JobCategory::background_compute},
        {"seismic.transcode", JobCategory::transcode},
        {"seismic.attribute", JobCategory::attribute},
        {"prediction.inference", JobCategory::inference},
        {"export", JobCategory::export_job},
        {"indexing", JobCategory::indexing},
        {"maintenance", JobCategory::maintenance},
    };
    for (const auto& [wire, cat] : kMap) {
        if (wire == id) return cat;
    }
    throw std::invalid_argument("unknown category id");
}

}  // namespace

TaskRequest request_for_spec(const JobSpec& spec, const std::string& job_id) {
    const JobCategory category = category_for_kind(spec.kind);
    const CategoryPolicy* policy = policy_for(category);
    TaskRequest request;
    request.category = category;
    // Python: priority=spec.priority if spec.priority else None — 0/empty
    // falls back to the category base priority.
    if (spec.priority) request.priority = spec.priority;
    request.title = spec.title.empty() ? spec.kind : spec.title;
    request.estimated_cpu_cores =
        (spec.resources && spec.resources->cpu_cores)
            ? *spec.resources->cpu_cores
            : (policy ? policy->default_cpu_cores : 1.0);
    request.estimated_ram_bytes =
        (spec.resources && spec.resources->ram_bytes)
            ? *spec.resources->ram_bytes
            : 0;
    request.estimated_vram_bytes =
        (spec.resources && spec.resources->vram_bytes)
            ? *spec.resources->vram_bytes
            : 0;
    if (spec.resources && spec.resources->io_weight) {
        request.io_weight = spec.resources->io_weight;
    }
    request.task_id = job_id;
    return request;
}

JobScheduler::AdmissionHook scheduler_admission_hook(ResourceGovernor& governor) {
    return [&governor](const JobSpec& spec,
                       const std::string& job_id) -> std::shared_ptr<AdmissionLease> {
        std::unique_ptr<ResourceLease> lease =
            governor.try_admit(request_for_spec(spec, job_id));
        if (!lease) return nullptr;
        return std::make_shared<GovernorLease>(std::move(lease));
    };
}

int clamp_workers(std::string_view category_id, int requested) {
    try {
        return global_governor().cpu_allowance(parse_category(category_id),
                                               requested);
    } catch (...) {
        return std::max(1, requested);
    }
}

std::map<std::string, bool> apply_all_budgets(const ResourceBudget& budget,
                                              const BudgetSinks& sinks) {
    std::map<std::string, bool> out;
    for (const auto& [name, sink] : sinks) {
        bool applied = false;
        try {
            applied = sink(budget);
        } catch (...) {
            applied = false;  // a missing/failed engine must not kill config
        }
        out[name] = applied;
    }
    return out;
}

ResourceGovernor& ensure_global_governance(const ResourceBudget* budget_or_null,
                                           JobScheduler* scheduler,
                                           const BudgetSinks& sinks) {
    if (budget_or_null != nullptr) {
        // Python order: engine caches pushed BEFORE the governor rebind so
        // a pressure sample sees the new caps already in effect.
        apply_all_budgets(*budget_or_null, sinks);
        configure_runtime_budget(*budget_or_null);
    }
    ResourceGovernor& governor = global_governor();
    JobScheduler& sched =
        scheduler != nullptr ? *scheduler : global_scheduler();
    sched.set_admission(scheduler_admission_hook(governor));
    return governor;
}

}  // namespace pwb::job
