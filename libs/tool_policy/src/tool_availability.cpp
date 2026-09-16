// Port of paleo_workbench/mapping/tool_availability.py — THE canonical tool
// state machine. Gate order inside each rule is deliberate (coarse -> fine;
// the first blocker wins). Reason strings are copied verbatim from the
// Python authority; cross-surface consistency relies on them not drifting.

#include <pwb/tool_policy/tool_availability.hpp>

#include <algorithm>
#include <functional>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include <pwb/tool_policy/layer_roles.hpp>
#include <pwb/tool_policy/stages.hpp>

namespace pwb::tool_policy {
namespace {

ToolAvailability make_ok(const std::string& tool_id, bool visible = true,
                         bool preferred = false) {
    ToolAvailability a;
    a.tool_id = tool_id;
    a.visible = visible;
    a.enabled = true;
    a.preferred = preferred;
    return a;
}

ToolAvailability make_no(const std::string& tool_id, const std::string& reason,
                         bool visible = true) {
    ToolAvailability a;
    a.tool_id = tool_id;
    a.visible = visible;
    a.enabled = false;
    a.disabled_reason = reason;
    return a;
}

bool starts_with(const std::string& text, const std::string& prefix) {
    return text.size() >= prefix.size()
        && text.compare(0, prefix.size(), prefix) == 0;
}

// ---------------------------------------------------------------- groups ----

const std::map<std::string, std::vector<std::string>> kToolGroups = {
    {"navigate", {"pan", "zoom_in", "zoom_out", "full_extent", "previous_extent",
                  "next_extent", "refresh"}},
    {"selection", {"select", "select_rectangle", "select_all", "invert_selection",
                   "clear_selection"}},
    {"inspection", {"identify", "measure_distance"}},
    {"edit_session", {"toggle_editing", "save_edits", "rollback"}},
    {"capture", {"add_point", "add_line", "add_polygon", "add_rectangle",
                 "add_circle", "add_arc", "add_regular_polygon", "add_ellipse",
                 "add_sector"}},
    {"geometry", {"move_feature", "vertex", "reshape", "undo", "redo",
                  "delete_selected", "split", "merge", "repair_geometry",
                  "duplicate_selected", "add_ring", "add_part", "explode_multipart",
                  "collect_multipart", "fault_cut", "boundary_reshape",
                  "delete_ring", "delete_part", "reverse_line", "simplify_feature",
                  "smooth_feature", "offset_curve", "rotate_feature", "scale_feature",
                  "cut_features", "copy_features", "paste_features",
                  "snap_geometries", "trim_line", "extend_line", "fill_ring",
                  "change_facies"}},
    {"snapping", {"snapping", "avoid_intersections", "tracing", "vertex_scope",
                  "topology", "cancel"}},
    {"layer", {"layer_new", "reference_import", "layer_properties",
               "attribute_table", "layer_zoom", "layer_export"}},
    {"symbology", {"symbology", "style_manager"}},
    {"factor", {"factor_workbench", "factor_overlay"}},
    {"qa", {"qa_run", "map_product_assemble"}},
    {"layout_export", {"map_export"}},
};

const std::unordered_set<std::string> kLineRoles = {
    std::string(layer_role::kProvenanceLine),
    std::string(layer_role::kProvenanceDirection),
    std::string(layer_role::kDistributionLine),
    std::string(layer_role::kPaleoShoreline),
    std::string(layer_role::kFaciesBoundary),
    std::string(layer_role::kFaultConstraint),
};
const std::unordered_set<std::string> kPolygonRoles = {
    std::string(layer_role::kInterpolationBoundary),
    std::string(layer_role::kMaskBoundary),
};

// Tools that require the native QGIS backend (disabled + reason when the
// bridge/canvas is absent or degraded; the capability is never hidden).
const std::unordered_set<std::string> kNativeOnlyTools = {
    "style_manager", "reshape", "add_ring", "add_part", "fault_cut",
    "boundary_reshape",
};

const std::unordered_set<std::string> kNeedsAnyLayer = {
    "identify", "select", "select_rectangle", "measure_distance",
    "clear_selection", "select_all", "invert_selection", "layer_properties",
    "layer_zoom", "layer_export", "symbology",
};
const std::unordered_set<std::string> kNeedsEditableLayer = {"toggle_editing"};
const std::unordered_set<std::string> kNeedsEditing = {
    "save_edits", "rollback", "add_point", "add_line", "add_polygon",
    "move_feature", "vertex", "reshape", "undo", "redo", "delete_selected",
    "split", "merge", "repair_geometry", "duplicate_selected", "add_ring",
    "add_part", "explode_multipart", "collect_multipart", "fault_cut",
    "boundary_reshape",
};
const std::unordered_set<std::string> kNeedsLayerGroups = {"layer", "symbology"};

const std::unordered_set<std::string> kBasicGroups = {
    "navigate", "selection", "inspection", "layer",
};

// Checked-state canvas tools (current_tool follows the actual map tool).
const std::unordered_set<std::string> kCheckedCanvasTools = {
    "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
    "measure_distance", "add_point", "add_line", "add_polygon", "add_rectangle",
    "add_circle", "add_arc", "add_regular_polygon", "add_ellipse", "add_sector",
    "move_feature", "vertex", "reshape", "add_ring", "add_part", "fault_cut",
    "boundary_reshape",
};

// Stage-specific group visibility overrides (missing group = visible).
const std::map<std::string, std::map<std::string, bool>> kStageGroupVisibility = {
    {"facies_calibration", {{"factor", false}, {"layout_export", false}}},
    {"constraint_factor", {{"factor", true}, {"layout_export", false}}},
    {"integrated_compilation", {{"factor", false}, {"layout_export", true}}},
};

// Stage whitelist for non-edit actions.
const std::map<std::string, std::vector<std::string>> kStageActionWhitelist = {
    {"factor_workbench", {"constraint_factor"}},
    {"factor_overlay", {"constraint_factor"}},
    {"map_product_assemble", {"integrated_compilation"}},
    {"map_export", {"integrated_compilation"}},
};

// Governed edit actions per stage (union = governed set; empty = no filter).
std::unordered_set<std::string> stage_edit_actions(MappingStage stage) {
    switch (stage) {
        case MappingStage::FaciesCalibration:
            return {"add_polygon", "move_feature", "vertex", "split", "merge",
                    "delete_selected", "undo", "redo"};
        case MappingStage::ConstraintFactor:
            return {"add_line", "add_polygon", "move_feature", "vertex", "split",
                    "merge", "delete_selected", "undo", "redo"};
        case MappingStage::IntegratedCompilation:
            return {"add_polygon", "add_line", "move_feature", "vertex", "split",
                    "merge", "delete_selected", "undo", "redo"};
    }
    return {};
}

const std::unordered_set<std::string>& governed_edit_actions() {
    static const std::unordered_set<std::string> governed = {
        "add_polygon", "add_line", "move_feature", "vertex", "split", "merge",
        "delete_selected", "undo", "redo",
    };
    return governed;
}

// ------------------------------------------------------------------ gates ----

std::optional<std::string> project_gate(const ToolContextSnapshot& c) {
    if (!c.project_open) return std::string("未打开工程");
    return std::nullopt;
}

std::optional<std::string> blocking_gate(const ToolContextSnapshot& c) {
    if (!c.blocking_task.empty())
        return "后台任务进行中：" + c.blocking_task;
    return std::nullopt;
}

std::optional<std::string> layer_gate(const ToolContextSnapshot& c) {
    if (!c.has_active_layer()) return std::string("没有活动的矢量图层");
    return std::nullopt;
}

std::optional<std::string> queryable_gate(const ToolContextSnapshot& c) {
    if (c.queryable_layer_count <= 0) return std::string("没有可查询的图层");
    return std::nullopt;
}

std::optional<std::string> vector_layer_gate(const ToolContextSnapshot& c) {
    if (!c.has_active_vector_layer()) return std::string("没有活动的矢量图层");
    return std::nullopt;
}

std::optional<std::string> writable_gate(const ToolContextSnapshot& c) {
    if (!c.vector_writable) return std::string("图层不可写");
    if (c.provider_writable.has_value() && !*c.provider_writable) {
        const std::string provider =
            c.provider_name.empty() ? std::string("provider") : c.provider_name;
        if (c.provider_writable_approximate) {
            return "图层 provider（" + provider
                + "）按能力位推断不支持编辑（桥未提供 supports_editing，判据为近似）——只读数据源";
        }
        return "图层 provider（" + provider + "）不支持编辑——只读数据源";
    }
    return std::nullopt;
}

std::optional<std::string> role_gate(const ToolContextSnapshot& c) {
    if (c.edit_gate_open.has_value()) {
        if (!*c.edit_gate_open) {
            if (!c.edit_gate_reason.empty()) return c.edit_gate_reason;
            if (c.layer_frozen) return frozen_layer_gate_reason();
            if (c.raw_locked) return raw_layer_gate_reason();
            if (c.stage_locked)
                return std::string("当前阶段的证据组已锁定，禁止编辑");
            return stage_lock_reason();
        }
        return std::nullopt;
    }
    return std::string("当前图层可编辑性未知");
}

std::optional<std::string> editing_gate(const ToolContextSnapshot& c) {
    if (!c.editing) return std::string("需要先开始编辑");
    return std::nullopt;
}

std::optional<std::string> native_tool_gate(const ToolContextSnapshot& c,
                                            const std::string& kind,
                                            const std::string& native_name) {
    if (kind == "__python_fallback__") return std::nullopt;
    if (c.native_canvas_available) {
        const std::string wanted = "qgis.native_tool." + kind;
        const bool found = std::find(c.capability_flags.begin(),
                                     c.capability_flags.end(), wanted)
                           != c.capability_flags.end();
        if (!found) {
            return "原生 " + native_name
                + " 工具在当前桥版本不可用（重建 qgis_render_bridge）";
        }
    }
    return std::nullopt;
}

std::optional<std::string> backend_gate(const ToolContextSnapshot& c) {
    const std::string& mode = c.backend_mode;
    if (mode == "native") return std::nullopt;
    if (mode == "degraded") {
        return "QGIS 原生后端降级（"
            + (c.backend_reason.empty() ? std::string("同步异常") : c.backend_reason)
            + "）——该功能暂不可用";
    }
    const std::string reason = !c.backend_reason.empty() ? c.backend_reason
        : (mode == "unknown" ? std::string("能力未知") : std::string("桥不可用"));
    return "需要 QGIS 原生编辑后端（" + reason + "）";
}

std::optional<std::string> kind_gate(const ToolContextSnapshot& c,
                                     const std::string& tool_id) {
    static const std::unordered_map<std::string, std::string> kind_required = {
        {"add_point", "point"}, {"add_line", "line"}, {"add_polygon", "polygon"},
        {"add_rectangle", "polygon"}, {"add_circle", "polygon"},
        {"add_regular_polygon", "polygon"}, {"add_arc", "line"},
        {"add_ellipse", "polygon"}, {"add_sector", "polygon"},
    };
    const std::string expected = kind_required.at(tool_id);
    const std::string& kind = c.active_layer_kind;
    if (kind.empty()) {
        return std::string("活动图层几何类型未知——不能确定可用的捕获工具");
    }
    if (kind != expected) {
        return "仅对" + layer_caption(expected) + "图层有效（活动图层为"
            + layer_caption(kind) + "图层，不能使用添加" + layer_caption(expected)
            + "）";
    }
    if (expected == "polygon" && kLineRoles.count(c.layer_role) > 0) {
        return "当前编辑目标为线要素角色（"
            + (c.layer_role_label.empty() ? std::string("线约束") : c.layer_role_label)
            + "），应使用添加线";
    }
    if (expected == "line" && kPolygonRoles.count(c.layer_role) > 0) {
        return "当前编辑目标为面要素角色（"
            + (c.layer_role_label.empty() ? std::string("边界/掩膜") : c.layer_role_label)
            + "），应使用添加面";
    }
    return std::nullopt;
}

// ---------------------------------------------------------- stage gates -----

std::optional<std::map<std::string, bool>> stage_visibility_for(
    const ToolContextSnapshot& c) {
    if (!c.mapping_stage.has_value()) return std::nullopt;
    if (!stage_from_value(*c.mapping_stage).has_value()) {
        std::map<std::string, bool> fail_closed;
        for (const auto& [group, tools] : kToolGroups)
            fail_closed[group] = kBasicGroups.count(group) > 0;
        return fail_closed;
    }
    std::map<std::string, bool> visibility;
    const auto it = kStageGroupVisibility.find(*c.mapping_stage);
    for (const auto& [group, tools] : kToolGroups) {
        bool visible = true;
        if (it != kStageGroupVisibility.end()) {
            const auto oit = it->second.find(group);
            if (oit != it->second.end()) visible = oit->second;
        }
        visibility[group] = visible;
    }
    return visibility;
}

std::optional<std::string> stage_group_gate(const ToolContextSnapshot& c,
                                            const std::string& tool_id) {
    if (tool_id == "cancel") return std::nullopt;  // global escape hatch
    if (!c.mapping_stage.has_value()) return std::nullopt;
    const auto visibility = stage_visibility_for(c);
    if (!visibility.has_value()) return std::nullopt;
    const std::string group = group_of(tool_id);
    const auto it = visibility->find(group);
    if (it != visibility->end() && !it->second) {
        if (!stage_from_value(*c.mapping_stage).has_value()) {
            return std::string("当前编图阶段未知——仅保留基础工具组");
        }
        return "当前阶段不提供该工具组（"
            + stage_display_or_raw(*c.mapping_stage) + "）";
    }
    return std::nullopt;
}

std::optional<std::string> stage_whitelist_gate(const ToolContextSnapshot& c,
                                                const std::string& tool_id) {
    const auto it = kStageActionWhitelist.find(tool_id);
    if (it == kStageActionWhitelist.end() || !c.mapping_stage.has_value())
        return std::nullopt;
    const auto& whitelist = it->second;
    if (std::find(whitelist.begin(), whitelist.end(), *c.mapping_stage)
        == whitelist.end()) {
        return stage_whitelist_reason(whitelist);
    }
    return std::nullopt;
}

std::optional<std::string> edit_action_stage_gate(const ToolContextSnapshot& c,
                                                  const std::string& tool_id) {
    if (governed_edit_actions().count(tool_id) == 0) return std::nullopt;
    if (!c.mapping_stage.has_value()) return std::nullopt;
    const auto stage = !c.mapping_stage->empty()
        ? stage_from_value(*c.mapping_stage) : std::nullopt;
    if (!stage.has_value()) return std::string("当前编图阶段未知");
    if (stage_edit_actions(*stage).count(tool_id) == 0) {
        return "当前阶段不允许此编辑动作（限 "
            + std::string(stage_label(*stage)) + "）";
    }
    return std::nullopt;
}

// ----------------------------------------------------------------- rules ----

ToolAvailability rule_navigation(const ToolContextSnapshot& c,
                                 const std::string& tool_id) {
    const auto reason = project_gate(c);
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_extent_history(const ToolContextSnapshot& c,
                                     const std::string& tool_id) {
    auto reason = project_gate(c);
    if (!reason && tool_id == "previous_extent" && !c.can_previous_extent)
        reason = std::string("没有上一视图");
    if (!reason && tool_id == "next_extent" && !c.can_next_extent)
        reason = std::string("没有下一视图");
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_inspection(const ToolContextSnapshot& c,
                                 const std::string& tool_id) {
    std::optional<std::string> reason;
    if (tool_id == "identify") {
        reason = project_gate(c) ? project_gate(c) : queryable_gate(c);
    } else if (tool_id == "select" || tool_id == "select_rectangle") {
        reason = project_gate(c) ? project_gate(c) : vector_layer_gate(c);
    } else {
        reason = project_gate(c) ? project_gate(c) : layer_gate(c);
    }
    if (!reason && tool_id == "identify")
        reason = native_tool_gate(c, "identify", "识别");
    if (!reason && (tool_id == "select" || tool_id == "select_rectangle"))
        reason = native_tool_gate(c, "select", "选择");
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_selection_commands(const ToolContextSnapshot& c,
                                         const std::string& tool_id) {
    auto reason = project_gate(c) ? project_gate(c) : vector_layer_gate(c);
    if (!reason && tool_id != "select_all" && c.selection_count <= 0)
        reason = std::string("没有选中的要素");
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_toggle_editing(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = writable_gate(c);
    return reason ? make_no("toggle_editing", *reason)
                  : make_ok("toggle_editing", true, c.editing);
}

ToolAvailability rule_save_edits(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && !c.dirty) reason = std::string("编辑会话没有未保存的修改");
    if (!reason && (!c.edit_gate_open.has_value() || !*c.edit_gate_open)) {
        if (!c.edit_gate_reason.empty()) {
            reason = c.edit_gate_reason;
        } else if (!c.edit_gate_open.has_value()) {
            reason = std::string("当前图层可编辑性未知");
        } else {
            reason = std::string("图层被编辑门禁锁定");
        }
    }
    return reason ? make_no("save_edits", *reason) : make_ok("save_edits");
}

ToolAvailability rule_rollback(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && !c.dirty) reason = std::string("编辑会话没有可回滚的修改");
    return reason ? make_no("rollback", *reason) : make_ok("rollback");
}

ToolAvailability rule_cancel(const ToolContextSnapshot&) {
    return make_ok("cancel");
}

ToolAvailability rule_capture(const ToolContextSnapshot& c,
                              const std::string& tool_id) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason) reason = kind_gate(c, tool_id);
    if (!reason) {
        const std::string native_kind = tool_id == "add_point" ? "addPoint"
            : tool_id == "add_line" ? "addLine" : "addPolygon";
        reason = native_tool_gate(c, native_kind, "采点");
    }
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id, true, true);
}

ToolAvailability rule_edit_tool(const ToolContextSnapshot& c,
                                const std::string& tool_id,
                                const std::string& native_kind) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason) {
        std::string label = tool_id;
        if (tool_id == "move_feature") label = "移动";
        else if (tool_id == "vertex") label = "节点编辑";
        else if (tool_id == "add_rectangle") label = "添加矩形";
        else if (tool_id == "add_circle") label = "添加圆";
        else if (tool_id == "add_arc") label = "添加圆弧";
        else if (tool_id == "add_regular_polygon") label = "添加正多边形";
        else if (tool_id == "add_ellipse") label = "添加椭圆";
        else if (tool_id == "add_sector") label = "添加扇形";
        reason = native_tool_gate(c, native_kind, label);
    }
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_geotopo_tool(const ToolContextSnapshot& c,
                                  const std::string& tool_id) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.active_layer_kind != "polygon")
        reason = std::string("仅面图层可用");
    if (!reason) {
        const bool is_fault = tool_id == "fault_cut";
        reason = native_tool_gate(c, is_fault ? "faultCut" : "boundaryReshape",
                                 is_fault ? "断层切割" : "共边重塑");
    }
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_ring_part(const ToolContextSnapshot& c,
                                const std::string& tool_id) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.selection_count != 1)
        reason = std::string("需要恰好选中一个要素");
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_selection_op(const ToolContextSnapshot& c,
                                   const std::string& tool_id) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.selection_count <= 0)
        reason = std::string("没有选中的要素");
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_change_facies(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason && !c.layer_is_facies)
        reason = std::string("该图层不是相带图层（换相仅对相/亚相/微相图层有效）");
    if (!reason && c.selection_count <= 0)
        reason = std::string("没有选中的要素");
    return reason ? make_no("change_facies", *reason) : make_ok("change_facies");
}

