#include <pwb/ui_visualqa/qa_states.hpp>

namespace pwb::ui_visualqa {

namespace {

const std::vector<std::string> kV6States = {
    "mapping_stage_phase1",
    "mapping_stage_phase2",
    "mapping_stage_phase3",
    "command_palette_context",
    "write_grant_dialog",
    "status_workbench_segment",
};

const std::vector<std::string> kWriteGrantActionIds = {
    "map.add_layer",
    "map.export",
};

const std::vector<std::string> kV7States = {
    "phase1_raw_blocked",
    "phase1_editing_session",
    "phase2_constraint_line",
    "phase2_factor_raster",
    "layer_tree_decorations",
    "task_cancelling",
    "toolbar_overflow_narrow",
    "inspector_factor",
};

const std::vector<std::string> kV8States = {
    "empty_project_tool_surface",
    "derived_polygon_editing_dirty",
    "frozen_map_product",
    "palette_disabled_reason",
    "native_activation_failure_revert",
    "blocking_task_tool_surface",
};

const std::vector<std::string> kV9States = {
    "compact_viewport",
    "wide_viewport",
    "ultrawide_viewport",
    "narrow_hub_page",
    "preset_visibility_only",
    "agent_grow_only",
};

const std::vector<std::string> kV10States = {
    "raw_layer_readonly_surface",
    "capture_preferred_line_role",
    "editing_dirty_chip",
    "snapping_detail_surface",
    "topology_error_chip",
    "crs_undeclared_surface",
    "crs_mismatch_warning",
    "frozen_layer_surface",
    "canvas_context_menu_surface",
    "compact_1366_toolbar_identity",
};

const std::vector<std::string> kV11Scenarios = {
    "first_open_empty_shell",
    "data_manager_surface",
    "well_task_workflow_panel",
    "seismic_context_surface",
    "stage_bar_phase1",
    "stage_bar_phase2",
    "stage_bar_phase3",
    "inspector_version_payload",
    "inspector_run_payload",
    "task_center_operations",
    "command_palette_disabled_reason",
    "error_empty_states_composite",
    "theme_matrix_smoke",
};

const std::vector<std::string> kThemeMatrixThemes = {"light", "dark"};
const std::vector<QaSize> kThemeMatrixSizes = {{1280, 720}, {1920, 1080}};

std::vector<QaShotEntry> entries_of(const std::vector<std::string>& states) {
    std::vector<QaShotEntry> out;
    out.reserve(states.size());
    for (const std::string& s : states) {
        out.push_back(QaShotEntry{s, true});
    }
    return out;
}

const std::vector<QaShotEntry> kV6Shots = entries_of(kV6States);
const std::vector<QaShotEntry> kV7Shots = entries_of(kV7States);

// v8_shot_table: empty_project_tool_surface uses none_factory
// (needs_project=false), the rest share make_project.
const std::vector<QaShotEntry> kV8Shots = [] {
    std::vector<QaShotEntry> out;
    out.reserve(kV8States.size());
    for (const std::string& s : kV8States) {
        out.push_back(QaShotEntry{s, s != "empty_project_tool_surface"});
    }
    return out;
}();

const std::vector<QaShotEntry> kV9Shots = entries_of(kV9States);
const std::vector<QaShotEntry> kV10Shots = entries_of(kV10States);

const std::vector<std::string> kAllV6V10 = [] {
    std::vector<std::string> out;
    for (const auto* table :
         {&kV6States, &kV7States, &kV8States, &kV9States, &kV10States}) {
        out.insert(out.end(), table->begin(), table->end());
    }
    return out;
}();

}  // namespace

const std::vector<std::string>& v6_states() { return kV6States; }
const std::vector<std::string>& write_grant_action_ids() {
    return kWriteGrantActionIds;
}
const std::string& palette_context_filter() {
    static const std::string k = "单因素";
    return k;
}

const std::vector<std::string>& v7_states() { return kV7States; }
const std::vector<std::string>& v8_states() { return kV8States; }
const std::vector<std::string>& v9_states() { return kV9States; }
const std::vector<std::string>& v10_states() { return kV10States; }

const std::vector<std::string>& v11_scenarios() { return kV11Scenarios; }
const std::vector<std::string>& theme_matrix_themes() {
    return kThemeMatrixThemes;
}
const std::vector<QaSize>& theme_matrix_sizes() { return kThemeMatrixSizes; }
const std::string& palette_stage_filter() {
    static const std::string k = "单因素";
    return k;
}
const std::string& palette_tool_filter() {
    static const std::string k = "开始编辑";
    return k;
}

const std::vector<QaShotEntry>& v6_shot_table() { return kV6Shots; }
const std::vector<QaShotEntry>& v7_shot_table() { return kV7Shots; }
const std::vector<QaShotEntry>& v8_shot_table() { return kV8Shots; }
const std::vector<QaShotEntry>& v9_shot_table() { return kV9Shots; }
const std::vector<QaShotEntry>& v10_shot_table() { return kV10Shots; }
const std::vector<std::string>& v11_shot_table() { return kV11Scenarios; }

bool scenario_needs_workstation_shell(const std::string& name) {
    // Python returns true for ("first_open_empty_shell",
    // "command_palette_disabled_reason"). In C++ the command-palette
    // scenario is built directly on the real CommandPalette +
    // CommandRegistry evaluator — the authoritative verdict path the
    // Python shell wires — so only the empty-shell scenario still needs
    // a full workstation surface. See ledger (UI-16 divergence note).
    return name == "first_open_empty_shell";
}

const std::vector<std::string>& all_v6_v10_states() { return kAllV6V10; }

}  // namespace pwb::ui_visualqa
