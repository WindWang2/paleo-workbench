#pragma once

// UI-11 — design-token literals mirrored from paleo_workbench/tokens.py,
// restricted to the values this slice's Qt-free cores embed in generated
// text/html. These constants are part of the frozen oracle contract, so
// they are compile-time literals here rather than theme lookups (the Qt
// side re-reads style_palette() for theme-aware widgets — same split as
// libs/ui_data_core/tokens.hpp).

#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace pwb::ui_review::tokens {

inline constexpr std::string_view kPrimary = "#0b5563";
inline constexpr std::string_view kAccent = "#a65313";
inline constexpr std::string_view kSuccess = "#15803d";
inline constexpr std::string_view kWarning = "#b45309";
inline constexpr std::string_view kError = "#d31f1f";
inline constexpr std::string_view kErrorRed = "#b91c1c";
inline constexpr std::string_view kTeal = "#0f766e";
inline constexpr std::string_view kTextPrimary = "#18232d";
inline constexpr std::string_view kTextSecondary = "#53616c";
inline constexpr std::string_view kBorder = "#d6dde3";
inline constexpr std::string_view kBgSearch = "#edf1f4";

// Layout metrics used by the panels (tokens.py values).
inline constexpr int kSpace1 = 4;
inline constexpr int kSpace2 = 8;
inline constexpr int kSpace3 = 12;
inline constexpr int kSpace4 = 20;
inline constexpr int kPanelPadding = 12;   // tokens.PANEL_PADDING
inline constexpr int kPageMargin = 16;     // tokens.PAGE_MARGIN

// tokens.DEFAULT_QC_RULES (review page 质检规则 dialog + rule column).
inline const std::vector<std::string>& default_qc_rules() {
    static const std::vector<std::string> rules = {
        "层级一致性",      "未分类区域",
        "低可信区",        "边界碎斑异常",
        "图例符号完整性",  "字段与输出格式完整性",
    };
    return rules;
}

// tokens.RULE_DESCRIPTIONS (qc_issue_table 检查说明 column).
inline const std::unordered_map<std::string, std::string>&
rule_descriptions() {
    static const std::unordered_map<std::string, std::string> map = {
        {"层级一致性", "各层级结构与命名是否一致"},
        {"未分类区域", "是否存在未分类或未赋值区域"},
        {"低可信区", "低可信区是否已复核确认"},
        {"边界碎斑异常", "是否存在碎斑、孤岛等异常斑块"},
        {"图例符号完整性", "图例符号与备注是否完整"},
        {"字段与输出格式完整性", "字段是否齐全、格式是否规范"},
        // QC engine rule keys map to display via these too:
        {"facies_polygons_present", "古地理图相带多边形是否存在"},
        {"target_horizon_present", "古地理图是否关联目标层位"},
        {"facies_geometry_valid", "相带多边形几何是否有效（无自交）"},
        {"well_overlays_present", "图面是否叠加井位"},
        {"contour_lines_present", "是否存在等值线线要素"},
        {"well_table_qc_clean", "井点表 MAD/砂地比异常是否已清理"},
    };
    return map;
}

}  // namespace pwb::ui_review::tokens
