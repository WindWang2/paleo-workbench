// CONV-32: reproduction.cpp — faithful port of
// paleo_workbench/workflow/dag/reproduction.py (describe_reproduction):
// a pure projection of one persisted run explaining how to re-run it
// (spec node order, exact key order). Frozen against
// tools/oracle/generate_workflow_store_fixtures.py.
#include <pwb/workflow_engine/store.hpp>

namespace pwb::workflow_engine {

namespace {

// bool(x) over the JSON subset (numbers truthy, "" / {} / [] / null falsy).
bool python_truthy(const domain::Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_string()) return !value.get<std::string>().empty();
    if (value.is_array() || value.is_object()) return !value.empty();
    return true;
}

// receipt.get(key) over `(node_run.receipt if node_run else None) or {}`:
// absent/falsy receipt and missing/null key all read as null. (A truthy
// non-object receipt would crash Python's .get; the projection degrades
// instead — receipts are always objects in practice.)
const domain::Json* receipt_get(const std::optional<domain::Json>& receipt,
                                const char* key) {
    if (!receipt.has_value() || !receipt->is_object() || receipt->empty()) {
        return nullptr;
    }
    const auto it = receipt->find(key);
    if (it == receipt->end() || it->is_null()) return nullptr;
    return &*it;
}

domain::Json json_or_null(const domain::Json* value) {
    return value != nullptr ? *value : domain::Json(nullptr);
}

}  // namespace

Json describe_reproduction(const workflow_spec::WorkflowRun& run) {
    domain::Json nodes = domain::Json::array();
    for (const auto& node : run.workflow.nodes) {
        const workflow_spec::NodeRun* node_run =
            run.find_node_run(node.node_id);
        domain::Json entry = domain::Json::object();
        entry["node_id"] = node.node_id;
        entry["action_id"] = node.action_id;
        entry["action_version"] =
            json_or_null(receipt_get(node_run ? node_run->receipt
                                              : std::nullopt,
                                     "action_version"));
        entry["deterministic_action"] = nullptr;
        entry["parameters"] =
            node_run != nullptr ? node_run->parameters
                                : domain::Json::object();
        domain::Json input_ids = domain::Json::array();
        if (node_run != nullptr) {
            for (const std::string& id : node_run->input_version_ids) {
                input_ids.push_back(id);
            }
        }
        entry["input_version_ids"] = std::move(input_ids);
        domain::Json output_ids = domain::Json::array();
        if (node_run != nullptr) {
            for (const std::string& id : node_run->output_version_ids) {
                output_ids.push_back(id);
            }
        }
        entry["output_version_ids"] = std::move(output_ids);
        entry["provider_id"] =
            json_or_null(receipt_get(node_run ? node_run->receipt
                                              : std::nullopt,
                                     "provider_id"));
        entry["provider_version"] =
            json_or_null(receipt_get(node_run ? node_run->receipt
                                              : std::nullopt,
                                     "provider_version"));
        // receipt.get("cache_identity") or node_run.cache_identity
        domain::Json cache_identity = nullptr;
        if (node_run != nullptr) {
            const domain::Json* from_receipt =
                receipt_get(node_run->receipt, "cache_identity");
            if (from_receipt != nullptr) {
                cache_identity = *from_receipt;
            } else if (node_run->cache_identity.has_value()) {
                cache_identity = *node_run->cache_identity;
            }
        }
        entry["cache_identity"] = std::move(cache_identity);
        entry["from_cache"] = node_run != nullptr
                                  ? domain::Json(node_run->from_cache)
                                  : domain::Json(nullptr);
        entry["executed"] =
            node_run != nullptr &&
            node_run->state == workflow_spec::NodeState::succeeded &&
            !node_run->from_cache;
        nodes.push_back(std::move(entry));
    }

    // FIRST node_run (insertion order) whose receipt carries a truthy
    // environment block.
    domain::Json environment = nullptr;
    for (const auto& [node_id, node_run] : run.node_runs) {
        if (!node_run.receipt.has_value()) continue;
        const domain::Json& receipt = *node_run.receipt;
        if (!receipt.is_object() || receipt.empty()) continue;
        const auto it = receipt.find("environment");
        if (it != receipt.end() && python_truthy(*it)) {
            environment = *it;
            break;
        }
    }

    return domain::Json{
        {"run_id", run.run_id},
        {"workflow_id", run.workflow.workflow_id},
        {"workflow_schema_version", run.workflow.schema_version},
        {"spec_hash", run.spec_hash.has_value()
                          ? domain::Json(*run.spec_hash)
                          : domain::Json(nullptr)},
        {"slot_values", run.slot_values},
        {"project",
         domain::Json{
             {"name", run.project_name.has_value()
                          ? domain::Json(*run.project_name)
                          : domain::Json(nullptr)},
             {"path", run.project_path.has_value()
                          ? domain::Json(*run.project_path)
                          : domain::Json(nullptr)},
         }},
        {"nodes", std::move(nodes)},
        {"environment", std::move(environment)},
        {"contract",
         domain::Json{
             {"bit_identity",
              "promised only for nodes whose action/provider declares "
              "deterministic and whose input version ids match"},
             {"how_to_rerun",
              "load the recipe saved from this run, rebind slots, and run "
              "through workflow.run — completed nodes with matching cache "
              "identity are reused, everything else re-executes"},
         }},
    };
}

}  // namespace pwb::workflow_engine
