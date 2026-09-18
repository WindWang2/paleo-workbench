// CONV-06: model.cpp — faithful port of paleo_workbench/workflow/dag/model.py.
#include <pwb/workflow_spec/model.hpp>

#include <algorithm>
#include <chrono>
#include <random>

#include <pwb/domain/sha256.hpp>

#include "python_repr.hpp"

namespace pwb::workflow_spec {

using detail::json_to_bool;
using detail::json_to_double;
using detail::json_to_int;
using detail::required_key;

std::string to_string(NodeState state) {
    switch (state) {
    case NodeState::pending: return "pending";
    case NodeState::running: return "running";
    case NodeState::succeeded: return "succeeded";
    case NodeState::failed: return "failed";
    case NodeState::cancelled: return "cancelled";
    case NodeState::skipped: return "skipped";
    case NodeState::unavailable: return "unavailable";
    }
    return "?";
}

NodeState node_state_from_string(const std::string& text) {
    if (text == "pending") return NodeState::pending;
    if (text == "running") return NodeState::running;
    if (text == "succeeded") return NodeState::succeeded;
    if (text == "failed") return NodeState::failed;
    if (text == "cancelled") return NodeState::cancelled;
    if (text == "skipped") return NodeState::skipped;
    if (text == "unavailable") return NodeState::unavailable;
    throw ModelError("unknown node state '" + text + "'");
}

bool is_terminal_node_state(NodeState state) noexcept {
    switch (state) {
    case NodeState::succeeded:
    case NodeState::failed:
    case NodeState::cancelled:
    case NodeState::skipped:
    case NodeState::unavailable:
        return true;
    default:
        return false;
    }
}

std::string to_string(RunState state) {
    switch (state) {
    case RunState::running: return "running";
    case RunState::completed: return "completed";
    case RunState::failed: return "failed";
    case RunState::cancelled: return "cancelled";
    case RunState::interrupted: return "interrupted";
    }
    return "?";
}

RunState run_state_from_string(const std::string& text) {
    if (text == "running") return RunState::running;
    if (text == "completed") return RunState::completed;
    if (text == "failed") return RunState::failed;
    if (text == "cancelled") return RunState::cancelled;
    if (text == "interrupted") return RunState::interrupted;
    throw ModelError("unknown run state '" + text + "'");
}

// ---------------------------------------------------------------- helpers --

namespace {

bool is_python_truthy(const domain::Json& value) {
    // Python `x or default` over JSON scalars/containers.
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_string()) return !value.get<std::string>().empty();
    if (value.is_array() || value.is_object()) return !value.empty();
    return true;  // numbers
}

// model._normalize: sort dict keys (UTF-8 byte order == code point order),
// pass scalars through.
domain::Json normalize_for_hash(const domain::Json& value) {
    if (value.is_object()) {
        std::vector<std::pair<std::string, domain::Json>> items;
        for (const auto& [key, item] : value.items()) {
            items.emplace_back(key, normalize_for_hash(item));
        }
        std::sort(items.begin(), items.end(),
                  [](const auto& a, const auto& b) { return a.first < b.first; });
        domain::Json sorted = domain::Json::object();
        for (auto& [key, item] : items) {
            sorted[key] = std::move(item);
        }
        return sorted;
    }
    if (value.is_array()) {
        domain::Json list = domain::Json::array();
        for (const auto& item : value) {
            list.push_back(normalize_for_hash(item));
        }
        return list;
    }
    return value;
}

}  // namespace

// ------------------------------------------------------------ RetryPolicy --

domain::Json RetryPolicy::to_dict() const {
    return domain::Json{
        {"max_attempts", max_attempts},
        {"backoff_seconds", backoff_seconds},
    };
}

RetryPolicy RetryPolicy::from_dict(const domain::Json& data) {
    const auto* retry =
        data.contains("retry") && !data.at("retry").is_null()
            ? &data.at("retry")
            : nullptr;
    RetryPolicy policy;
    if (retry != nullptr) {
        if (auto it = retry->find("max_attempts"); it != retry->end()) {
            policy.max_attempts = json_to_int(*it, "retry.max_attempts");
        }
        if (auto it = retry->find("backoff_seconds"); it != retry->end()) {
            policy.backoff_seconds =
                json_to_double(*it, "retry.backoff_seconds");
        }
    }
    return policy;
}

