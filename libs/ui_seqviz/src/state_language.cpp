// UI-10 — state_language.cpp: frozen vocabulary table + lookups.

#include "pwb/ui_seqviz/state_language.hpp"

namespace pwb::ui_seqviz {

namespace {

const StateToken kUnknown{"·", "未知", "muted"};

using Table = std::map<std::string, StateToken>;

const std::map<std::string, Table>& vocabulary() {
    static const std::map<std::string, Table> table = {
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
             {"missing_input", {"✕", "输入缺失", "error"}},
             {"superseded", {"↻", "已被取代", "warn"}},
             {"unknown", {"·", "状态未知", "muted"}},
         }},
        {"session",
         {
             {"editing", {"✎", "编辑中", "info"}},
             {"dirty", {"✎", "未保存修改", "warn"}},
         }},
        {"editability",
         {
             {"editable", {"✎", "可编辑", "ok"}},
             {"raw", {"▣", "RAW 不可编辑", "locked"}},
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

const std::map<std::string, std::string>& tone_to_badge_map() {
    static const std::map<std::string, std::string> map = {
        {"ok", "success"},  {"info", "primary"}, {"warn", "warning"},
        {"error", "error"}, {"muted", "neutral"}, {"locked", "neutral"},
    };
    return map;
}

}  // namespace

const StateToken& unknown_state_token() { return kUnknown; }

StateToken state_token(const std::string& category, const std::string& value) {
    const auto& vocab = vocabulary();
    const auto cat = vocab.find(category);
    if (cat == vocab.end()) {
        throw UnknownStateCategory(category);
    }
    const auto it = cat->second.find(value);
    if (it == cat->second.end()) {
        return kUnknown;
    }
    return it->second;
}

StateToken state_token(const std::string& category, const char* value) {
    return state_token(category, std::string(value == nullptr ? "" : value));
}

StateToken state_token(const std::string& category, std::nullptr_t) {
    const auto& vocab = vocabulary();
    if (vocab.find(category) == vocab.end()) {
        throw UnknownStateCategory(category);
    }
    return kUnknown;
}

std::string tone_to_badge(const std::string& tone) {
    const auto& map = tone_to_badge_map();
    const auto it = map.find(tone);
    return it == map.end() ? "neutral" : it->second;
}

}  // namespace pwb::ui_seqviz
