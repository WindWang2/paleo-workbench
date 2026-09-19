#include <pwb/ui_visualqa/qa_checks.hpp>

#include <algorithm>
#include <cmath>
#include <map>
#include <optional>
#include <string>

#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui_visualqa/qa_states.hpp>

namespace pwb::ui_visualqa {

namespace {

// --- small helpers --------------------------------------------------------

const QaActionState& action(const WorkstationSnapshot& s,
                            const std::string& id) {
    static const QaActionState kMissing{};
    const auto it = s.actions.find(id);
    return it != s.actions.end() ? it->second : kMissing;
}

const QaToolVerdict& verdict(const WorkstationSnapshot& s,
                             const std::string& id) {
    static const QaToolVerdict kMissing{};
    const auto it = s.availability.find(id);
    return it != s.availability.end() ? it->second : kMissing;
}

QaDockState dock(const WorkstationSnapshot& s, const std::string& key) {
    const auto it = s.docks.find(key);
    return it != s.docks.end() ? it->second : QaDockState{};
}

bool contains(const std::string& haystack, const std::string& needle) {
    return haystack.find(needle) != std::string::npos;
}

std::string join(const std::vector<std::string>& parts,
                 const std::string& sep) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i) out += sep;
        out += parts[i];
    }
    return out;
}

int session_value(const WorkstationSnapshot& s, const std::string& key,
                  int fallback) {
    const auto it = s.session_values.find(key);
    return it != s.session_values.end() ? it->second : fallback;
}

bool ends_with(const std::string& text, const std::string& suffix) {
    return text.size() >= suffix.size() &&
           text.compare(text.size() - suffix.size(), suffix.size(),
                        suffix) == 0;
}

// UTF-8 codepoint-aware head/tail — Python str[:n] / str[-n:] slice
// parity (byte substr could split a multi-byte sequence into mojibake).
std::size_t utf8_advance(const std::string& s, std::size_t pos,
                       std::size_t codepoints) {
    for (std::size_t i = 0; i < codepoints && pos < s.size(); ++i) {
        const unsigned char c = static_cast<unsigned char>(s[pos]);
        const std::size_t len = c < 0x80   ? 1
                                : c < 0xE0 ? 2
                                : c < 0xF0 ? 3
                                           : 4;
        pos = std::min(s.size(), pos + len);
    }
    return pos;
}
std::string utf8_head(const std::string& s, std::size_t codepoints) {
    return s.substr(0, utf8_advance(s, 0, codepoints));
}
std::string utf8_tail(const std::string& s, std::size_t codepoints) {
    // Walk codepoints from the front, remember the boundary n back.
    std::vector<std::size_t> bounds{0};
    std::size_t pos = 0;
    while (pos < s.size()) {
        pos = utf8_advance(s, pos, 1);
        bounds.push_back(pos);
    }
    const std::size_t start =
        bounds.size() > codepoints ? bounds[bounds.size() - 1 - codepoints]
                                   : 0;
    return s.substr(start);
}

}  // namespace

// ==========================================================================
// V6 — visual_qa_v6.py
// ==========================================================================

// _mapping_stage_checks(target): stage bar marker + stage panel page +
// toolbar stage filtering + stage dock visibility.
std::vector<CheckResult> check_mapping_stage(
    const WorkstationSnapshot& s, const std::string& target_stage_value) {
    using pwb::tool_policy::MappingStage;
    const std::optional<MappingStage> target =
        pwb::tool_policy::stage_from_value(target_stage_value);

    std::vector<CheckResult> results;
    // 1. Stage bar: target stage button checked, the others unchecked.
    for (const MappingStage stage : pwb::tool_policy::kStageOrder) {
        const std::string value =
            pwb::tool_policy::stage_value(stage);
        const auto it = s.stage_marker_checked.find(value);
        const bool present = it != s.stage_marker_checked.end();
        const bool checked = present && it->second;
        const bool want = target.has_value() && stage == *target;
        results.push_back(make_check(
            "stage_bar_marker[" + value + "]", present && checked == want,
            "checked=" + std::string(present ? (checked ? "true" : "false")
                                            : "None") +
                " want=" + (want ? "true" : "false")));
    }
    // 2. Stage panel: stack current page is the target stage page.
    results.push_back(make_check(
        "stage_panel_current_page", s.stage_panel_shows_target,
        std::string("shows_target=") +
            (s.stage_panel_shows_target ? "true" : "false")));
    // 3. Toolbar stage filter: add_line visible only in stages 2/3;
    //    add_polygon visible in all three.
    const QaActionState& add_line = action(s, "add_line");
    const QaActionState& add_polygon = action(s, "add_polygon");
    const bool line_want =
        target.has_value() &&
        (*target == MappingStage::ConstraintFactor ||
         *target == MappingStage::IntegratedCompilation);
    results.push_back(make_check(
        "toolbar_add_line_stage_visibility",
        add_line.exists && add_line.visible == line_want,
        "visible=" + std::string(add_line.exists
                                     ? (add_line.visible ? "true" : "false")
                                     : "None") +
            " want=" + (line_want ? "true" : "false")));
    results.push_back(make_check(
        "toolbar_add_polygon_always_visible",
        add_polygon.exists && add_polygon.visible,
        "visible=" + std::string(add_polygon.exists
                                     ? (add_polygon.visible ? "true"
                                                            : "false")
                                     : "None")));
    // 4. Stage panel dock visible (the shot subject is on screen).
    results.push_back(make_check(
        "stage_dock_visible", !dock(s, "stage").hidden, ""));
    return results;
}