// ----------------------------------------------------------- NodeCondition --

domain::Json NodeCondition::to_dict() const {
    domain::Json d{{"kind", kind}};
    if (node.has_value()) d["node"] = *node;
    if (key.has_value()) d["key"] = *key;
    if (state.has_value()) d["state"] = *state;
    if (!value.is_null()) d["value"] = value;
    if (!conditions.empty()) {
        domain::Json list = domain::Json::array();
        for (const auto& sub : conditions) {
            list.push_back(sub.to_dict());
        }
        d["conditions"] = std::move(list);
    }
    if (has_condition()) d["condition"] = inner_condition().to_dict();
    return d;
}

NodeCondition NodeCondition::from_dict(const domain::Json& data) {
    NodeCondition parsed;
    // str(data.get("kind", "")) — scalars stringify, matching Python.
    if (auto it = data.find("kind"); it != data.end()) {
        parsed.kind = it->is_string() ? it->get<std::string>()
                                      : detail::py_str_scalar(*it);
    }
    if (auto it = data.find("conditions"); it != data.end()) {
        if (!it->is_array()) {
            // Python iterates the value and crashes on non-lists; fail closed
            // instead (D5).
            throw ModelError("conditions: expected a list");
        }
        for (const auto& item : *it) {
            parsed.conditions.push_back(NodeCondition::from_dict(item));
        }
    }
    if (auto it = data.find("condition"); it != data.end() && it->is_object()) {
        parsed.condition.push_back(NodeCondition::from_dict(*it));
    }
    if (auto it = data.find("node"); it != data.end() && it->is_string()) {
        parsed.node = it->get<std::string>();
    }
    if (auto it = data.find("key"); it != data.end() && it->is_string()) {
        parsed.key = it->get<std::string>();
    }
    if (auto it = data.find("value"); it != data.end() && !it->is_null()) {
        parsed.value = *it;
    }
    if (auto it = data.find("state"); it != data.end() && it->is_string()) {
        parsed.state = it->get<std::string>();
    }
    return parsed;
}

// --------------------------------------------------- validate_condition_tree --

std::vector<std::string> validate_condition_tree(const NodeCondition& condition) {
    static const std::vector<std::string> kSortedKinds = {
        "all_of", "any_of", "node_output_equals", "node_state",
        "node_succeeded", "not",
    };
    const bool kind_known =
        std::find(kSortedKinds.begin(), kSortedKinds.end(), condition.kind) !=
        kSortedKinds.end();
    if (!kind_known) {
        std::string joined = "[";
        for (std::size_t i = 0; i < kSortedKinds.size(); ++i) {
            if (i != 0) joined += ", ";
            joined += "'" + kSortedKinds[i] + "'";
        }
        joined += "]";
        return {"condition kind '" + condition.kind + "' is not one of " + joined};
    }

    std::vector<std::string> problems;
    const bool needs_node = condition.kind == "node_succeeded" ||
                            condition.kind == "node_output_equals" ||
                            condition.kind == "node_state";
    // Python checks `not condition.node` etc. — an empty string is falsy and
    // reported exactly like a missing reference.
    if (needs_node &&
        (!condition.node.has_value() || condition.node->empty())) {
        problems.push_back("condition '" + condition.kind +
                           "' requires a node reference");
    }
    if (condition.kind == "node_output_equals" &&
        (!condition.key.has_value() || condition.key->empty())) {
        problems.push_back("node_output_equals requires an output key");
    }
    if (condition.kind == "node_state" &&
        (!condition.state.has_value() || condition.state->empty())) {
        problems.push_back("node_state requires a state value");
    }
    if (condition.kind == "all_of" || condition.kind == "any_of") {
        if (condition.conditions.empty()) {
            problems.push_back(condition.kind + " requires conditions");
        }
        for (const auto& sub : condition.conditions) {
            for (auto& problem : validate_condition_tree(sub)) {
                problems.push_back(std::move(problem));
            }
        }
    }
    if (condition.kind == "not") {
        if (!condition.has_condition()) {
            problems.push_back("'not' requires a condition");
        } else {
            for (auto& problem :
                 validate_condition_tree(condition.inner_condition())) {
                problems.push_back(std::move(problem));
            }
        }
    }
    return problems;
}

