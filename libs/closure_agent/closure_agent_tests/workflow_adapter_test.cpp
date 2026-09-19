// closure_agent.workflow — line-02 RunEngine consumption through the
// adapter: workflow nodes execute through the guarded HarnessExecutor
// (guard pipeline never bypassed) and the run persists through the engine's
// own store. Cancellation note (honest scope): the token→cancel_probe
// bridge into node bodies is covered at the executor level
// (closure_agent.executor asserts a probe-armed context lands `cancelled`);
// flipping the ENGINE token mid-run is the engine's own tested contract
// (workflow_engine_tests), so no cross-thread engine-cancel test lives here.
#include "test_util.hpp"

#include <pwb/closure_agent/workflow/workflow_engine_runner.hpp>

#include <filesystem>

using namespace pwb::closure_agent;

namespace {

std::filesystem::path store_dir() {
    return std::filesystem::temp_directory_path() / "closure-agent-workflow-test";
}

ActionRegistry& shared_registry() {
    static ActionRegistry registry;
    static const bool initialized = [] {
        auto add = [](ActionRegistry& reg, const std::string& id, ActionRisk risk,
                      ActionHandler handler) {
            ActionSpec spec;
            spec.action_id = id;
            spec.description = "workflow adapter action " + id;
            spec.risk = risk;
            spec.handler = std::move(handler);
            reg.register_spec(spec);
        };
        add(registry, "data.discover", ActionRisk::Read,
            [](void*, const Json& p) { return Json{{"assets", 3}, {"in", p}}; });
        add(registry, "carto.interpolate", ActionRisk::Compute,
            [](void*, const Json& p) {
                return Json{{"grid", Json::array({1.0, 2.0, 3.0, 4.0, 5.0})},
                            {"source", p.value("source", "none")}};
            });
        add(registry, "map.export", ActionRisk::Write,
            [](void*, const Json&) { return Json{{"exported", true}}; });
        return true;
    }();
    (void)initialized;
    return registry;
}

}  // namespace

int main() {
    std::error_code ec;
    std::filesystem::remove_all(store_dir(), ec);

    ActionRegistry& registry = shared_registry();
    HarnessExecutor executor(registry);
    WorkflowEngineRunner runner(&executor, &registry, store_dir());

    // ---- successful run: every node through the guard pipeline --------------
    Json spec = Json::object();
    spec["workflow_id"] = "wf-factor-map";
    spec["name"] = "因子编图小流程";
    spec["schema_version"] = "1.0";
    spec["slots"] = Json::array();
    Json nodes = Json::array();
    Json discover = Json::object();
    discover["node_id"] = "discover";
    discover["action_id"] = "data.discover";
    discover["parameters"] = Json::object();
    discover["depends_on"] = std::vector<std::string>{};
    nodes.push_back(discover);
    Json interpolate = Json::object();
    interpolate["node_id"] = "interpolate";
    interpolate["action_id"] = "carto.interpolate";
    Json params = Json::object();
    params["source"] = "discover";
    interpolate["parameters"] = params;
    interpolate["depends_on"] = std::vector<std::string>{"discover"};
    nodes.push_back(interpolate);
    spec["nodes"] = nodes;

    ActionContext context;
    context.workspace_id = "workspace-x";
    const Json summary = runner.run(spec, Json::object(), context);
    check(summary["workflow_id"] == "wf-factor-map", "run summary workflow id");
    check(summary["state"] == "completed", "run completed: " + summary.dump());
    check(summary["nodes"]["discover"]["state"] == "succeeded",
          "discover node succeeded");
    check(summary["nodes"]["interpolate"]["state"] == "succeeded",
          "interpolate node succeeded");

    // The run persisted through the engine's own store (02's checkpointing).
    bool persisted = false;
    for (const auto& entry : std::filesystem::directory_iterator(store_dir())) {
        if (entry.path().extension() == ".json") persisted = true;
    }
    check(persisted, "workflow run checkpointed by the engine store");

    // ---- guard pipeline active inside workflow nodes -------------------------
    // A write-risk action without permission must fail the node (rejected),
    // not bypass the guards.
    Json write_spec = Json::object();
    write_spec["workflow_id"] = "wf-write";
    write_spec["name"] = "导出小流程";
    write_spec["slots"] = Json::array();
    Json write_nodes = Json::array();
    Json export_node = Json::object();
    export_node["node_id"] = "export";
    export_node["action_id"] = "map.export";
    export_node["depends_on"] = std::vector<std::string>{};
    write_nodes.push_back(export_node);
    write_spec["nodes"] = write_nodes;
    ActionContext read_only;  // READ+COMPUTE default permissions
    const Json write_summary = runner.run(write_spec, Json::object(), read_only);
    check(write_summary["state"] == "failed",
          "unauthorized workflow node fails the run");
    check(write_summary["nodes"]["export"]["status"] == "rejected",
          "guard verdict surfaced on the node (rejected)");

    std::filesystem::remove_all(store_dir(), ec);

    return test_exit("closure_agent.workflow");
}
