#pragma once

// Agent session — the C++ product's conversational agent state machine,
// consolidating what the Python product splits across
// paleo_workbench/agent/harness.py (query -> intent -> plan -> execution
// loop -> deliverable) and ui/workstation/agent_panel.py (session write
// grants, cancel-at-safe-point, history).
//
// Every plan step executes through the guarded HarnessExecutor (tool
// calling), every terminal step is audited with a receipt, every terminal
// step lands a checkpoint, and a restarted host rebuilds the session from
// the checkpoint and resumes the pending steps. Cooperative cancellation is
// a first-class outcome: a result that arrives after cancellation is
// recorded as late and never resurrects the turn.

#include <pwb/closure_agent/checkpoint.hpp>
#include <pwb/closure_agent/context.hpp>
#include <pwb/closure_agent/events.hpp>
#include <pwb/closure_agent/executor.hpp>
#include <pwb/closure_agent/intent.hpp>
#include <pwb/closure_agent/planner.hpp>

#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;

enum class SessionState {
    Idle,                 // no active turn
    Planning,             // intent parse + DAG construction
    AwaitingConfirmation, // WRITE actions present, grant pending
    Running,              // executing the plan
    Cancelling,           // cancel() armed, draining to a safe point
    Cancelled,            // terminal: the user cancelled
    Failed,               // terminal: plan finished with failures
    Completed,            // terminal: plan finished clean
};

std::string to_string(SessionState state);

// Receipt for one audited step execution (audit trail / recovery dedup).
struct StepReceipt {
    std::string receipt_id;   // "rcpt-" + sha256(canonical)[0:16]
    std::string turn_id;
    std::string node_id;
    std::string action_id;
    std::string action_version;
    std::string status;       // ActionResult status (positive steps only)
    Json parameters = Json::object();
    Json result_summary = Json::object();
    double elapsed_ms = 0.0;
    double finished_at_sec = 0.0;

    Json to_json() const;
    static StepReceipt from_json(const Json& json);
};

// Thrown by apply_receipt when a receipt id is replayed (duplicate
// acknowledgement); recovery relies on this failing closed.
class DuplicateReceiptError : public std::runtime_error {
public:
    explicit DuplicateReceiptError(std::string receipt_id);
    const std::string& receipt_id() const noexcept { return receipt_id_; }

private:
    std::string receipt_id_;
};

struct SessionTurn {
    std::string turn_id;
    std::string query;
    ParsedIntent intent;
    TaskGraph plan;
    std::string status = "running";  // running|awaiting_confirmation|completed|failed|cancelled|rejected
    std::optional<std::string> error;
    Json deliverable = Json(nullptr);
};

// Host binding: which harness action executes a plan node. Resolution order:
// 1. node_actions (node id -> action id), 2. agent_actions (agent name ->
// action id). Unresolved -> the node fails "Agent '<name>' not found."
// (Python harness parity), keeping the skeleton honest about missing
// capabilities.
struct NodeBindings {
    std::map<std::string, std::string> node_actions;
    std::map<std::string, std::string> agent_actions;

    std::optional<std::string> resolve(const TaskNode& node) const;
};

struct SessionConfig {
    const ActionRegistry* registry = nullptr;
    const HarnessExecutor* executor = nullptr;
    SessionCheckpointStore* checkpoints = nullptr;  // optional
    AgentEventBus* events = nullptr;                // optional
    NodeBindings bindings;
    // Host service-injection seam: mutates the per-turn ActionContext before
    // execution (catalog port, provider registry handle, workspace root...).
    std::function<void(ActionContext&)> context_initializer;
    std::function<double()> clock;                  // monotonic seconds
    std::function<std::string()> turn_id_generator; // deterministic in tests
    int max_iterations = 20;                        // agent/harness.py parity
};

class AgentSession {
public:
    explicit AgentSession(SessionConfig config);

    // query -> intent -> plan -> (WRITE? confirmation) -> guarded execution.
    // Returns the terminal turn. Events carry the detail; the state machine
    // guarantees one terminal state per turn.
    SessionTurn submit(const std::string& query,
                       const Json& context_parameters = Json::object());

    // Confirmation boundary (agent_panel.py session write grants): the whole
    // plan's write set must be covered exactly; extra ids are granted too
    // (Python |= semantics) but a partial grant does not run the plan.
    SessionTurn confirm_write(const std::vector<std::string>& action_ids);
    SessionTurn reject_write();

    // Cooperative cancel: arms the token ONLY (the token is the thread-safe
    // seam — safe to call from any thread, matching the Python panel's
    // scheduler-Event model). The run loop performs the Cancelling state
    // transition itself at the next safe point, so all state writes and
    // event publications stay on the session's run thread. Idempotent.
    void cancel();

    // Audit surface: receipts of the current session (chronological).
    const std::vector<StepReceipt>& receipts() const { return receipts_; }
    // Recovery/audit intake: duplicate ids are rejected explicitly.
    void apply_receipt(StepReceipt receipt);

    // Persistence: checkpoint the current turn state (no-op when no store).
    // Returns the checkpoint id, or "" when checkpointing is disabled.
    std::string checkpoint_now();

    // Rebuild from the newest checkpoint: plan + completed steps + receipts
    // are restored, receipts re-applied (duplicates -> DuplicateReceiptError
    // — a corrupt or replayed history fails closed). Returns the restored
    // turn; pending nodes can be resumed with resume().
    SessionTurn recover(const std::string& session_id);
    // Continue a recovered (or cancelled) turn: re-run the pending plan.
    SessionTurn resume();

    SessionState state() const { return state_; }
    const SessionTurn* current_turn() const { return current_turn_.get(); }
    const std::set<std::string>& write_grants() const { return write_grants_; }
    const CancelToken* cancel_token() const { return cancel_token_.get(); }
    const std::string& session_id() const { return session_id_; }

    // Checkpoint payload projection (tests + hosts verifying the envelope).
    Json checkpoint_payload() const;

private:
    void set_state(SessionState state, const char* event, Json extra = Json::object());
    void publish(const char* type, const std::string& node_id,
                 Json payload = Json::object());
    std::vector<std::string> plan_write_actions() const;
    SessionTurn run_plan();
    void emit_receipt(const TaskNode& node, const ActionResult& result);

    SessionConfig config_;
    std::string session_id_;
    SessionState state_ = SessionState::Idle;
    std::unique_ptr<SessionTurn> current_turn_;
    std::vector<StepReceipt> receipts_;
    std::set<std::string> receipt_ids_;
    std::set<std::string> write_grants_;
    // Shared pointer: providers::CancelToken is non-assignable (atomic
    // member), so a fresh token per turn is a fresh object.
    std::shared_ptr<CancelToken> cancel_token_ = std::make_shared<CancelToken>();
    std::vector<std::string> pending_write_actions_;
    // Set by checkpoint_now() when a checkpoint write fails; the run loop
    // treats it as fatal for the turn (workflow engine __checkpoint__
    // parity) and the terminal mapping routes to failed — never completed.
    bool checkpoint_failure_ = false;
};

}  // namespace pwb::closure_agent