// ---------------------------------------------------------------- NodeSpec --

domain::Json NodeSpec::to_dict() const {
    domain::Json d{
        {"node_id", node_id},
        {"action_id", action_id},
        {"parameters", parameters},
        {"depends_on", domain::Json::array()},
        {"condition", nullptr},
        {"retry", retry.to_dict()},
        {"description", description},
    };
    for (const auto& dep : depends_on) {
        d["depends_on"].push_back(dep);
    }
    if (condition.has_value()) d["condition"] = condition->to_dict();
    return d;
}

NodeSpec NodeSpec::from_dict(const domain::Json& data) {
    NodeSpec parsed;
    // str(data["node_id"]) / str(data["action_id"]) — required keys.
    {
        const auto& raw = required_key(data, "node_id");
        if (!raw.is_string()) {
            throw ModelError("node_id: expected a string");
        }
        parsed.node_id = raw.get<std::string>();
    }
    {
        const auto& raw = required_key(data, "action_id");
        if (!raw.is_string()) {
            throw ModelError("action_id: expected a string");
        }
        parsed.action_id = raw.get<std::string>();
    }
    if (auto it = data.find("parameters"); it != data.end()) {
        // dict(data.get("parameters") or {}): falsy values fall to {}.
        if (is_python_truthy(*it)) {
            if (!it->is_object()) {
                throw ModelError("parameters: expected an object");
            }
            parsed.parameters = *it;
        }
    }
    if (auto it = data.find("depends_on"); it != data.end()) {
        // tuple(data.get("depends_on") or ()): falsy values fall to ().
        if (is_python_truthy(*it)) {
            if (!it->is_array()) {
                // Python's tuple(str) char-splitting quirk is not reproduced;
                // garbage fails closed (D5).
                throw ModelError("depends_on: expected a list");
            }
            for (const auto& dep : *it) {
                parsed.depends_on.push_back(dep.get<std::string>());
            }
        }
    }
    if (auto it = data.find("condition"); it != data.end() && it->is_object()) {
        parsed.condition = NodeCondition::from_dict(*it);
    }
    parsed.retry = RetryPolicy::from_dict(data);
    if (auto it = data.find("description");
        it != data.end() && is_python_truthy(*it)) {
        if (!it->is_string()) {
            throw ModelError("description: expected a string");
        }
        parsed.description = it->get<std::string>();
    }
    return parsed;
}

// ---------------------------------------------------------------- SlotSpec --

domain::Json SlotSpec::to_dict() const {
    return domain::Json{
        {"name", name},
        {"schema", schema},
        {"required", required},
        {"default", default_value},
        {"description", description},
    };
}

SlotSpec SlotSpec::from_dict(const domain::Json& data) {
    SlotSpec parsed;
    {
        const auto& raw = required_key(data, "name");
        if (!raw.is_string()) {
            throw ModelError("name: expected a string");
        }
        parsed.name = raw.get<std::string>();
    }
    if (auto it = data.find("schema"); it != data.end()) {
        if (is_python_truthy(*it)) {
            if (!it->is_object()) {
                throw ModelError("schema: expected an object");
            }
            parsed.schema = *it;
        }
    }
    if (auto it = data.find("required"); it != data.end()) {
        parsed.required = json_to_bool(*it);
    }
    if (auto it = data.find("default"); it != data.end()) {
        parsed.default_value = *it;
    }
    if (auto it = data.find("description");
        it != data.end() && is_python_truthy(*it)) {
        if (!it->is_string()) {
            throw ModelError("description: expected a string");
        }
        parsed.description = it->get<std::string>();
    }
    return parsed;
}

