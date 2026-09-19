#pragma once

// UI-09 — SeismicContextToolbar / SeismicAttributePanel attribute catalog
// (Qt-free).
//
// Ports _ATTRIBUTE_GROUPS + ALL_SEISMIC_ATTRIBUTES verbatim — the same
// ordered groups drive the combo items and the "切换地震属性" submenu.

#include <string>
#include <vector>

namespace pwb::ui_wellseis {

struct SeismicAttributeGroup {
    std::string group_label;
    std::vector<std::string> attributes;
};

// _ATTRIBUTE_GROUPS verbatim: 振幅/频率/连续性/结构/多属性融合.
const std::vector<SeismicAttributeGroup>& seismic_attribute_groups();

// ALL_SEISMIC_ATTRIBUTES — flat list in group order.
const std::vector<std::string>& all_seismic_attributes();

// Membership probe (unknown attributes still select — the Python page
// accepts any non-empty label, but panels show catalog membership).
bool is_known_seismic_attribute(const std::string& attribute);

// SeismicAttributePanel's own grouping (separate table from the toolbar):
// every enabled leaf maps to a wired kernel id; unimplemented reference
// labels sit under an explicit 未实现 group.
const std::vector<SeismicAttributeGroup>& seismic_attribute_panel_groups();

// kernel id -> user-facing label (_COMPUTABLE_LABELS verbatim).
const std::vector<std::pair<std::string, std::string>>&
computable_kernel_labels();

// label -> kernel id (_LABEL_TO_KERNEL); "" when the label is not a
// computable option (e.g. a 未实现 leaf).
std::string kernel_for_label(const std::string& label);

// Display-mode tokens (the toolbar's checkable modes).
inline const char* kDisplayModeVd = "vd";
inline const char* kDisplayModeWiggle = "wiggle";
const std::vector<std::string>& seismic_display_modes();

}  // namespace pwb::ui_wellseis
