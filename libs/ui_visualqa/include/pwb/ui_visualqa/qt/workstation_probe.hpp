#pragma once

// UI-16 — the workstation probe seam (qt target).
//
// The V6..V10 drive functions orchestrate a live PaleoWorkbenchWindow
// (app_shell → workstation → composite → stage/edit/action controllers).
// That composition root is the integration slice's domain — the window
// itself is unported. So every Python attribute access the drivers and
// checks make is declared here as an explicit seam: the future C++
// MainWindow adapter binds the real surfaces, the test suite binds a
// fake. Nothing in this library fakes the window.
//
// Method names mirror the Python member paths they replace
// (composite.stage_controller.set_stage → set_mapping_stage,
// composite._on_command_requested → request_command,
// ws._enforce_toolbar_rows → enforce_toolbar_rows, …).

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_visualqa/qa_snapshot.hpp>

namespace pwb::ui_visualqa::qt {

// The docks the drivers show()/raise() — key strings of
// WorkstationSnapshot::docks.
enum class QaDock {
    Stage,           // ws.mapping_stage_dock
    CompositeLayer,  // ws.composite_layer_dock
    Inspector,       // ws.inspector_dock
    Task,            // ws.task_dock
    Agent,           // ws.agent_dock
    Nav,             // ws.nav_dock
    Hub,             // ws.hub_dock
};
const char* qa_dock_key(QaDock dock);

// Cancel checkpoint injected into scheduler task bodies — the Python
// `context.check_cancelled()` parity (throws/signals when cancellation
// was requested).
class QaTaskContext {
public:
    virtual ~QaTaskContext() = default;
    virtual void check_cancelled() = 0;
};

// One edit-session feature insert (VectorFeature parity): GeoJSON
// geometry text + the flat properties map.
struct QaFeatureInsert {
    std::string feature_id;
    std::string geometry_json;   // GeoJSON geometry object text
    std::map<std::string, std::string> properties;
    // session.edit_source("visual_qa") parity; empty = plain add_feature.
    std::string edit_source;
};

// One synthetic QA layer request (the V7 _add_layer helper parity):
// edit_controller.create_layer(name or role.label, kind) +
// stage_controller.state.set_membership(role[, factor_task_id]) +
// edit_controller.set_active_layer + composite._sync_action_state.
struct QaLayerSpec {
    std::string kind;            // "point"|"line"|"polygon"
    std::string role;            // LayerRole value (tool_policy vocab)
    std::string name;            // "" -> host resolves role.label
    std::string factor_task_id;  // membership extra; "" = absent
};

// The probe itself — every method is a Python member path the drivers
// touch. Returning bool means "the underlying surface existed" (the
// Python guard `if session is not None` / getattr(...,None) parity).
class VisualQaProbe {
public:
    virtual ~VisualQaProbe() = default;

    // ---- window / docks -------------------------------------------------
    virtual void show_window() = 0;                    // window.show()
    virtual void resize_window(int w, int h) = 0;      // window.resize
    virtual void show_dock(QaDock dock) = 0;           // dock.show()
    virtual void raise_dock(QaDock dock) = 0;          // dock.raise_()
    // _dock_host.resizeDocks([dock],[px],Horizontal) parity.
    virtual void resize_dock_horizontal(QaDock dock, int px) = 0;
    // dock.resize(dock.width(), px) parity (agent grow-only driver).
    virtual void resize_dock_height(QaDock dock, int px) = 0;

    // ---- stage / composite ----------------------------------------------
    // composite.stage_controller.set_stage(stage_value).
    virtual void set_mapping_stage(const std::string& stage_value) = 0;
    // The _add_layer helper; returns the new layer id ("" = refused).
    virtual std::string add_layer(const QaLayerSpec& spec) = 0;
    // composite.layer_manager.select_layer(layer_id).
    virtual void select_layer(const std::string& layer_id) = 0;
    // composite._on_command_requested(command_id).
    virtual void request_command(const std::string& command_id) = 0;
    // session = layer.edit_session; session.add_feature(...) inside the
    // optional edit_source block. false = no edit session (Python's
    // `if session is not None` guard — caller skips the follow-up sync).
    virtual bool add_edit_feature(const std::string& layer_id,
                                  const QaFeatureInsert& feature) = 0;
    // composite._sync_action_state() / _sync_composition_now().
    virtual void sync_action_state() = 0;
    virtual void sync_composition_now() = 0;
    // stage_controller.state.set_maturity(key, maturity).
    virtual void set_maturity(const std::string& key,
                              const std::string& maturity) = 0;
    // edit_controller.blocking_task_label = label.
    virtual void set_blocking_task_label(const std::string& label) = 0;
    // edit_controller.project_crs = crs.
    virtual void set_project_crs(const std::string& crs) = 0;
    // setattr(layer, "crs", crs) parity (dataclass __setattr__ included).
    virtual void set_layer_crs(const std::string& layer_id,
                               const std::string& crs) = 0;
    // edit_controller._topology.record_validation(layer, error_count).
    virtual void record_topology_validation(const std::string& layer_id,
                                            int error_count) = 0;
    // canvas.native_tool_activation_failed.emit(tool_id, reason) —
    // the V8 fallback-canvas signal surface.
    virtual void emit_native_tool_activation_failed(
        const std::string& tool_id, const std::string& reason) = 0;
    // window._v8_status_log = []; status_message.connect(log.append).
    virtual void begin_status_capture() = 0;
    // window._v10_canvas_menu = composite._build_canvas_menu().
    virtual void build_canvas_menu() = 0;
    // agent._build_write_grant_dialog(action_ids) -> resize(560,480),
    // show(), window._v6_grab_widget = dialog.
    virtual void build_write_grant_dialog(
        const std::vector<std::string>& action_ids) = 0;

    // ---- scheduler (task_cancelling parity) -----------------------------
    // get_scheduler().submit(TaskSpec(title, callable=body)) -> task_id.
    virtual std::string submit_task(
        const std::string& title,
        std::function<void(QaTaskContext&)> body) = 0;
    // get_scheduler().cancel(task_id).
    virtual void cancel_task(const std::string& task_id) = 0;

    // ---- workstation misc ------------------------------------------------
    // ws._enforce_toolbar_rows().
    virtual void enforce_toolbar_rows() = 0;
    // ws._inspect_layer_selection(layer_id).
    virtual void inspect_layer_selection(const std::string& layer_id) = 0;
    // ws.apply_layout_preset(preset_id).
    virtual void apply_layout_preset(const std::string& preset_id) = 0;
    // ws.show_agent() / ws.show_hub_page(title).
    virtual void show_agent() = 0;
    virtual void show_hub_page(const std::string& title) = 0;
    // shell.ui_context_service.refresh().
    virtual void refresh_ui_context() = 0;
    // shell.command_palette.popup() + filter_input.setText(text).
    virtual void popup_palette() = 0;
    virtual void set_palette_filter(const std::string& text) = 0;

    // ---- session scratch bag ---------------------------------------------
    // window._v9_nav_width_before / _v9_agent_height_before parity —
    // plain window attributes the drivers stash and the checks read.
    virtual void set_session_value(const std::string& key, int value) = 0;

    // ---- read -------------------------------------------------------------
    // Collect the full read surface once — the checks' `window` parity.
    virtual WorkstationSnapshot collect() const = 0;
};

}  // namespace pwb::ui_visualqa::qt
