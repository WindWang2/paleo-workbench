#pragma once

// pwb::workflow_engine — in-memory DAG workflow executor (full-conversion
// plan M7 executor slice). A faithful C++ subset of
// paleo_workbench/workflow/dag/engine.py `_drive_sequential` +
// `_ready_batch` + `_skip_dependents` + `_cancel_pending` + `_finalize`:
//   * topological execution order (Kahn, spec-order tie-break; cycles are a
//     validation error with the Python message "dependency cycle among
//     nodes [...]");
//   * failure short-circuit: a failed node marks every pending dependent
//     SKIPPED ("upstream <id> failed") — a failed node never lets a
//     dependent pretend to succeed;
//   * cooperative cancellation at node boundaries (pending → CANCELLED,
//     run → CANCELLED, succeeded nodes stay SUCCEEDED) and inside node
//     functions through the token;
//   * one stdout-level log line per node transition and per run outcome.
// Node bodies come from a function registry (explicit registration, no
// static self-registration); built-ins are "noop" plus the mapping_kernel
// wrappers (see ops.hpp).
//
// Deliberately NOT this slice (see ledgers/07-decisions.md): run store /
// checkpoints, resume/rerun, cache identity, retry, conditions, slots,
// parallel drive, TaskScheduler bridge, INTERRUPTED/UNAVAILABLE states.
// The spec is the minimal {node_id, op, params, depends_on} subset; the
// full model+validation is libs/workflow_spec (conversion slice 06) — the
// frozen validation messages here match Python verbatim to keep that merge
// delta small. Qt-free, Python-free.

#include <pwb/domain/json.hpp>

#include <any>
#include <atomic>
#include <functional>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_engine {

using pwb::domain::Json;

enum class NodeState : std::uint8_t {
    pending,
    running,
    succeeded,
    failed,
    cancelled,
    skipped
};

enum class RunState : std::uint8_t { running, completed, failed, cancelled };

[[nodiscard]] inline const char* to_string(NodeState state) noexcept {
    switch (state) {
    case NodeState::pending: return "pending";
    case NodeState::running: return "running";
    case NodeState::succeeded: return "succeeded";
    case NodeState::failed: return "failed";
    case NodeState::cancelled: return "cancelled";
    case NodeState::skipped: return "skipped";
    }
    return "?";
}

[[nodiscard]] inline const char* to_string(RunState state) noexcept {
    switch (state) {
    case RunState::running: return "running";
    case RunState::completed: return "completed";
    case RunState::failed: return "failed";
    case RunState::cancelled: return "cancelled";
    }
    return "?";
}

// Cooperative cancellation (geoviz token shape: cancel / is_cancelled /
// raise_if_cancelled). Thread-safe: cancel() may be called from any thread
// while the engine drives the run on its caller's thread.
struct Cancelled : std::runtime_error {
    explicit Cancelled(const std::string& message = "workflow run cancelled")
        : std::runtime_error(message) {}
};

class CancelToken {
public:
    [[nodiscard]] bool is_cancelled() const noexcept {
        return flag_.load(std::memory_order_acquire);
    }
    void cancel() noexcept { flag_.store(true, std::memory_order_release); }
    void throw_if_cancelled() const {
        if (is_cancelled()) throw Cancelled{};
    }

private:
    std::atomic<bool> flag_{false};
};

// One node of the static graph (minimal spec subset; 06's workflow_spec
// owns the full model). `op` is the registry key (Python action_id).
struct NodeSpec {
    std::string node_id;
    std::string op;
    Json params = Json::object();  // JSON literals + {"$ref": node[, "key"]}
    std::vector<std::string> depends_on;
};

struct WorkflowSpec {
    std::string workflow_id;
    std::vector<NodeSpec> nodes;

    // {"workflow_id", "nodes": [{"node_id","op","params","depends_on"}]};
    // missing workflow_id/nodes (or a node without node_id/op) is invalid.
    static WorkflowSpec from_json(const Json& data);
};

// Fail-closed static gate (validate_workflow_spec subset). Message strings
// are the Python engine's, frozen in the oracle fixture.
struct ValidationError : std::runtime_error {
    std::vector<std::string> problems;
    ValidationError(std::string workflow_id, std::vector<std::string> problems);
};

class NodeRegistry;

std::vector<std::string> validate_spec(const WorkflowSpec& spec,
                                       const NodeRegistry& registry);
// Kahn order, spec-order tie-break. Precondition: validate_spec found no
// cycle (throws std::logic_error otherwise).
std::vector<std::string> topological_order(const WorkflowSpec& spec);

struct NodeRun {
    std::string node_id;
    NodeState state = NodeState::pending;
    int attempt = 0;
    Json outputs = Json::object();  // JSON-able projection (bind/$ref surface)
    std::any payload;               // typed artifact when the op produces one
    std::string error;
    std::string skip_reason;
    double started_at = 0.0;  // epoch seconds (Python time.time() parity)
    double finished_at = 0.0;
};

struct WorkflowRun {
    WorkflowSpec spec;
    RunState state = RunState::running;
    std::vector<NodeRun> node_runs;  // spec order

    [[nodiscard]] const NodeRun* find(const std::string& node_id) const;
    NodeRun* find(const std::string& node_id);
};

struct NodeResult {
    Json outputs = Json::object();
    std::any payload;
};

// Node body: bound params in, result (or exception / Cancelled) out.
using NodeFunction =
    std::function<NodeResult(const Json& bound_params, const CancelToken& token)>;

// Explicit registration (M1 precedent: no static self-registration).
class NodeRegistry {
public:
    void register_op(std::string name, NodeFunction fn) {
        ops_[std::move(name)] = std::move(fn);
    }
    [[nodiscard]] bool has(const std::string& name) const {
        return ops_.find(name) != ops_.end();
    }
    [[nodiscard]] const NodeFunction* find(const std::string& name) const {
        const auto it = ops_.find(name);
        return it == ops_.end() ? nullptr : &it->second;
    }

private:
    std::map<std::string, NodeFunction> ops_;
};

using LogSink = std::function<void(const std::string&)>;

class Engine {
public:
    explicit Engine(const NodeRegistry& registry, LogSink sink = nullptr);

    // Validates first (ValidationError on any problem — nothing executes),
    // then drives the nodes in topological order on the calling thread.
    WorkflowRun run(const WorkflowSpec& spec, const CancelToken& token) const;
    WorkflowRun run(const WorkflowSpec& spec) const;

private:
    const NodeRegistry& registry_;
    LogSink sink_;

    void log(const std::string& line) const;
};

}  // namespace pwb::workflow_engine