std::vector<CheckResult> check_command_palette_context(
    const WorkstationSnapshot& s) {
    std::vector<CheckResult> results;
    results.push_back(make_check("palette_open", s.palette_present &&
                                                     !s.palette_hidden,
                                 ""));
    int disabled_count = 0;
    bool reason_ok = false;
    bool stage_scoped = false;
    bool filter_hit = false;
    for (const QaPaletteItem& item : s.palette_items) {
        if (!item.enabled) {
            ++disabled_count;
            if (contains(item.text, "不允许") ||
                contains(item.text, "不可用")) {
                reason_ok = true;
            }
            if (item.stage_scoped) {
                stage_scoped = true;
            }
        }
        if (contains(item.text, "单因素")) {
            filter_hit = true;
        }
    }
    results.push_back(make_check(
        "palette_has_disabled_stage_command", disabled_count > 0,
        "disabled=" + std::to_string(disabled_count)));
    results.push_back(make_check("disabled_item_shows_reason", reason_ok, ""));
    results.push_back(
        make_check("disabled_item_is_stage_scoped", stage_scoped, ""));
    results.push_back(make_check(
        "palette_filter_matched", filter_hit,
        "rows=" + std::to_string(s.palette_items.size())));
    return results;
}

std::vector<CheckResult> check_write_grant_dialog(
    const WorkstationSnapshot& s) {
    const QaDialogSnapshot& d = s.grab_dialog;
    if (!d.present) {
        return {make_check("dialog_constructed", false,
                           "no _v6_grab_widget")};
    }
    std::vector<CheckResult> results;
    results.push_back(make_check(
        "dialog_constructed",
        d.object_name == "WriteGrantDialog" && !d.hidden, d.object_name));
    results.push_back(make_check(
        "deny_button_is_default", d.deny_present && d.deny_default,
        "default=" + std::string(d.deny_default ? "true" : "false")));
    results.push_back(make_check(
        "deny_button_labelled", d.deny_present && d.deny_text == "拒绝",
        d.deny_text));
    results.push_back(make_check(
        "grant_button_labelled", d.grant_present && d.grant_text == "授权",
        d.grant_text));
    // Uninteracted: granted must be exactly False (no pre-authorization).
    results.push_back(make_check(
        "dialog_not_pre_granted",
        d.granted.has_value() && !*d.granted,
        d.granted.has_value() ? (*d.granted ? "True" : "False") : "None"));
    for (const std::string& action_id : write_grant_action_ids()) {
        bool found = false;
        for (const std::string& text : d.label_texts) {
            if (contains(text, action_id)) {
                found = true;
                break;
            }
        }
        results.push_back(
            make_check("action_card[" + action_id + "]", found, ""));
    }
    bool unknown_fallback = false;
    for (const std::string& text : d.label_texts) {
        if (contains(text, "注册表中无此动作")) {
            unknown_fallback = true;
            break;
        }
    }
    results.push_back(
        make_check("no_unknown_action_fallback", !unknown_fallback, ""));
    return results;
}

std::vector<CheckResult> check_status_workbench_segment(
    const WorkstationSnapshot& s) {
    using pwb::tool_policy::MappingStage;
    const std::string& text = s.workbench_label_text;
    const char* label =
        pwb::tool_policy::stage_label(MappingStage::ConstraintFactor);
    const char* short_label =
        pwb::tool_policy::stage_short_label(MappingStage::ConstraintFactor);
    bool blank = true;
    for (char c : text) {
        if (c != ' ' && c != '\t' && c != '\n' && c != '\r') {
            blank = false;
            break;
        }
    }
    return {
        make_check("segment_label_non_empty", !blank, "'" + text + "'"),
        make_check("segment_shows_backend_state", contains(text, "QGIS"),
                   "'" + text + "'"),
        make_check("segment_shows_mapping_stage",
                   contains(text, label) || contains(text, short_label),
                   "'" + text + "'"),
        make_check("segment_visible", !s.workbench_label_hidden, ""),
    };
}

// ==========================================================================
// V7 — visual_qa_v7.py
// ==========================================================================

std::vector<CheckResult> check_phase1_raw_blocked(
    const WorkstationSnapshot& s) {
    const QaActionState& toggle = action(s, "toggle_editing");
    const QaActionState& add_polygon = action(s, "add_polygon");
    return {
        make_check("raw_toggle_editing_disabled",
                   toggle.exists && !toggle.enabled),
        make_check("raw_reason_in_status_tip",
                   toggle.exists && contains(toggle.status_tip, "RAW"),
                   toggle.status_tip),
        make_check("raw_capture_disabled",
                   add_polygon.exists && !add_polygon.enabled),
        make_check("raw_view_tools_enabled",
                   verdict(s, "layer_properties").enabled),
    };
}

std::vector<CheckResult> check_phase1_editing_session(
    const WorkstationSnapshot& s) {
    const QaActionState& toggle = action(s, "toggle_editing");
    const QaActionState& save = action(s, "save_edits");
    const QaActionState& add_polygon = action(s, "add_polygon");
    const bool session_text = contains(s.tree_status_joined, "编辑中") ||
                              contains(s.tree_status_joined, "未保存");
    return {
        make_check("editing_toggle_checked",
                   toggle.exists && toggle.checked),
        make_check("editing_save_enabled", save.exists && save.enabled),
        make_check("editing_capture_enabled",
                   add_polygon.exists && add_polygon.enabled),
        make_check("editing_tree_shows_session", session_text,
                   s.tree_status_joined),
    };
}

std::vector<CheckResult> check_phase2_constraint_line(
    const WorkstationSnapshot& s) {
    const QaActionState& add_line = action(s, "add_line");
    const QaActionState& add_polygon = action(s, "add_polygon");
    return {
        make_check("line_add_line_enabled",
                   add_line.exists && add_line.enabled),
        make_check("line_add_polygon_disabled",
                   add_polygon.exists && !add_polygon.enabled),
        make_check("line_kind_reason",
                   add_polygon.exists &&
                       (contains(add_polygon.status_tip, "线") ||
                        contains(add_polygon.status_tip, "面")),
                   add_polygon.status_tip),
    };
}

