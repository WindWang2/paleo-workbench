#include "pwb/ui_shell/operation_registry.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace pwb::ui_shell {

bool operation_state_terminal(OperationState state) {
    return state == OperationState::Completed ||
           state == OperationState::Warning || state == OperationState::Failed ||
           state == OperationState::Cancelled;
}

const char* operation_state_value(OperationState state) {
    switch (state) {
        case OperationState::Queued:
            return "queued";
        case OperationState::Running:
            return "running";
        case OperationState::Cancelling:
            return "cancelling";
        case OperationState::Completed:
            return "completed";
        case OperationState::Warning:
            return "warning";
        case OperationState::Failed:
            return "failed";
        case OperationState::Cancelled:
            return "cancelled";
    }
    return "queued";
}

double OperationRecord::elapsed_s() const {
    const auto end = finished_at.value_or(std::chrono::steady_clock::now());
    const auto delta =
        std::chrono::duration<double>(end - started_at).count();
    return std::max(0.0, delta);
}

std::optional<double> OperationRecord::progress_fraction() const {
    if (!done.has_value() || !total.has_value() || *total == 0) {
        return std::nullopt;
    }
    const double fraction = static_cast<double>(*done) / *total;
    return std::clamp(fraction, 0.0, 1.0);
}

void OperationRegistry::emit_changed(const std::string& op_id) {
    if (on_changed) {
        on_changed(op_id);
    }
}

void OperationRegistry::emit_removed(const std::string& op_id) {
    if (on_removed) {
        on_removed(op_id);
    }
}

const OperationRecord& OperationRegistry::begin(
    const std::string& op_id, const std::string& title,
    std::optional<std::string> object_label, bool cancellable,
    std::optional<int> total, bool queued) {
    if (op_id.empty()) {
        throw std::invalid_argument("op_id 不能为空");
    }
    OperationRecord record;
    record.op_id = op_id;
    record.title = title;
    record.object_label = std::move(object_label);
    record.cancellable = cancellable;
    record.total = total;
    record.state = queued ? OperationState::Queued : OperationState::Running;
    const auto [it, inserted] = ops_.emplace(op_id, std::move(record));
    if (inserted) {
        insertion_order_.push_back(op_id);
    }
    emit_changed(op_id);
    return it->second;
}

void OperationRegistry::update(const std::string& op_id,
                               std::optional<int> done,
                               std::optional<int> total,
                               std::optional<std::string> stage,
                               std::optional<std::string> object_label) {
    auto it = ops_.find(op_id);
    if (it == ops_.end() || operation_state_terminal(it->second.state)) {
        return;
    }
    OperationRecord& record = it->second;
    if (done.has_value()) {
        record.done = std::max(0, *done);
    }
    if (total.has_value()) {
        record.total = std::max(0, *total);
    }
    if (stage.has_value()) {
        record.stage = std::move(*stage);
    }
    if (object_label.has_value()) {
        record.object_label = std::move(*object_label);
    }
    if (record.state == OperationState::Queued) {
        record.state = OperationState::Running;
    }
    emit_changed(op_id);
}

void OperationRegistry::set_cancel(const std::string& op_id,
                                   std::function<void()> cancel) {
    auto it = ops_.find(op_id);
    if (it == ops_.end()) {
        return;
    }
    it->second.cancel = std::move(cancel);
    it->second.cancellable = true;
}

