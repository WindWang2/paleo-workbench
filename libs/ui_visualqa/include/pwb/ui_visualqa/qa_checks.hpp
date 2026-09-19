#pragma once

// UI-16 — the check semantics, ported pure.
//
// Every Python `_check_<state>(window)` reads live widget attributes; the
// C++ port reads a collected snapshot so the verdict logic is Qt-free and
// oracle-testable. Each function below mirrors one Python check body
// verbatim — same check names, same predicates, same detail payloads.
// Missing surface facts (absent action/dock keys) yield ok=false like a
// Python KeyError/AttributeError failing the check — never a fake pass.

#include <string>
#include <vector>

#include <pwb/ui_visualqa/qa_check.hpp>
#include <pwb/ui_visualqa/qa_snapshot.hpp>

namespace pwb::ui_visualqa {

// run_state_checks(state, snapshot) — the V6..V10 dispatch table parity
// (visual_qa_v{6..10}.py _CHECK_TABLE). Unknown state -> empty list.
std::vector<CheckResult> run_state_checks(
    const std::string& state, const WorkstationSnapshot& snapshot);

// run_scenario_checks(name, snapshot) — the V11 _CHECKS parity. Unknown
// scenario -> empty list; a missing snapshot section yields a single
// `*_surface_snapshot` failing check (the widget-side collector's
// contract — Python would AttributeError on a malformed widget).
std::vector<CheckResult> run_scenario_checks(
    const std::string& name, const ScenarioSnapshot& snapshot);

// ---- per-state check bodies (parity mirrors; used by the dispatch) ----

// V6 — _mapping_stage_checks(target) covers the three phase states.
std::vector<CheckResult> check_mapping_stage(
    const WorkstationSnapshot& s, const std::string& target_stage_value);
std::vector<CheckResult> check_command_palette_context(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_write_grant_dialog(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_status_workbench_segment(
    const WorkstationSnapshot& s);

// V7
std::vector<CheckResult> check_phase1_raw_blocked(const WorkstationSnapshot& s);
std::vector<CheckResult> check_phase1_editing_session(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_phase2_constraint_line(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_phase2_factor_raster(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_layer_tree_decorations(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_task_cancelling(const WorkstationSnapshot& s);
std::vector<CheckResult> check_toolbar_overflow_narrow(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_inspector_factor(const WorkstationSnapshot& s);

// V8
std::vector<CheckResult> check_empty_project_tool_surface(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_derived_polygon_editing_dirty(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_frozen_map_product(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_palette_disabled_reason(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_native_activation_failure_revert(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_blocking_task_tool_surface(
    const WorkstationSnapshot& s);

// V9
std::vector<CheckResult> check_compact_viewport(const WorkstationSnapshot& s);
std::vector<CheckResult> check_wide_viewport(const WorkstationSnapshot& s);
std::vector<CheckResult> check_ultrawide_viewport(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_narrow_hub_page(const WorkstationSnapshot& s);
std::vector<CheckResult> check_preset_visibility_only(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_agent_grow_only(const WorkstationSnapshot& s);

// V10
std::vector<CheckResult> check_raw_layer_readonly_surface(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_capture_preferred_line_role(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_editing_dirty_chip(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_snapping_detail_surface(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_topology_error_chip(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_crs_undeclared_surface(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_crs_mismatch_warning(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_frozen_layer_surface(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_canvas_context_menu_surface(
    const WorkstationSnapshot& s);
std::vector<CheckResult> check_compact_1366_toolbar_identity(
    const WorkstationSnapshot& s);

// V11 (scenario sections; stage target derives from the scenario name)
std::vector<CheckResult> check_first_open(const QaShellSnapshot& s);
std::vector<CheckResult> check_data_manager(const QaDataManagerSnapshot& s);
std::vector<CheckResult> check_task_panel(const QaTaskPanelSnapshot& s);
std::vector<CheckResult> check_seismic_context(
    const QaSeismicContextSnapshot& s);
std::vector<CheckResult> check_stage_surface(
    const QaStageSurfaceSnapshot& s, const std::string& target_stage_value);
std::vector<CheckResult> check_inspector_version(
    const QaInspectorSnapshot& s);
std::vector<CheckResult> check_inspector_run(const QaInspectorSnapshot& s);
std::vector<CheckResult> check_task_center(const QaTaskCenterSnapshot& s);
std::vector<CheckResult> check_command_palette_scenario(
    const QaPaletteScenarioSnapshot& s);
std::vector<CheckResult> check_error_empty_states(
    const QaStatesCompositeSnapshot& s);
std::vector<CheckResult> check_theme_matrix(
    const std::vector<QaThemeRender>& renders);

}  // namespace pwb::ui_visualqa
