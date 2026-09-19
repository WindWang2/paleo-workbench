#pragma once
// CONV-32 — UI-independent workflow plan model (dag/plan_view.py port).
// Task Center / Agent panel consume THIS model — never the engine internals,
// never widgets. One WorkflowPlanView renders a workflow_spec::WorkflowRun
// (live or finished) as an ordered checklist:
//
//     ✓ 输入检查            succeeded
//     ● 插值 61%           running + progress
//     ○ 等值线             pending
//     ↷ 质检（条件未满足）   skipped
//     ✗ 导出               failed
//
// The view never touches Qt; the panel decides how to paint it.
//
// Types are the CONV-06 workflow_spec DTOs, fully qualified on every use:
// this namespace also hosts the legacy minimal engine.hpp
// NodeState/RunState/WorkflowSpec/WorkflowRun (M7 executor slice), and the
// qualified spellings keep both headers includable from one TU without
// collisions. Qt-free, Python-free.
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/workflow_spec/model.hpp>

namespace pwb::workflow_engine {

using domain::Json;

// plan_view.PlanItem — one checklist row (pure data).
struct PlanItem {
    std::string node_id;
    std::string label;
    workflow_spec::NodeState state = workflow_spec::NodeState::pending;
    std::string detail;
    bool from_cache = false;
    std::optional<std::string> receipt_status;
    std::optional<std::string> error;

    // _SYMBOLS lookup; unknown states fall back to ○ (Python .get default).
    [[nodiscard]] std::string symbol() const;
    // Key order: node_id, label, state, detail, from_cache, receipt_status,
    // error, symbol (frozen against Python to_dict).
    [[nodiscard]] Json to_dict() const;
};

// plan_view.WorkflowPlanView — checklist model of one workflow (plan-ahead
// or live/finished run).
struct WorkflowPlanView {
    std::string workflow_id;
    std::string name;
    std::string state{"running"};  // RunState.RUNNING.value
    double progress = 0.0;
    std::vector<PlanItem> items;

    // Plan-ahead view: every node PENDING, in spec order.
    [[nodiscard]] static WorkflowPlanView from_spec(
        const workflow_spec::WorkflowSpec& spec);
    // Live/finished run: construct + update_from_run.
    [[nodiscard]] static WorkflowPlanView from_run(
        const workflow_spec::WorkflowRun& run);
    // Rebuild from a persisted run summary (e.g. a workflow.run action
    // result) — the panel never needs the engine for this. Spec given ->
    // spec node order filtered to ids present in the summary nodes map
    // (absent spec nodes dropped); spec absent -> nodes-map insertion
    // order with info["label"] fallback labels.
    [[nodiscard]] static WorkflowPlanView from_summary(
        const Json& summary, const workflow_spec::WorkflowSpec* spec = nullptr);

    // state = run.state; progress = round(done/total, 3); items from
    // node_runs insertion order, then STABLE sort by spec node position
    // (missing -> 10**9) so the checklist keeps the spec's authored order.
    void update_from_run(const workflow_spec::WorkflowRun& run);

    // Label of the first RUNNING item, else nullopt.
    [[nodiscard]] std::optional<std::string> current_node() const;
    // _STATE_LABELS lookup. Deliberate divergence from Python: an unknown
    // raw state string returns itself instead of raising (the panel must
    // not crash on a drifted summary; see receipt_plan_view_test.cpp case
    // "state_labels" which also freezes the Python ValueError text).
    [[nodiscard]] std::string state_label() const;
    // Rows for a checklist renderer: item dicts with running rows' empty
    // details filled from progress ("33%") and a trailing
    // "current": true on rows matching current_node().
    [[nodiscard]] Json checklist() const;
    // Key order: workflow_id, name, state, state_label, progress,
    // current_node, items (frozen against Python to_dict).
    [[nodiscard]] Json to_dict() const;
};

}  // namespace pwb::workflow_engine
