// session.cpp — the agent session state machine: submit -> plan ->
// confirmation boundary -> guarded execution -> audit -> checkpoint ->
// recovery. Status transitions publish events; every terminal node leaves a
// receipt and a checkpoint entry; a result arriving after cancellation is
// recorded late and never resurrects the turn.
#include <pwb/closure_agent/session.hpp>

#include <pwb/domain/sha256.hpp>
#include <pwb/providers/schema.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <memory>

namespace pwb::closure_agent {

std::string to_string(SessionState state) {
    switch (state) {
        case SessionState::Idle: return "idle";
        case SessionState::Planning: return "planning";
        case SessionState::AwaitingConfirmation: return "awaiting_confirmation";
        case SessionState::Running: return "running";
        case SessionState::Cancelling: return "cancelling";
        case SessionState::Cancelled: return "cancelled";
        case SessionState::Failed: return "failed";
        case SessionState::Completed: return "completed";
    }
    return "idle";
}

DuplicateReceiptError::DuplicateReceiptError(std::string receipt_id)
    : std::runtime_error("duplicate receipt " +
                         pwb::providers::python_repr(receipt_id) +
                         " refused (already applied)"),
      receipt_id_(std::move(receipt_id)) {}

Json StepReceipt::to_json() const {
    Json json = Json::object();
    json["receipt_id"] = receipt_id;
    json["turn_id"] = turn_id;
    json["node_id"] = node_id;
    json["action_id"] = action_id;
    json["action_version"] = action_version;
    json["status"] = status;
    json["parameters"] = parameters;
    json["result_summary"] = result_summary;
    Json elapsed = std::round(elapsed_ms * 1000.0) / 1000.0;
    json["elapsed_ms"] = elapsed;
    json["finished_at"] = finished_at_sec;
    return json;
}

StepReceipt StepReceipt::from_json(const Json& json) {
    StepReceipt receipt;
    receipt.receipt_id = json.value("receipt_id", "");
    receipt.turn_id = json.value("turn_id", "");
    receipt.node_id = json.value("node_id", "");
    receipt.action_id = json.value("action_id", "");
    receipt.action_version = json.value("action_version", "");
    receipt.status = json.value("status", "success");
    const auto parameters = json.find("parameters");
    if (parameters != json.end() && parameters->is_object()) {
        receipt.parameters = *parameters;
    }
    const auto summary = json.find("result_summary");
    if (summary != json.end() && summary->is_object()) {
        receipt.result_summary = *summary;
    }
    receipt.elapsed_ms = json.value("elapsed_ms", 0.0);
    receipt.finished_at_sec = json.value("finished_at", 0.0);
    return receipt;
}

std::optional<std::string> NodeBindings::resolve(const TaskNode& node) const {
    const auto by_node = node_actions.find(node.id);
    if (by_node != node_actions.end()) return by_node->second;
    const auto by_agent = agent_actions.find(node.agent_name);
    if (by_agent != agent_actions.end()) return by_agent->second;
    return std::nullopt;
}

namespace {

double wall_seconds() {
    return std::chrono::duration<double>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

std::string default_turn_id() {
    static std::atomic<long long> counter{0};
    return "turn-" +
           std::to_string(counter.fetch_add(1, std::memory_order_acq_rel) + 1);
}

std::string receipt_id_for(const StepReceipt& receipt) {
    // Content-addressed: the same step outcome always hashes to the same id,
    // which is what makes replay dedup meaningful.
    pwb::domain::Sha256 digest;
    const std::string canonical = receipt.turn_id + "|" + receipt.node_id + "|" +
                                  receipt.action_id + "|" +
                                  receipt.action_version + "|" + receipt.status;
    digest.update(canonical.data(), canonical.size());
    return "rcpt-" + digest.hex_digest().substr(0, 16);
}

// Python _write_granted_for: frozenset(action_ids) <= grants.
bool covers_grants(const std::set<std::string>& grants,
                   const std::vector<std::string>& action_ids) {
    for (const auto& id : action_ids) {
        if (grants.count(id) == 0) return false;
    }
    return true;
}

}  // namespace

AgentSession::AgentSession(SessionConfig config) : config_(std::move(config)) {
    if (config_.registry == nullptr || config_.executor == nullptr) {
        throw std::invalid_argument(
            "AgentSession requires a registry and an executor");
    }
    session_id_ = ActionContext().session_id;
}

void AgentSession::publish(const char* type, const std::string& node_id,
                           Json payload) {
    if (config_.events == nullptr || current_turn_ == nullptr) return;
    AgentEvent event;
    event.type = type;
    event.session_id = session_id_;
    event.turn_id = current_turn_->turn_id;
    event.node_id = node_id;
    event.payload = std::move(payload);
    config_.events->publish(std::move(event));
}

void AgentSession::set_state(SessionState state, const char* event,
                             Json extra) {
    state_ = state;
    Json payload = Json::object();
    payload["state"] = to_string(state);
    if (!extra.is_null()) payload["detail"] = std::move(extra);
    publish(event, "", std::move(payload));
}

std::vector<std::string> AgentSession::plan_write_actions() const {
    std::vector<std::string> writes;
    if (current_turn_ == nullptr) return writes;
    for (const auto& node : current_turn_->plan.nodes) {
        const auto action_id = config_.bindings.resolve(node);
        if (!action_id) continue;
        const ActionSpec* spec = config_.registry->find(*action_id);
        if (spec != nullptr && spec->risk == ActionRisk::Write) {
            if (std::find(writes.begin(), writes.end(), *action_id) ==
                writes.end()) {
                writes.push_back(*action_id);
            }
        }
    }
    return writes;
}

SessionTurn AgentSession::submit(const std::string& query,
                                 const Json& context_parameters) {
    cancel_token_ = std::make_shared<CancelToken>();  // fresh per turn
    checkpoint_failure_ = false;                      // fresh turn, fresh fate
    current_turn_ = std::make_unique<SessionTurn>();
    current_turn_->turn_id =
        config_.turn_id_generator ? config_.turn_id_generator() : default_turn_id();
    current_turn_->query = query;

    set_state(SessionState::Planning, "session.state_changed");

    // 1. Intent parsing (frozen keyword port).
    IntentParser parser;
    current_turn_->intent = parser.parse(query, context_parameters.is_object()
                                                      ? context_parameters
                                                      : Json(nullptr));
    publish("session.intent_parsed", "", current_turn_->intent.to_dict());

    // 2. Task graph planning (fixed skeleton port).
    TaskPlanner planner;
    current_turn_->plan = planner.create_plan(current_turn_->intent);
    Json plan_summary = Json::object();
    Json nodes = Json::array();
    for (const auto& node : current_turn_->plan.nodes) {
        nodes.push_back(node.id);
    }
    plan_summary["nodes"] = nodes;
    publish("session.plan_created", "", plan_summary);

    // 3. Confirmation boundary for WRITE-bearing plans.
    pending_write_actions_ = plan_write_actions();
    if (!pending_write_actions_.empty() &&
        !covers_grants(write_grants_, pending_write_actions_)) {
        current_turn_->status = "awaiting_confirmation";
        set_state(SessionState::AwaitingConfirmation,
                  "session.confirmation_required");
        Json detail = Json::object();
        detail["write_actions"] = pending_write_actions_;
        publish("session.awaiting_confirmation", "", std::move(detail));
        return *current_turn_;
    }

    // 4. Guarded execution.
    return run_plan();
}

SessionTurn AgentSession::confirm_write(const std::vector<std::string>& action_ids) {
    if (state_ != SessionState::AwaitingConfirmation || current_turn_ == nullptr) {
        throw std::runtime_error("no confirmation pending");
    }
    write_grants_.insert(action_ids.begin(), action_ids.end());
    if (!covers_grants(write_grants_, pending_write_actions_)) {
        Json detail = Json::object();
        detail["granted"] = std::vector<std::string>(action_ids.begin(),
                                                     action_ids.end());
        publish("session.confirmation_partial", "", std::move(detail));
        return *current_turn_;
    }
    Json detail = Json::object();
    detail["granted"] = std::vector<std::string>(action_ids.begin(), action_ids.end());
    publish("session.confirmation_granted", "", std::move(detail));
    return run_plan();
}

SessionTurn AgentSession::reject_write() {
    if (state_ != SessionState::AwaitingConfirmation || current_turn_ == nullptr) {
        throw std::runtime_error("no confirmation pending");
    }
    current_turn_->status = "rejected";
    current_turn_->error = "write actions rejected by user";
    set_state(SessionState::Completed, "session.state_changed");
    Json detail = Json::object();
    detail["status"] = "rejected";
    publish("session.rejected", "", std::move(detail));
    return *current_turn_;
}

void AgentSession::cancel() {
    // Arms the token only: the token is the thread-safe seam (atomic flag);
    // every state write / event publication happens on the run thread at
    // the next safe point (see run_plan), so cancel() is callable from any
    // thread without racing the session state machine.
    cancel_token_->cancel();
}

void AgentSession::apply_receipt(StepReceipt receipt) {
    if (receipt.receipt_id.empty()) {
        receipt.receipt_id = receipt_id_for(receipt);
    }
    if (receipt_ids_.count(receipt.receipt_id) > 0) {
        throw DuplicateReceiptError(receipt.receipt_id);
    }
    receipt_ids_.insert(receipt.receipt_id);
    receipts_.push_back(std::move(receipt));
}

void AgentSession::emit_receipt(const TaskNode& node,
                                const ActionResult& result) {
    StepReceipt receipt;
    receipt.turn_id = current_turn_ != nullptr ? current_turn_->turn_id : "";
    receipt.node_id = node.id;
    receipt.action_id = result.action_id;
    const ActionSpec* spec = config_.registry->find(result.action_id);
    receipt.action_version = spec != nullptr ? spec->version : "1.0";
    receipt.status = result.status;
    // Result summary: statuses + compact outputs projection (no raw bulk).
    Json summary = Json::object();
    summary["ok"] = result.ok();
    if (result.outputs.is_object()) {
        for (auto it = result.outputs.begin();
             it != result.outputs.end() && summary.size() < 8; ++it) {
            summary[it.key()] = it.value();
        }
    }
    receipt.result_summary = std::move(summary);
    receipt.elapsed_ms = result.elapsed_ms;
    receipt.finished_at_sec =
        config_.clock ? config_.clock() : wall_seconds();
    receipt.receipt_id = receipt_id_for(receipt);
    apply_receipt(std::move(receipt));
    Json payload = Json::object();
    payload["receipt"] = receipts_.back().to_json();
    publish("session.receipt_issued", node.id, std::move(payload));
}

SessionTurn AgentSession::run_plan() {
    SessionTurn& turn = *current_turn_;
    turn.status = "running";
    set_state(SessionState::Running, "session.state_changed");

    ActionContext context;  // session-scoped context (READ+COMPUTE default)
    context.session_id = session_id_;
    context.cancel = cancel_token_.get();
    if (config_.context_initializer) config_.context_initializer(context);
    // The confirmation boundary elevates exactly the granted plan's WRITE
    // risk (agent_panel.py: permissions = DEFAULT | {WRITE} after the grant
    // dialog); an ungranted WRITE plan never reaches run_plan. The plan's
    // write set is re-derived (not the submit-time cache) so a recovered
    // session resumes with its restored grants intact.
    const std::vector<std::string> plan_writes = plan_write_actions();
    if (!plan_writes.empty() && covers_grants(write_grants_, plan_writes)) {
        context.permissions.insert(ActionRisk::Write);
    }

    int iteration = 0;
    while (!turn.plan.is_finished() && iteration < config_.max_iterations) {
        if (cancel_token_->is_cancelled()) {
            // Safe-point transition: the state write stays on the run
            // thread even though cancel() was called from elsewhere.
            if (state_ == SessionState::Running) {
                set_state(SessionState::Cancelling, "session.cancelling");
            }
            break;
        }
        ++iteration;
        auto ready = turn.plan.executable_nodes();
        if (ready.empty()) break;
        for (TaskNode* node : ready) {
            if (cancel_token_->is_cancelled()) {
                if (state_ == SessionState::Running) {
                    set_state(SessionState::Cancelling, "session.cancelling");
                }
                break;
            }
            node->status = TaskStatus::Running;
            publish("session.node_started", node->id);

            const auto action_id = config_.bindings.resolve(*node);
            if (!action_id) {
                // Python harness parity: missing agent is an explicit,
                // honest failure of that node.
                node->status = TaskStatus::Failed;
                node->error = "Agent '" + node->agent_name + "' not found.";
                publish("session.node_finished", node->id,
                        Json{{"status", "failed"},
                             {"error", *node->error}});
                continue;
            }

            const ActionResult result =
                config_.executor->execute(*action_id, node->parameters, &context);
            if (cancel_token_->is_cancelled() && result.ok()) {
                // Late result after cancellation: recorded, audited as
                // late, and never counted as work done.
                node->status = TaskStatus::Skipped;
                node->error = "late result after cancellation";
                node->result = result.to_dict();
                Json detail = Json::object();
                detail["late"] = true;
                detail["action"] = *action_id;
                publish("session.node_late_result", node->id, std::move(detail));
                continue;
            }
            node->result = result.to_dict();
            if (result.ok()) {
                node->status = TaskStatus::Completed;
                emit_receipt(*node, result);
                publish("session.node_finished", node->id,
                        Json{{"status", result.status}});
            } else if (result.status == to_string(ActionStatus::Cancelled)) {
                node->status = TaskStatus::Skipped;
                node->error = result.error.value_or("cancelled");
                publish("session.node_finished", node->id,
                        Json{{"status", "cancelled"}});
                cancel_token_->cancel();  // propagate to the rest of the plan
            } else {
                node->status = TaskStatus::Failed;
                node->error = result.error.value_or("failed");
                publish("session.node_finished", node->id,
                        Json{{"status", result.status},
                             {"error", node->error.value_or("")}});
                // Dependents of a failed node never become ready; the
                // terminal mapping below marks them skipped.
            }
            checkpoint_now();
            if (checkpoint_failure_) break;  // fatal: route to failed below
        }
        if (checkpoint_failure_) break;
    }

    // Terminal mapping. Checkpoint persistence failure is fatal for the
    // turn (workflow engine __checkpoint__ parity): it wins over the other
    // terminal branches so the turn can never end `completed` without its
    // terminal checkpoint on disk.
    if (checkpoint_failure_) {
        for (auto& node : turn.plan.nodes) {
            if (node.status == TaskStatus::Pending ||
                node.status == TaskStatus::Running) {
                node.status = TaskStatus::Skipped;
                node.error = "checkpoint persistence failed";
            }
        }
        turn.status = "failed";
        if (!turn.error.has_value() || turn.error->find("checkpoint") ==
                                           std::string::npos) {
            turn.error = "checkpoint persistence failed";
        }
        set_state(SessionState::Failed, "session.failed");
    } else if (cancel_token_->is_cancelled()) {
        for (auto& node : turn.plan.nodes) {
            if (node.status == TaskStatus::Pending) {
                node.status = TaskStatus::Skipped;
                node.error = "cancelled";
            }
        }
        turn.status = "cancelled";
        turn.error = "cancelled by user";
        set_state(SessionState::Cancelled, "session.cancelled");
    } else if (turn.plan.has_failures()) {
        for (auto& node : turn.plan.nodes) {
            if (node.status == TaskStatus::Pending) {
                node.status = TaskStatus::Skipped;
                node.error = "upstream failure";
            }
        }
        turn.status = "failed";
        turn.error = "plan finished with failures";
        set_state(SessionState::Failed, "session.failed");
    } else if (!turn.plan.is_finished()) {
        // Interrupted (crash / iteration budget exhausted): unfinished work
        // stays PENDING so recovery+resume can continue it — Python harness
        // parity (success = not failures AND finished).
        turn.status = "failed";
        turn.error = "plan did not finish (interrupted)";
        set_state(SessionState::Failed, "session.failed");
    } else {
        const TaskNode* delivery = turn.plan.find("task_result_delivery");
        if (delivery != nullptr && delivery->result.is_object()) {
            const auto outputs = delivery->result.find("outputs");
            if (outputs != delivery->result.end()) {
                turn.deliverable = *outputs;
            }
        }
        turn.status = "completed";
        set_state(SessionState::Completed, "session.completed");
        Json detail = Json::object();
        detail["deliverable"] = turn.deliverable;
        publish("session.deliverable", "", std::move(detail));
    }
    if (!checkpoint_failure_) {
        checkpoint_now();
    }
    return turn;
}

std::string AgentSession::checkpoint_now() {
    if (config_.checkpoints == nullptr || current_turn_ == nullptr) return "";
    try {
        const CheckpointRecord record =
            config_.checkpoints->save(session_id_, checkpoint_payload());
        Json detail = Json::object();
        detail["checkpoint_id"] = record.checkpoint_id;
        publish("session.checkpoint_written", "", std::move(detail));
        return record.checkpoint_id;
    } catch (const std::exception& exc) {
        // A failed checkpoint write is fatal for the turn (workflow engine
        // __checkpoint__ parity) — never an unguarded pass. The flag stops
        // the run loop; the terminal mapping routes to failed so the turn
        // can never end `completed` without its checkpoint on disk.
        checkpoint_failure_ = true;
        current_turn_->status = "failed";
        current_turn_->error =
            std::string("checkpoint persistence failed: ") + exc.what();
        set_state(SessionState::Failed, "session.failed");
        return "";
    }
}

Json AgentSession::checkpoint_payload() const {
    Json payload = Json::object();
    payload["schema_version"] = "1.0";
    payload["session_id"] = session_id_;
    payload["state"] = to_string(state_);
    if (current_turn_ != nullptr) {
        Json turn = Json::object();
        turn["turn_id"] = current_turn_->turn_id;
        turn["query"] = current_turn_->query;
        turn["status"] = current_turn_->status;
        turn["intent"] = current_turn_->intent.to_dict();
        Json nodes = Json::array();
        for (const auto& node : current_turn_->plan.nodes) {
            Json entry = Json::object();
            entry["id"] = node.id;
            entry["agent_name"] = node.agent_name;
            entry["action"] = node.action;
            entry["description"] = node.description;
            entry["dependencies"] = node.dependencies;
            entry["parameters"] = node.parameters;
            entry["status"] = to_string(node.status);
            entry["result"] = node.result;
            entry["error"] = node.error ? Json(*node.error) : Json(nullptr);
            nodes.push_back(std::move(entry));
        }
        turn["plan_nodes"] = nodes;
        turn["deliverable"] = current_turn_->deliverable;
        payload["turn"] = turn;
    }
    Json receipt_list = Json::array();
    for (const auto& receipt : receipts_) receipt_list.push_back(receipt.to_json());
    payload["receipts"] = receipt_list;
    Json grants = Json::array();
    for (const auto& grant : write_grants_) grants.push_back(grant);
    payload["write_grants"] = grants;
    return payload;
}

SessionTurn AgentSession::recover(const std::string& session_id) {
    if (config_.checkpoints == nullptr) {
        throw std::runtime_error("no checkpoint store configured");
    }
    const CheckpointRecord record = config_.checkpoints->load(session_id);
    const Json& payload = record.payload;
    // Checksum only proves the bytes are intact, not that the schema is
    // understood (sha256 is not a MAC): a payload without a turn object is
    // a corrupt checkpoint, not a crash.
    const auto turn_entry = payload.find("turn");
    if (turn_entry == payload.end() || !turn_entry->is_object()) {
        throw CheckpointCorruptError(
            "checkpoint is corrupted: payload has no turn object");
    }
    current_turn_ = std::make_unique<SessionTurn>();
    current_turn_->turn_id = turn_entry->value("turn_id", "");
    current_turn_->query = turn_entry->value("query", "");
    current_turn_->status = turn_entry->value("status", "running");
    current_turn_->deliverable = turn_entry->value("deliverable", Json(nullptr));

    // Intent restore.
    const Json intent_json = turn_entry->value("intent", Json::object());
    const auto domain = task_domain_from_string(intent_json.value("primary_domain", "general"));
    ParsedIntent intent;
    intent.raw_query = intent_json.value("raw_query", "");
    intent.primary_domain = domain.value_or(TaskDomain::General);
    intent.target_horizon = intent_json.value("target_horizon", "");
    intent.factor_type = intent_json.value("factor_type", "");
    intent.confidence = intent_json.value("confidence", 1.0);
    const auto params = intent_json.find("parameters");
    if (params != intent_json.end() && params->is_object()) {
        intent.parameters = *params;
    }
    current_turn_->intent = intent;

    // Plan restore (statuses preserved; RUNNING nodes restart as PENDING —
    // the crash-mapping contract of the workflow engine, session scope).
    TaskGraph graph;
    for (const auto& entry : turn_entry->value("plan_nodes", Json::array())) {
        TaskNode node;
        node.id = entry.value("id", "");
        node.agent_name = entry.value("agent_name", "");
        node.action = entry.value("action", "");
        node.description = entry.value("description", "");
        node.dependencies = entry.value("dependencies", std::vector<std::string>{});
        node.parameters = entry.value("parameters", Json::object());
        node.status = task_status_from_string(entry.value("status", "pending"))
                          .value_or(TaskStatus::Pending);
        const auto result = entry.find("result");
        if (result != entry.end()) node.result = *result;
        const auto error = entry.find("error");
        if (error != entry.end() && error->is_string()) node.error = error->get<std::string>();
        if (node.status == TaskStatus::Running) node.status = TaskStatus::Pending;
        graph.add_node(std::move(node));
    }
    current_turn_->plan = std::move(graph);

    // Receipt restore — replay-dedup guards against a corrupt history.
    for (const auto& entry : payload.value("receipts", Json::array())) {
        apply_receipt(StepReceipt::from_json(entry));
    }
    for (const auto& grant : payload.value("write_grants", Json::array())) {
        if (grant.is_string()) write_grants_.insert(grant.get<std::string>());
    }

    session_id_ = session_id;
    set_state(SessionState::Idle, "session.recovered");
    Json detail = Json::object();
    detail["checkpoint_id"] = record.checkpoint_id;
    publish("session.recovered", "", std::move(detail));
    return *current_turn_;
}

SessionTurn AgentSession::resume() {
    if (current_turn_ == nullptr) {
        throw std::runtime_error("no turn to resume");
    }
    // Terminal-by-decision turns are not resurrected: a completed plan (or
    // a turn the user rejected at the confirmation boundary) stays as it
    // is. Resume continues interrupted/failed execution only.
    if (current_turn_->status == "completed" ||
        current_turn_->status == "rejected") {
        return *current_turn_;
    }
    cancel_token_ = std::make_shared<CancelToken>();
    checkpoint_failure_ = false;  // a resumed run retries persistence
    if (current_turn_->plan.is_finished()) {
        return *current_turn_;  // nothing pending; terminal state stands
    }
    current_turn_->status = "running";
    return run_plan();
}

}  // namespace pwb::closure_agent
