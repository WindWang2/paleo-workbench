#include <pwb/ui_controllers/map_actions.hpp>

#include <unordered_set>

#include <pwb/ui_workstation/tool_help.hpp>

namespace pwb::ui_controllers {

namespace {

const std::vector<std::string> kToolIds = {
    "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
    "measure_distance", "add_point", "add_line", "add_polygon",
    "move_feature", "vertex", "reshape", "add_ring", "add_part",
    "fault_cut", "boundary_reshape",
    "add_rectangle", "add_circle", "add_arc", "add_regular_polygon",
    "add_ellipse", "add_sector",
};

const std::vector<std::string> kCommandIds = {
    "full_extent", "previous_extent", "next_extent", "refresh",
    "clear_selection", "select_all", "invert_selection", "toggle_editing",
    "save_edits", "rollback", "delete_selected",
    "undo", "redo", "split", "merge",
    "duplicate_selected", "explode_multipart", "collect_multipart",
    "delete_ring", "delete_part", "reverse_line", "simplify_feature",
    "smooth_feature", "offset_curve",
    "rotate_feature", "scale_feature", "cut_features", "copy_features",
    "paste_features", "snap_geometries",
    "trim_line", "extend_line", "fill_ring",
    "change_facies",
    "snapping", "avoid_intersections", "tracing", "vertex_scope",
    "topology", "cancel",
};

const std::vector<std::string> kCheckableCommandIds = {
    "snapping", "topology", "toggle_editing",
    "avoid_intersections", "tracing", "vertex_scope",
};

const std::vector<std::string> kSurfaceExtensionIds = {
    "layer_new", "reference_import", "layer_properties", "attribute_table",
    "layer_zoom", "layer_export", "symbology", "style_manager",
    "factor_workbench", "factor_overlay", "qa_run", "map_product_assemble",
    "map_export", "repair_geometry",
};

// action_registry._specs literal sets --------------------------------------

const std::map<std::string, std::string> kSurfaceIcons = {
    {"layer_new", "tree-add-layer"},
    {"reference_import", "btn-import"},
    {"layer_properties", "tree-properties"},
    {"attribute_table", "attribute_table"},
    {"layer_zoom", "tree-zoom"},
    {"layer_export", "tree-export"},
    {"symbology", "rb-colorbar"},
    {"style_manager", "rb-settings"},
    {"factor_workbench", "rb-grid"},
    {"factor_overlay", "btn-contour-draft"},
    {"qa_run", "rb-qc"},
    {"map_product_assemble", "rb-finalize"},
    {"cut_features", "delete_selected"},
    {"copy_features", "duplicate_selected"},
    {"paste_features", "duplicate_selected"},
    {"map_export", "rb-export"},
    {"repair_geometry", "btn-health"},
    {"change_facies", "change_facies"},
};

const std::unordered_set<std::string> kCanvasTools = {
    "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
    "measure_distance", "add_point", "add_line", "add_polygon",
    "move_feature", "vertex", "reshape", "add_ring", "add_part",
    "fault_cut", "boundary_reshape",
    "add_rectangle", "add_circle", "add_arc", "add_regular_polygon",
    "add_ellipse", "add_sector",
};

const std::unordered_set<std::string> kNativeOnly = {
    "style_manager", "reshape", "add_ring", "add_part",
    "fault_cut", "boundary_reshape",
};

const std::unordered_set<std::string> kWriteTools = {
    "toggle_editing", "save_edits", "rollback", "add_point", "add_line",
    "add_polygon", "move_feature", "vertex", "reshape", "delete_selected",
    "split", "merge", "repair_geometry", "undo", "redo", "topology",
    "layer_new", "factor_overlay", "map_product_assemble",
    "duplicate_selected", "add_ring", "add_part", "explode_multipart",
    "collect_multipart", "fault_cut", "boundary_reshape",
    "add_rectangle", "add_circle", "snap_geometries",
    "delete_ring", "delete_part", "reverse_line", "simplify_feature",
    "smooth_feature", "offset_curve",
    "rotate_feature", "scale_feature", "cut_features", "copy_features",
    "paste_features",
    "add_arc", "add_regular_polygon", "trim_line", "extend_line",
    "fill_ring", "add_sector",
    "change_facies",
};

const std::unordered_set<std::string> kSelectionTools = {
    "select", "select_rectangle", "select_all", "invert_selection",
    "clear_selection",
};

const std::unordered_set<std::string> kStructuralTools = {
    "layer_export", "reference_import", "map_export",
};

const std::unordered_set<std::string> kLayerMenuTools = {
    "layer_properties", "attribute_table", "layer_zoom", "layer_export",
    "symbology", "toggle_editing", "repair_geometry", "layer_new",
    "reference_import",
};

const std::unordered_set<std::string> kCanvasMenuTools = {
    "pan", "identify", "select", "select_rectangle", "measure_distance",
    "zoom_in", "zoom_out", "full_extent", "previous_extent", "next_extent",
    "select_all", "invert_selection", "clear_selection", "toggle_editing",
    "save_edits", "snapping", "topology", "layer_properties",
    "attribute_table", "change_facies",
    "avoid_intersections", "tracing", "vertex_scope",
};

}  // namespace

const std::vector<std::string>& map_tool_ids() { return kToolIds; }
const std::vector<std::string>& map_command_ids() { return kCommandIds; }
const std::vector<std::string>& map_checkable_command_ids() {
    return kCheckableCommandIds;
}
const std::vector<std::string>& map_surface_extension_ids() {
    return kSurfaceExtensionIds;
}

const std::map<std::string, MapActionSpec>& action_specs() {
    static const std::map<std::string, MapActionSpec> specs = [] {
        const auto& labels = ui_workstation::tool_labels();
        const auto& shortcuts = ui_workstation::tool_shortcuts();
        std::map<std::string, MapActionSpec> out;
        auto label_of = [&](const std::string& id) -> std::string {
            const auto it = labels.find(id);
            return it != labels.end() ? it->second : id;
        };
        auto shortcut_of = [&](const std::string& id) -> std::string {
            const auto it = shortcuts.find(id);
            return it != shortcuts.end() ? it->second : std::string{};
        };
        auto icon_of = [&](const std::string& id) -> std::string {
            const auto it = kSurfaceIcons.find(id);
            return it != kSurfaceIcons.end() ? it->second : id;
        };
        auto risk_of = [&](const std::string& id) -> std::string {
            if (kWriteTools.count(id)) return kRiskWrite;
            if (kSelectionTools.count(id)) return kRiskSelection;
            if (kStructuralTools.count(id)) return kRiskStructural;
            return kRiskRead;
        };
        // ACTION_SPECS iterates the evaluator's flat namespace (tool_ids()).
        for (const auto& id : tool_policy::tool_ids()) {
            MapActionSpec spec;
            spec.tool_id = id;
            spec.label = label_of(id);
            spec.group = tool_policy::group_of(id);
            spec.icon = icon_of(id);
            spec.risk = risk_of(id);
            spec.shortcut = shortcut_of(id);
            spec.surfaces = {"toolbar", "palette"};
            if (kLayerMenuTools.count(id))
                spec.surfaces.push_back("layer_menu");
            if (kCanvasMenuTools.count(id))
                spec.surfaces.push_back("canvas_menu");
            spec.canvas_interaction = kCanvasTools.count(id) != 0;
            spec.requires_native = kNativeOnly.count(id) != 0;
            out.emplace(id, std::move(spec));
        }
        return out;
    }();
    return specs;
}

MapActionPresentation availability_text(
    const std::string& action_id,
    const tool_policy::ToolAvailability& result,
    const std::optional<std::pair<std::string, std::string>>& help_override) {
    MapActionPresentation plan;
    plan.enabled = result.enabled;
    plan.visible = result.visible;
    plan.checked = result.checked;
    std::string label = action_id;
    const auto spec_it = action_specs().find(action_id);
    if (spec_it != action_specs().end()) label = spec_it->second.label;
    if (help_override) {
        plan.tooltip = help_override->first;
        plan.status_tip = help_override->second;
    } else if (!result.disabled_reason.empty()) {
        plan.tooltip = label + "\n" + result.disabled_reason;
        plan.status_tip = label + "（" + result.disabled_reason + "）";
    } else {
        plan.tooltip = label;
        plan.status_tip = label;
    }
    return plan;
}

std::vector<ToolbarEntry> toolbar_plan(
    const std::vector<std::vector<std::string>>& action_id_entries) {
    std::vector<ToolbarEntry> entries;
    for (std::size_t index = 0; index < action_id_entries.size(); ++index) {
        const auto& entry = action_id_entries[index];
        // A grouped (multi-id) entry gets a separator before it — never
        // the first entry, never for lone ids (Python `index and
        // isinstance(entry, tuple)` parity).
        if (index != 0 && entry.size() > 1) {
            entries.push_back(ToolbarEntry{true, {}});
        }
        for (const auto& id : entry) {
            entries.push_back(ToolbarEntry{false, id});
        }
    }
    return entries;
}

}  // namespace pwb::ui_controllers
