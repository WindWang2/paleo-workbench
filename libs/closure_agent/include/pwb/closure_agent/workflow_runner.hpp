#pragma once

// Workflow consumption seam — line 11's session delegates workflow-shaped
// work to line 02's engine (libs/workflow_engine RunEngine) through this
// interface. The adapter target (pwb_closure_agent_workflow) is compiled
// only when the workflow engine is part of the build; it bridges
// ActionRegistry <-> IActionCatalog and routes every workflow node through
// the guarded HarnessExecutor (guard pipeline never bypassed).

#include <pwb/closure_agent/context.hpp>

#include <pwb/domain/json.hpp>

#include <string>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;

class IWorkflowRunner {
public:
    virtual ~IWorkflowRunner() = default;

    // Run a WorkflowSpec ({"nodes": [...], "edges": [...], "params": {...},
    // "slots": {...}} shape) with the given slot values. Returns a summary:
    // {"run_id","workflow_id","state","nodes":{id:{"state","status"}}}.
    // Throws std::runtime_error on validation/persistence failure
    // (WorkflowValidationError / CheckpointFailed pass through).
    virtual Json run(const Json& workflow_spec, const Json& slot_values,
                     ActionContext& context) = 0;
};

}  // namespace pwb::closure_agent
