#pragma once

// UI-09 — prediction-task state helpers (Qt-free).
//
// Ports:
//   viz/prediction_helpers.py::active_prediction_task  (last element)
//   task_panel_base.py::_task_key / update_state        (key + selection)
//   workstation/state_language.py task vocabulary + _TASK_STATUS_ALIASES
//   task_panel_base.py::_render_task_row                ("name · label")
//
// The state-language "task" vocabulary is owned by UI-12; the frozen
// task-status token table is duplicated here verbatim (7 entries) because
// the row text is part of THIS slice's panel semantics — flagged in the
// ledger as a deliberate minimal overlap, never a second authority on
// non-task categories.

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <pwb/ui_wellseis/slices.hpp>

namespace pwb::ui_wellseis {

// "id:<id>" when the task carries an id, else "name:<name>" — the stable
// reconcile key (TaskPanelBase._task_key).
std::string task_key(const PredictionTaskSlice& task);

// prediction_helpers.active_prediction_task: last element or nullptr.
const PredictionTaskSlice* active_prediction_task(
    const std::vector<PredictionTaskSlice>& tasks);

// state_language StateToken for the "task" category.
struct TaskStatusToken {
    std::string glyph;
    std::string label;
    std::string tone;  // ok|info|warn|error|muted
};

// task_panel_base.task_status_token: alias map first (pending->queued,
// complete/completed->done, warning->degraded, ...); unknown statuses fall
// back to a muted token carrying the raw status text (or 待开始).
TaskStatusToken task_status_token(std::string_view status);

// state_language.tone_to_badge mapping (ok->success, info->primary,
// warn->warning, error->error, muted/locked->neutral).
std::string badge_tone_of(const std::string& state_tone);

// "{name} · {token.label}" — the task row text (未命名预测任务 fallback).
std::string task_row_text(const PredictionTaskSlice& task);
std::string task_row_tooltip(const PredictionTaskSlice& task);

// The panel's selected index: explicit selection when valid, else the
// active task's row (TaskPanelBase.update_state semantics).
int task_panel_active_row(
    const std::vector<PredictionTaskSlice>& tasks,
    const std::optional<int>& selected_index);

// The page's id-anchored reselection: index of the task whose id matches
// selected_task_id (V11 C4 — selection anchors ids, never positions).
std::optional<int> index_of_task_id(
    const std::vector<PredictionTaskSlice>& tasks,
    const std::string& task_id);

// The well-name seam used by set_selected_well: index of the task whose
// name matches (first match), nullopt otherwise.
std::optional<int> index_of_task_named(
    const std::vector<PredictionTaskSlice>& tasks,
    const std::string& well_name);

}  // namespace pwb::ui_wellseis