ToolAvailability rule_copy_paste(const ToolContextSnapshot& c,
                                 const std::string& tool_id) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (tool_id != "copy_features" && !reason) reason = editing_gate(c);
    if (!reason && c.selection_count <= 0)
        reason = std::string("没有选中的要素");
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_delete_selected(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.selection_count <= 0)
        reason = std::string("没有选中的要素");
    return reason ? make_no("delete_selected", *reason)
                  : make_ok("delete_selected");
}

ToolAvailability rule_split(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && !c.split_ready)
        reason = std::string("分割需要：一个正在编辑且选中了多边形的面图层 + 一条选中的切割线");
    return reason ? make_no("split", *reason) : make_ok("split");
}

ToolAvailability rule_merge(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.topology_error_count > 0)
        reason = std::string("当前编辑会话存在拓扑错误，不能合并");
    if (!reason && !c.merge_ready)
        reason = std::string("合并需要至少两个选中的兼容面要素");
    return reason ? make_no("merge", *reason) : make_ok("merge");
}

ToolAvailability rule_reshape(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && !c.native_canvas_available)
        reason = std::string("重塑需要原生 QGIS 画布（无回退实现）");
    if (!reason && c.active_layer_kind != "line" && c.active_layer_kind != "polygon")
        reason = std::string("重塑仅支持线/面图层");
    if (!reason && c.selection_count != 1)
        reason = std::string("重塑需要恰好选中一个要素");
    if (!reason && !c.has_capability("qgis.native_tool.addLine"))
        reason = std::string("重塑需要原生数字化工具（无回退实现）");
    else if (!reason && !c.has_capability("qgis.geometry_op.reshape"))
        reason = std::string("重塑需要 QGIS reshape 几何算子（重建 qgis_render_bridge）");
    return reason ? make_no("reshape", *reason) : make_ok("reshape");
}

