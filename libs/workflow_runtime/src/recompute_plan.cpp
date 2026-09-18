// recompute_plan.cpp — C++ port of paleo_workbench/workflow/recompute_plan.py
// (CONV-26). See include/pwb/workflow_runtime/recompute_plan.hpp.

#include <pwb/workflow_runtime/recompute_plan.hpp>

#include "python_compat.hpp"

#include <algorithm>
#include <functional>
#include <set>
#include <unordered_map>
#include <unordered_set>

namespace pwb::workflow_runtime {

namespace {

Json to_json(const std::optional<std::string>& value) {
    return value ? Json(*value) : Json(nullptr);
}

// Task-level consumer links (H11): consumer task id -> producer task ids it
// consumes (prediction.input_factor_map_ids, map.linked_prediction_task_id).
// These links exist even when the consumer's run-graph lineage is empty.
std::map<std::string, std::set<std::string>> task_consumer_links(
    const Json& project, const std::set<std::string>& affected_task_ids) {
    std::map<std::string, std::set<std::string>> links;
    if (affected_task_ids.empty() || !project.is_object()) return links;

    for (const auto& task : pycompat::dict_get(project, "prediction_tasks",
                                               Json::array())) {
        const std::string id =
            pycompat::str_scalar(pycompat::dict_get(task, "id", Json("")));
        std::set<std::string> factor_ids;
        for (const auto& fid : pycompat::dict_get(task, "input_factor_map_ids",
                                                  Json::array())) {
            factor_ids.insert(pycompat::str_scalar(fid));
        }
        std::set<std::string> producers;
        for (const auto& fid : factor_ids) {
            if (affected_task_ids.count(fid) != 0) producers.insert(fid);
        }
        if (!producers.empty()) {
            links[id].merge(producers);
        }
    }

    std::set<std::string> pred_consumers;
    for (const auto& [tid, producers] : links) {
        (void)producers;
        pred_consumers.insert(tid);
    }
    for (const auto& doc : pycompat::dict_get(project, "paleomap_documents",
                                              Json::array())) {
        const std::string id =
            pycompat::str_scalar(pycompat::dict_get(doc, "id", Json("")));
        const Json linked_json =
            pycompat::dict_get(doc, "linked_prediction_task_id",
                               Json(nullptr));
        if (linked_json.is_null()) continue;
        const std::string linked = pycompat::str_scalar(linked_json);
        std::set<std::string> candidates = affected_task_ids;
        candidates.merge(pred_consumers);
        if (candidates.count(linked) != 0) {
            links[id].insert(linked);
        }
    }
    return links;
}

std::set<std::string> task_linked_run_ids(
    const pwb::workflow_graph::DependencyGraph& graph,
    const std::map<std::string, std::set<std::string>>& task_links) {
    std::set<std::string> out;
    for (const auto& [tid, producers] : task_links) {
        (void)producers;
        for (const auto& [key, run_ids] : graph.domain_task_runs()) {
            if (key != tid) continue;
            for (const auto& rid : run_ids) out.insert(rid);
        }
    }
    return out;
}

std::vector<std::string> current_inputs_for_run(
    const DataRunRef& run, const FreshnessService& freshness) {
    // Map each historical input to the currently selected version of its
    // product.
    std::vector<std::string> result;
    for (const std::string& in_vid : run.input_version_ids) {
        auto mismatch = freshness.selection_mismatch(in_vid);
        if (mismatch) {
            result.push_back(mismatch->first);
        } else {
            result.push_back(in_vid);
        }
    }
    return result;
}

std::string step_label(const DataRunRef& run,
                       const FreshnessService& freshness) {
    const std::string base = [&] {
        const auto it = OPERATION_LABELS_ZH.find(run.operation);
        return it != OPERATION_LABELS_ZH.end() ? it->second : run.operation;
    }();
    if (run.domain_task_id) {
        return base + " (" + *run.domain_task_id + ")";
    }
    if (!run.output_version_ids.empty()) {
        const std::string& first = run.output_version_ids.front();
        std::string name;
        const auto label_it = freshness.context().labels().find(first);
        if (label_it != freshness.context().labels().end()) {
            name = label_it->second;
        }
        if (name.empty()) {
            const DataVersionRef* ver = freshness.graph().version(first);
            if (ver != nullptr) name = ver->name;
        }
        if (!name.empty()) {
            return base + " " + name;
        }
    }
    return base;
}

}  // namespace

const char* plan_action_value(PlanAction action) {
    switch (action) {
    case PlanAction::RequiresCompute: return "requires_compute";
    case PlanAction::ReuseExisting: return "reuse_existing";
    case PlanAction::SkipDisplayOnly: return "skip_display_only";
    case PlanAction::Blocked: return "blocked";
    }
    return "?";
}

Json RecomputeStep::to_dict() const {
    Json reuse_outputs = Json::array();
    for (const auto& id : reuse_output_version_ids) reuse_outputs.push_back(id);
    Json inputs = Json::array();
    for (const auto& id : input_version_ids) inputs.push_back(id);
    Json outputs = Json::array();
    for (const auto& id : output_version_ids) outputs.push_back(id);
    Json out = Json::object();
    out["order"] = order;
    out["run_id"] = to_json(run_id);
    out["operation"] = operation;
    out["domain_task_id"] = to_json(domain_task_id);
    out["action"] = plan_action_value(action);
    out["reason"] = reason ? reason->to_dict() : Json(nullptr);
    out["reuse_run_id"] = to_json(reuse_run_id);
    out["reuse_output_version_ids"] = std::move(reuse_outputs);
    out["input_version_ids"] = std::move(inputs);
    out["output_version_ids"] = std::move(outputs);
    out["label"] = label;
    out["can_reuse_existing"] = can_reuse_existing;
    out["requires_compute"] = requires_compute;
    return out;
}

std::vector<const RecomputeStep*> RecomputePlan::compute_steps() const {
    std::vector<const RecomputeStep*> out;
    for (const RecomputeStep& s : steps) {
        if (s.requires_compute) out.push_back(&s);
    }
    return out;
}

std::string RecomputePlan::summary_zh() const {
    const auto compute = compute_steps();
    if (compute.empty()) return "无需更新";
    std::string lines =
        std::to_string(compute.size()) + " 个步骤需要更新\n";
    for (const RecomputeStep* s : compute) {
        std::string label = !s->label.empty()
                                ? s->label
                                : (!s->operation.empty()
                                       ? s->operation
                                       : (s->domain_task_id
                                              ? *s->domain_task_id
                                              : (s->run_id ? *s->run_id
                                                           : "?")));
        lines += "\n" + std::to_string(s->order) + ". " + label;
    }
    return lines;
}

Json RecomputePlan::to_dict() const {
    Json step_list = Json::array();
    for (const RecomputeStep& s : steps) step_list.push_back(s.to_dict());
    auto str_list = [](const std::vector<std::string>& ids) {
        Json arr = Json::array();
        for (const auto& id : ids) arr.push_back(id);
        return arr;
    };
    Json out = Json::object();
    out["steps"] = std::move(step_list);
    out["changed_version_ids"] = str_list(changed_version_ids);
    out["cycle_error"] = to_json(cycle_error);
    out["completed_run_ids"] = str_list(completed_run_ids);
    out["failed_run_ids"] = str_list(failed_run_ids);
    out["skipped_run_ids"] = str_list(skipped_run_ids);
    return out;
}

const std::map<std::string, std::string> OPERATION_LABELS_ZH = {
    {"factor_map", "单因素图"},
    {"prediction", "地震相预测"},
    {"map_compile", "古地理图编绘"},
    {"qc", "质量检查"},
    {"export", "成果导出"},
    {"horizon_interpretation", "层位解释"},
    {"modeling", "三维建模"},
    {"stratigraphic_correlation", "连井对比"},
    {"fault_interpretation", "断层解释"},
    // V9 (P1-12): fusion/commit/assembly/interpretation ops join the
    // recompute vocabulary — stale runs can be PLANNED, not just labelled.
    {"factor_fusion", "多因素融合"},
    {"factor_fusion:confidence", "融合置信度"},
    {"factor_fusion:variance", "融合方差"},
    {"constraint_commit", "约束版本提交"},
    {"map_product_assembly", "地图产品组装"},
    {"integrated_interpretation", "综合解释提交"},
};

RecomputePlan build_recompute_plan(FreshnessService& freshness,
                                   const RecomputePlanOptions& options) {
    const pwb::workflow_graph::DependencyGraph& graph = freshness.graph();
    RecomputePlan plan;
    plan.changed_version_ids = options.changed_version_ids;

    if (graph.has_cycle()) {
        // Still try to plan unaffected subsets; flag the cycle.
        std::vector<std::string> sorted_cycles(graph.cycles().begin(),
                                               graph.cycles().end());
        if (sorted_cycles.size() > 8) sorted_cycles.resize(8);
        std::string joined;
        for (std::size_t i = 0; i < sorted_cycles.size(); ++i) {
            if (i != 0) joined += ", ";
            joined += sorted_cycles[i];
        }
        plan.cycle_error = "provenance cycle involving: " + joined;
    }

    // Insertion-ordered dict snapshots of the graph views.
    std::unordered_map<std::string, std::vector<std::string>> asset_versions;
    for (const auto& [asset, vers] : graph.asset_versions()) {
        asset_versions[asset] = vers;
    }
    std::unordered_map<std::string, std::vector<std::string>> run_outputs;
    for (const auto& [rid, outs] : graph.run_outputs()) {
        run_outputs[rid] = outs;
    }
    std::unordered_map<std::string, std::string> producing_run;
    for (const auto& [vid, rid] : graph.producing_run()) {
        producing_run[vid] = rid;
    }

    std::vector<const DataRunRef*> candidate_runs;
    std::set<std::string> task_forced;
    std::map<std::string, std::set<std::string>> task_links;

    if (!options.changed_version_ids.empty()) {
        // Roots include the new tip AND prior versions of the same asset
        // (dependents of superseded versions stay in the plan) plus
        // domain-task sibling outputs.
        std::set<std::string> roots;
        for (const std::string& vid : options.changed_version_ids) {
            roots.insert(vid);
            const auto asset = graph.asset_id_for(vid);
            if (asset) {
                const auto av_it = asset_versions.find(*asset);
                if (av_it != asset_versions.end()) {
                    for (const auto& other : av_it->second) {
                        roots.insert(other);
                    }
                }
            }
            const auto prod_it = producing_run.find(vid);
            if (prod_it != producing_run.end()) {
                const DataRunRef* run = graph.run(prod_it->second);
                if (run != nullptr && run->domain_task_id) {
                    for (const auto& [tid, rids] :
                         graph.domain_task_runs()) {
                        if (tid != *run->domain_task_id) continue;
                        for (const auto& rid : rids) {
                            const auto ro_it = run_outputs.find(rid);
                            if (ro_it != run_outputs.end()) {
                                for (const auto& out : ro_it->second) {
                                    roots.insert(out);
                                }
                            }
                        }
                    }
                }
            }
        }
        std::vector<std::string> roots_vec(roots.begin(), roots.end());
        candidate_runs = graph.transitive_downstream_runs(roots_vec);

        if (options.project.is_object()) {
            // Empty-lineage consumers still depend on the changed versions
            // at the task level: include their runs as candidates (H11).
            std::set<std::string> affected_task_ids;
            for (const DataRunRef* run : candidate_runs) {
                if (run->domain_task_id) {
                    affected_task_ids.insert(*run->domain_task_id);
                }
            }
            task_links =
                task_consumer_links(options.project, affected_task_ids);
            task_forced = task_linked_run_ids(graph, task_links);
            std::set<std::string> seen_ids;
            for (const DataRunRef* run : candidate_runs) {
                seen_ids.insert(run->run_id);
            }
            for (const auto& rid : task_forced) {
                if (seen_ids.count(rid) == 0) {
                    const DataRunRef* run = graph.run(rid);
                    if (run != nullptr) candidate_runs.push_back(run);
                }
            }
        }
    } else {
        for (const DataRunRef& run : graph.run_list()) {
            candidate_runs.push_back(&run);
        }
    }

    std::set<std::string> op_filter(options.operations.begin(),
                                    options.operations.end());
    const bool has_op_filter = !op_filter.empty();
    std::vector<std::string> stale_run_ids;
    std::unordered_map<std::string, FreshnessReport> reports;

    for (const DataRunRef* run : candidate_runs) {
        if (has_op_filter && op_filter.count(run->operation) == 0) {
            continue;
        }
        FreshnessReport report = freshness.evaluate_run(run->run_id);
        reports[run->run_id] = report;
        if (options.stale_only &&
            report.state != FreshnessState::Stale &&
            report.state != FreshnessState::Missing &&
            report.state != FreshnessState::Failed) {
            // UNKNOWN runs are not forced — EXCEPT task-linked consumers:
            // recomputing them re-establishes lineage (H11).
            if (!(report.state == FreshnessState::Unknown &&
                  task_forced.count(run->run_id) != 0)) {
                continue;
            }
        }
        stale_run_ids.push_back(run->run_id);
    }

    std::vector<const DataRunRef*> ordered;
    try {
        std::optional<std::map<std::string, std::set<std::string>>>
            consumers_arg;
        if (!task_links.empty()) consumers_arg = task_links;
        ordered = graph.topological_runs(stale_run_ids, consumers_arg);
    } catch (const pwb::workflow_graph::DependencyGraphError& exc) {
        plan.cycle_error = exc.what();
        for (const std::string& rid : stale_run_ids) {
            const DataRunRef* run = graph.run(rid);
            if (run != nullptr) ordered.push_back(run);
        }
    }

    int order = 0;
    for (const DataRunRef* run_ptr : ordered) {
        const DataRunRef& run = *run_ptr;
        auto report_it = reports.find(run.run_id);
        if (report_it == reports.end()) {
            report_it = reports
                            .emplace(run.run_id,
                                     freshness.evaluate_run(run.run_id))
                            .first;
        }
        const FreshnessReport& report = report_it->second;
        std::optional<FreshnessReason> reason;
        if (const FreshnessReason* primary = report.primary_reason()) {
            reason = *primary;
        }

        // Provenance reuse with CURRENT inputs for the same identity.
        const std::vector<std::string> current_inputs =
            current_inputs_for_run(run, freshness);
        const DataRunRef* reuse = graph.find_reuse_run(
            run.operation, current_inputs, run.generator_version,
            run.input_snapshot_hash, Json(nullptr), true);
        const bool can_reuse =
            reuse != nullptr && reuse->run_id != run.run_id &&
            reuse->input_version_ids == current_inputs;

        ++order;
        const std::string label = step_label(run, freshness);
        // Outputs are version-namespace ids — the executor poisons these so
        // downstream steps consuming them are skipped after a failure
        // (audit #847-4).
        std::vector<std::string> output_ids;
        const auto ro_it = run_outputs.find(run.run_id);
        if (ro_it != run_outputs.end()) output_ids = ro_it->second;

        RecomputeStep step;
        step.order = order;
        step.run_id = run.run_id;
        step.operation = run.operation;
        step.domain_task_id = run.domain_task_id;
        step.reason = reason;
        step.input_version_ids = current_inputs;
        step.output_version_ids = output_ids;
        step.label = label;
        if (can_reuse && reuse != nullptr) {
            step.action = PlanAction::ReuseExisting;
            step.reuse_run_id = reuse->run_id;
            step.reuse_output_version_ids = reuse->output_version_ids;
            step.can_reuse_existing = true;
            step.requires_compute = false;
        } else {
            step.action = PlanAction::RequiresCompute;
            step.can_reuse_existing = false;
            step.requires_compute = true;
        }
        plan.steps.push_back(std::move(step));
    }

    return plan;
}

PlanExecutor::PlanExecutor(std::map<std::string, StepHandler> handlers,
                           int generation, bool stop_on_failure,
                           bool skip_dependents_on_failure)
    : handlers_(std::move(handlers)),
      generation_(generation),
      stop_on_failure_(stop_on_failure),
      skip_dependents_on_failure_(skip_dependents_on_failure),
      active_generation_(generation) {}

void PlanExecutor::cancel() { cancelled_ = true; }

int PlanExecutor::bump_generation() {
    ++generation_;
    active_generation_ = generation_;
    cancelled_ = true;
    return generation_;
}

PlanExecutionResult PlanExecutor::execute(RecomputePlan& plan,
                                          std::optional<int> generation) {
    const int gen = generation ? *generation : generation_;
    PlanExecutionResult result;
    result.plan = &plan;
    std::set<std::string> failed_run_ids;
    std::set<std::string> poisoned_versions;

    for (const RecomputeStep& step : plan.steps) {
        if (cancelled_ || gen != active_generation_) {
            result.stopped_early = true;
            result.messages.push_back("cancelled by generation guard");
            break;
        }

        const std::string step_run_key = [&] {
            if (step.run_id) return *step.run_id;
            if (step.reuse_run_id) return *step.reuse_run_id;
            return std::string();
        }();

        if (step.action == PlanAction::ReuseExisting) {
            plan.completed_run_ids.push_back(step_run_key);
            result.messages.push_back("reuse " + step.label);
            continue;
        }

        if (!step.requires_compute) {
            plan.skipped_run_ids.push_back(step.run_id.value_or(""));
            continue;
        }

        if (skip_dependents_on_failure_ && !poisoned_versions.empty()) {
            bool poisoned = false;
            for (const std::string& vid : step.input_version_ids) {
                if (poisoned_versions.count(vid) != 0) {
                    poisoned = true;
                    break;
                }
            }
            if (poisoned) {
                plan.skipped_run_ids.push_back(step.run_id.value_or(""));
                result.messages.push_back("skip " + step.label +
                                          " (upstream failure)");
                continue;
            }
        }

        if (stop_on_failure_ && !failed_run_ids.empty()) {
            plan.skipped_run_ids.push_back(step.run_id.value_or(""));
            result.messages.push_back("skip " + step.label +
                                      " (upstream failure)");
            continue;
        }

        const auto handler_it = handlers_.find(step.operation);
        if (handler_it == handlers_.end()) {
            const std::string rid = step.run_id.value_or("");
            plan.failed_run_ids.push_back(rid);
            failed_run_ids.insert(rid);
            for (const std::string& vid : step.output_version_ids) {
                poisoned_versions.insert(vid);
            }
            for (const std::string& vid : step.reuse_output_version_ids) {
                poisoned_versions.insert(vid);
            }
            result.messages.push_back(
                "no handler for operation " +
                pycompat::repr_str(step.operation) + "; mark failed");
            if (stop_on_failure_) {
                result.stopped_early = true;
            }
            continue;
        }

        try {
            handler_it->second(step);
            plan.completed_run_ids.push_back(step_run_key);
            result.messages.push_back("ok " + step.label);
        } catch (const std::exception& exc) {
            const std::string rid = step.run_id.value_or("");
            plan.failed_run_ids.push_back(rid);
            failed_run_ids.insert(rid);
            for (const std::string& vid : step.output_version_ids) {
                poisoned_versions.insert(vid);
            }
            for (const std::string& vid : step.reuse_output_version_ids) {
                poisoned_versions.insert(vid);
            }
            result.messages.push_back("failed " + step.label + ": " +
                                      exc.what());
            if (stop_on_failure_) {
                result.stopped_early = true;
                // Continue loop only to mark skips.
            }
        }
    }

    return result;
}

}  // namespace pwb::workflow_runtime
