#pragma once

// Port of paleo_workbench/ui/operations.py (UI-01).
// V11 统一操作注册表：前台长操作的登记处（TaskCenter/状态条统一视图）。
// 不是调度器 —— 计算调度仍归 job_runtime；本类只管表现层记录。
//
// Qt-free core: the QObject signal pair (operation_changed/removed) is
// replaced by injected callbacks so the state machine is testable headless;
// the qt target wraps it with a QObject that emits real signals.

#include <chrono>
#include <deque>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_shell {

enum class OperationState {
    Queued,
    Running,
    Cancelling,
    Completed,
    Warning,
    Failed,
    Cancelled,
};

// Python OperationState.terminal parity.
bool operation_state_terminal(OperationState state);
const char* operation_state_value(OperationState state);

struct OperationRecord {
    std::string op_id;
    std::string title;
    OperationState state = OperationState::Queued;
    std::optional<std::string> object_label;
    std::optional<int> done;
    std::optional<int> total;
    std::optional<std::string> stage;
    std::chrono::steady_clock::time_point started_at =
        std::chrono::steady_clock::now();
    std::optional<std::chrono::steady_clock::time_point> finished_at;
    std::optional<std::string> error;
    bool cancellable = false;
    std::optional<std::string> result_label;
    // 跳转回调由登记方持有页面引用（随页面销毁失效时调用方须容忍失效）。
    std::function<void()> jump;
    std::function<void()> cancel;

    // max(0, end - started_at); end = finished_at or now.
    double elapsed_s() const;
    // done/total clamped [0,1]; nullopt without both or total == 0.
    std::optional<double> progress_fraction() const;
};

class OperationRegistry {
public:
    // Change notifications (Python Signal(str) parity). Bound by the qt
    // wrapper; may be left empty in headless use.
    std::function<void(const std::string& op_id)> on_changed;
    std::function<void(const std::string& op_id)> on_removed;

    static constexpr int kMaxTerminal = 40;  // terminal FIFO cap

    // Registers a record. queued=true starts in Queued else Running.
    // Throws std::invalid_argument on empty op_id (Python ValueError parity).
    const OperationRecord& begin(const std::string& op_id,
                                 const std::string& title,
                                 std::optional<std::string> object_label =
                                     std::nullopt,
                                 bool cancellable = false,
                                 std::optional<int> total = std::nullopt,
                                 bool queued = false);

    // Progress update: clamps done/total >= 0; Queued promotes to Running;
    // terminal records are inert.
    void update(const std::string& op_id,
                std::optional<int> done = std::nullopt,
                std::optional<int> total = std::nullopt,
                std::optional<std::string> stage = std::nullopt,
                std::optional<std::string> object_label = std::nullopt);

    void set_cancel(const std::string& op_id, std::function<void()> cancel);

    // Runs the cancel hook: failure -> false (original state preserved);
    // hook may synchronously finish the task (terminal state not regressed);
    // otherwise the record goes Cancelling. False when nothing to cancel.
    bool request_cancel(const std::string& op_id);

    // finish only accepts terminal states — a live-state argument degrades
    // honestly to Failed. A late finish never regresses a terminal record.
    void finish(const std::string& op_id,
                OperationState state = OperationState::Completed,
                std::optional<std::string> error = std::nullopt,
                std::optional<std::string> result_label = std::nullopt,
                std::function<void()> jump = nullptr);

    const OperationRecord* record(const std::string& op_id) const;

    // All records, newest first (Python reversed dict-values parity).
    std::vector<const OperationRecord*> records() const;
    std::vector<const OperationRecord*> active_records() const;
    // "title · object_label" of the newest active record; empty when none.
    std::string active_label() const;

    // 工程关闭: drop all records AND their dangling callbacks (no held
    // page references survive a project close).
    void clear();

private:
    void evict_terminals();
    void emit_changed(const std::string& op_id);
    void emit_removed(const std::string& op_id);

    std::map<std::string, OperationRecord> ops_;
    std::vector<std::string> insertion_order_;
    std::deque<std::string> terminal_order_;
};

// Process-level lazy registry (Python module-global `operation_registry()`
// parity). Product writers register/finish through this single global;
// readers keep a reference instead of re-calling.
OperationRegistry& operation_registry();

}  // namespace pwb::ui_shell
