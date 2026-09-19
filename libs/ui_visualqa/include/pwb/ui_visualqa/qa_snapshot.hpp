#pragma once

// UI-16 — Qt-free snapshot vocabulary for the visual-QA checks.
//
// The Python check functions read live widget attributes
// (ws.stage_bar._buttons, palette.result_list items, status chips…).
// The C++ port keeps every check PURE: a host-side probe collects the
// same facts into these plain-data snapshots and the check functions in
// qa_checks.hpp evaluate them. Each field is commented with the Python
// attribute it mirrors so parity is auditable. No Qt types here.

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_visualqa {

// ---- V6..V10 workstation snapshot --------------------------------------

// One QAction/QAbstractButton-like surface fact (action_controller.actions
// entry parity). `exists=false` mirrors a missing dict key — the Python
// check would raise KeyError; the ported check records ok=false instead.
struct QaActionState {
    bool exists = false;
    bool enabled = false;
    bool checked = false;
    bool visible = false;
    std::string text;
    std::string status_tip;
    std::string tool_tip;
};

// One tool_availability() verdict (ToolAvailability parity: enabled /
// disabled_reason / preferred / checked). Missing key -> exists=false.
struct QaToolVerdict {
    bool exists = false;
    bool enabled = false;
    bool preferred = false;
    bool checked = false;
    std::string disabled_reason;
};

// One dock's visibility + geometry facts (QDockWidget parity).
struct QaDockState {
    bool hidden = true;
    int width = 0;
    int height = 0;
    int min_size_hint_width = 0;  // minimumSizeHint().width()
};

// One palette result row (QListWidgetItem parity): display text, the
// ItemIsEnabled flag, the spec's stage scope (spec.stages non-empty —
// resolved from UserRole spec id by the collector), and the tooltip.
struct QaPaletteItem {
    std::string text;
    bool enabled = true;
    bool stage_scoped = false;
    std::string spec_id;
    std::string tool_tip;
};

// The write-grant dialog facts (_v6_grab_widget parity).
struct QaDialogSnapshot {
    bool present = false;
    std::string object_name;
    bool hidden = true;
    bool deny_present = false;
    bool deny_default = false;
    std::string deny_text;
    bool grant_present = false;
    std::string grant_text;
    std::optional<bool> granted;      // getattr(dialog,"granted",None)
    std::vector<std::string> label_texts;  // findChildren(QLabel).text()
};

// One scheduler handle (TaskHandle parity): TaskState.value + the
// cancel_requested flag — the V9 "取消中" presentation window check.
struct QaTaskHandle {
    std::string task_id;
    std::string state;            // "running"|"cancelling"|… (TaskState.value)
    bool cancel_requested = false;
};

// One canvas context-menu action (menu.actions() parity). `tool_id` is the
// objectName "MapAction:<id>" suffix (empty for non-mapped actions).
struct QaMenuAction {
    std::string text;
    std::string tool_id;
    bool enabled = true;
};

// The whole read surface the V6..V10 checks consume — collected by the
// injected probe (qt/workstation_probe.hpp), one collect() call per
// run_state_checks like Python reads the window once per check run.
//
// `bound` is the fail-closed guard: false when the probe could not reach
// a live workstation window at all. A missing sub-surface (palette,
// dialog, canvas menu) is still recorded via its own *_present flag —
// the Python checks fail on those individually. `bound=false` makes
// run_state_checks return one honest failing check instead of N fake
// passes on default values (Python would AttributeError → error).
struct WorkstationSnapshot {
    bool bound = false;
    // Stage bar markers: stage value -> checked (absent key = no button,
    // Python `_buttons.get(stage)` -> None parity).
    std::map<std::string, bool> stage_marker_checked;
    // mapping_stage_panel._pages[target] exists AND stack.currentWidget()
    // is that page (identity check collapsed — the collector knows).
    bool stage_panel_shows_target = false;
    // composite.action_controller.actions by id.
    std::map<std::string, QaActionState> actions;
    // composite.tool_availability() by tool id.
    std::map<std::string, QaToolVerdict> availability;
    // Docks by key: "nav"|"inspector"|"stage"|"task"|"agent"|"hub"|
    // "composite_layer".
    std::map<std::string, QaDockState> docks;
    // Command palette (shell.command_palette).
    bool palette_present = false;
    bool palette_hidden = true;
    std::vector<QaPaletteItem> palette_items;
    // status_bar.workbench_label text (V6 workbench segment).
    std::string workbench_label_text;
    bool workbench_label_hidden = true;  // label.isHidden()
    // composite.status_bar chips.
    std::string edit_chip_text;         // status_bar.edit
    std::string snapping_text;          // status_bar.snapping
    std::string snapping_tooltip;
    bool topology_chip_hidden = true;   // status_bar.topology_issue
    std::string topology_chip_text;
    std::string crs_text;               // status_bar.crs
    std::string crs_tooltip;
    // layer_manager.tree col-1 texts joined " | " (V7 _tree_status_texts).
    std::string tree_status_joined;
    // Scheduler statuses() snapshot (V7 task_cancelling).
    std::vector<QaTaskHandle> task_handles;
    // _dock_host.toolBarArea(host_map_toolbars()) -> TopToolBarArea.
    bool map_top_in_top_area = false;
    bool map_bottom_in_top_area = false;
    // findChildren(QWidget,"WorkstationOverlayToolbar") count.
    int overflow_toolbar_children = 0;
    // inspector.header text.
    std::string inspector_header;
    // Window + layout facts (V9/V10).
    int window_width = 0;
    int window_height = 0;
    int window_min_width = 0;
    int composite_width = 0;
    int canvas_width = 0;               // composite.canvas.width()
    bool responsive_hid_inspector = false;  // ws._responsive_hid_inspector
    bool user_hid_inspector = false;        // ws._user_hid_inspector
    int command_input_min_width = 0;    // app_bar.command_input.minimumWidth
    bool stage_label_visible = false;   // stage_bar.horizon_label.isVisibleTo
    int hub_scroll_min_width = 0;       // hub_scroll.minimumSizeHint().width()
    std::string current_preset_id;      // ws.current_preset_id
    // Grab-widget dialog (V6 write grant).
    QaDialogSnapshot grab_dialog;
    // composite._empty_hint.isVisible().
    bool empty_hint_visible = false;
    // _v8_status_log entries (composite.status_message capture).
    std::vector<std::string> status_messages;
    // _v10_canvas_menu facts.
    bool canvas_menu_present = false;
    std::vector<QaMenuAction> canvas_menu_actions;
    // _map_toolbar_top.widgetForAction(add_line).property("preferred").
    bool preferred_button_present = false;
    bool preferred_button_property = false;
    // Session scratch bag (window._v9_nav_width_before / _v9_agent_height_
    // before parity — drivers write, checks read).
    std::map<std::string, int> session_values;
};

// ---- V11 scenario snapshots ---------------------------------------------

// first_open_empty_shell (AppShell parity).
struct QaShellSnapshot {
    bool workstation_present = false;
    std::string inspector_header;        // ws.inspector.header.text()
    bool inspector_current_is_project = false;  // ws.inspector._current is shell.project
    int task_center_rows = 0;            // task_center.model.rowCount()
    int project_wells = 0;
    int project_resources = 0;
};

// data_manager_surface (DataPage parity).
struct QaDataManagerSnapshot {
    int asset_rows = 0;                  // asset_table._active_model().rowCount()
    int resource_count = 0;              // len(project.resources)
    std::string inspector_title;         // inspector_panel.title_label.text()
    bool inspector_empty_hidden = false; // inspector_panel.empty_label.isHidden()
    bool inspector_tabs_hidden = false;  // inspector_panel.tabs.isHidden()
};

// well_task_workflow_panel (PredictionTaskPanel parity).
struct QaTaskPanelSnapshot {
    bool panel_found = false;            // _v11_task_panel present
    std::vector<std::string> row_texts;  // task_list item texts
    std::string status_badge_text;       // status_badge.text()
    std::string status_badge_tone;       // status_badge.tone / property("tone")
};

// seismic_context_surface (SeismicContextToolbar parity).
struct QaSeismicContextSnapshot {
    bool toolbar_found = false;          // findChild(SeismicContextToolbar)
    std::string source_text;             // seismic_source_combo.currentText()
    std::string attribute_text;          // attribute_combo.currentText()
    std::string horizon_text;            // horizon_value.text()
    std::string task_text;               // task_value.text()
    std::string shape_text;              // shape_value.text()
    std::string status_text;             // status_value.text()
};

// stage_bar_phase{1,2,3} (MappingStageBar+Panel parity). The check knows
// the target stage from the scenario name.
struct QaStageSurfaceSnapshot {
    std::map<std::string, bool> stage_marker_checked;  // bar._buttons
    bool stage_panel_shows_target = false;             // _pages[target] is current
    std::string current_horizon;                       // bar.current_horizon()
    bool constraints_row_visible = false;              // _constraints_row.isVisibleTo(panel)
};

// inspector_version/run_payload (WorkstationInspector parity): header +
// the read-only form field values the Python _form_values collects.
struct QaInspectorSnapshot {
    std::string header;
    std::vector<std::string> property_values;
    std::vector<std::string> interpretation_values;
};

// task_center_operations (TaskCenter + OperationRegistry parity).
struct QaTaskCenterSnapshot {
    std::vector<std::string> row_ids;             // handle.task_id per row
    bool running_present = false;                 // "op:v11qa-import" row
    bool finished_present = false;                // "op:v11qa-verify" row
    std::string running_state_text;               // delegate state text
    std::optional<double> running_progress;       // handle.progress
    std::string finished_message;                 // handle.message
    bool cancel_request_result = false;           // registry.request_cancel(id)
};

// command_palette_disabled_reason: two item sweeps — the stage filter
// first, then the tool filter the check applies mid-run (parity with the
// Python check's own setText(PALETTE_TOOL_FILTER) + settle).
struct QaPaletteScenarioSnapshot {
    bool open = false;
    int enabled_count = 0;                    // enabled rows under stage filter
    std::vector<QaPaletteItem> stage_items;   // rows under PALETTE_STAGE_FILTER
    std::vector<QaPaletteItem> tool_items;    // rows under PALETTE_TOOL_FILTER
};

// error_empty_states_composite.
struct QaBadgeSnapshot {
    std::string tone;
    std::string text;
};
struct QaStatesCompositeSnapshot {
    bool empty_found = false;
    std::string empty_title;             // _title.text()
    bool empty_hint_hidden = true;       // _hint.isHidden()
    bool loading_found = false;
    std::string loading_text;            // _text.text()
    bool loading_indeterminate = false;  // _bar minimum==0 && maximum==0
    std::vector<QaBadgeSnapshot> badges;
};

// theme_matrix_smoke: one render result per (theme, size) — produced by
// the Qt layer (grab() + sampled distinct colors), evaluated Qt-free.
struct QaThemeRender {
    std::string theme;
    int want_width = 0;
    int want_height = 0;
    int width = 0;
    int height = 0;
    int distinct_colors = 0;
    bool null_pixmap = true;
};

// The scenario collector bag — each builder fills exactly its section.
struct ScenarioSnapshot {
    std::optional<QaShellSnapshot> shell;
    std::optional<QaDataManagerSnapshot> data_manager;
    std::optional<QaTaskPanelSnapshot> task_panel;
    std::optional<QaSeismicContextSnapshot> seismic;
    std::optional<QaStageSurfaceSnapshot> stage;
    std::optional<QaInspectorSnapshot> inspector;
    std::optional<QaTaskCenterSnapshot> task_center;
    std::optional<QaPaletteScenarioSnapshot> palette;
    std::optional<QaStatesCompositeSnapshot> states_composite;
    std::vector<QaThemeRender> theme_renders;
};

}  // namespace pwb::ui_visualqa