std::vector<CheckResult> check_phase2_factor_raster(
    const WorkstationSnapshot& s) {
    const QaActionState& toggle = action(s, "toggle_editing");
    return {
        make_check("factor_vector_edit_disabled",
                   toggle.exists && !toggle.enabled),
        make_check("factor_raw_reason",
                   toggle.exists && contains(toggle.status_tip, "RAW"),
                   toggle.status_tip),
        make_check("factor_view_tools_enabled",
                   verdict(s, "layer_properties").enabled &&
                       verdict(s, "symbology").enabled &&
                       verdict(s, "layer_export").enabled),
    };
}

std::vector<CheckResult> check_layer_tree_decorations(
    const WorkstationSnapshot& s) {
    return {
        make_check("tree_status_column_has_frozen",
                   contains(s.tree_status_joined, "冻结"),
                   s.tree_status_joined),
        make_check("tree_status_column_has_glyph",
                   contains(s.tree_status_joined, "❄"),
                   s.tree_status_joined),
    };
}

std::vector<CheckResult> check_task_cancelling(
    const WorkstationSnapshot& s) {
    // V9 vocabulary: 取消中 = CANCELLING (explicit) or
    // RUNNING+cancel_requested (claim-window race) — both are the honest
    // "cancel pending" presentation window.
    int cancelling = 0;
    for (const QaTaskHandle& h : s.task_handles) {
        if (h.cancel_requested &&
            (h.state == "running" || h.state == "cancelling")) {
            ++cancelling;
        }
    }
    return {
        make_check("task_cancel_pending", cancelling > 0,
                   std::to_string(s.task_handles.size()) + " tasks"),
        make_check("task_dock_visible", !dock(s, "task").hidden),
    };
}

std::vector<CheckResult> check_toolbar_overflow_narrow(
    const WorkstationSnapshot& s) {
    const QaActionState& add_polygon = action(s, "add_polygon");
    const QaActionState& toggle = action(s, "toggle_editing");
    return {
        make_check("toolbar_row2_top", s.map_top_in_top_area),
        make_check("toolbar_row2_bottom", s.map_bottom_in_top_area),
        make_check("toolbar_no_overlay",
                   s.overflow_toolbar_children == 0),
        make_check("overflow_core_visible",
                   add_polygon.exists && add_polygon.visible &&
                       toggle.exists && toggle.visible),
    };
}

std::vector<CheckResult> check_inspector_factor(
    const WorkstationSnapshot& s) {
    return {make_check("inspector_shows_factor_section",
                       contains(s.inspector_header, "单因素"),
                       s.inspector_header)};
}

// ==========================================================================
// V8 — visual_qa_v8.py
// ==========================================================================

std::vector<CheckResult> check_empty_project_tool_surface(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& toggle = verdict(s, "toggle_editing");
    return {
        make_check("empty_pan_enabled", verdict(s, "pan").enabled),
        make_check("empty_layer_new_enabled",
                   verdict(s, "layer_new").enabled),
        make_check("empty_toggle_disabled_with_reason",
                   !toggle.enabled &&
                       contains(toggle.disabled_reason, "图层"),
                   toggle.disabled_reason),
        make_check("empty_cancel_enabled", verdict(s, "cancel").enabled),
        make_check("empty_hint_visible", s.empty_hint_visible),
    };
}

std::vector<CheckResult> check_derived_polygon_editing_dirty(
    const WorkstationSnapshot& s) {
    const QaActionState& toggle = action(s, "toggle_editing");
    const QaToolVerdict& save = verdict(s, "save_edits");
    return {
        make_check("dirty_save_enabled", save.enabled),
        make_check("dirty_rollback_enabled", verdict(s, "rollback").enabled),
        make_check("dirty_undo_enabled", verdict(s, "undo").enabled),
        make_check("dirty_save_reason_cleared",
                   !contains(save.disabled_reason, "未保存"),
                   save.disabled_reason),
        make_check("dirty_toggle_checked",
                   toggle.exists && toggle.checked),
    };
}

std::vector<CheckResult> check_frozen_map_product(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& toggle = verdict(s, "toggle_editing");
    return {
        make_check("frozen_toggle_disabled", !toggle.enabled),
        make_check("frozen_reason_authoritative",
                   contains(toggle.disabled_reason, "冻结"),
                   toggle.disabled_reason),
        make_check("frozen_view_tools_enabled",
                   verdict(s, "layer_properties").enabled &&
                       verdict(s, "layer_export").enabled),
        make_check("frozen_capture_disabled",
                   !verdict(s, "add_polygon").enabled),
    };
}

std::vector<CheckResult> check_palette_disabled_reason(
    const WorkstationSnapshot& s) {
    std::vector<std::string> texts;
    texts.reserve(s.palette_items.size());
    for (const QaPaletteItem& item : s.palette_items) {
        texts.push_back(item.text);
    }
    const std::string joined = join(texts, "\n");
    const std::string preview = utf8_head(joined, 200);
    const QaToolVerdict& map_export = verdict(s, "map_export");
    return {
        make_check("palette_has_map_entries",
                   contains(joined, "编图 ·"), preview),
        make_check("palette_map_export_stage_gated",
                   !contains(joined, "导出图面") ||
                       contains(joined, "不可用") ||
                       contains(joined, "（"),
                   preview),
        make_check("palette_reason_source_is_evaluator",
                   !map_export.disabled_reason.empty(),
                   map_export.disabled_reason),
    };
}

std::vector<CheckResult> check_native_activation_failure_revert(
    const WorkstationSnapshot& s) {
    const QaActionState& pan = action(s, "pan");
    const QaActionState& add_polygon = action(s, "add_polygon");
    bool emitted = false;
    for (const std::string& msg : s.status_messages) {
        if (contains(msg, "激活失败")) {
            emitted = true;
            break;
        }
    }
    std::string log_preview;
    for (std::size_t i = 0;
         i < s.status_messages.size() && i < 3; ++i) {
        if (i) log_preview += ", ";
        log_preview += s.status_messages[i];
    }
    return {
        make_check("revert_pan_checked", pan.exists && pan.checked),
        make_check("revert_add_polygon_unchecked",
                   add_polygon.exists && !add_polygon.checked),
        make_check("revert_status_reason_emitted", emitted,
                   "[" + log_preview + "]"),
    };
}

