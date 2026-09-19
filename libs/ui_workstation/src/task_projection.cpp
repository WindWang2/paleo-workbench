#include "pwb/ui_workstation/task_projection.hpp"

#include <algorithm>
#include <chrono>
#include <cstdio>

namespace pwb::ui_workstation {

namespace {

// OperationRecord.state → JobState (the adapter's mapping dict).
job::JobState job_state_for_operation(
    ui_shell::OperationState state) {
    switch (state) {
    case ui_shell::OperationState::Queued:
        return job::JobState::queued;
    case ui_shell::OperationState::Running:
        return job::JobState::running;
    case ui_shell::OperationState::Cancelling:
        return job::JobState::cancelling;
    case ui_shell::OperationState::Completed:
        return job::JobState::done;
    case ui_shell::OperationState::Warning:
        return job::JobState::degraded;
    case ui_shell::OperationState::Failed:
        return job::JobState::failed;
    case ui_shell::OperationState::Cancelled:
        return job::JobState::cancelled;
    }
    return job::JobState::running;  // dict.get(...) fallback
}

}  // namespace

TaskRow task_row_from_job(const job::JobSnapshot& s) {
    TaskRow row;
    row.task_id = s.job_id;
    row.title = !s.title.empty() ? s.title
                                 : (!s.kind.empty() ? s.kind : s.job_id);
    row.kind = s.kind;
    row.state = s.state;
    row.progress = s.progress;
    if (!s.message.empty()) row.message = s.message;
    if (!s.error.empty()) row.error = s.error;
    row.submitted_at = s.submitted_at;
    row.started_at = s.started_at;
    row.finished_at = s.finished_at;
    row.cancel_requested = s.cancel_requested;
    return row;
}

TaskRow task_row_from_operation(
    const ui_shell::OperationRecord& record) {
    TaskRow row;
    row.task_id = "op:" + record.op_id;
    row.op_id = record.op_id;
    row.title = record.title;
    row.kind = "operation";
    row.state = job_state_for_operation(record.state);
    const auto fraction = record.progress_fraction();
    row.progress = fraction.value_or(0.0);
    std::string message;
    if (record.object_label.has_value()) {
        message += *record.object_label;
    }
    if (record.stage.has_value()) {
        if (!message.empty()) message += " · ";
        message += *record.stage;
    }
    if (ui_shell::operation_state_terminal(record.state) &&
        record.result_label.has_value()) {
        if (!message.empty()) message += " · ";
        message += *record.result_label;
    }
    if (!message.empty()) row.message = message;
    if (record.error.has_value()) row.error = record.error;
    // Same monotonic timeline as JobSnapshot.submitted_at (both are
    // steady_clock seconds), so the merged sort is a real interleave.
    row.submitted_at =
        std::chrono::duration<double>(record.started_at.time_since_epoch())
            .count();
    if (record.finished_at.has_value()) {
        row.finished_at = std::chrono::duration<double>(
                              record.finished_at->time_since_epoch())
                              .count();
    }
    row.cancel_requested =
        record.state == ui_shell::OperationState::Cancelling;
    row.registry_op = true;
    row.has_jump = static_cast<bool>(record.jump);
    row.result_label = record.result_label;
    return row;
}

std::vector<TaskRow> build_task_rows(
    const std::vector<job::JobSnapshot>& jobs,
    const std::vector<const ui_shell::OperationRecord*>& operations) {
    std::vector<TaskRow> rows;
    rows.reserve(jobs.size() + operations.size());
    for (const auto& job : jobs) rows.push_back(task_row_from_job(job));
    // Python sorted() is stable — equal submitted_at keeps the input
    // order (jobs first, then ops in registry order).
    for (const auto* op : operations) {
        rows.push_back(task_row_from_operation(*op));
    }
    std::stable_sort(rows.begin(), rows.end(), [](const TaskRow& a,
                                                  const TaskRow& b) {
        return a.submitted_at > b.submitted_at;
    });
    if (rows.size() > static_cast<std::size_t>(kTaskCenterMaxRows)) {
        rows.resize(kTaskCenterMaxRows);
    }
    return rows;
}

int active_task_count(const std::vector<TaskRow>& rows) {
    int n = 0;
    for (const auto& row : rows) {
        if (row.state == job::JobState::queued ||
            row.state == job::JobState::running) {
            ++n;
        }
    }
    return n;
}

std::string task_state_text(const TaskRow& row) {
    using JS = job::JobState;
    std::string text;
    switch (row.state) {
    case JS::queued:     text = "排队"; break;
    case JS::running:    text = "运行中"; break;
    case JS::cancelling: text = "取消中"; break;
    case JS::done:       text = "完成"; break;
    case JS::degraded:   text = "降级完成"; break;
    case JS::failed:     text = "失败"; break;
    case JS::cancelled:  text = "已取消"; break;
    }
    if (row.cancel_requested &&
        (row.state == JS::queued || row.state == JS::running)) {
        // V7 R1-P1: 取消中优先于运行中.
        return "取消中";
    }
    if (row.state == JS::running) {
        const int pct = static_cast<int>(row.progress * 100 + 0.5);
        text += " " + std::to_string(pct) + "%";
    }
    return text;
}

std::string task_title_text(const TaskRow& row) {
    if (row.state == job::JobState::failed &&
        row.error.has_value()) {
        std::string short_error = *row.error;
        const auto nl = short_error.find('\n');
        if (nl != std::string::npos) short_error.resize(nl);
        // strip + first 40 chars
        const auto start = short_error.find_first_not_of(" \t");
        if (start == std::string::npos) return row.title;
        short_error = short_error.substr(start, 40);
        return row.title + " — " + short_error;
    }
    return row.title;
}

std::string task_tooltip_text(const TaskRow& row) {
    if (row.message.has_value()) return *row.message;
    if (row.error.has_value()) return *row.error;
    return row.task_id;
}

std::string format_task_elapsed(double seconds) {
    if (seconds < 60.0) {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%.0f s", seconds);
        return buf;
    }
    const int total = static_cast<int>(seconds);
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%02d:%02d", total / 60, total % 60);
    return buf;
}

double task_row_elapsed(const TaskRow& row, double now) {
    const double end = row.finished_at.value_or(now);
    const double start = row.started_at.value_or(row.submitted_at);
    return std::max(0.0, end - start);
}

std::vector<TaskMenuItem> task_menu_items(const TaskRow& row) {
    std::vector<TaskMenuItem> items;
    if (row.cancellable()) {
        TaskMenuItem cancel{TaskMenuAction::Cancel, "取消"};
        if (row.cancel_requested) {
            cancel.enabled = false;
            cancel.tooltip =
                "正在等待任务协作取消（长计算步骤间检查取消点）";
        }
        items.push_back(std::move(cancel));
    }
    if (row.registry_op && row.has_jump && row.is_terminal()) {
        TaskMenuItem jump{TaskMenuAction::JumpToResult,
                          row.result_label.has_value()
                              ? "跳转：" + *row.result_label
                              : "跳转到结果"};
        items.push_back(std::move(jump));
    }
    if (row.state == job::JobState::failed ||
        row.state == job::JobState::cancelled) {
        TaskMenuItem retry{TaskMenuAction::Retry, "重试"};
        retry.tooltip = "用完全相同的参数重新提交该任务";
        retry.enabled = !row.registry_op;  // 无 spec 可重放
        items.push_back(std::move(retry));
    }
    items.push_back({TaskMenuAction::CopyTaskId, "复制任务 ID"});
    items.push_back({TaskMenuAction::Details, "详情…"});
    return items;
}

std::string task_details_text(const TaskRow& row,
                              const std::string& result_text) {
    using job::to_string;
    const int pct = static_cast<int>(row.progress * 100 + 0.5);
    std::string out = "任务 ID: " + row.task_id + "\n";
    out += "类型: " + row.kind + "\n";
    out += "状态: " + std::string(to_string(row.state)) + "\n";
    out += "进度: " + std::to_string(pct) + "%\n";
    out += "消息: " + row.message.value_or("—") + "\n";
    out += "错误: " + row.error.value_or("—") + "\n";
    out += "结果: " + (result_text.empty() ? "—" : result_text);
    return out;
}

}  // namespace pwb::ui_workstation