bool OperationRegistry::request_cancel(const std::string& op_id) {
    auto it = ops_.find(op_id);
    if (it == ops_.end() || operation_state_terminal(it->second.state) ||
        it->second.state == OperationState::Cancelling || !it->second.cancel) {
        return false;
    }
    // R2-25: the hook is arbitrary user code — it may reenter the registry
    // (cancel → project close → clear()) and free this node while we still
    // hold the reference. Snapshot the hook, drop the reference across the
    // call, and re-lookup afterwards.
    auto cancel_hook = it->second.cancel;
    try {
        cancel_hook();
    } catch (...) {
        // Cancel hook failure does not hide the original state.
        return false;
    }
    it = ops_.find(op_id);
    if (it == ops_.end()) {
        return true;  // the hook cleared the registry — nothing to mark
    }
    OperationRecord& record = it->second;
    // The hook may synchronously finish the task — terminal state does not
    // regress (review P2-4 parity).
    if (operation_state_terminal(record.state)) {
        return true;
    }
    record.state = OperationState::Cancelling;
    emit_changed(op_id);
    return true;
}

void OperationRegistry::finish(const std::string& op_id, OperationState state,
                               std::optional<std::string> error,
                               std::optional<std::string> result_label,
                               std::function<void()> jump) {
    auto it = ops_.find(op_id);
    if (it == ops_.end()) {
        return;
    }
    OperationRecord& record = it->second;
    // A late finish never regresses a terminal record.
    if (operation_state_terminal(record.state)) {
        return;
    }
    if (!operation_state_terminal(state)) {
        // finish only accepts terminal states — honest degradation.
        state = OperationState::Failed;
    }
    record.state = state;
    record.finished_at = std::chrono::steady_clock::now();
    record.error = std::move(error);
    record.result_label = std::move(result_label);
    record.jump = std::move(jump);
    terminal_order_.push_back(op_id);
    evict_terminals();
    emit_changed(op_id);
}

const OperationRecord* OperationRegistry::record(
    const std::string& op_id) const {
    const auto it = ops_.find(op_id);
    return it == ops_.end() ? nullptr : &it->second;
}

std::vector<const OperationRecord*> OperationRegistry::records() const {
    std::vector<const OperationRecord*> out;
    out.reserve(ops_.size());
    for (auto it = insertion_order_.rbegin(); it != insertion_order_.rend();
         ++it) {
        const auto found = ops_.find(*it);
        if (found != ops_.end()) {
            out.push_back(&found->second);
        }
    }
    return out;
}

std::vector<const OperationRecord*> OperationRegistry::active_records() const {
    std::vector<const OperationRecord*> out;
    for (const OperationRecord* r : records()) {
        if (!operation_state_terminal(r->state)) {
            out.push_back(r);
        }
    }
    return out;
}

std::string OperationRegistry::active_label() const {
    const auto active = active_records();
    if (active.empty()) {
        return {};
    }
    const OperationRecord* first = active.front();
    if (first->object_label.has_value() && !first->object_label->empty()) {
        return first->title + " · " + *first->object_label;
    }
    return first->title;
}

void OperationRegistry::clear() {
    ops_.clear();
    insertion_order_.clear();
    terminal_order_.clear();
}

void OperationRegistry::evict_terminals() {
    while (terminal_order_.size() > kMaxTerminal) {
        const std::string victim = terminal_order_.front();
        terminal_order_.pop_front();
        const auto it = ops_.find(victim);
        // Reused op_id (begin again) may leave a stale queue key pointing at
        // a live record — only evict genuinely terminal records.
        if (it == ops_.end() || !operation_state_terminal(it->second.state)) {
            continue;
        }
        ops_.erase(it);
        emit_removed(victim);
    }
}

namespace {

OperationRegistry& fallback_registry() {
    static OperationRegistry fallback;
    return fallback;
}

OperationRegistry*& current_registry() {
    static OperationRegistry* current = &fallback_registry();
    return current;
}

}  // namespace

OperationRegistry& operation_registry() {
    return *current_registry();
}

void bind_registry_to_shell(OperationRegistry* shell_registry) {
    // The global slot forwards to whatever registry the current shell
    // bound; nullptr rebinds the lazy fallback (shell teardown path).
    current_registry() = shell_registry != nullptr
                             ? shell_registry
                             : &fallback_registry();
}

}  // namespace pwb::ui_shell