std::vector<CheckResult> check_blocking_task_tool_surface(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& toggle = verdict(s, "toggle_editing");
    const QaToolVerdict& pan = verdict(s, "pan");
    return {
        make_check("blocking_toggle_disabled", !toggle.enabled),
        make_check("blocking_pan_disabled", !pan.enabled),
        make_check("blocking_reason",
                   pan.disabled_reason.rfind("后台任务进行中", 0) == 0,
                   pan.disabled_reason),
        make_check("blocking_cancel_enabled",
                   verdict(s, "cancel").enabled),
    };
}

// ==========================================================================
// V9 — visual_qa_v9.py
// ==========================================================================

std::vector<CheckResult> check_compact_viewport(
    const WorkstationSnapshot& s) {
    return {
        make_check("compact_inspector_folded",
                   dock(s, "inspector").hidden),
        make_check("compact_inspector_flagged_responsive",
                   s.responsive_hid_inspector && !s.user_hid_inspector),
        make_check("compact_command_floor_220",
                   s.command_input_min_width <= 220),
        make_check("compact_stage_label_hidden", !s.stage_label_visible),
        make_check("compact_nav_visible", !dock(s, "nav").hidden),
        make_check("compact_canvas_floor_kept", s.composite_width >= 300,
                   "canvas=" + std::to_string(s.composite_width)),
    };
}

std::vector<CheckResult> check_wide_viewport(const WorkstationSnapshot& s) {
    return {
        make_check("wide_inspector_visible",
                   !dock(s, "inspector").hidden),
        make_check("wide_command_floor_300",
                   s.command_input_min_width >= 300),
        make_check("wide_stage_label_visible", s.stage_label_visible),
        make_check("wide_canvas_roomy", s.composite_width >= 800,
                   "canvas=" + std::to_string(s.composite_width)),
    };
}

std::vector<CheckResult> check_ultrawide_viewport(
    const WorkstationSnapshot& s) {
    const bool visible = !dock(s, "nav").hidden &&
                         !dock(s, "inspector").hidden &&
                         !dock(s, "composite_layer").hidden;
    return {
        make_check("ultrawide_core_docks_visible", visible),
        make_check("ultrawide_no_responsive_fold",
                   !s.responsive_hid_inspector),
        make_check("ultrawide_canvas_roomy", s.composite_width >= 1400,
                   "canvas=" + std::to_string(s.composite_width)),
    };
}

std::vector<CheckResult> check_narrow_hub_page(
    const WorkstationSnapshot& s) {
    return {
        make_check("narrow_hub_dock_open", !dock(s, "hub").hidden),
        make_check("narrow_hub_scroll_host_small_min",
                   s.hub_scroll_min_width <= 80,
                   "min=" + std::to_string(s.hub_scroll_min_width)),
        make_check("narrow_hub_dock_resizable_below_page_min",
                   dock(s, "hub").min_size_hint_width <= 80,
                   "min=" +
                       std::to_string(dock(s, "hub").min_size_hint_width)),
        make_check("narrow_canvas_floor_kept", s.composite_width >= 300,
                   "canvas=" + std::to_string(s.composite_width)),
        make_check("narrow_window_min_960", s.window_min_width <= 960),
    };
}

std::vector<CheckResult> check_preset_visibility_only(
    const WorkstationSnapshot& s) {
    const int before = session_value(s, "v9_nav_width_before", 0);
    const int after = dock(s, "nav").width;
    const bool preserved = before > 0 && std::abs(after - before) <= 40;
    return {
        make_check("preset_kept_user_nav_width", preserved,
                   "before=" + std::to_string(before) +
                       " after=" + std::to_string(after)),
        make_check("preset_applied_flag", s.current_preset_id == "review",
                   s.current_preset_id),
    };
}

std::vector<CheckResult> check_agent_grow_only(
    const WorkstationSnapshot& s) {
    const int before = session_value(s, "v9_agent_height_before", 0);
    const int after = dock(s, "agent").height;
    const bool kept = before > 0 && after >= std::min(before, 380);
    return {
        make_check("agent_row_not_snapped_back", kept,
                   "before=" + std::to_string(before) +
                       " after=" + std::to_string(after)),
        make_check("agent_dock_visible", !dock(s, "agent").hidden),
    };
}

// ==========================================================================
// V10 — visual_qa_v10.py
// ==========================================================================

std::vector<CheckResult> check_raw_layer_readonly_surface(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& toggle = verdict(s, "toggle_editing");
    return {
        make_check("raw_toggle_disabled", !toggle.enabled),
        make_check("raw_reason_from_gate",
                   contains(toggle.disabled_reason, "RAW"),
                   toggle.disabled_reason),
        make_check("raw_status_chip_text",
                   s.edit_chip_text == "RAW · 只读", s.edit_chip_text),
        make_check("raw_capture_disabled",
                   !verdict(s, "add_polygon").enabled),
        make_check("raw_view_tools_enabled",
                   verdict(s, "layer_properties").enabled),
    };
}

std::vector<CheckResult> check_capture_preferred_line_role(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& add_line = verdict(s, "add_line");
    const QaToolVerdict& add_polygon = verdict(s, "add_polygon");
    const QaActionState& add_line_action = action(s, "add_line");
    return {
        make_check("line_role_add_line_preferred",
                   add_line.enabled && add_line.preferred),
        make_check("line_role_add_polygon_role_blocked",
                   !add_polygon.enabled, add_polygon.disabled_reason),
        make_check("preferred_button_property",
                   s.preferred_button_present &&
                       s.preferred_button_property,
                   s.preferred_button_present
                       ? (s.preferred_button_property ? "true" : "false")
                       : "None"),
        make_check("capture_tooltip_target_block",
                   add_line_action.exists &&
                       contains(add_line_action.tool_tip, "当前编辑目标"),
                   utf8_tail(add_line_action.tool_tip, 120)),
    };
}

