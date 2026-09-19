// catalog/governance.py read-side port — GOVERNANCE_KEYS order,
// governance_values() and governance_display(). The write-side
// (normalize_governance_*) is a catalog mutation concern, out of this slice.
#pragma once

#include "pwb/domain/json.hpp"
#include "pwb/ui_data_core/json_util.hpp"

#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace pwb::ui_data_core {

// GOVERNANCE_KEYS — declaration order in GOVERNANCE_FIELDS.
inline const std::vector<std::string>& governance_keys() {
    static const std::vector<std::string> keys = {
        "source", "region", "creator", "discipline", "confidence",
        "review_status",
    };
    return keys;
}

namespace detail {
inline const std::unordered_map<std::string, std::string>& discipline_display() {
    static const std::unordered_map<std::string, std::string> map = {
        {"seismic", "地震"},       {"well_log", "测井"},
        {"horizon", "层位"},       {"interpretation", "解释"},
        {"correlation", "地层对比"}, {"fault", "断层"},
        {"factor_map", "因子制图"}, {"prediction", "预测"},
        {"paleomap", "古地图编制"}, {"qc", "质量控制"},
        {"export", "成果导出"},     {"modeling", "三维建模"},
        {"general", "综合"},
    };
    return map;
}
inline const std::unordered_map<std::string, std::string>& confidence_display() {
    static const std::unordered_map<std::string, std::string> map = {
        {"high", "高"}, {"medium", "中"}, {"low", "低"},
    };
    return map;
}
inline const std::unordered_map<std::string, std::string>& review_status_display() {
    static const std::unordered_map<std::string, std::string> map = {
        {"draft", "草稿"},
        {"pending_review", "待审核"},
        {"approved", "已通过"},
        {"rejected", "已驳回"},
    };
    return map;
}
}  // namespace detail

// governance_values(metadata): insertion-ordered (key, str(value)) pairs for
// members present and not (None, ""). Python `not in (None, "")` keeps 0 and
// False, so JSON falsy numbers/bools are kept and stringified.
inline std::vector<std::pair<std::string, std::string>> governance_values(
    const domain::Json& metadata) {
    std::vector<std::pair<std::string, std::string>> out;
    if (!metadata.is_object()) {
        return out;
    }
    for (const auto& key : governance_keys()) {
        const auto it = metadata.find(key);
        if (it == metadata.end() || it->is_null()) {
            continue;
        }
        if (it->is_string() && it->get<std::string>().empty()) {
            continue;
        }
        out.emplace_back(key, json_str(*it));
    }
    return out;
}

// governance_display(key, value): Chinese display label; free text / unknown
// keys pass through unchanged.
inline std::string governance_display(std::string_view key,
                                      std::string_view value) {
    if (value.empty()) {
        return std::string(value);
    }
    const std::unordered_map<std::string, std::string>* display = nullptr;
    if (key == "discipline") {
        display = &detail::discipline_display();
    } else if (key == "confidence") {
        display = &detail::confidence_display();
    } else if (key == "review_status") {
        display = &detail::review_status_display();
    }
    if (display == nullptr) {
        return std::string(value);  // free-text fields: no vocabulary mapping
    }
    const auto it = display->find(std::string(value));
    return it != display->end() ? it->second : std::string(value);
}

// Field label for inspector tables (GOVERNANCE_FIELDS[key].label).
inline std::string governance_field_label(std::string_view key) {
    static const std::unordered_map<std::string, std::string> labels = {
        {"source", "来源"},        {"region", "区域"},
        {"creator", "负责人"},      {"discipline", "学科方向"},
        {"confidence", "可信等级"}, {"review_status", "审核状态"},
    };
    const auto it = labels.find(std::string(key));
    return it != labels.end() ? it->second : std::string(key);
}

// governance_display_rows: (label, display-value) pairs in GOVERNANCE_KEYS
// order for members present in governance_values().
inline std::vector<std::pair<std::string, std::string>> governance_display_rows(
    const domain::Json& metadata) {
    const auto values = governance_values(metadata);
    std::vector<std::pair<std::string, std::string>> rows;
    rows.reserve(values.size());
    for (const auto& [key, value] : values) {
        rows.emplace_back(governance_field_label(key),
                          governance_display(key, value));
    }
    return rows;
}

}  // namespace pwb::ui_data_core