ToolAvailability rule_repair(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = writable_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason && c.active_layer_kind != "polygon")
        reason = std::string("几何修复针对面图层");
    return reason ? make_no("repair_geometry", *reason) : make_ok("repair_geometry");
}

ToolAvailability rule_duplicate_selected(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.selection_count <= 0)
        reason = std::string("没有选中的要素");
    return reason ? make_no("duplicate_selected", *reason)
                  : make_ok("duplicate_selected");
}

ToolAvailability rule_add_ring(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.active_layer_kind != "polygon")
        reason = std::string("添加环需要面图层");
    if (!reason && c.selection_count != 1)
        reason = std::string("添加环需要恰好选中一个面要素");
    if (!reason && !c.native_canvas_available)
        reason = std::string("添加环需要原生 QGIS 画布（无回退实现）");
    else if (!reason && !c.has_capability("qgis.native_tool.addPolygon"))
        reason = std::string("添加环需要原生数字化工具（无回退实现）");
    return reason ? make_no("add_ring", *reason) : make_ok("add_ring");
}

ToolAvailability rule_add_part(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.active_layer_kind.empty())
        reason = std::string("未知图层几何类型");
    if (!reason && c.selection_count != 1)
        reason = std::string("添加部件需要恰好选中一个要素");
    if (!reason && !c.native_canvas_available)
        reason = std::string("添加部件需要原生 QGIS 画布（无回退实现）");
    else if (!reason && !c.has_capability("qgis.geometry_op.add_part"))
        reason = std::string("添加部件需要 QGIS add_part 几何算子（重建 qgis_render_bridge）");
    else if (!reason) {
        const std::string kind = c.active_layer_kind == "point" ? "addPoint"
            : c.active_layer_kind == "line" ? "addLine"
            : c.active_layer_kind == "polygon" ? "addPolygon" : std::string();
        if (!kind.empty() && !c.has_capability("qgis.native_tool." + kind))
            reason = std::string("添加部件需要原生数字化工具（无回退实现）");
    }
    return reason ? make_no("add_part", *reason) : make_ok("add_part");
}

