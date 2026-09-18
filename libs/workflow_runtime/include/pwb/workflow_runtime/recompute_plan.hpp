#pragma once

// C++ port of paleo_workbench/workflow/recompute_plan.py (CONV-26) —
// minimal incremental recomputation plans (Stage 9). The planner decides
// WHAT needs scientific recomputation and in which topological order;
// domain handlers decide HOW. Style/display changes never appear here.
//
// Ported surface: PlanAction / RecomputeStep / RecomputePlan /
// build_recompute_plan (changed-root expansion, task-level dependency
// links for empty-lineage consumers (H11), stale-only filtering with
// task-forced UNKNOWN passes, provenance reuse matching, topological
// ordering with synthetic task edges) / PlanExecutor (generation guard,
// cooperative cancel, failure isolation with version-namespace output
// poisoning) / OPERATION_LABELS_ZH / plan execution result.
//
// Project seam: Python walks project.prediction_tasks /
// paleomap_documents attribute graphs; the C++ side takes the same data as
// a Json view:
//   {"prediction_tasks": [{"id", "input_factor_map_ids": [task ids]}],
//    "paleomap_documents": [{"id", "linked_prediction_task_id"}]}
// (null / missing keys == empty project).
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/freshness.hpp>

#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;

enum class PlanAction {
    RequiresCompute,
    ReuseExisting,
    SkipDisplayOnly,
    Blocked,
};
const char* plan_action_value(PlanAction action);

struct RecomputeStep {
    int order = 0;
    std::optional<std::string> run_id;
    std::string operation;
    std::optional<std::string> domain_task_id;
    PlanAction action = PlanAction::RequiresCompute;
    std::optional<FreshnessReason> reason;
    std::optional<std::string> reuse_run_id;
    std::vector<std::string> reuse_output_version_ids;
    std::vector<std::string> input_version_ids;
    std::vector<std::string> output_version_ids;
    std::string label;
    bool can_reuse_existing = false;
    bool requires_compute = true;

    Json to_dict() const;
};

struct RecomputePlan {
    std::vector<RecomputeStep> steps;
    std::vector<std::string> changed_version_ids;
    std::optional<std::string> cycle_error;
    // Execution bookkeeping (filled by PlanExecutor).
    std::vector<std::string> completed_run_ids;
    std::vector<std::string> failed_run_ids;
    std::vector<std::string> skipped_run_ids;

    [[nodiscard]] std::vector<const RecomputeStep*> compute_steps() const;

    std::string summary_zh() const;
    Json to_dict() const;
};

// Human-readable operation labels (Chinese UI).
extern const std::map<std::string, std::string> OPERATION_LABELS_ZH;

struct RecomputePlanOptions {
    // When given, only transitive dependents of these versions are
    // considered (roots expand to asset + domain-task siblings).
    std::vector<std::string> changed_version_ids;
    bool stale_only = true;
    // Empty == no operation filter.
    std::vector<std::string> operations;
    // Optional project view (task-level links for empty-lineage runs).
    Json project = Json(nullptr);
};

[[nodiscard]] RecomputePlan build_recompute_plan(
    const FreshnessService& freshness, const RecomputePlanOptions& options);

struct PlanExecutionResult {
    RecomputePlan* plan = nullptr;
    bool stopped_early = false;
    std::vector<std::string> messages;
};

// Domain handler: performs the step's compute. Throws on failure (the
// executor marks the step failed and poisons its output versions).
using StepHandler = std::function<void(const RecomputeStep&)>;

class PlanExecutor {
public:
    // generation guards cancel mid-flight work when a newer plan supersedes.
    PlanExecutor(std::map<std::string, StepHandler> handlers = {},
                 int generation = 0, bool stop_on_failure = true,
                 bool skip_dependents_on_failure = true);

    void cancel();
    int bump_generation();

    // Partial failure: successful steps stay done; dependents of a failed
    // step are skipped (remain STALE) — Stage-9 semantics.
    PlanExecutionResult execute(RecomputePlan& plan,
                                std::optional<int> generation = std::nullopt);

private:
    std::map<std::string, StepHandler> handlers_;
    int generation_;
    bool stop_on_failure_;
    bool skip_dependents_on_failure_;
    bool cancelled_ = false;
    int active_generation_;
};

}  // namespace pwb::workflow_runtime