std::vector<CheckResult> check_editing_dirty_chip(
    const WorkstationSnapshot& s) {
    return {
        make_check("dirty_chip_modified_text",
                   contains(s.edit_chip_text, "未保存"), s.edit_chip_text),
        make_check("dirty_chip_not_color_only",
                   contains(s.edit_chip_text, "编辑") &&
                       contains(s.edit_chip_text, "●"),
                   s.edit_chip_text),
        make_check("dirty_save_enabled", verdict(s, "save_edits").enabled),
    };
}

std::vector<CheckResult> check_snapping_detail_surface(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& snapping = verdict(s, "snapping");
    const QaActionState& snapping_action = action(s, "snapping");
    return {
        make_check("snapping_readout_on",
                   s.snapping_text == "捕捉: 开", s.snapping_text),
        make_check("snapping_tooltip_detail",
                   contains(s.snapping_tooltip, "容差"),
                   utf8_head(s.snapping_tooltip, 120)),
        make_check("snapping_evaluator_checked",
                   snapping.enabled && snapping.checked),
        make_check("snapping_tool_tooltip_config",
                   snapping_action.exists &&
                       contains(snapping_action.tool_tip, "捕捉设置"),
                   utf8_tail(snapping_action.tool_tip, 120)),
    };
}

std::vector<CheckResult> check_topology_error_chip(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& merge = verdict(s, "merge");
    return {
        make_check("topology_chip_visible", !s.topology_chip_hidden),
        make_check("topology_chip_count",
                   contains(s.topology_chip_text, "3") &&
                       contains(s.topology_chip_text, "拓扑"),
                   s.topology_chip_text),
        make_check("topology_chip_not_color_only",
                   contains(s.topology_chip_text, "⚠"),
                   s.topology_chip_text),
        make_check("topology_merge_blocked",
                   !merge.enabled &&
                       contains(merge.disabled_reason, "拓扑"),
                   merge.disabled_reason),
    };
}

std::vector<CheckResult> check_crs_undeclared_surface(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& topology = verdict(s, "topology");
    return {
        make_check("crs_honest_undeclared",
                   s.crs_text == "CRS: 未声明", s.crs_text),
        make_check("crs_topology_gated", !topology.enabled,
                   topology.disabled_reason),
    };
}

std::vector<CheckResult> check_crs_mismatch_warning(
    const WorkstationSnapshot& s) {
    // "4326" must not leak outside the layer CRS itself (no fake project
    // CRS): text.replace("EPSG:32650", "") parity.
    std::string scrubbed = s.crs_text;
    const std::string token = "EPSG:32650";
    std::size_t pos = 0;
    while ((pos = scrubbed.find(token, pos)) != std::string::npos) {
        scrubbed.erase(pos, token.size());
    }
    return {
        make_check("crs_mismatch_warn_glyph",
                   s.crs_text.rfind("⚠", 0) == 0, s.crs_text),
        make_check("crs_mismatch_tooltip_explains",
                   contains(s.crs_tooltip, "不一致"),
                   utf8_head(s.crs_tooltip, 160)),
        make_check("crs_mismatch_no_fake_crs",
                   !contains(scrubbed, "4326"), s.crs_text),
    };
}

std::vector<CheckResult> check_frozen_layer_surface(
    const WorkstationSnapshot& s) {
    const QaToolVerdict& toggle = verdict(s, "toggle_editing");
    return {
        make_check("frozen_chip_text", s.edit_chip_text == "已冻结",
                   s.edit_chip_text),
        make_check("frozen_toggle_disabled", !toggle.enabled),
        make_check("frozen_reason_authoritative",
                   contains(toggle.disabled_reason, "冻结"),
                   toggle.disabled_reason),
    };
}

std::vector<CheckResult> check_canvas_context_menu_surface(
    const WorkstationSnapshot& s) {
    if (!s.canvas_menu_present) {
        return {make_check("canvas_menu_built", false, "menu missing")};
    }
    bool has_view_group = false;
    bool has_capture_config = false;
    bool consistent = true;
    bool add_line_enabled_or_absent = true;
    std::vector<std::string> mapped_ids;
    for (const QaMenuAction& item : s.canvas_menu_actions) {
        if (contains(item.text, "全图")) has_view_group = true;
        if (contains(item.text, "捕捉设置")) has_capture_config = true;
        if (!item.tool_id.empty()) {
            mapped_ids.push_back(item.tool_id);
            const QaToolVerdict& v = verdict(s, item.tool_id);
            if (item.enabled != v.enabled) {
                consistent = false;
            }
            if (item.tool_id == "add_line" && !item.enabled) {
                add_line_enabled_or_absent = false;
            }
        }
    }
    std::sort(mapped_ids.begin(), mapped_ids.end());
    return {
        make_check("canvas_menu_has_view_group", has_view_group),
        make_check("canvas_menu_has_capture_config", has_capture_config),
        make_check("canvas_menu_evaluator_consistent", consistent,
                   join(mapped_ids, ",")),
        make_check("canvas_menu_add_line_enabled",
                   add_line_enabled_or_absent),
    };
}

std::vector<CheckResult> check_compact_1366_toolbar_identity(
    const WorkstationSnapshot& s) {
    const bool identity = action(s, "pan").exists &&
                          action(s, "add_line").exists &&
                          action(s, "save_edits").exists;
    bool consistent = true;
    for (const char* id :
         {"pan", "add_line", "toggle_editing", "snapping"}) {
        const QaActionState& a = action(s, id);
        const QaToolVerdict& v = verdict(s, id);
        // Overflow collapse is a Qt presentation behavior; the action's
        // enable verdict must not drift while visible.
        if (a.visible && a.enabled != v.enabled) {
            consistent = false;
        }
    }
    return {
        make_check("compact_actions_identity_kept", identity),
        make_check("compact_verdict_consistency", consistent),
        make_check("compact_window_size", s.window_width <= 1366 + 1,
                   std::to_string(s.window_width) + "x" +
                       std::to_string(s.window_height)),
        make_check("compact_canvas_present", s.canvas_width > 0),
    };
}