ToolAvailability rule_explode_multipart(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.selection_multipart_count < 1)
        reason = std::string("拆分多部件需要选中至少一个多部件要素");
    return reason ? make_no("explode_multipart", *reason)
                  : make_ok("explode_multipart");
}

ToolAvailability rule_collect_multipart(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = role_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && c.topology_error_count > 0)
        reason = std::string("当前编辑会话存在拓扑错误，不能合并部件");
    if (!reason && !c.collect_ready)
        reason = std::string("组合多部件需要至少两个同类型的单部件要素");
    return reason ? make_no("collect_multipart", *reason)
                  : make_ok("collect_multipart");
}

ToolAvailability rule_history(const ToolContextSnapshot& c,
                              const std::string& tool_id) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && tool_id == "undo" && !c.can_undo)
        reason = std::string("没有可撤销的操作");
    if (!reason && tool_id == "redo" && !c.can_redo)
        reason = std::string("没有可重做的操作");
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_snapping(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason && !c.snapping_available)
        reason = std::string("当前环境的捕捉引擎不可用（桥缺少 snapping 配置通道）");
    return reason ? make_no("snapping", *reason) : make_ok("snapping");
}

ToolAvailability rule_avoid_intersections(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason && !c.snapping_available)
        reason = std::string("当前环境的捕捉引擎不可用（桥缺少避免重叠通道）");
    return reason ? make_no("avoid_intersections", *reason)
                  : make_ok("avoid_intersections");
}

