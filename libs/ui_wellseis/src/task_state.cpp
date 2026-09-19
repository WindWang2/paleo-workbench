#include <pwb/ui_wellseis/task_state.hpp>

#include <unordered_map>

namespace pwb::ui_wellseis {

std::string task_key(const PredictionTaskSlice& task) {
    if (!task.id.empty()) {
        return "id:" + task.id;
    }
    return "name:" + task.name;
}

const PredictionTaskSlice* active_prediction_task(
    const std::vector<PredictionTaskSlice>& tasks) {
    if (tasks.empty()) {
        return nullptr;
    }
    return &tasks.back();
}

namespace {

// state_language.py "task" vocabulary (frozen — see header note).
const std::unordered_map<std::string, TaskStatusToken>& task_vocab() {
    static const std::unordered_map<std::string, TaskStatusToken> table = {
        {"queued", {"…", "排队中", "muted"}},
        {"running", {"▶", "运行中", "info"}},
        {"cancelling", {"⏸", "取消中", "warn"}},
        {"cancelled", {"■", "已取消", "muted"}},
        {"failed", {"✕", "失败", "error"}},
        {"done", {"✓", "完成", "ok"}},
        {"degraded", {"!", "降级完成", "warn"}},
    };
    return table;
}

// task_panel_base._TASK_STATUS_ALIASES (raw domain status -> task key).
const std::unordered_map<std::string, std::string>& status_aliases() {
    static const std::unordered_map<std::string, std::string> table = {
        {"pending", "queued"},   {"queued", "queued"},
        {"running", "running"},  {"cancelling", "cancelling"},
        {"cancelled", "cancelled"},
        {"complete", "done"},    {"completed", "done"},
        {"done", "done"},        {"failed", "failed"},
        {"warning", "degraded"},
    };
    return table;
}

std::string ascii_lower(std::string_view value) {
    std::string out(value);
    for (char& c : out) {
        if (c >= 'A' && c <= 'Z') {
            c = static_cast<char>(c - 'A' + 'a');
        }
    }
    return out;
}

std::string strip(std::string_view value) {
    std::size_t b = 0, e = value.size();
    while (b < e && (value[b] == ' ' || value[b] == '\t' ||
                     value[b] == '\n' || value[b] == '\r')) {
        ++b;
    }
    while (e > b && (value[e - 1] == ' ' || value[e - 1] == '\t' ||
                     value[e - 1] == '\n' || value[e - 1] == '\r')) {
        --e;
    }
    return std::string(value.substr(b, e - b));
}

}  // namespace

TaskStatusToken task_status_token(std::string_view status) {
    const std::string key = ascii_lower(strip(status));
    const auto alias = status_aliases().find(key);
    if (alias == status_aliases().end()) {
        // Unknown statuses are never coerced to 排队中 — the raw text
        // renders muted (Python's StateToken("·", status or "待开始")).
        return {"·", key.empty() ? std::string("待开始") : std::string(status),
                "muted"};
    }
    const auto token = task_vocab().find(alias->second);
    if (token == task_vocab().end()) {
        return {"·", "未知", "muted"};
    }
    return token->second;
}

std::string badge_tone_of(const std::string& state_tone) {
    static const std::unordered_map<std::string, std::string> table = {
        {"ok", "success"}, {"info", "primary"}, {"warn", "warning"},
        {"error", "error"}, {"muted", "neutral"}, {"locked", "neutral"},
    };
    const auto it = table.find(state_tone);
    return it == table.end() ? "neutral" : it->second;
}

std::string task_row_text(const PredictionTaskSlice& task) {
    const std::string name =
        task.name.empty() ? std::string("未命名预测任务") : task.name;
    return name + " · " + task_status_token(task.status).label;
}

std::string task_row_tooltip(const PredictionTaskSlice& task) {
    const std::string name =
        task.name.empty() ? std::string("未命名预测任务") : task.name;
    return name + "\n状态：" + task_status_token(task.status).label;
}

int task_panel_active_row(
    const std::vector<PredictionTaskSlice>& tasks,
    const std::optional<int>& selected_index) {
    int index = -1;
    if (selected_index.has_value() && *selected_index >= 0 &&
        *selected_index < static_cast<int>(tasks.size())) {
        index = *selected_index;
    } else {
        const PredictionTaskSlice* active = active_prediction_task(tasks);
        if (active != nullptr) {
            index = static_cast<int>(active - tasks.data());
        }
    }
    return index;
}

std::optional<int> index_of_task_id(
    const std::vector<PredictionTaskSlice>& tasks,
    const std::string& task_id) {
    if (task_id.empty()) {
        return std::nullopt;
    }
    for (std::size_t i = 0; i < tasks.size(); ++i) {
        if (tasks[i].id == task_id) {
            return static_cast<int>(i);
        }
    }
    return std::nullopt;
}

std::optional<int> index_of_task_named(
    const std::vector<PredictionTaskSlice>& tasks,
    const std::string& well_name) {
    if (well_name.empty()) {
        return std::nullopt;
    }
    for (std::size_t i = 0; i < tasks.size(); ++i) {
        if (tasks[i].name == well_name) {
            return static_cast<int>(i);
        }
    }
    return std::nullopt;
}

}  // namespace pwb::ui_wellseis
