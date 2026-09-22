#include "pwb/ui_stageflow/stage_presentation.hpp"

#include <sstream>

namespace pwb::ui_stageflow {

namespace {

// The three profiles as plain data — the projection of
// tool_policy::kStageGroupVisibility into panel terms:
//   stage1 (facies_calibration):  factor OFF, layout_export OFF
//   stage2 (constraint_factor):    factor ON,  layout_export OFF
//   stage3 (integrated_compilation): factor OFF, layout_export ON
// "factor surfaces" = composite_input (输入与结果) + composite_linked (联动视图)
// + mapping.reference + mapping.bottom (单因素参考架).
// "layout_export surfaces" = mapping.composer.
// Docks the profile does NOT list (nav/mapping_stage/inspector/
// composite_layer/hub/agent/tasks/logs/console) stay under user + viewport
// policy — a stage switch must never yank navigation or diagnostics away.

StageLayoutProfile make_profile(const char* stage_value,
                                const char* lower_pane,
                                std::initializer_list<
                                    std::pair<const char*, bool>> visibility) {
    StageLayoutProfile profile;
    profile.stage_value = stage_value;
    profile.lower_pane_mode = lower_pane;
    for (const auto& [key, visible] : visibility) {
        profile.visibility[key] = visible;
    }
    return profile;
}

}  // namespace

std::string stage_display_label(const std::string& stage_value) {
    const auto stage = tool_policy::stage_from_value(stage_value);
    if (!stage.has_value()) {
        return stage_value.empty() ? std::string("未进入编图") : stage_value;
    }
    return tool_policy::stage_label(*stage);
}

StageLayoutProfile stage_layout_profile(const std::string& stage_value) {
    return presentation_profile(stage_value);
}

StageLayoutProfile presentation_profile(const std::string& presentation_key) {
    const auto stage = tool_policy::stage_from_value(presentation_key);
    if (!stage.has_value()) {
        if (presentation_key == kPresentationDataManagement) {
            // 数据管理工作区: the data page owns the central area — every
            // science/mapping surface steps aside. Docks the profile does
            // NOT list (nav/mapping_stage/inspector/hub/agent/tasks/logs/
            // console/composite_layer) stay under user + viewport policy.
            return make_profile(
                kPresentationDataManagement, kLowerPaneNone,
                {
                    {"workstation.facies_palette", false},
                    {"workstation.composite_input", false},
                    {"workstation.composite_linked", false},
                    {"workstation.well", false},
                    {"workstation.seismic", false},
                    {"mapping.chrome", false},
                    {"mapping.reference", false},
                    {"mapping.composer", false},
                    {"mapping.bottom", false},
                    {"window.constraint_panel", false},
                    {"window.factor_stats", false},
                });
        }
        if (presentation_key == kPresentationValidation) {
            // 验证工作区 (M2 placeholder page, M5 fills the content): the
            // review/QC surfaces visible (chrome/reference/bottom), the
            // composer and factor/constraint surfaces off.
            return make_profile(
                kPresentationValidation, kLowerPaneNone,
                {
                    {"workstation.facies_palette", false},
                    {"workstation.composite_input", false},
                    {"workstation.composite_linked", false},
                    {"workstation.well", false},
                    {"workstation.seismic", false},
                    {"mapping.chrome", true},
                    {"mapping.reference", true},
                    {"mapping.composer", false},
                    {"mapping.bottom", true},
                    {"window.constraint_panel", false},
                    {"window.factor_stats", false},
                });
        }
        // Lenient fallback: unknown/empty key behaves as stage 1
        // (workspace codec parity — never fails, never invents stage 4).
        return presentation_profile(kStage1Value);
    }
    switch (*stage) {
        case tool_policy::MappingStage::FaciesCalibration:
            // Stage 1 智能预测 (M3): the seismic/well surfaces live in the
            // science-host bottom two-pane now — the legacy workstation
            // placeholder docks stay managed-but-hidden (the preference
            // machinery keeps working, the empty chrome never shows).
            return make_profile(
                kStage1Value, kLowerPaneSeismicWell,
                {
                    {"workstation.facies_palette", true},
                    {"workstation.composite_input", false},
                    {"workstation.composite_linked", false},
                    {"workstation.well", false},
                    {"workstation.seismic", false},
                    {"mapping.chrome", false},
                    {"mapping.reference", false},
                    {"mapping.composer", false},
                    {"mapping.bottom", false},
                    {"window.constraint_panel", false},
                    {"window.factor_stats", false},
                });
        case tool_policy::MappingStage::ConstraintFactor:
            // Stage 2 约束与单因素 (M3): 连井剖面 + 数据制备 host in the
            // science-host bottom tabs; factor/constraint docks on.
            return make_profile(
                kStage2Value, kLowerPaneCrossWell,
                {
                    {"workstation.facies_palette", false},
                    {"workstation.composite_input", true},
                    {"workstation.composite_linked", true},
                    {"workstation.well", false},
                    {"workstation.seismic", false},
                    {"mapping.chrome", true},
                    {"mapping.reference", true},
                    {"mapping.composer", false},
                    {"mapping.bottom", true},
                    {"window.constraint_panel", true},
                    {"window.factor_stats", true},
                });
        case tool_policy::MappingStage::IntegratedCompilation:
            // Stage 3 综合编图: layout/export surfaces on (composer),
            // factor surfaces off; bottom pane hosts the factor reference
            // strip of the compilation workbench.
            return make_profile(
                kStage3Value, kLowerPaneFactors,
                {
                    {"workstation.facies_palette", false},
                    {"workstation.composite_input", false},
                    {"workstation.composite_linked", false},
                    {"workstation.well", false},
                    {"workstation.seismic", false},
                    {"mapping.chrome", true},
                    {"mapping.reference", true},
                    {"mapping.composer", true},
                    {"mapping.bottom", true},
                    {"window.constraint_panel", false},
                    {"window.factor_stats", false},
                });
    }
    return presentation_profile(kStage1Value);  // unreachable, kept honest
}

std::vector<std::string> profile_managed_keys() {
    std::vector<std::string> keys;
    const auto profile = stage_layout_profile(kStage1Value);
    for (const auto& [key, value] : profile.visibility) {
        (void)value;
        keys.push_back(key);
    }
    return keys;
}

// ---------------------------------------------------------------------------
// Preference (de)serialization
// ---------------------------------------------------------------------------

std::string serialize_stage_preferences(const StageUserPreferences& prefs) {
    // "key=value,key=value" — '=' and ',' cannot appear in managed keys
    // (they are namespaced identifiers), values are "0"/"1".
    std::string out;
    for (const auto& [key, visible] : prefs.visibility_overrides) {
        if (!out.empty()) out += ',';
        out += key + '=' + (visible ? '1' : '0');
    }
    return out;
}

StageUserPreferences parse_stage_preferences(const std::string& blob) {
    StageUserPreferences prefs;
    std::istringstream stream(blob);
    std::string entry;
    while (std::getline(stream, entry, ',')) {
        const auto eq = entry.find('=');
        if (eq == std::string::npos || eq == 0 || eq + 1 == entry.size()) {
            continue;  // corrupt entry — skip honestly, keep the rest
        }
        const std::string key = entry.substr(0, eq);
        const char value = entry[eq + 1];
        if (value != '0' && value != '1') continue;
        prefs.visibility_overrides[key] = (value == '1');
    }
    return prefs;
}

StagePreferenceStore::StagePreferenceStore(StagePreferenceSink sink)
    : sink_(std::move(sink)) {}

StageUserPreferences StagePreferenceStore::load(
    const std::string& stage_value) const {
    if (!sink_.load) return StageUserPreferences{};
    const auto version = sink_.load("version");
    if (!version.has_value() ||
        *version != std::to_string(kPreferenceVersion)) {
        return StageUserPreferences{};  // fence mismatch -> defaults
    }
    const auto blob = sink_.load(stage_value + "/visibility");
    if (!blob.has_value()) return StageUserPreferences{};
    return parse_stage_preferences(*blob);
}

void StagePreferenceStore::save(const std::string& stage_value,
                                const StageUserPreferences& prefs) {
    if (!sink_.save) return;
    sink_.save("version", std::to_string(kPreferenceVersion));
    sink_.save(stage_value + "/visibility",
               serialize_stage_preferences(prefs));
}

std::map<std::string, bool> effective_visibility(
    const StageLayoutProfile& profile,
    const StageUserPreferences& prefs) {
    auto merged = profile.visibility;
    for (const auto& [key, visible] : prefs.visibility_overrides) {
        merged[key] = visible;  // user toggle wins, including for keys the
                                // profile does not manage this stage
    }
    return merged;
}

}  // namespace pwb::ui_stageflow