ToolAvailability rule_tracing(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason && !c.native_canvas_available)
        reason = std::string("追踪需要 QGIS 原生画布（当前为回退画布）");
    if (!reason && !c.snapping_available)
        reason = std::string("当前环境的捕捉引擎不可用（桥缺少追踪通道）");
    return reason ? make_no("tracing", *reason) : make_ok("tracing");
}

ToolAvailability rule_vertex_scope(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason) reason = editing_gate(c);
    if (!reason && !c.native_canvas_available)
        reason = std::string("顶点档位需要 QGIS 原生画布（当前为回退画布）");
    return reason ? make_no("vertex_scope", *reason) : make_ok("vertex_scope");
}

ToolAvailability rule_topology(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = layer_gate(c);
    if (!reason && !c.topology_available)
        reason = std::string("拓扑校验引擎不可用（需 QGIS 桥 validate 或 Shapely）");
    if (!reason && !c.crs_valid)
        reason = std::string("工程 CRS 无效，拓扑校验不可用");
    return reason ? make_no("topology", *reason) : make_ok("topology");
}

ToolAvailability rule_layer_management(const ToolContextSnapshot& c,
                                       const std::string& tool_id) {
    const auto reason = project_gate(c);
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_layer_scoped(const ToolContextSnapshot& c,
                                   const std::string& tool_id) {
    auto reason = project_gate(c);
    if (!reason && !c.has_active_layer())
        reason = std::string("当前无活动图层");
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_style_manager(const ToolContextSnapshot& c) {
    std::optional<std::string> reason = project_gate(c);
    if (!reason) reason = backend_gate(c);
    if (!reason) reason = layer_gate(c);
    return reason ? make_no("style_manager", *reason) : make_ok("style_manager");
}

ToolAvailability rule_factor(const ToolContextSnapshot& c,
                             const std::string& tool_id) {
    auto reason = project_gate(c);
    if (!reason) reason = stage_whitelist_gate(c, tool_id);
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

ToolAvailability rule_qa(const ToolContextSnapshot& c,
                         const std::string& tool_id) {
    auto reason = project_gate(c);
    if (!reason && tool_id == "map_product_assemble")
        reason = stage_whitelist_gate(c, tool_id);
    return reason ? make_no(tool_id, *reason) : make_ok(tool_id);
}

using Rule = std::function<ToolAvailability(const ToolContextSnapshot&)>;

const std::unordered_map<std::string, Rule>& rule_table() {
    static const std::unordered_map<std::string, Rule> table = {
        {"pan", [](const ToolContextSnapshot& c) { return rule_navigation(c, "pan"); }},
        {"zoom_in", [](const ToolContextSnapshot& c) { return rule_navigation(c, "zoom_in"); }},
        {"zoom_out", [](const ToolContextSnapshot& c) { return rule_navigation(c, "zoom_out"); }},
        {"full_extent", [](const ToolContextSnapshot& c) { return rule_navigation(c, "full_extent"); }},
        {"previous_extent", [](const ToolContextSnapshot& c) { return rule_extent_history(c, "previous_extent"); }},
        {"next_extent", [](const ToolContextSnapshot& c) { return rule_extent_history(c, "next_extent"); }},
        {"refresh", [](const ToolContextSnapshot& c) { return rule_navigation(c, "refresh"); }},
        {"identify", [](const ToolContextSnapshot& c) { return rule_inspection(c, "identify"); }},
        {"select", [](const ToolContextSnapshot& c) { return rule_inspection(c, "select"); }},
        {"select_rectangle", [](const ToolContextSnapshot& c) { return rule_inspection(c, "select_rectangle"); }},
        {"measure_distance", [](const ToolContextSnapshot& c) { return rule_inspection(c, "measure_distance"); }},
        {"clear_selection", [](const ToolContextSnapshot& c) { return rule_selection_commands(c, "clear_selection"); }},
        {"select_all", [](const ToolContextSnapshot& c) { return rule_selection_commands(c, "select_all"); }},
        {"invert_selection", [](const ToolContextSnapshot& c) { return rule_selection_commands(c, "invert_selection"); }},
        {"toggle_editing", rule_toggle_editing},
        {"save_edits", rule_save_edits},
        {"rollback", rule_rollback},
        {"cancel", rule_cancel},
        {"add_point", [](const ToolContextSnapshot& c) { return rule_capture(c, "add_point"); }},
        {"add_line", [](const ToolContextSnapshot& c) { return rule_capture(c, "add_line"); }},
        {"add_polygon", [](const ToolContextSnapshot& c) { return rule_capture(c, "add_polygon"); }},
        {"move_feature", [](const ToolContextSnapshot& c) { return rule_edit_tool(c, "move_feature", "move"); }},
        {"vertex", [](const ToolContextSnapshot& c) { return rule_edit_tool(c, "vertex", "vertex"); }},
        {"fault_cut", [](const ToolContextSnapshot& c) { return rule_geotopo_tool(c, "fault_cut"); }},
        {"boundary_reshape", [](const ToolContextSnapshot& c) { return rule_geotopo_tool(c, "boundary_reshape"); }},
        {"delete_ring", [](const ToolContextSnapshot& c) { return rule_ring_part(c, "delete_ring"); }},
        {"delete_part", [](const ToolContextSnapshot& c) { return rule_ring_part(c, "delete_part"); }},
        {"reverse_line", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "reverse_line"); }},
        {"simplify_feature", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "simplify_feature"); }},
        {"smooth_feature", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "smooth_feature"); }},
        {"offset_curve", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "offset_curve"); }},
        {"rotate_feature", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "rotate_feature"); }},
        {"scale_feature", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "scale_feature"); }},
        {"cut_features", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "cut_features"); }},
        {"copy_features", [](const ToolContextSnapshot& c) { return rule_copy_paste(c, "copy_features"); }},
        {"paste_features", [](const ToolContextSnapshot& c) { return rule_copy_paste(c, "paste_features"); }},
        {"add_rectangle", [](const ToolContextSnapshot& c) { return rule_edit_tool(c, "add_rectangle", "__python_fallback__"); }},
        {"add_circle", [](const ToolContextSnapshot& c) { return rule_edit_tool(c, "add_circle", "__python_fallback__"); }},
        {"snap_geometries", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "snap_geometries"); }},
        {"add_arc", [](const ToolContextSnapshot& c) { return rule_edit_tool(c, "add_arc", "__python_fallback__"); }},
        {"add_regular_polygon", [](const ToolContextSnapshot& c) { return rule_edit_tool(c, "add_regular_polygon", "__python_fallback__"); }},
        {"trim_line", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "trim_line"); }},
        {"extend_line", [](const ToolContextSnapshot& c) { return rule_selection_op(c, "extend_line"); }},
        {"fill_ring", [](const ToolContextSnapshot& c) { return rule_ring_part(c, "fill_ring"); }},
        {"add_ellipse", [](const ToolContextSnapshot& c) { return rule_edit_tool(c, "add_ellipse", "__python_fallback__"); }},
        {"add_sector", [](const ToolContextSnapshot& c) { return rule_edit_tool(c, "add_sector", "__python_fallback__"); }},
        {"change_facies", rule_change_facies},
        {"delete_selected", rule_delete_selected},
        {"split", rule_split},
        {"merge", rule_merge},
        {"reshape", rule_reshape},
        {"repair_geometry", rule_repair},
        {"duplicate_selected", rule_duplicate_selected},
        {"add_ring", rule_add_ring},
        {"add_part", rule_add_part},
        {"explode_multipart", rule_explode_multipart},
        {"collect_multipart", rule_collect_multipart},
        {"undo", [](const ToolContextSnapshot& c) { return rule_history(c, "undo"); }},
        {"redo", [](const ToolContextSnapshot& c) { return rule_history(c, "redo"); }},
        {"snapping", rule_snapping},
        {"avoid_intersections", rule_avoid_intersections},
        {"tracing", rule_tracing},
        {"vertex_scope", rule_vertex_scope},
        {"topology", rule_topology},
        {"layer_new", [](const ToolContextSnapshot& c) { return rule_layer_management(c, "layer_new"); }},
        {"reference_import", [](const ToolContextSnapshot& c) { return rule_layer_management(c, "reference_import"); }},
        {"layer_properties", [](const ToolContextSnapshot& c) { return rule_layer_scoped(c, "layer_properties"); }},
        {"attribute_table", [](const ToolContextSnapshot& c) { return rule_layer_scoped(c, "attribute_table"); }},
        {"layer_zoom", [](const ToolContextSnapshot& c) { return rule_layer_scoped(c, "layer_zoom"); }},
        {"layer_export", [](const ToolContextSnapshot& c) { return rule_layer_scoped(c, "layer_export"); }},
        {"symbology", [](const ToolContextSnapshot& c) { return rule_layer_scoped(c, "symbology"); }},
        {"style_manager", rule_style_manager},
        {"factor_workbench", [](const ToolContextSnapshot& c) { return rule_factor(c, "factor_workbench"); }},
        {"factor_overlay", [](const ToolContextSnapshot& c) { return rule_factor(c, "factor_overlay"); }},
        {"qa_run", [](const ToolContextSnapshot& c) { return rule_qa(c, "qa_run"); }},
        {"map_product_assemble", [](const ToolContextSnapshot& c) { return rule_qa(c, "map_product_assemble"); }},
        {"map_export", [](const ToolContextSnapshot& c) { return rule_factor(c, "map_export"); }},
    };
    return table;
}

