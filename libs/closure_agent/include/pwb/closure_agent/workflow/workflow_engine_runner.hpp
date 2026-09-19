#pragma once

// RunEngine adapter — binds line 02's workflow engine
// (pwb::workflow_engine::RunEngine) to the line-11 guarded executor. Every
// workflow node executes through HarnessExecutor.execute (guard pipeline
// never bypassed — Harness 2.0 H2 contract); node cancellation bridges from
// the engine's CancelToken via the ActionContext cancel probe.
//
// This target exists only when Pwb::WorkflowEngine is part of the build
// (configure with PWB_BUILD_CONV_06 + PWB_BUILD_CONV_07 + kernel).

#include <pwb/closure_agent/executor.hpp>
#include <pwb/closure_agent/workflow_runner.hpp>

#include <filesystem>

namespace pwb::closure_agent {

class WorkflowEngineRunner : public IWorkflowRunner {
public:
    WorkflowEngineRunner(const HarnessExecutor* executor,
                         const ActionRegistry* registry,
                         std::filesystem::path store_directory);

    // Run a full WorkflowSpec (workflow_spec::WorkflowSpec::from_dict JSON
    // shape) to completion in the calling thread. Returns
    // {"run_id","workflow_id","state","nodes":{id:{"state","status"}}}.
    Json run(const Json& workflow_spec, const Json& slot_values,
             ActionContext& context) override;

private:
    const HarnessExecutor* executor_;
    const ActionRegistry* registry_;
    std::filesystem::path store_directory_;
};

}  // namespace pwb::closure_agent
