#pragma once

// cpp-close-02 — typed host bindings: the composition root that wires the
// existing UI controller seams (ui_controllers::WorkflowCore, UI-14) to
// the REAL native workflow services, plus the reopen-recovery path.
//
// UI-14's WorkflowCore consumes injected seams ("the host binds the real
// services; tests inject fakes") — until this library existed there was
// no native host binding, so the controller ran on fakes or degraded
// paths. These bindings close that gap WITHOUT touching the controller:
// every returned std::function has the exact WorkflowCore seam signature.
//
// The recovery path (reopen_project_workflow) is the product closed loop:
// open project → load the persistent provenance store → resolve the
// five-segment current context → freshness session → stale report +
// minimal recompute plan. A restarted process resumes exactly where the
// catalog says it stopped — completed steps stay done (reuse-matched),
// interrupted work replans.
//
// Qt-free, Python-free.

#include <pwb/closure_workflow/integrated_compilation.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/project/document.hpp>
#include <pwb/workflow_engine/engine.hpp>
#include <pwb/workflow_engine/run_engine.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/recompute_plan.hpp>
#include <pwb/workflow_runtime/runtime_service.hpp>

#include <functional>
#include <memory>
#include <string>

namespace pwb::closure_workflow {

// ------------------------------------------------------- host session --

// The engine's ISessionContext seam bound to host-owned session state
// (Python ActionContext.current_map_id / map_documents): a cache-hit node
// did not re-publish its in-process handle; when the same process still
// holds the document, restore the pointer, else fail honestly downstream.
class SessionPointerBridge : public pwb::workflow_engine::ISessionContext {
public:
    // Host-owned current-document slot; *has_document* answers whether
    // this process still holds the live handle for a document id.
    SessionPointerBridge(std::string* current_map_id,
                         std::function<bool(const std::string&)> has_document)
        : current_map_id_(current_map_id),
          has_document_(std::move(has_document)) {}

    void merge_session_pointers() override {}  // single-host slot: merge is a no-op
    void restore_session_pointers(
        const pwb::domain::Json& outputs) override;

private:
    std::string* current_map_id_;
    std::function<bool(const std::string&)> has_document_;
};

// ------------------------------------------------------- ui bindings --

// Typed bundle for ui_controllers::WorkflowServiceApi's service seams.
// Each field matches the controller's std::function signature; bind into
// the controller's API struct verbatim.
struct WorkflowUiServiceBindings {
    // workflow.service.dashboard_state(project_root) → Json dict.
    std::function<pwb::domain::Json(const pwb::domain::Json&)> dashboard_state;
    // workflow.service.home_workflow_steps(project_root) → Json list.
    std::function<pwb::domain::Json(const pwb::domain::Json&)> home_workflow_steps;
    // workflow.qc.active_quality_reports(project_root) → Json list.
    std::function<pwb::domain::Json(const pwb::domain::Json&)>
        active_quality_reports;
    // workflow.service.build_affected_products_plan(project_root) → plan.
    std::function<pwb::workflow_runtime::RecomputePlan(const pwb::domain::Json&)>
        build_affected_plan;
};

// Bind the native services. `catalog` may be null (the controller's
// seams degrade exactly like Python's try/except paths — evidence-only).
[[nodiscard]] WorkflowUiServiceBindings bind_workflow_ui_services(
    pwb::workflow_runtime::CatalogRepository* catalog);

// ------------------------------------------------------ reopen recovery --

struct ReopenedWorkflow {
    pwb::workflow_runtime::CurrentProjectVersionContext context;
    // run_id → {state, completed/failed/pending node counts} of every
    // persisted run (the store authority — no in-memory ghosts).
    pwb::domain::Json runs;
    // Stale subjects under the resolved context (freshness evaluation).
    pwb::domain::Json staleness;
    // The minimal recompute plan for the stale products (REUSE_EXISTING
    // for finished work, REQUIRES_COMPUTE for the rest).
    pwb::workflow_runtime::RecomputePlan recompute_plan;
};

// Reopen recovery: reload persisted state and rebuild the workflow view.
// `store` is the persisted provenance (FileCatalogRepository reopened by
// the caller); `project` the portable document tree.
[[nodiscard]] ReopenedWorkflow reopen_project_workflow(
    const pwb::domain::Json& project,
    pwb::workflow_runtime::WorkflowRuntimeService& runtime);

}  // namespace pwb::closure_workflow
