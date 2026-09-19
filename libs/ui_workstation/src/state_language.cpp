#include "pwb/ui_workstation/state_language.hpp"

#include <map>
#include <stdexcept>

namespace pwb::ui_workstation {

namespace {

const StateToken kUnknown{"·", "未知", "muted"};

const std::map<std::string, std::map<std::string, StateToken>>&
vocabulary() {
    static const std::map<std::string, std::map<std::string, StateToken>>
        table = {
            {"maturity",
             {
                 {"raw", {"▣", "RAW 原始", "locked"}},
                 {"derived", {"◈", "派生", "info"}},
                 {"intermediate", {"◇", "中间成果", "info"}},
                 {"output", {"★", "成果", "ok"}},
                 {"working", {"✎", "工作副本", "info"}},
                 {"draft", {"✎", "草稿", "info"}},
                 {"reviewed", {"✓", "已复核", "ok"}},
                 {"frozen", {"❄", "冻结", "locked"}},
                 {"published", {"◉", "已发布", "ok"}},
             }},
            {"freshness",
             {
                 {"current", {"✓", "最新", "ok"}},
                 {"stale", {"↻", "已过期", "warn"}},
                 {"missing", {"✕", "缺失", "error"}},
                 // V7 §7 (tree decoration): aligned to
                 // dependencies.FreshnessStatus — missing_input /
                 // superseded previously only had domain-side labels.
                 {"missing_input", {"✕", "输入缺失", "error"}},
                 {"superseded", {"↻", "已被取代", "warn"}},
                 {"unknown", {"·", "状态未知", "muted"}},
             }},
            // V7 §7: edit-session presentation state (layer-level dirty
            // signal).
            {"session",
             {
                 {"editing", {"✎", "编辑中", "info"}},
                 {"dirty", {"✎", "未保存修改", "warn"}},
             }},
            {"editability",
             {
                 {"editable", {"✎", "可编辑", "ok"}},
                 {"raw", {"▣", "RAW 不可编辑", "locked"}},
                 // 「⊘」 replaces the old lock emoji glyph (goal §7 bans
                 // emoji; glyph+text dual signal kept).
                 {"locked", {"⊘", "证据锁定", "locked"}},
                 {"none", {"·", "无编辑目标", "muted"}},
             }},
            {"task",
             {
                 {"queued", {"…", "排队中", "muted"}},
                 {"running", {"▶", "运行中", "info"}},
                 {"cancelling", {"⏸", "取消中", "warn"}},
                 {"cancelled", {"■", "已取消", "muted"}},
                 {"failed", {"✕", "失败", "error"}},
                 {"done", {"✓", "完成", "ok"}},
                 // V11: degraded completion (done with warnings —
                 // OperationRegistry.WARNING and legacy warning states
                 // converge here; task center 「降级完成」 synonym).
                 {"degraded", {"!", "降级完成", "warn"}},
             }},
            {"backend",
             {
                 {"native", {"◆", "原生", "ok"}},
                 {"fallback", {"◌", "回退", "warn"}},
                 {"missing", {"✕", "不可用", "error"}},
             }},
            {"permission",
             {
                 {"granted", {"✓", "已授权写入", "ok"}},
                 {"read_only", {"▣", "只读会话", "muted"}},
             }},
            // V7 §6: stage readiness (readiness items).
            {"readiness",
             {
                 {"ok", {"✓", "就绪", "ok"}},
                 {"warning", {"!", "注意", "warn"}},
                 {"error", {"✕", "未就绪", "error"}},
                 {"info", {"·", "说明", "muted"}},
             }},
        };
    return table;
}

const std::map<std::string, std::string>& tone_bridge() {
    static const std::map<std::string, std::string> bridge = {
        {"ok", "success"},   {"info", "primary"}, {"warn", "warning"},
        {"error", "error"},  {"muted", "neutral"}, {"locked", "neutral"},
    };
    return bridge;
}

}  // namespace

const StateToken& unknown_state_token() {
    return kUnknown;
}

StateToken state_token(const std::string& category,
                       const std::optional<std::string>& value) {
    const auto it = vocabulary().find(category);
    if (it == vocabulary().end()) {
        throw std::out_of_range("state_language: unknown category '" +
                                category + "'");
    }
    if (!value.has_value()) {
        return kUnknown;
    }
    const auto token = it->second.find(*value);
    return token != it->second.end() ? token->second : kUnknown;
}

StateToken state_token(const std::string& category, const char* value) {
    return state_token(category,
                       value == nullptr
                           ? std::nullopt
                           : std::optional<std::string>(value));
}

std::string tone_to_badge(const std::string& tone) {
    const auto it = tone_bridge().find(tone);
    return it != tone_bridge().end() ? it->second : "neutral";
}

std::string workbench_context_text(
    const UIContextSnapshot& snapshot,
    const std::function<std::string(const std::string&)>& layer_name) {
    std::vector<std::string> parts;
    // Python truthiness parity: empty strings are falsy and skipped.
    if (snapshot.mapping_stage_label.has_value() &&
        !snapshot.mapping_stage_label->empty()) {
        parts.push_back(*snapshot.mapping_stage_label);
    }
    const auto& target = snapshot.active_layer_id;
    if (target.has_value() && layer_name) {
        const std::string name = layer_name(*target);
        if (snapshot.active_layer_editable.has_value() &&
            !*snapshot.active_layer_editable) {
            const std::string reason =
                snapshot.active_layer_block_reason.value_or("不可编辑");
            parts.push_back(name + " — " +
                            (reason.empty() ? "不可编辑" : reason));
        } else if (snapshot.editing_active) {
            parts.push_back("编辑中：" + name);
        } else {
            parts.push_back("目标：" + name);
        }
    } else if (snapshot.active_layer_block_reason.has_value() &&
               !snapshot.active_layer_block_reason->empty() &&
               !target.has_value()) {
        parts.push_back(*snapshot.active_layer_block_reason);
    }
    if (snapshot.qgis_bridge_available.has_value()) {
        if (*snapshot.qgis_bridge_available) {
            parts.push_back("QGIS 原生");
        } else {
            parts.push_back("画布回退（QGIS 桥不可用）");
        }
    }
    if (snapshot.running_task_count) {
        parts.push_back("任务 ×" + std::to_string(snapshot.running_task_count));
    }
    if (parts.empty()) {
        parts.push_back(snapshot.project_open ? "就绪" : "未打开工程");
    }
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i) out += " · ";
        out += parts[i];
    }
    return out;
}

}  // namespace pwb::ui_workstation