bool needs_role_gate(const std::string& tool_id) {
    return kNeedsEditableLayer.count(tool_id) > 0 || kNeedsEditing.count(tool_id) > 0;
}

bool coarsely_blocked(const ToolContextSnapshot& c, const std::string& tool_id) {
    if (!c.project_open) return true;
    if (needs_role_gate(tool_id) && c.has_active_layer()
        && (!c.edit_gate_open.has_value() || !*c.edit_gate_open)) {
        return true;
    }
    return false;
}

bool layer_fact_gated(const std::string& tool_id) {
    return kNeedsAnyLayer.count(tool_id) > 0 || kNeedsEditableLayer.count(tool_id) > 0
        || kNeedsEditing.count(tool_id) > 0;
}

void apply_disable_metadata(const ToolContextSnapshot& c, const std::string& tool_id,
                            ToolAvailability& a) {
    if (a.enabled || a.disabled_reason.empty()) return;
    std::optional<std::string> severity;
    std::optional<std::string> remediation;
    if (c.project_open && c.has_active_layer() && c.edit_gate_open.has_value()
        && !*c.edit_gate_open && needs_role_gate(tool_id)) {
        severity = "warning";
        if (c.raw_locked) remediation = std::string("创建 DERIVED 草稿后编辑");
        else if (c.layer_frozen) remediation = std::string("另存草稿或解除冻结");
    }
    if (!severity.has_value()) {
        const auto wit = kStageActionWhitelist.find(tool_id);
        if (c.project_open && wit != kStageActionWhitelist.end()
            && c.mapping_stage.has_value()
            && std::find(wit->second.begin(), wit->second.end(), *c.mapping_stage)
                   == wit->second.end()) {
            severity = "warning";
        }
    }
    if (!severity.has_value() && c.provider_writable.has_value()
        && !*c.provider_writable
        && starts_with(a.disabled_reason, "图层 provider（")) {
        severity = "warning";
    }
    if (!severity.has_value() && a.disabled_reason == "没有选中的要素") {
        severity = "info";
    }
    if (severity.has_value() || remediation.has_value()) {
        a.severity = severity;
        a.remediation = remediation;
    }
}

}  // namespace