// ==========================================================================
// Dispatch — V6..V10 _CHECK_TABLE parity
// ==========================================================================

std::vector<CheckResult> run_state_checks(
    const std::string& state, const WorkstationSnapshot& s) {
    using pwb::tool_policy::MappingStage;
    // Fail-closed: an unbound probe reports one honest failure instead of
    // N verdicts on default values (Python would raise on the window's
    // missing attributes → the gate errors the same way).
    if (!s.bound) {
        return {make_check("workstation_surface_bound", false,
                           "probe could not reach a workstation window")};
    }
    // V6
    if (state == "mapping_stage_phase1")
        return check_mapping_stage(
            s, pwb::tool_policy::stage_value(MappingStage::FaciesCalibration));
    if (state == "mapping_stage_phase2")
        return check_mapping_stage(
            s, pwb::tool_policy::stage_value(MappingStage::ConstraintFactor));
    if (state == "mapping_stage_phase3")
        return check_mapping_stage(
            s, pwb::tool_policy::stage_value(
                   MappingStage::IntegratedCompilation));
    if (state == "command_palette_context")
        return check_command_palette_context(s);
    if (state == "write_grant_dialog")
        return check_write_grant_dialog(s);
    if (state == "status_workbench_segment")
        return check_status_workbench_segment(s);
    // V7
    if (state == "phase1_raw_blocked") return check_phase1_raw_blocked(s);
    if (state == "phase1_editing_session")
        return check_phase1_editing_session(s);
    if (state == "phase2_constraint_line")
        return check_phase2_constraint_line(s);
    if (state == "phase2_factor_raster")
        return check_phase2_factor_raster(s);
    if (state == "layer_tree_decorations")
        return check_layer_tree_decorations(s);
    if (state == "task_cancelling") return check_task_cancelling(s);
    if (state == "toolbar_overflow_narrow")
        return check_toolbar_overflow_narrow(s);
    if (state == "inspector_factor") return check_inspector_factor(s);
    // V8
    if (state == "empty_project_tool_surface")
        return check_empty_project_tool_surface(s);
    if (state == "derived_polygon_editing_dirty")
        return check_derived_polygon_editing_dirty(s);
    if (state == "frozen_map_product") return check_frozen_map_product(s);
    if (state == "palette_disabled_reason")
        return check_palette_disabled_reason(s);
    if (state == "native_activation_failure_revert")
        return check_native_activation_failure_revert(s);
    if (state == "blocking_task_tool_surface")
        return check_blocking_task_tool_surface(s);
    // V9
    if (state == "compact_viewport") return check_compact_viewport(s);
    if (state == "wide_viewport") return check_wide_viewport(s);
    if (state == "ultrawide_viewport") return check_ultrawide_viewport(s);
    if (state == "narrow_hub_page") return check_narrow_hub_page(s);
    if (state == "preset_visibility_only")
        return check_preset_visibility_only(s);
    if (state == "agent_grow_only") return check_agent_grow_only(s);
    // V10
    if (state == "raw_layer_readonly_surface")
        return check_raw_layer_readonly_surface(s);
    if (state == "capture_preferred_line_role")
        return check_capture_preferred_line_role(s);
    if (state == "editing_dirty_chip") return check_editing_dirty_chip(s);
    if (state == "snapping_detail_surface")
        return check_snapping_detail_surface(s);
    if (state == "topology_error_chip") return check_topology_error_chip(s);
    if (state == "crs_undeclared_surface")
        return check_crs_undeclared_surface(s);
    if (state == "crs_mismatch_warning")
        return check_crs_mismatch_warning(s);
    if (state == "frozen_layer_surface") return check_frozen_layer_surface(s);
    if (state == "canvas_context_menu_surface")
        return check_canvas_context_menu_surface(s);
    if (state == "compact_1366_toolbar_identity")
        return check_compact_1366_toolbar_identity(s);
    return {};
}

// ==========================================================================
// V11 — visual_qa_v11.py scenario checks
// ==========================================================================

std::vector<CheckResult> check_first_open(const QaShellSnapshot& s) {
    return {
        make_check("shell_workstation_present", s.workstation_present),
        make_check("first_open_inspector_project_context",
                   s.inspector_header.rfind("检查器 · 工程", 0) == 0,
                   s.inspector_header),
        make_check("first_open_no_object_selected",
                   s.inspector_current_is_project,
                   std::string("current_is_project=") +
                       (s.inspector_current_is_project ? "true" : "false")),
        make_check("first_open_task_center_empty", s.task_center_rows == 0,
                   "rows=" + std::to_string(s.task_center_rows)),
        make_check("first_open_no_wells_no_resources",
                   s.project_wells == 0 && s.project_resources == 0),
    };
}

std::vector<CheckResult> check_data_manager(
    const QaDataManagerSnapshot& s) {
    return {
        make_check("asset_table_row_count",
                   s.asset_rows == s.resource_count,
                   "rows=" + std::to_string(s.asset_rows) +
                       " want=" + std::to_string(s.resource_count)),
        make_check("inspector_shows_selected_asset",
                   contains(s.inspector_title, "A12.las"),
                   s.inspector_title),
        make_check("inspector_empty_label_hidden",
                   s.inspector_empty_hidden),
        make_check("inspector_tabs_visible", !s.inspector_tabs_hidden),
    };
}

