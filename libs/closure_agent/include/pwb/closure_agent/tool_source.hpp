#pragma once

// ToolSource seam — C++ port of paleo_workbench/harness/llm.py's
// HarnessToolSource: binds a HarnessExecutor + ActionRegistry as the tool
// surface an external agent runtime calls. Tool names use the derived
// schema naming ("geology__factor_summary"); execution goes through the
// guarded pipeline — never around it.

#include <pwb/closure_agent/context.hpp>
#include <pwb/closure_agent/executor.hpp>

#include <functional>
#include <vector>

namespace pwb::closure_agent {

class HarnessToolSource {
public:
    HarnessToolSource(const HarnessExecutor& executor,
                      const ActionRegistry& registry,
                      std::function<ActionContext()> context_factory = nullptr);

    // Agent tool schemas derived from the registry (single source of truth).
    std::vector<Json> tool_schemas() const;

    // `name` uses the derived schema naming; `arguments` is the parameter
    // object. Returns ActionResult.to_dict().
    Json execute_tool(const std::string& name, const Json& arguments) const;

private:
    const HarnessExecutor* executor_;
    const ActionRegistry* registry_;
    std::function<ActionContext()> context_factory_;
};

}  // namespace pwb::closure_agent