// ------------------------------------------------------------ wordings ------

std::string layer_caption(const std::string& kind) {
    if (kind == "point") return "点";
    if (kind == "line") return "线";
    if (kind == "polygon") return "面";
    return "未知";
}

std::string raw_layer_gate_reason(const std::string& layer_label) {
    if (!layer_label.empty()) {
        return "RAW/模型结果图层「" + layer_label
            + "」不可直接编辑——请创建 DERIVED 草稿后编辑";
    }
    return "RAW 图层不可变，请创建 DERIVED 草稿后编辑";
}

std::string frozen_layer_gate_reason(const std::string& layer_label) {
    if (!layer_label.empty()) {
        return "当前结果（" + layer_label + "）已冻结——需先解除冻结或另存草稿";
    }
    return "当前结果已冻结——需先解除冻结或另存草稿";
}

std::string stage_lock_reason(const std::string& reason) {
    if (!reason.empty()) return "图层被编辑门禁锁定：" + reason;
    return "图层被编辑门禁锁定";
}

std::string stage_whitelist_reason(const std::vector<std::string>& stages) {
    std::string joined;
    for (size_t i = 0; i < stages.size(); ++i) {
        if (i > 0) joined += "/";
        joined += stage_display_or_raw(stages[i]);
    }
    return "当前阶段不允许该操作（限 " + joined + "）";
}

const std::map<std::string, std::vector<std::string>>& tool_groups() {
    return kToolGroups;
}

const std::vector<std::string>& tool_ids() {
    static const std::vector<std::string> ids = [] {
        std::vector<std::string> flat;
        for (const auto& [group, members] : kToolGroups)
            flat.insert(flat.end(), members.begin(), members.end());
        return flat;
    }();
    return ids;
}

