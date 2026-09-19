#include "pwb/ui_workstation/tool_surface.hpp"

namespace pwb::ui_workstation {

tool_policy::ToolContextSnapshot tool_context_from_ui_snapshot(
    const UIContextSnapshot& s) {
    // capability_mode tri-state; absent -> derive from the boolean bridge
    // probe (Python parity: True->native, False->unavailable,
    // None->unknown).
    std::string mode;
    if (s.capability_mode.has_value()) {
        mode = *s.capability_mode;
    } else if (s.qgis_bridge_available.has_value()) {
        mode = *s.qgis_bridge_available ? "native" : "unavailable";
    } else {
        mode = "unknown";
    }

    tool_policy::ToolContextSnapshot ctx;
    ctx.project_open = s.project_open;
    ctx.mapping_stage = s.mapping_stage;
    ctx.backend_mode = mode;
    ctx.backend_reason = s.capability_reason.value_or("");
    ctx.active_layer_id = s.active_layer_id.value_or("");
    ctx.active_layer_kind = s.active_layer_kind.value_or("");
    ctx.layer_role = s.active_layer_role.value_or("");
    ctx.artifact_maturity = s.active_layer_maturity.value_or("");
    ctx.layer_frozen = s.active_layer_frozen;
    ctx.layer_missing = s.active_layer_missing;
    ctx.layer_degraded = s.active_layer_degraded;
    ctx.qgis_layer_type =
        s.active_layer_is_raster
            ? "raster"
            : (s.active_layer_id.has_value() ? "vector" : "");
    ctx.edit_gate_open = s.active_layer_editable;
    ctx.edit_gate_reason = s.active_layer_block_reason.value_or("");
    ctx.vector_writable = s.active_layer_writable.has_value()
                              ? *s.active_layer_writable
                              : s.active_layer_editable.value_or(false);
    ctx.editing = s.editing_active;
    ctx.dirty = s.editing_dirty.value_or(false);
    ctx.selection_count = s.selection_count.value_or(0);
    ctx.can_undo = s.can_undo.value_or(false);
    ctx.can_redo = s.can_redo.value_or(false);
    ctx.split_ready = s.split_ready.value_or(false);
    ctx.merge_ready = s.merge_ready.value_or(false);
    ctx.reshape_ready = s.reshape_ready.value_or(false);
    ctx.blocking_task = s.blocking_task.value_or("");
    ctx.write_granted = s.write_granted;
    // Provider-absent fallback: an active layer implies at least one
    // queryable layer (execution-side re-gate re-checks the full count;
    // this only keeps the palette from a false disable).
    ctx.queryable_layer_count =
        s.queryable_layer_count.value_or(s.active_layer_id.has_value() ? 1 : 0);
    ctx.native_canvas_available = s.native_canvas_available.value_or(false);
    ctx.capability_flags = s.native_capability_flags;
    return ctx;
}

void apply_layer_facts(const LayerCapabilitySnapshot& layer,
                       tool_policy::ToolContextSnapshot& ctx) {
    ctx.active_layer_id = layer.layer_id.value_or("");
    ctx.active_layer_kind = layer.kind.value_or("");
    ctx.layer_name = layer.name.value_or("");
    ctx.layer_role = layer.role.value_or("");
    ctx.layer_role_label = layer.role_label.value_or("");
    ctx.artifact_maturity = layer.maturity.value_or("");
    ctx.layer_frozen = layer.frozen;
    ctx.layer_missing = layer.missing;
    ctx.layer_degraded = layer.degraded;
}

}  // namespace pwb::ui_workstation
