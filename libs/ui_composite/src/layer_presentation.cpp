// V14 layer presentation — see layer_presentation.hpp.
#include "pwb/ui_composite/layer_presentation.hpp"

#include <algorithm>

namespace pwb::ui_composite {

namespace {

// RAW-protected roles: original interpretation results — direct editing
// is forbidden (create a DERIVED draft instead); matches the edit-gate
// vocabulary in stage_profiles/layer_roles.
bool role_is_raw_protected(const std::string& role) {
    // layer_roles.py ROLE_RAW_PROTECTED (7 roles): original
    // interpretation results — direct editing forbidden (create a
    // DERIVED draft instead).
    return role == "initial_facies_source" ||
           role == "well_facies_prediction" ||
           role == "seismic_facies_prediction" ||
           role == "well_facies_confidence" ||
           role == "seismic_facies_confidence" ||
           role == "factor_grid" ||
           role == "factor_classification";
}

}  // namespace

LayerRowStatus build_layer_row_status(const LayerRowInputs& inputs) {
    LayerRowStatus status;
    if (inputs.binding != nullptr) {
        status.role = inputs.binding->role;
        status.binding_unknown = false;
        const std::string_view kind =
            pwb::workspace::effective_binding_kind(*inputs.binding);
        status.bound_to_version = kind == pwb::workspace::kBindingCatalogVersion;
        status.bound_by_fingerprint =
            kind == pwb::workspace::kBindingContentFingerprint;
    }
    status.raw_protected = role_is_raw_protected(status.role);

    // Flags use the FROZEN vocabulary of contracts 03 §9 — anything
    // outside it travels on the struct's boolean fields, never as a flag
    // string (additions need an ADR).
    if (inputs.is_active) status.flags.push_back("active");
    if (inputs.is_editing) status.flags.push_back("editing");
    if (inputs.is_dirty) status.flags.push_back("dirty");
    if (inputs.is_selected) status.flags.push_back("selected");
    if (inputs.is_locked) status.flags.push_back("locked");
    if (status.raw_protected) status.flags.push_back("raw");
    if (!status.role.empty()) status.flags.push_back("role:" + status.role);
    // Freshness flags (aligned with the bridge indicator kinds).
    switch (inputs.freshness) {
        case LayerFreshness::Stale:
            status.flags.push_back("stale");
            break;
        case LayerFreshness::SourceMissing:
            status.flags.push_back("source_missing");
            break;
        case LayerFreshness::Superseded:
            status.flags.push_back("superseded");
            break;
        case LayerFreshness::Fresh:
        case LayerFreshness::Unknown:
            break;  // never fabricate a freshness claim
    }
    if (inputs.selection_mismatch) status.flags.push_back("warning");
    return status;
}

std::string layer_row_summary(const LayerRowInputs& inputs) {
    const LayerRowStatus status = build_layer_row_status(inputs);
    std::string out = inputs.layer_id;
    if (!status.role.empty()) out += "｜角色 " + status.role;
    if (inputs.binding != nullptr) {
        if (!inputs.binding->source_version_id.empty()) {
            out += "｜版本 " + inputs.binding->source_version_id;
        } else if (!inputs.binding->source_asset_id.empty()) {
            out += "｜资产 " + inputs.binding->source_asset_id;
        } else {
            out += "｜数据源未知";
        }
        const std::string kind(pwb::workspace::effective_binding_kind(
            *inputs.binding));
        if (!kind.empty()) out += "（" + kind + "）";
    }
    if (status.has_flag("stale")) out += "｜输入已过期";
    if (status.has_flag("source_missing")) out += "｜数据源缺失";
    if (status.has_flag("superseded")) out += "｜已被新版本取代";
    if (status.has_flag("editing")) {
        out += status.has_flag("dirty") ? "｜编辑中（有未提交修改）"
                                        : "｜编辑中";
    }
    if (status.has_flag("active")) out += "｜活动目标";
    if (status.has_flag("locked")) out += "｜已锁定";
    if (status.has_flag("raw")) out += "｜RAW 原始成果（不可直接编辑）";
    if (status.has_flag("warning")) out += "｜注意：选中层与工具写入目标不一致";
    return out;
}

}  // namespace pwb::ui_composite