std::string group_of(const std::string& tool_id) {
    for (const auto& [group, members] : kToolGroups) {
        if (std::find(members.begin(), members.end(), tool_id) != members.end())
            return group;
    }
    return std::string();
}

std::map<std::string, bool> stage_group_visibility_no_stage() {
    std::map<std::string, bool> all;
    for (const auto& [group, tools] : kToolGroups) all[group] = true;
    return all;
}

std::map<std::string, bool> stage_group_visibility(const std::string& stage_value) {
    if (!stage_from_value(stage_value).has_value()) {
        std::map<std::string, bool> fail_closed;
        for (const auto& [group, tools] : kToolGroups)
            fail_closed[group] = kBasicGroups.count(group) > 0;
        return fail_closed;
    }
    std::map<std::string, bool> visibility;
    const auto it = kStageGroupVisibility.find(stage_value);
    for (const auto& [group, tools] : kToolGroups) {
        bool visible = true;
        if (it != kStageGroupVisibility.end()) {
            const auto oit = it->second.find(group);
            if (oit != it->second.end()) visible = oit->second;
        }
        visibility[group] = visible;
    }
    return visibility;
}

void ToolAvailability::validate() const {
    if (enabled && !disabled_reason.empty())
        throw std::logic_error("an enabled tool must not carry a disabled_reason");
    if (!visible && enabled)
        throw std::logic_error("an invisible tool cannot be enabled");
    if (enabled && (severity.has_value() || remediation.has_value()))
        throw std::logic_error("an enabled tool must not carry severity/remediation");
    if (severity.has_value() && *severity != "info" && *severity != "warning"
        && *severity != "critical") {
        throw std::logic_error("unknown severity '" + *severity + "'");
    }
}

bool ToolContextSnapshot::has_capability(const std::string& flag) const {
    return std::find(capability_flags.begin(), capability_flags.end(), flag)
           != capability_flags.end();
}

// ------------------------------------------------------------- evaluate -----

ToolAvailability evaluate_tool(const std::string& tool_id,
                               const ToolContextSnapshot& ctx) {
    const auto& table = rule_table();
    const auto rule_it = table.find(tool_id);
    if (rule_it == table.end()) {
        ToolAvailability unknown;
        unknown.tool_id = tool_id;
        unknown.visible = false;
        unknown.enabled = false;
        unknown.disabled_reason = "未知工具 '" + tool_id + "'";
        return unknown;
    }

    // Surface existence verdict (group-level hiding) — before blocking/rules
    // so stage-hidden groups never flash disabled during a blocking task.
    const std::string group = group_of(tool_id);
    if (kNeedsLayerGroups.count(group) > 0 && !ctx.has_active_layer()
        && tool_id != "layer_new" && tool_id != "reference_import") {
        ToolAvailability hidden;
        hidden.tool_id = tool_id;
        hidden.visible = false;
        hidden.disabled_reason = "当前无活动图层——该工具组未显示";
        return hidden;
    }

    if (!coarsely_blocked(ctx, tool_id)) {
        auto stage_reason = stage_group_gate(ctx, tool_id);
        if (!stage_reason) stage_reason = edit_action_stage_gate(ctx, tool_id);
        if (stage_reason) {
            ToolAvailability hidden;
            hidden.tool_id = tool_id;
            hidden.visible = false;
            hidden.disabled_reason = *stage_reason;
            return hidden;
        }
    }

    // Global gates (centralised, take precedence over specific rules).
    if (tool_id != "cancel") {
        if (const auto blocking = blocking_gate(ctx)) {
            return make_no(tool_id, *blocking);
        }
    }
    if (layer_fact_gated(tool_id) && ctx.project_open && ctx.has_active_layer()) {
        if (ctx.layer_missing) {
            return make_no(tool_id, !ctx.edit_gate_reason.empty()
                ? ctx.edit_gate_reason
                : std::string("图层源缺失（文件被移动或删除）"));
        }
        if (ctx.layer_degraded && (!ctx.edit_gate_open.has_value()
                                   || !*ctx.edit_gate_open)) {
            return make_no(tool_id, !ctx.edit_gate_reason.empty()
                ? ctx.edit_gate_reason
                : std::string("图层处于降级状态（数据不完整）"));
        }
    }

    ToolAvailability availability = rule_it->second(ctx);
    apply_disable_metadata(ctx, tool_id, availability);

    // checked follows the actual tool/session/toggle state.
    std::optional<bool> checked;
    if (tool_id == "toggle_editing") {
        checked = ctx.editing;
    } else if (tool_id == "snapping") {
        checked = ctx.snapping_enabled;
    } else if (tool_id == "avoid_intersections") {
        checked = ctx.avoid_intersections_enabled;
    } else if (tool_id == "tracing") {
        checked = ctx.tracing_enabled;
    } else if (tool_id == "vertex_scope") {
        checked = ctx.vertex_all_layers;
    } else if (tool_id == "topology") {
        checked = ctx.topology_enabled;
    } else if (kCheckedCanvasTools.count(tool_id) > 0) {
        checked = ctx.current_tool == tool_id && availability.enabled;
    }
    if (checked.has_value()) availability.checked = *checked;
    return availability;
}

std::map<std::string, ToolAvailability> evaluate_all(const ToolContextSnapshot& ctx) {
    std::map<std::string, ToolAvailability> result;
    for (const std::string& id : tool_ids()) result[id] = evaluate_tool(id, ctx);
    return result;
}

}  // namespace pwb::tool_policy