std::vector<CheckResult> check_task_panel(const QaTaskPanelSnapshot& s) {
    if (!s.panel_found) {
        return {make_check("task_panel_found", false,
                           "PredictionTaskPanel missing")};
    }
    bool pending = false, running = false, complete = false;
    for (const std::string& t : s.row_texts) {
        if (contains(t, "排队中")) pending = true;
        if (contains(t, "运行中")) running = true;
        if (contains(t, "完成")) complete = true;
    }
    return {
        make_check("task_panel_row_count", s.row_texts.size() == 3,
                   "rows=" + std::to_string(s.row_texts.size())),
        make_check("task_panel_pending_rendered", pending,
                   join(s.row_texts, "|")),
        make_check("task_panel_running_rendered", running,
                   join(s.row_texts, "|")),
        make_check("task_panel_complete_rendered", complete,
                   join(s.row_texts, "|")),
        make_check("task_panel_active_status_badge",
                   s.status_badge_text == "运行中", s.status_badge_text),
        make_check("task_panel_status_badge_tone",
                   s.status_badge_tone == "primary" ||
                       s.status_badge_tone == "warning",
                   s.status_badge_tone),
    };
}

std::vector<CheckResult> check_seismic_context(
    const QaSeismicContextSnapshot& s) {
    if (!s.toolbar_found) {
        return {make_check("seismic_toolbar_found", false,
                           "toolbar missing")};
    }
    return {
        make_check("seismic_source_selected",
                   s.source_text == "HZ26_3D_full.sgy", s.source_text),
        make_check("seismic_attribute_synced",
                   s.attribute_text == "RMS振幅", s.attribute_text),
        make_check("seismic_settings_details",
                   s.horizon_text == "D63" &&
                       s.task_text == "振幅属性提取 · HZ26" &&
                       s.shape_text == "301 × 401 × 1201",
                   "horizon=" + s.horizon_text + " task=" + s.task_text +
                       " shape=" + s.shape_text),
        make_check("seismic_status_readout",
                   s.status_text == "运行中 · 第 4/9 属性",
                   s.status_text),
    };
}

std::vector<CheckResult> check_stage_surface(
    const QaStageSurfaceSnapshot& s,
    const std::string& target_stage_value) {
    using pwb::tool_policy::MappingStage;
    const std::optional<MappingStage> target =
        pwb::tool_policy::stage_from_value(target_stage_value);
    bool marker_ok = true;
    for (const MappingStage stage : pwb::tool_policy::kStageOrder) {
        const auto it =
            s.stage_marker_checked.find(pwb::tool_policy::stage_value(stage));
        const bool checked = it != s.stage_marker_checked.end() && it->second;
        const bool want = target.has_value() && stage == *target;
        if (checked != want) {
            marker_ok = false;
        }
    }
    return {
        make_check("stage_bar_marker[" + target_stage_value + "]",
                   marker_ok),
        make_check("stage_panel_current_page", s.stage_panel_shows_target),
        make_check("stage_horizon_selected", s.current_horizon == "D63",
                   s.current_horizon),
        make_check("stage_constraints_row_visibility",
                   s.constraints_row_visible ==
                       (target_stage_value == "constraint_factor")),
    };
}

std::vector<CheckResult> check_inspector_version(
    const QaInspectorSnapshot& s) {
    auto any_of = [&s](const char* needle) {
        for (const std::string& v : s.property_values) {
            if (contains(v, needle)) return true;
        }
        return false;
    };
    auto any_exact = [&s](const std::string& want) {
        for (const std::string& v : s.property_values) {
            if (v == want) return true;
        }
        return false;
    };
    return {
        make_check("inspector_version_header",
                   contains(s.header, "版本"), s.header),
        make_check("inspector_version_number_row", any_of("v3"),
                   join(s.property_values, "|")),
        make_check("inspector_version_run_row",
                   any_exact("run_compile_0451"),
                   join(s.property_values, "|")),
        make_check("inspector_version_parents_row", any_of("1 项"),
                   join(s.property_values, "|")),
        make_check("inspector_version_checksum_abbreviated", any_of("…"),
                   join(s.property_values, "|")),
    };
}

std::vector<CheckResult> check_inspector_run(const QaInspectorSnapshot& s) {
    auto any_of = [](const std::vector<std::string>& values,
                     const char* needle) {
        for (const std::string& v : values) {
            if (contains(v, needle)) return true;
        }
        return false;
    };
    return {
        make_check("inspector_run_header", contains(s.header, "Run"),
                   s.header),
        make_check("inspector_run_id_row",
                   any_of(s.property_values, "run_compile_0451"),
                   join(s.property_values, "|")),
        make_check("inspector_run_io_rows",
                   any_of(s.property_values, "3 项") &&
                       any_of(s.property_values, "1 项"),
                   join(s.property_values, "|")),
        make_check("inspector_run_state_token",
                   any_of(s.property_values, "失败") ||
                       any_of(s.property_values, "降级"),
                   join(s.property_values, "|")),
        make_check("inspector_run_model_row",
                   any_of(s.interpretation_values, "ConstrainedIDW"),
                   join(s.interpretation_values, "|")),
    };
}

std::vector<CheckResult> check_task_center(const QaTaskCenterSnapshot& s) {
    return {
        make_check("task_center_registry_rows_present",
                   s.running_present && s.finished_present,
                   "rows=" + join(s.row_ids, ",")),
        make_check("task_center_running_state_text",
                   contains(s.running_state_text, "运行中"),
                   s.running_state_text),
        make_check("task_center_running_progress",
                   s.running_progress.has_value() &&
                       std::abs(*s.running_progress - 0.42) < 1e-6,
                   "progress=" +
                       (s.running_progress.has_value()
                            ? std::to_string(*s.running_progress)
                            : std::string("None"))),
        make_check("task_center_finished_result_label",
                   contains(s.finished_message, "2 项过期"),
                   s.finished_message),
        make_check("task_center_registry_cancellable",
                   s.cancel_request_result),
    };
}

