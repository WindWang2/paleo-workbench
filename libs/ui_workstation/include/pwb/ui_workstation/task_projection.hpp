#pragma once

// Port of paleo_workbench/ui/workstation/task_center.py's row layer
// (UI-12): scheduler JobSnapshots and OperationRegistry records project
// into ONE table (V11 goal §12) with one state vocabulary, one cancel
// interaction, and one context-menu contract. This module is the
// Qt-free projection; the widget side is an incremental
// QAbstractTableModel that diffs on task_id.
//
// Python constants: _MAX_ROWS = 100; column order
// 状态/任务/进度/用时/操作.

#include <optional>
#include <string>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_shell/operation_registry.hpp>

namespace pwb::ui_workstation {

inline constexpr int kTaskCenterMaxRows = 100;

// Unified row over both authorities. `submitted_at` is the sort key
// (desc — newest on top); `sort_order` is the registry insertion rank
// used as a stable tiebreak for operation records.
struct TaskRow {
    std::string task_id;         // job_id or "op:<op_id>"
    std::string title;           // spec.title | spec.kind | task_id
    std::string kind;
    job::JobState state = job::JobState::queued;
    double progress = 0.0;       // clamped [0,1] by the runtime/registry
    std::optional<std::string> message;
    std::optional<std::string> error;
    double submitted_at = 0.0;
    std::optional<double> started_at;
    std::optional<double> finished_at;
    bool cancel_requested = false;
    // _OperationHandleAdapter parity: registry rows cancel via
    // registry.request_cancel and cannot "重试" (no spec to resubmit).
    bool registry_op = false;
    // Terminal registry records may carry a result jump (goal §12).
    bool has_jump = false;
    std::optional<std::string> result_label;
    // The op_id for registry rows (empty for scheduler rows).
    std::string op_id;

    bool is_terminal() const {
        return state == job::JobState::done ||
               state == job::JobState::degraded ||
               state == job::JobState::failed ||
               state == job::JobState::cancelled;
    }
    bool cancellable() const {
        return state == job::JobState::queued ||
               state == job::JobState::running;
    }
};

// JobSnapshot → TaskRow (direct field pass-through).
TaskRow task_row_from_job(const job::JobSnapshot& snapshot);

// OperationRecord → TaskRow (_OperationHandleAdapter parity):
// state vocabulary maps queued/running/cancelling/completed/warning/
// failed/cancelled → queued/running/cancelling/done/degraded/failed/
// cancelled; message = "object_label · stage · result_label(terminal)";
// task_id = "op:<op_id>".
TaskRow task_row_from_operation(
    const ui_shell::OperationRecord& record);

// Merge + order (submitted_at desc) + cap at _MAX_ROWS.
std::vector<TaskRow> build_task_rows(
    const std::vector<job::JobSnapshot>& jobs,
    const std::vector<const ui_shell::OperationRecord*>& operations);

// Active = queued + running (Python refresh() parity).
int active_task_count(const std::vector<TaskRow>& rows);

// --- display text ------------------------------------------------------

// _TaskRowDelegate._state_text parity:
// 排队/运行中/取消中/完成/降级完成/失败/已取消; cancel_requested on
// queued/running shows 取消中 (V7 R1-P1); running shows "运行中 N%".
std::string task_state_text(const TaskRow& row);

// Display title: "spec.title | spec.kind | task_id"; failed rows append
// " — <first 40 chars of error line 1>" (visual QA 10).
std::string task_title_text(const TaskRow& row);

// Tooltip: message | error | task_id.
std::string task_tooltip_text(const TaskRow& row);

// TaskCenter.format_elapsed parity: <60 s → "N s"; else "MM:SS".
std::string format_task_elapsed(double seconds);

// Row elapsed: max(0, (finished_at or now) - (started_at or
// submitted_at)).
double task_row_elapsed(const TaskRow& row, double now);

// --- context menu -------------------------------------------------------

enum class TaskMenuAction {
    Cancel,
    JumpToResult,
    Retry,
    CopyTaskId,
    Details,
};

struct TaskMenuItem {
    TaskMenuAction action;
    std::string label;
    bool enabled = true;
    std::string tooltip;
};

// _show_context_menu parity: 取消 (cancellable; disabled + tooltip when
// cancel_requested), 跳转 (terminal registry rows with a jump),
// 重试 (failed/cancelled scheduler rows only), 复制任务 ID, 详情…
std::vector<TaskMenuItem> task_menu_items(const TaskRow& row);

// 详情… dialog body (Python _show_details parity; `result_text` is the
// adapter-rendered repr — "—" when none).
std::string task_details_text(const TaskRow& row,
                              const std::string& result_text = "");

}  // namespace pwb::ui_workstation
