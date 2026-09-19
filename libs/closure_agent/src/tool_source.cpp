// tool_source.cpp — HarnessToolSource binding (harness/llm.py port).
#include <pwb/closure_agent/tool_source.hpp>

namespace pwb::closure_agent {

HarnessToolSource::HarnessToolSource(const HarnessExecutor& executor,
                                     const ActionRegistry& registry,
                                     std::function<ActionContext()> context_factory)
    : executor_(&executor), registry_(&registry),
      context_factory_(std::move(context_factory)) {}

std::vector<Json> HarnessToolSource::tool_schemas() const {
    return registry_->tool_schemas();
}

Json HarnessToolSource::execute_tool(const std::string& name,
                                     const Json& arguments) const {
    // Python: action_id = name.replace("__", ".").
    std::string mapped;
    mapped.reserve(name.size());
    for (std::size_t i = 0; i < name.size(); ++i) {
        if (i + 1 < name.size() && name[i] == '_' && name[i + 1] == '_') {
            mapped += '.';
            ++i;
        } else {
            mapped += name[i];
        }
    }
    ActionContext context =
        context_factory_ ? context_factory_() : ActionContext();
    const ActionResult result = executor_->execute(
        mapped, arguments.is_object() ? arguments : Json::object(), &context);
    return result.to_dict();
}

}  // namespace pwb::closure_agent
