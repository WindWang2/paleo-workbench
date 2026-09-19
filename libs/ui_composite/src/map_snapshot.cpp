#include <pwb/ui_composite/map_snapshot.hpp>

#include <pwb/ui_composite/stage_vocabulary.hpp>

namespace pwb::ui_composite {

// ---------------------------------------------------------------------------
// LayerCapabilitySnapshot
// ---------------------------------------------------------------------------

tool_policy::ToolContextSnapshot LayerCapabilitySnapshot::layer_facts()
    const {
    tool_policy::ToolContextSnapshot ctx;
    ctx.active_layer_id = layer_id.value_or("");
    ctx.active_layer_kind = kind.value_or("");
    ctx.layer_name = name.value_or("");
    ctx.layer_role = role.value_or("");
    ctx.layer_role_label = role_label.value_or("");
    ctx.artifact_maturity = maturity.value_or("");
    ctx.layer_frozen = frozen;
    ctx.layer_missing = missing;
    ctx.layer_degraded = degraded;
    return ctx;
}

// ---------------------------------------------------------------------------
// tool_context_from_ui_snapshot
// ---------------------------------------------------------------------------

tool_policy::ToolContextSnapshot tool_context_from_ui_snapshot(
    const UiContextSnapshot& s) {
    std::string mode;
    if (s.capability_mode.has_value()) {
        mode = *s.capability_mode;
    } else if (s.qgis_bridge_available.has_value()) {
        mode = *s.qgis_bridge_available ? "native" : "unavailable";
    } else {
        mode = "unknown";
    }
    int queryable =
        s.queryable_layer_count.value_or(s.active_layer_id.has_value() &&
                                                 !s.active_layer_id->empty()
                                             ? 1
                                             : 0);

    tool_policy::ToolContextSnapshot ctx;
    ctx.project_open = s.project_open;
    ctx.mapping_stage = s.mapping_stage;
    ctx.backend_mode = mode;
    ctx.backend_reason = s.capability_reason.value_or("");
    ctx.native_canvas_available =
        s.native_canvas_available.value_or(false);
    ctx.capability_flags = s.native_capability_flags;
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
            : (s.active_layer_id.has_value() && !s.active_layer_id->empty()
                   ? "vector"
                   : "");
    if (s.active_layer_editable.has_value())
        ctx.edit_gate_open = *s.active_layer_editable;
    ctx.edit_gate_reason = s.active_layer_block_reason.value_or("");
    ctx.vector_writable =
        s.active_layer_writable.value_or(
            s.active_layer_editable.value_or(false));
    ctx.editing = s.editing_active.value_or(false);
    ctx.dirty = s.editing_dirty.value_or(false);
    ctx.selection_count = s.selection_count.value_or(0);
    ctx.can_undo = s.can_undo.value_or(false);
    ctx.can_redo = s.can_redo.value_or(false);
    ctx.split_ready = s.split_ready.value_or(false);
    ctx.merge_ready = s.merge_ready.value_or(false);
    ctx.reshape_ready = s.reshape_ready.value_or(false);
    ctx.blocking_task = s.blocking_task.value_or("");
    ctx.write_granted = s.write_granted.value_or(false);
    ctx.queryable_layer_count = queryable;
    return ctx;
}

// ---------------------------------------------------------------------------
// evaluate_stage_commands (V11 §7)
// ---------------------------------------------------------------------------

std::map<std::string, std::pair<bool, std::string>>
evaluate_stage_commands(const std::string& stage_value,
                        const UiContextSnapshot& snapshot) {
    const auto actions = stage_context_actions(stage_value);
    std::map<std::string, std::pair<bool, std::string>> availability;
    if (actions.empty()) return availability;
    const bool project_open = snapshot.project_open;
    const auto& mapping_stage = snapshot.mapping_stage;
    for (const auto& [action_id, _title] : actions) {
        if (!project_open) {
            availability[action_id] = {false, "未打开工程"};
            continue;
        }
        // 阶段白名单（palette stages=(stage.value,) 同语义；fail-closed）。
        if (!mapping_stage.has_value()) {
            availability[action_id] = {false, "当前编图阶段未知"};
            continue;
        }
        if (*mapping_stage != stage_value) {
            availability[action_id] = {
                false,
                tool_policy::stage_whitelist_reason({stage_value})};
            continue;
        }
        std::string tool_id = stage_action_tool_id(action_id);
        if (tool_id.empty()) {
            availability[action_id] = {true, ""};
            continue;
        }
        auto verdict = tool_policy::evaluate_tool(
            tool_id, tool_context_from_ui_snapshot(snapshot));
        if (verdict.enabled) {
            availability[action_id] = {true, ""};
        } else {
            availability[action_id] = {
                false,
                verdict.disabled_reason.empty() ? "当前不可用"
                                                : verdict.disabled_reason};
        }
    }
    return availability;
}

}  // namespace pwb::ui_composite
