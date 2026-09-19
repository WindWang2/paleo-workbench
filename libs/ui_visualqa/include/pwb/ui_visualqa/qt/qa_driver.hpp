#pragma once

// UI-16 — the V6..V10 drive recipes + the probe-bound check entry points.
//
// Every drive_<state>(window) in visual_qa_v{6..10}.py becomes a free
// function over the injected VisualQaProbe: same call sequence, same
// settle() waits, same guard semantics. run_state_checks(state, probe)
// collects one snapshot and evaluates the Qt-free check table in
// qa_checks.hpp — the Python `run_state_checks(state, window)` parity.

#include <functional>
#include <string>
#include <vector>

#include <pwb/ui_visualqa/qa_check.hpp>
#include <pwb/ui_visualqa/qa_snapshot.hpp>
#include <pwb/ui_visualqa/qt/workstation_probe.hpp>

class QWidget;

namespace pwb::ui_visualqa::qt {

// _settle parity: QEventLoop wait + processEvents — the harness's
// settle-then-shot rhythm.
void settle(int ms);

// The V7 task_cancelling body (_long_task parity): 50 uninterruptible
// 2 s segments with a cancel checkpoint between them — the cancel
// request lands mid-run so the task center shows the 取消中 window.
void cancellable_demo_task(QaTaskContext& ctx);

// drive_state(state, probe) — dispatch over the V6..V10 drive tables.
// Unknown state -> false (the Python shot tables simply have no entry).
bool drive_state(const std::string& state, VisualQaProbe& probe);

// run_state_checks(state, probe) — collect() once, then the pure check
// table (qa_checks.hpp). Unknown state -> empty list (Python parity:
// `_CHECK_TABLE.get(state)` -> []).
std::vector<CheckResult> run_state_checks(const std::string& state,
                                          VisualQaProbe& probe);

// ---- per-state drive bodies (the Python drive_<state> parity set) -----

void drive_mapping_stage_phase1(VisualQaProbe& p);
void drive_mapping_stage_phase2(VisualQaProbe& p);
void drive_mapping_stage_phase3(VisualQaProbe& p);
void drive_command_palette_context(VisualQaProbe& p);
void drive_write_grant_dialog(VisualQaProbe& p);
void drive_status_workbench_segment(VisualQaProbe& p);

void drive_phase1_raw_blocked(VisualQaProbe& p);
void drive_phase1_editing_session(VisualQaProbe& p);
void drive_phase2_constraint_line(VisualQaProbe& p);
void drive_phase2_factor_raster(VisualQaProbe& p);
void drive_layer_tree_decorations(VisualQaProbe& p);
void drive_task_cancelling(VisualQaProbe& p);
void drive_toolbar_overflow_narrow(VisualQaProbe& p);
void drive_inspector_factor(VisualQaProbe& p);

void drive_empty_project_tool_surface(VisualQaProbe& p);
void drive_derived_polygon_editing_dirty(VisualQaProbe& p);
void drive_frozen_map_product(VisualQaProbe& p);
void drive_palette_disabled_reason(VisualQaProbe& p);
void drive_native_activation_failure_revert(VisualQaProbe& p);
void drive_blocking_task_tool_surface(VisualQaProbe& p);

void drive_compact_viewport(VisualQaProbe& p);
void drive_wide_viewport(VisualQaProbe& p);
void drive_ultrawide_viewport(VisualQaProbe& p);
void drive_narrow_hub_page(VisualQaProbe& p);
void drive_preset_visibility_only(VisualQaProbe& p);
void drive_agent_grow_only(VisualQaProbe& p);

void drive_raw_layer_readonly_surface(VisualQaProbe& p);
void drive_capture_preferred_line_role(VisualQaProbe& p);
void drive_editing_dirty_chip(VisualQaProbe& p);
void drive_snapping_detail_surface(VisualQaProbe& p);
void drive_topology_error_chip(VisualQaProbe& p);
void drive_crs_undeclared_surface(VisualQaProbe& p);
void drive_crs_mismatch_warning(VisualQaProbe& p);
void drive_frozen_layer_surface(VisualQaProbe& p);
void drive_canvas_context_menu_surface(VisualQaProbe& p);
void drive_compact_1366_toolbar_identity(VisualQaProbe& p);

}  // namespace pwb::ui_visualqa::qt