// ------------------------------------------------------------- WorkflowSpec --

domain::Json WorkflowSpec::to_dict() const {
    domain::Json d{
        {"schema_version", schema_version},
        {"workflow_id", workflow_id},
        {"name", name},
        {"description", description},
        {"max_concurrency", max_concurrency},
        {"slots", domain::Json::array()},
        {"nodes", domain::Json::array()},
    };
    for (const auto& slot : slots) {
        d["slots"].push_back(slot.to_dict());
    }
    for (const auto& n : nodes) {
        d["nodes"].push_back(n.to_dict());
    }
    return d;
}

WorkflowSpec WorkflowSpec::from_dict(const domain::Json& data) {
    WorkflowSpec parsed;
    {
        const auto& raw = required_key(data, "workflow_id");
        if (!raw.is_string()) {
            throw ModelError("workflow_id: expected a string");
        }
        parsed.workflow_id = raw.get<std::string>();
    }
    {
        const auto& raw = required_key(data, "name");
        if (!raw.is_string()) {
            throw ModelError("name: expected a string");
        }
        parsed.name = raw.get<std::string>();
    }
    if (auto it = data.find("nodes"); it != data.end()) {
        if (!it->is_array()) {
            throw ModelError("nodes: expected a list");
        }
        for (const auto& item : *it) {
            parsed.nodes.push_back(NodeSpec::from_dict(item));
        }
    }
    if (auto it = data.find("slots"); it != data.end()) {
        if (!it->is_array()) {
            throw ModelError("slots: expected a list");
        }
        for (const auto& item : *it) {
            parsed.slots.push_back(SlotSpec::from_dict(item));
        }
    }
    // schema_version uses data.get(..., default) — presence wins even when
    // falsy (unlike the description fields' `or ""` semantics).
    if (auto it = data.find("schema_version"); it != data.end()) {
        if (!it->is_string()) {
            throw ModelError("schema_version: expected a string");
        }
        parsed.schema_version = it->get<std::string>();
    }
    if (auto it = data.find("max_concurrency"); it != data.end()) {
        parsed.max_concurrency = json_to_int(*it, "max_concurrency");
    }
    if (auto it = data.find("description");
        it != data.end() && is_python_truthy(*it)) {
        if (!it->is_string()) {
            throw ModelError("description: expected a string");
        }
        parsed.description = it->get<std::string>();
    }
    return parsed;
}

const NodeSpec& WorkflowSpec::node(const std::string& node_id) const {
    for (const auto& n : nodes) {
        if (n.node_id == node_id) {
            return n;
        }
    }
    throw ModelError("workflow '" + workflow_id + "' has no node '" + node_id +
                     "'");
}

std::string WorkflowSpec::spec_hash() const {
    return canonical_hash(to_dict());
}

// ----------------------------------------------------------------- NodeRun --

domain::Json NodeRun::to_dict() const {
    domain::Json d{
        {"node_id", node_id},
        {"state", to_string(state)},
        {"attempt", attempt},
        {"action_status", nullptr},
        {"from_cache", from_cache},
        {"parameters", parameters},
        {"input_version_ids", domain::Json::array()},
        {"cache_identity", nullptr},
        {"output_version_ids", domain::Json::array()},
        {"outputs", outputs},
        {"receipt", nullptr},
        {"skip_reason", nullptr},
        {"error", nullptr},
        {"started_at", nullptr},
        {"finished_at", nullptr},
    };
    for (const auto& id : input_version_ids) {
        d["input_version_ids"].push_back(id);
    }
    if (action_status.has_value()) d["action_status"] = *action_status;
    if (cache_identity.has_value()) d["cache_identity"] = *cache_identity;
    for (const auto& id : output_version_ids) {
        d["output_version_ids"].push_back(id);
    }
    if (receipt.has_value()) d["receipt"] = *receipt;
    if (skip_reason.has_value()) d["skip_reason"] = *skip_reason;
    if (error.has_value()) d["error"] = *error;
    if (!started_at.is_null()) d["started_at"] = started_at;
    if (!finished_at.is_null()) d["finished_at"] = finished_at;
    return d;
}

