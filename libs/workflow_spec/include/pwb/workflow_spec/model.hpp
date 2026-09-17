// WorkflowSpec DAG pure model, ported from
// paleo_workbench/workflow/dag/model.py (CONV-06, full-conversion plan M7
// leaf: DAG *definition*, not the executor — engine/store stay Python until
// the 07 slice).
//
// Specs are data, never code: parameters are JSON literals or typed binding
// markers ($slot / $ref / $context); conditions are declarative trees. JSON
// round-trip (to_dict key order, from_dict coercions, canonical_hash) is
// frozen against the Python oracle; see
// docs/development/cpp-conversion-swarm-20/ledgers/06-decisions.md.
#pragma once

#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::workflow_spec {

// model.WORKFLOW_SCHEMA_VERSION
inline constexpr std::string_view kWorkflowSchemaVersion = "1.0";

// model.NodeState — unknown strings throw (Python ValueError parity).
enum class NodeState {
    pending,
    running,
    succeeded,
    failed,
    cancelled,
    skipped,
    unavailable,
};

[[nodiscard]] std::string to_string(NodeState state);
[[nodiscard]] NodeState node_state_from_string(const std::string& text);

// model.TERMINAL_NODE_STATES — states that do not re-execute on resume.
[[nodiscard]] bool is_terminal_node_state(NodeState state) noexcept;

// model.RunState
enum class RunState {
    running,
    completed,
    failed,
    cancelled,
    interrupted,
};

[[nodiscard]] std::string to_string(RunState state);
[[nodiscard]] RunState run_state_from_string(const std::string& text);

// Thrown where the Python model raises KeyError/ValueError on malformed
// input (missing required key, non-serialisable state string, ...).
struct ModelError : std::invalid_argument {
    using std::invalid_argument::invalid_argument;
};

// model.RetryPolicy — fixed-backoff retry for retryable outcomes only.
struct RetryPolicy {
    int max_attempts = 1;
    double backoff_seconds = 0.0;

    [[nodiscard]] domain::Json to_dict() const;
    [[nodiscard]] static RetryPolicy from_dict(const domain::Json& data);
};

// model.NodeCondition — declarative skip-condition tree (no eval, ever).
// The recursive child uses a 0-or-1 vector (std::optional may not hold an
// incomplete type); `condition.has_value()` from the Python model reads as
// `condition_child(...) != nullptr` / `!condition.empty()`.
struct NodeCondition {
    std::string kind;
    std::optional<std::string> node;
    std::optional<std::string> key;
    domain::Json value = nullptr;    // None is indistinguishable from absent
                                    // on to_dict (Python parity, see D4)
    std::optional<std::string> state;
    std::vector<NodeCondition> conditions;
    std::vector<NodeCondition> condition;  // 0 or 1 child ('not')

    [[nodiscard]] bool has_condition() const noexcept {
        return !condition.empty();
    }
    [[nodiscard]] const NodeCondition& inner_condition() const noexcept {
        return condition.front();
    }

    [[nodiscard]] domain::Json to_dict() const;
    [[nodiscard]] static NodeCondition from_dict(const domain::Json& data);
};

// model.validate_condition_tree — static problems of one condition tree.
[[nodiscard]] std::vector<std::string>
validate_condition_tree(const NodeCondition& condition);

// model.NodeSpec — one node of the static workflow graph.
struct NodeSpec {
    std::string node_id;
    std::string action_id;
    domain::Json parameters = domain::Json::object();
    std::vector<std::string> depends_on;
    std::optional<NodeCondition> condition;
    RetryPolicy retry;
    std::string description;

    [[nodiscard]] domain::Json to_dict() const;
    [[nodiscard]] static NodeSpec from_dict(const domain::Json& data);
};

// model.SlotSpec — a typed workflow input slot.
struct SlotSpec {
    std::string name;
    domain::Json schema = domain::Json::object({{"type", "string"}});
    bool required = true;
    domain::Json default_value = nullptr;
    std::string description;

    [[nodiscard]] domain::Json to_dict() const;
    [[nodiscard]] static SlotSpec from_dict(const domain::Json& data);
};

// model.WorkflowSpec — static DAG of professional actions.
struct WorkflowSpec {
    std::string workflow_id;
    std::string name;
    std::vector<NodeSpec> nodes;
    std::vector<SlotSpec> slots;
    std::string schema_version{std::string(kWorkflowSchemaVersion)};
    int max_concurrency = 1;
    std::string description;

    // model.WorkflowSpec.node — throws ModelError when absent (KeyError
    // message parity).
    [[nodiscard]] const NodeSpec& node(const std::string& node_id) const;
    [[nodiscard]] std::string spec_hash() const;

    [[nodiscard]] domain::Json to_dict() const;
    [[nodiscard]] static WorkflowSpec from_dict(const domain::Json& data);
};

// model.NodeRun — checkpoint of one node execution.
struct NodeRun {
    std::string node_id;
    NodeState state = NodeState::pending;
    int attempt = 0;
    std::optional<std::string> action_status;
    bool from_cache = false;
    domain::Json parameters = domain::Json::object();
    std::vector<std::string> input_version_ids;
    std::optional<std::string> cache_identity;
    std::vector<std::string> output_version_ids;
    domain::Json outputs = domain::Json::object();
    std::optional<domain::Json> receipt;
    std::optional<std::string> skip_reason;
    std::optional<std::string> error;
    domain::Json started_at = nullptr;  // raw JSON number: int stays int
    domain::Json finished_at = nullptr;

    [[nodiscard]] domain::Json to_dict() const;
    [[nodiscard]] static NodeRun from_dict(const domain::Json& data);
};

// model.WorkflowRun — one persisted execution of a WorkflowSpec.
struct WorkflowRun {
    std::string run_id;
    WorkflowSpec workflow;
    RunState state = RunState::running;
    domain::Json slot_values = domain::Json::object();
    // Insertion-ordered: keys follow spec node order (dict semantics).
    std::vector<std::pair<std::string, NodeRun>> node_runs;
    std::optional<std::string> project_name;
    std::optional<std::string> project_path;
    std::optional<std::string> spec_hash;
    std::optional<std::string> parent_run_id;
    domain::Json created_at = nullptr;  // raw JSON number: int stays int
    domain::Json updated_at = nullptr;

    [[nodiscard]] NodeRun* find_node_run(const std::string& node_id);
    [[nodiscard]] const NodeRun* find_node_run(const std::string& node_id) const;

    [[nodiscard]] domain::Json to_dict() const;
    [[nodiscard]] static WorkflowRun from_dict(const domain::Json& data);
};

// model.WorkflowRun.create — run_id = 16 hex chars, timestamps = now
// (explicit values injectable for tests; D8).
[[nodiscard]] WorkflowRun create_run(const WorkflowSpec& workflow,
                                     domain::Json slot_values);
[[nodiscard]] WorkflowRun create_run(const WorkflowSpec& workflow,
                                     domain::Json slot_values,
                                     std::string run_id, double now_seconds);

// model.canonical_hash — sha256 of the sorted-key compact JSON dump
// (json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)).
[[nodiscard]] std::string canonical_hash(const domain::Json& value);

}  // namespace pwb::workflow_spec