std::vector<CheckResult> check_command_palette_scenario(
    const QaPaletteScenarioSnapshot& s) {
    int disabled = 0;
    bool reason_visible = false;
    bool stage_scoped = false;
    for (const QaPaletteItem& item : s.stage_items) {
        if (!item.enabled) {
            ++disabled;
            if (contains(item.text, "（") && ends_with(item.text, "）")) {
                reason_visible = true;
            }
            if (item.stage_scoped) {
                stage_scoped = true;
            }
        }
    }
    std::vector<std::string> disabled_texts;
    for (const QaPaletteItem& item : s.stage_items) {
        if (!item.enabled) disabled_texts.push_back(item.text);
    }
    std::string preview;
    for (std::size_t i = 0; i < disabled_texts.size() && i < 3; ++i) {
        if (i) preview += ", ";
        preview += disabled_texts[i];
    }
    int tool_specs_with_details = 0;
    bool tooltip_explains = false;
    for (const QaPaletteItem& item : s.tool_items) {
        if (item.spec_id.rfind("map:", 0) == 0 && !item.tool_tip.empty()) {
            ++tool_specs_with_details;
            if (contains(item.tool_tip, "前置条件")) {
                tooltip_explains = true;
            }
        }
    }
    return {
        make_check("palette_open", s.open),
        make_check("palette_has_disabled_command", disabled > 0,
                   "disabled=" + std::to_string(disabled) +
                       " enabled=" + std::to_string(s.enabled_count)),
        make_check("palette_disabled_reason_in_text", reason_visible,
                   "[" + preview + "]"),
        make_check("palette_disabled_item_is_stage_scoped", stage_scoped,
                   ""),
        make_check("palette_map_tool_tooltip_details",
                   tool_specs_with_details > 0 && tooltip_explains,
                   "tools_with_tooltip=" +
                       std::to_string(tool_specs_with_details)),
    };
}

std::vector<CheckResult> check_error_empty_states(
    const QaStatesCompositeSnapshot& s) {
    std::vector<std::string> tones;
    bool badge0 = false;
    if (!s.badges.empty()) {
        badge0 = s.badges[0].tone == "warning" &&
                 s.badges[0].text == "2 项过期";
    }
    for (const QaBadgeSnapshot& b : s.badges) {
        tones.push_back(b.tone);
    }
    const std::vector<std::string> want = {"warning", "error", "success"};
    return {
        make_check("empty_state_title", s.empty_found &&
                                           s.empty_title == "暂无数据资产",
                   s.empty_title),
        make_check("empty_state_hint_visible",
                   s.empty_found && !s.empty_hint_hidden),
        make_check("loading_state_text",
                   s.loading_found &&
                       contains(s.loading_text, "HZ26_3D_full.sgy"),
                   s.loading_text),
        make_check("loading_state_indeterminate",
                   s.loading_found && s.loading_indeterminate),
        make_check("warning_badge_tone", badge0,
                   s.badges.empty() ? "" :
                       "tone=" + s.badges[0].tone +
                           " text=" + s.badges[0].text),
        make_check("badge_row_tones_distinct", tones == want,
                   "[" + join(tones, ", ") + "]"),
    };
}

std::vector<CheckResult> check_theme_matrix(
    const std::vector<QaThemeRender>& renders) {
    std::vector<CheckResult> results;
    for (const QaThemeRender& r : renders) {
        results.push_back(make_check(
            "theme_matrix[" + r.theme + "@" +
                std::to_string(r.want_width) + "x" +
                std::to_string(r.want_height) + "]",
            !r.null_pixmap && r.width == r.want_width &&
                r.height == r.want_height && r.distinct_colors >= 2,
            "size=" + std::to_string(r.width) + "x" +
                std::to_string(r.height) +
                " colors=" + std::to_string(r.distinct_colors)));
    }
    return results;
}

// run_scenario_checks — the V11 _CHECKS table parity.
std::vector<CheckResult> run_scenario_checks(
    const std::string& name, const ScenarioSnapshot& s) {
    auto missing = [](const std::string& what) {
        return std::vector<CheckResult>{make_check(what, false,
                                                   "snapshot section missing")};
    };
    if (name == "first_open_empty_shell") {
        if (!s.shell) return missing("first_open_surface_snapshot");
        return check_first_open(*s.shell);
    }
    if (name == "data_manager_surface") {
        if (!s.data_manager) return missing("data_manager_surface_snapshot");
        return check_data_manager(*s.data_manager);
    }
    if (name == "well_task_workflow_panel") {
        if (!s.task_panel) return missing("task_panel_snapshot");
        return check_task_panel(*s.task_panel);
    }
    if (name == "seismic_context_surface") {
        if (!s.seismic) return missing("seismic_context_snapshot");
        return check_seismic_context(*s.seismic);
    }
    if (name == "stage_bar_phase1" || name == "stage_bar_phase2" ||
        name == "stage_bar_phase3") {
        if (!s.stage) return missing("stage_surface_snapshot");
        using pwb::tool_policy::MappingStage;
        const char* value =
            name == "stage_bar_phase1"
                ? pwb::tool_policy::stage_value(MappingStage::FaciesCalibration)
                : name == "stage_bar_phase2"
                      ? pwb::tool_policy::stage_value(
                            MappingStage::ConstraintFactor)
                      : pwb::tool_policy::stage_value(
                            MappingStage::IntegratedCompilation);
        return check_stage_surface(*s.stage, value);
    }
    if (name == "inspector_version_payload") {
        if (!s.inspector) return missing("inspector_snapshot");
        return check_inspector_version(*s.inspector);
    }
    if (name == "inspector_run_payload") {
        if (!s.inspector) return missing("inspector_snapshot");
        return check_inspector_run(*s.inspector);
    }
    if (name == "task_center_operations") {
        if (!s.task_center) return missing("task_center_snapshot");
        return check_task_center(*s.task_center);
    }
    if (name == "command_palette_disabled_reason") {
        if (!s.palette) return missing("palette_scenario_snapshot");
        return check_command_palette_scenario(*s.palette);
    }
    if (name == "error_empty_states_composite") {
        if (!s.states_composite) return missing("states_composite_snapshot");
        return check_error_empty_states(*s.states_composite);
    }
    if (name == "theme_matrix_smoke") {
        return check_theme_matrix(s.theme_renders);
    }
    return {};
}

}  // namespace pwb::ui_visualqa