NodeRun NodeRun::from_dict(const domain::Json& data) {
    NodeRun parsed;
    {
        const auto& raw = required_key(data, "node_id");
        if (!raw.is_string()) {
            throw ModelError("node_id: expected a string");
        }
        parsed.node_id = raw.get<std::string>();
    }
    if (auto it = data.find("state"); it != data.end()) {
        // NodeState(data.get("state", "pending")): a present non-string is a
        // Python ValueError, never a silent default.
        if (!it->is_string()) {
            throw ModelError("state: expected a string");
        }
        parsed.state = node_state_from_string(it->get<std::string>());
    }
    if (auto it = data.find("attempt"); it != data.end()) {
        parsed.attempt = json_to_int(*it, "attempt");
    }
    if (auto it = data.find("action_status");
        it != data.end() && it->is_string()) {
        parsed.action_status = it->get<std::string>();
    }
    if (auto it = data.find("from_cache"); it != data.end()) {
        parsed.from_cache = json_to_bool(*it);
    }
    if (auto it = data.find("parameters"); it != data.end()) {
        if (is_python_truthy(*it)) {
            if (!it->is_object()) {
                throw ModelError("parameters: expected an object");
            }
            parsed.parameters = *it;
        }
    }
    if (auto it = data.find("input_version_ids");
        it != data.end() && !it->is_null()) {
        for (const auto& id : *it) {
            parsed.input_version_ids.push_back(id.get<std::string>());
        }
    }
    if (auto it = data.find("cache_identity");
        it != data.end() && it->is_string()) {
        parsed.cache_identity = it->get<std::string>();
    }
    if (auto it = data.find("output_version_ids");
        it != data.end() && !it->is_null()) {
        for (const auto& id : *it) {
            parsed.output_version_ids.push_back(id.get<std::string>());
        }
    }
    if (auto it = data.find("outputs"); it != data.end()) {
        if (is_python_truthy(*it)) {
            if (!it->is_object()) {
                throw ModelError("outputs: expected an object");
            }
            parsed.outputs = *it;
        }
    }
    if (auto it = data.find("receipt"); it != data.end() && !it->is_null()) {
        parsed.receipt = *it;
    }
    if (auto it = data.find("skip_reason"); it != data.end() && it->is_string()) {
        parsed.skip_reason = it->get<std::string>();
    }
    if (auto it = data.find("error"); it != data.end() && it->is_string()) {
        parsed.error = it->get<std::string>();
    }
    if (auto it = data.find("started_at"); it != data.end()) {
        parsed.started_at = *it;  // int stays int (Python has no coercion)
    }
    if (auto it = data.find("finished_at"); it != data.end()) {
        parsed.finished_at = *it;
    }
    return parsed;
}

// -------------------------------------------------------------- WorkflowRun --

NodeRun* WorkflowRun::find_node_run(const std::string& id) {
    for (auto& [node_id, node_run] : node_runs) {
        if (node_id == id) return &node_run;
    }
    return nullptr;
}

const NodeRun* WorkflowRun::find_node_run(const std::string& id) const {
    for (const auto& [node_id, node_run] : node_runs) {
        if (node_id == id) return &node_run;
    }
    return nullptr;
}

domain::Json WorkflowRun::to_dict() const {
    domain::Json d{
        {"run_id", run_id},
        {"workflow", workflow.to_dict()},
        {"state", to_string(state)},
        {"slot_values", slot_values},
        {"node_runs", domain::Json::array()},
        {"project_name", nullptr},
        {"project_path", nullptr},
        {"created_at", nullptr},
        {"updated_at", nullptr},
        {"spec_hash", nullptr},
        {"parent_run_id", nullptr},
    };
    for (const auto& [node_id, node_run] : node_runs) {
        d["node_runs"].push_back(node_run.to_dict());
    }
    if (project_name.has_value()) d["project_name"] = *project_name;
    if (project_path.has_value()) d["project_path"] = *project_path;
    if (!created_at.is_null()) d["created_at"] = created_at;
    if (!updated_at.is_null()) d["updated_at"] = updated_at;
    if (spec_hash.has_value()) d["spec_hash"] = *spec_hash;
    if (parent_run_id.has_value()) d["parent_run_id"] = *parent_run_id;
    return d;
}

