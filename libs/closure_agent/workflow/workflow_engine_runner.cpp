// WorkflowEngineRunner implementation — catalog bridge + guarded node
// functions over the line-02 RunEngine.
#include <pwb/closure_agent/workflow/workflow_engine_runner.hpp>

#include <pwb/workflow_engine/engine.hpp>
#include <pwb/workflow_engine/run_engine.hpp>
#include <pwb/workflow_engine/store.hpp>
#include <pwb/workflow_spec/model.hpp>

#include <map>
#include <memory>
#include <stdexcept>

namespace pwb::closure_agent {

namespace {

// ActionRegistry viewed as the engine's IActionCatalog.
class CatalogBridge : public pwb::workflow_engine::IActionCatalog {
public:
    explicit CatalogBridge(const ActionRegistry* registry) : registry_(registry) {}

    std::optional<pwb::workflow_engine::ActionInfo> get(
        const std::string& action_id) const override {
        const ActionSpec* spec = registry_->find(action_id);
        if (spec == nullptr) return std::nullopt;
        pwb::workflow_engine::ActionInfo info;
        info.action_id = spec->action_id;
        info.version = spec->version;
        info.cacheable = spec->cacheable;
        info.input_schema = spec->input_schema.is_object() ? spec->input_schema
                                                          : Json::object();
        info.description = spec->description;
        return info;
    }

    std::vector<std::string> ids() const override {
        std::vector<std::string> names;
        for (const auto* spec : registry_->specs()) names.push_back(spec->action_id);
        return names;
    }

private:
    const ActionRegistry* registry_;
};

}  // namespace

WorkflowEngineRunner::WorkflowEngineRunner(const HarnessExecutor* executor,
                                           const ActionRegistry* registry,
                                           std::filesystem::path store_directory)
    : executor_(executor), registry_(registry),
      store_directory_(std::move(store_directory)) {
    if (executor_ == nullptr || registry_ == nullptr) {
        throw std::invalid_argument(
            "WorkflowEngineRunner requires an executor and a registry");
    }
}

Json WorkflowEngineRunner::run(const Json& workflow_spec_json,
                               const Json& slot_values, ActionContext& context) {
    namespace we = pwb::workflow_engine;
    namespace ws = pwb::workflow_spec;

    ws::WorkflowSpec spec = ws::WorkflowSpec::from_dict(workflow_spec_json);

    CatalogBridge catalog(registry_);
    we::WorkflowRunStore store(store_directory_);

    // One guarded executor body per workflow action. The engine keys the
    // function map by ACTION id (the spec's op); the engine hands us the
    // node's bound parameters and the action runs through the SAME guard
    // pipeline as a direct agent tool call. `context` must outlive the
    // engine.run() call (caller contract).
    we::RunFunctionMap functions;
    for (const auto& node : spec.nodes) {
        functions[node.action_id] =
            [this, &context, action_id = node.action_id](const Json& bound_params,
                                                         const we::CancelToken& token)
            -> we::ActionResultView {
            if (token.is_cancelled()) throw we::Cancelled{};
            ActionContext node_context = context.derived();
            node_context.cancel_probe = [&token] { return token.is_cancelled(); };
            const ActionResult result =
                executor_->execute(action_id, bound_params, &node_context);
            we::ActionResultView view;
            view.status = result.status;
            view.outputs = result.outputs;
            view.verification = result.verification;
            view.warnings = result.warnings;
            view.metrics = result.metrics;
            view.error = result.error;
            view.elapsed_ms = result.elapsed_ms;
            return view;
        };
    }

    we::RunEngine engine(catalog, std::move(functions), store);

    we::RunContext run_context;
    run_context.workspace_id = context.workspace_id.value_or("");
    run_context.project_path = context.project_path.value_or("");

    we::RunOptions options;
    ws::WorkflowRun run = engine.create_run(spec, slot_values, &run_context);
    run = engine.run(run.run_id, &run_context, options);

    Json summary = Json::object();
    summary["run_id"] = run.run_id;
    summary["workflow_id"] = run.workflow.workflow_id;
    summary["state"] = pwb::workflow_spec::to_string(run.state);
    Json nodes = Json::object();
    for (const auto& [node_id, node_run] : run.node_runs) {
        Json entry = Json::object();
        entry["state"] = pwb::workflow_spec::to_string(node_run.state);
        entry["status"] =
            node_run.action_status ? Json(*node_run.action_status) : Json(nullptr);
        entry["error"] =
            node_run.error ? Json(*node_run.error) : Json(nullptr);
        nodes[node_id] = entry;
    }
    summary["nodes"] = nodes;
    return summary;
}

}  // namespace pwb::closure_agent
