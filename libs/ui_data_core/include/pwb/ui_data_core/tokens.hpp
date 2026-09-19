// Design-token constants mirrored from paleo_workbench/tokens.py.
//
// Only the tokens the UI-03 core-data/preview ports actually read are
// carried — the full palette/theme machinery stays in
// libs/platform_services (theme_tokens.hpp). Hex values and label strings
// are part of the frozen oracle contract, so they are compile-time
// constants here rather than theme lookups.
#pragma once

#include <string>
#include <string_view>
#include <unordered_map>

namespace pwb::ui_data_core::tokens {

inline constexpr std::string_view kPrimary = "#0b5563";
inline constexpr std::string_view kAccent = "#a65313";
inline constexpr std::string_view kSuccess = "#15803d";
inline constexpr std::string_view kWarning = "#b45309";
inline constexpr std::string_view kError = "#d31f1f";
inline constexpr std::string_view kErrorRed = "#b91c1c";
inline constexpr std::string_view kTeal = "#0f766e";
inline constexpr std::string_view kTextPrimary = "#18232d";
inline constexpr std::string_view kTextSecondary = "#53616c";
inline constexpr std::string_view kTextDark = "#101820";

// tokens.STATUS_TEXT
inline const std::unordered_map<std::string, std::string>& status_text() {
    static const std::unordered_map<std::string, std::string> map = {
        {"complete", "已完成"},
        {"stale", "需更新"},
        {"running", "处理中"},
        {"pending", "待开始"},
        {"warning", "警告"},
        {"failed", "异常"},
        {"ready", "就绪"},
        {"skipped", "已跳过"},
        {"mock", "Mock"},
    };
    return map;
}

// tokens.TASK_STATUS_LABELS
inline const std::unordered_map<std::string, std::string>& task_status_labels() {
    static const std::unordered_map<std::string, std::string> map = {
        {"complete", "已生成"},
        {"pending", "待生成"},
        {"running", "进行中"},
        {"failed", "失败"},
    };
    return map;
}

// tokens.QC_RESULT_COLORS
inline const std::unordered_map<std::string, std::string>& qc_result_colors() {
    static const std::unordered_map<std::string, std::string> map = {
        {"pass", std::string(kSuccess)},
        {"warning", std::string(kWarning)},
        {"error", std::string(kErrorRed)},
    };
    return map;
}

// tokens.QC_RESULT_LABELS
inline const std::unordered_map<std::string, std::string>& qc_result_labels() {
    static const std::unordered_map<std::string, std::string> map = {
        {"pass", "✓通过"},
        {"warning", "!警告"},
        {"error", "!待处理"},
    };
    return map;
}

// tokens.RESOURCE_LABELS
inline const std::unordered_map<std::string, std::string>& resource_labels() {
    static const std::unordered_map<std::string, std::string> map = {
        {"well_log", "测井数据"},
        {"seismic", "地震数据"},
        {"horizon", "层位数据"},
    };
    return map;
}

}  // namespace pwb::ui_data_core::tokens