WorkflowRun WorkflowRun::from_dict(const domain::Json& data) {
    WorkflowRun run;
    {
        const auto& raw = required_key(data, "run_id");
        if (!raw.is_string()) {
            throw ModelError("run_id: expected a string");
        }
        run.run_id = raw.get<std::string>();
    }
    run.workflow = WorkflowSpec::from_dict(required_key(data, "workflow"));
    if (auto it = data.find("state"); it != data.end()) {
        if (!it->is_string()) {
            throw ModelError("state: expected a string");
        }
        run.state = run_state_from_string(it->get<std::string>());
    }
    if (auto it = data.find("slot_values"); it != data.end()) {
        if (is_python_truthy(*it)) {
            if (!it->is_object()) {
                throw ModelError("slot_values: expected an object");
            }
            run.slot_values = *it;
        }
    }
    if (auto it = data.find("project_name"); it != data.end() && it->is_string()) {
        run.project_name = it->get<std::string>();
    }
    if (auto it = data.find("project_path"); it != data.end() && it->is_string()) {
        run.project_path = it->get<std::string>();
    }
    if (auto it = data.find("created_at"); it != data.end()) {
        run.created_at = *it;
    }
    if (auto it = data.find("updated_at"); it != data.end()) {
        run.updated_at = *it;
    }
    if (auto it = data.find("spec_hash"); it != data.end() && it->is_string()) {
        run.spec_hash = it->get<std::string>();
    }
    if (auto it = data.find("parent_run_id");
        it != data.end() && it->is_string()) {
        run.parent_run_id = it->get<std::string>();
    }
    if (auto it = data.find("node_runs"); it != data.end()) {
        if (!it->is_array()) {
            throw ModelError("node_runs: expected a list");
        }
        for (const auto& item : *it) {
            NodeRun node_run = NodeRun::from_dict(item);
            if (NodeRun* existing = run.find_node_run(node_run.node_id)) {
                // Python dict: assignment keeps the first insertion slot.
                *existing = node_run;
            } else {
                run.node_runs.emplace_back(node_run.node_id,
                                           std::move(node_run));
            }
        }
    }
    // Tolerate store schema drift: every spec node gets a pending entry.
    for (const auto& n : run.workflow.nodes) {
        if (run.find_node_run(n.node_id) == nullptr) {
            run.node_runs.emplace_back(n.node_id, NodeRun{n.node_id});
        }
    }
    return run;
}

// -------------------------------------------------------------- create_run --

WorkflowRun create_run(const WorkflowSpec& workflow, domain::Json slot_values) {
    const auto now = std::chrono::duration<double>(
                         std::chrono::system_clock::now().time_since_epoch())
                         .count();
    static std::mt19937_64 generator{std::random_device{}()};
    static const char* kHex = "0123456789abcdef";
    std::string run_id;
    for (int i = 0; i < 16; ++i) {
        run_id += kHex[generator() % 16];
    }
    return create_run(workflow, std::move(slot_values), std::move(run_id), now);
}

WorkflowRun create_run(const WorkflowSpec& workflow, domain::Json slot_values,
                       std::string run_id, double now_seconds) {
    WorkflowRun run;
    run.run_id = std::move(run_id);
    run.workflow = workflow;
    run.slot_values = std::move(slot_values);
    run.created_at = domain::Json(now_seconds);
    run.updated_at = domain::Json(now_seconds);
    run.spec_hash = workflow.spec_hash();
    for (const auto& n : workflow.nodes) {
        run.node_runs.emplace_back(n.node_id, NodeRun{n.node_id});
    }
    return run;
}

// ---------------------------------------------------------- canonical_hash --

std::string canonical_hash(const domain::Json& value) {
    const std::string payload = normalize_for_hash(value).dump();
    return domain::Sha256::of_bytes(payload);
}

}  // namespace pwb::workflow_spec
