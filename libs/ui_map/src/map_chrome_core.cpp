#include <pwb/ui_map/map_chrome_core.hpp>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <stdexcept>

namespace pwb::ui_map {

// ---------------------------------------------------------------------------
// Frozen constants
// ---------------------------------------------------------------------------

const std::map<std::string, std::string>& layer_labels() {
    static const std::map<std::string, std::string> labels = {
        {"facies", "相带"}, {"well", "井"}, {"line", "线"}, {"label", "注记"},
    };
    return labels;
}

const std::vector<std::string>& default_chrome_elements() {
    static const std::vector<std::string> elements = {
        "图例", "指北针", "比例尺", "标题栏"};
    return elements;
}

const std::map<std::string, std::string>& authoring_kind_geometry() {
    static const std::map<std::string, std::string> mapping = {
        {"facies", "polygon"},
        {"line", "line"},
        {"well", "point"},
        {"label", "point"},
    };
    return mapping;
}

const std::set<std::string>& layer_bound_tool_actions() {
    static const std::set<std::string> actions = {
        "select", "identify", "select_rectangle", "move_feature", "vertex"};
    return actions;
}

const std::map<std::string, std::string>& kind_bound_tool_actions() {
    static const std::map<std::string, std::string> mapping = {
        {"add_point", "well"},
        {"add_line", "line"},
        {"add_polygon", "facies"},
    };
    return mapping;
}

const std::map<std::string, Json>& fault_ref_style() {
    static const std::map<std::string, Json> style = {
        {"fill", "#9c6644"}, {"stroke", "#4d3322"}, {"stroke_width", 1.0}};
    return style;
}

const std::vector<std::pair<double, std::string>>& factor_ramp_fallback() {
    static const std::vector<std::pair<double, std::string>> stops = {
        {0.0, "#053061"}, {0.5, "#f7f7f7"}, {1.0, "#67001f"}};
    return stops;
}

const std::vector<std::pair<std::string, std::string>>&
workarea_legend_items() {
    // WORKAREA_LEGEND_ITEMS verbatim (workarea_map_snapshot.py palette).
    static const std::vector<std::pair<std::string, std::string>> items = {
        {"工区边界", "#64748b"},   // _COLOR_BOUNDARY
        {"地震工区", "#0d9488"},   // _COLOR_SURVEY
        {"井位", "#409cff"},       // _COLOR_WELL_OK
        {"井位（坐标待处理）", "#f59e0b"},  // _COLOR_WELL_FLAGGED
    };
    return items;
}

// ---------------------------------------------------------------------------
// Document access
// ---------------------------------------------------------------------------

Json field_value(const Json& source, const std::string& name,
                 const Json& fallback) {
    if (!source.is_object()) {
        return fallback;
    }
    const auto it = source.find(name);
    return it == source.end() ? fallback : *it;
}

std::string field_value_str(const Json& source, const std::string& name,
                            const std::string& fallback) {
    const Json value = field_value(source, name, Json(nullptr));
    if (value.is_string()) {
        return value.get<std::string>();
    }
    if (value.is_null()) {
        return fallback;
    }
    if (value.is_number_integer()) {
        return std::to_string(value.get<long long>());
    }
    if (value.is_number_unsigned()) {
        return std::to_string(value.get<unsigned long long>());
    }
    if (value.is_number_float()) {
        // Python str(float): shortest round-trip repr — to_chars general.
        char buffer[64];
        const double number = value.get<double>();
        const auto result = std::to_chars(
            buffer, buffer + sizeof(buffer), number,
            std::chars_format::general);
        if (result.ec == std::errc()) {
            return std::string(buffer, result.ptr);
        }
        return std::to_string(number);
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    return fallback;
}

const Json* active_map_document(const std::vector<Json>& documents,
                                const std::string& prefer_id) {
    if (documents.empty()) {
        return nullptr;
    }
    if (!prefer_id.empty()) {
        for (const auto& doc : documents) {
            const Json id = field_value(doc, "id", Json(nullptr));
            if (id.is_string() && id.get<std::string>() == prefer_id) {
                return &doc;
            }
        }
    }
    return &documents.back();
}

namespace {

std::string identity_tag(const void* identity) {
    // Python id(obj) parity: a per-process identity tag. The pointer bytes
    // are the same class of unstable identity; never persisted.
    char buffer[32];
    std::snprintf(buffer, sizeof(buffer), "%p", identity);
    return buffer;
}

}  // namespace

std::string document_key(const Json& document, const void* identity) {
    const std::string doc_id = field_value_str(document, "id", "");
    return doc_id.empty() ? "doc@" + identity_tag(identity)
                          : "doc:" + doc_id;
}

std::string reference_layer_key(const Json& layer, const void* identity) {
    const std::string layer_id = field_value_str(layer, "id", "");
    return layer_id.empty() ? "ref@" + identity_tag(identity)
                            : "ref:" + layer_id;
}

std::string document_list_key(const Json& document, const void* identity) {
    const std::string doc_id = field_value_str(document, "id", "");
    return doc_id.empty() ? "doc@" + identity_tag(identity) : doc_id;
}

std::string panel_title_fallback(const std::string& key) {
    const auto pos = key.rfind(':');
    if (pos == std::string::npos) {
        return key;
    }
    const std::string tail = key.substr(pos + 1);
    return tail.empty() ? key : tail;
}

std::string reference_scene_layer_id(const std::string& document_id_or_empty,
                                     const std::string& reference_id) {
    const std::string doc_id =
        document_id_or_empty.empty() ? "map" : document_id_or_empty;
    return doc_id + ":reference:" + reference_id;
}

// ---------------------------------------------------------------------------
// Mode / visibility rules
// ---------------------------------------------------------------------------

ModeUiState resolve_mode_ui(bool preview_mode, bool unified_authoring_mode,
                            bool canvas_priority, bool bottom_user_visible) {
    ModeUiState state;
    const bool preview_surface = preview_mode || unified_authoring_mode;
    state.center_index = preview_surface ? 1 : 0;
    state.preview_shows_unified = preview_surface;
    state.bottom_visible =
        bottom_user_visible && !canvas_priority && !preview_mode;
    return state;
}

std::vector<int> saved_dock_splitter_sizes(
    const std::optional<std::vector<int>>& dock_record,
    const std::optional<std::vector<int>>& layers_record,
    const std::vector<int>& fallback) {
    if (dock_record.has_value() && !dock_record->empty()) {
        return *dock_record;
    }
    if (layers_record.has_value() && !layers_record->empty()) {
        return *layers_record;
    }
    return fallback;
}

// ---------------------------------------------------------------------------
// Unified revision translation
// ---------------------------------------------------------------------------

std::optional<std::map<std::string, long long>> unified_data_revisions(
    UnifiedRevisionState& state, const void* authoring,
    bool unified_authoring_mode,
    const std::function<Json(const std::string& kind)>& raw_revision_fn) {
    if (authoring == nullptr || !unified_authoring_mode) {
        return std::nullopt;
    }
    if (state.owner != authoring) {
        // New authoring object: force a bump for every kind even when raw
        // keys repeat, keeping effective revisions globally monotonic.
        state.owner = authoring;
        state.raw.clear();
    }
    std::map<std::string, long long> revisions;
    for (const char* kind_c : kLayerKeys) {
        const std::string kind(kind_c);
        const Json raw = raw_revision_fn(kind);
        const auto it = state.raw.find(kind);
        // dict.get parity: a missing cache entry compares as None, so an
        // absent (null) raw key is NOT a change — only a present raw key
        // bumps on first sight (or on a different cached value).
        const bool changed =
            it == state.raw.end() ? !raw.is_null() : it->second != raw;
        if (changed) {
            state.raw[kind] = raw;
            state.effective[kind] =
                state.effective.count(kind) ? state.effective[kind] + 1 : 1;
        }
        revisions[kind] =
            state.effective.count(kind) ? state.effective[kind] : 1;
    }
    return revisions;
}

// ---------------------------------------------------------------------------
// Layer field names
// ---------------------------------------------------------------------------

std::vector<std::string> layer_field_names(const Json& vector_features) {
    std::vector<std::string> names;
    std::set<std::string> seen;
    if (!vector_features.is_array()) {
        return names;
    }
    for (const auto& feature : vector_features) {
        const Json properties =
            field_value(feature.is_object() ? feature : Json::object(),
                        "properties", Json::object());
        if (!properties.is_object()) {
            continue;
        }
        for (const auto& [key, _value] : properties.items()) {
            if (key.empty() || key.rfind("__", 0) == 0 ||
                seen.count(key)) {
                continue;
            }
            seen.insert(key);
            names.push_back(key);
        }
        // The 64-cap check sits BETWEEN features in Python — all keys of
        // one feature are appended before the cutoff is evaluated.
        if (names.size() >= 64) {
            break;
        }
    }
    return names;
}

// ---------------------------------------------------------------------------
// Mapping context / dirty projection
// ---------------------------------------------------------------------------

Json mapping_context(const Json* active_document, bool dirty, bool preview) {
    std::string map_name = "未选择";
    std::string horizon;
    if (active_document != nullptr) {
        const std::string name =
            field_value_str(*active_document, "name", "");
        if (!name.empty()) {
            map_name = name;
        }
        horizon = field_value_str(*active_document, "linked_target_horizon",
                                  "");
    }
    return Json{{"map_name", map_name},
                {"horizon", horizon},
                {"dirty", dirty},
                {"preview", preview}};
}

// ---------------------------------------------------------------------------
// Unified overlay state
// ---------------------------------------------------------------------------

Json legend_items(const std::vector<LegendLayerView>& layers) {
    Json items = Json::array();
    for (const auto& layer : layers) {
        if (!layer.visible || layer.is_group) {
            continue;
        }
        std::string color = layer.style_fill;
        if (color.empty()) {
            color = layer.style_stroke;
        }
        if (color.empty()) {
            color = kLegendSwatchFallback;
        }
        items.push_back(Json{{"label", layer.name}, {"color", color}});
    }
    return items;
}

Json overlay_decorations(const Json& chrome,
                         const std::string& document_name,
                         const std::vector<LegendLayerView>& layers) {
    std::string title = field_value_str(chrome, "title", "");
    if (title.empty()) {
        title = document_name;
    }
    Json elements = field_value(chrome, "elements", Json(nullptr));
    if (!elements.is_array() || elements.empty()) {
        elements = Json::array();
        for (const auto& element : default_chrome_elements()) {
            elements.push_back(element);
        }
    }
    return Json{{"title", title},
                {"elements", std::move(elements)},
                {"legend_items", legend_items(layers)}};
}

Json unified_overlay_state(const Json& selected_features,
                           const Json& capture_points, const Json& snap_point,
                           const Json& chrome,
                           const std::string& document_name,
                           const std::vector<LegendLayerView>& layers) {
    return Json{
        {"selected_features",
         selected_features.is_array() ? selected_features : Json::array()},
        {"capture_points",
         capture_points.is_array() ? capture_points : Json::array()},
        {"snap_point", snap_point},
        {"decorations",
         overlay_decorations(chrome, document_name, layers)}};
}

std::vector<std::string> snapshot_source_version_ids(const Json& snapshot) {
    std::vector<std::string> ids;
    std::set<std::string> seen;
    const Json layers = field_value(snapshot, "layers", Json::array());
    if (!layers.is_array()) {
        return ids;
    }
    for (const auto& layer : layers) {
        const Json raw =
            field_value(layer, "source_version_id", Json(nullptr));
        if (!raw.is_string()) {
            continue;
        }
        const std::string id = raw.get<std::string>();
        if (!id.empty() && !seen.count(id)) {
            seen.insert(id);
            ids.push_back(id);
        }
    }
    return ids;
}

// ---------------------------------------------------------------------------
// Extent math + history
// ---------------------------------------------------------------------------

double map_units_per_pixel(const Extent& view_extent, int width_px,
                           int height_px) {
    const int w = std::max(1, width_px);
    const int h = std::max(1, height_px);
    const double span_x = view_extent[2] - view_extent[0];
    const double span_y = view_extent[3] - view_extent[1];
    if (w <= 0 || h <= 0) {
        return 1.0;
    }
    const double per_pixel = std::max(span_x / w, span_y / h);
    if (!std::isfinite(per_pixel)) {
        return 1.0;
    }
    return per_pixel;
}

Extent zoom_by(const Extent& view_extent, double factor,
               std::optional<std::pair<double, double>> center) {
    if (factor <= 0.0) {
        throw std::invalid_argument("zoom factor must be positive");
    }
    const double cx = center.has_value()
                          ? center->first
                          : (view_extent[0] + view_extent[2]) / 2.0;
    const double cy = center.has_value()
                          ? center->second
                          : (view_extent[1] + view_extent[3]) / 2.0;
    return Extent{cx + (view_extent[0] - cx) * factor,
                  cy + (view_extent[1] - cy) * factor,
                  cx + (view_extent[2] - cx) * factor,
                  cy + (view_extent[3] - cy) * factor};
}

ExtentHistory::ExtentHistory() {
    entries_.push_back(Extent{0.0, 0.0, 1.0, 1.0});
    index_ = 0;
}

void ExtentHistory::record(const Extent& extent, bool coalesce) {
    if (index_ < entries_.size() - 1) {
        entries_.resize(index_ + 1);
    }
    if (coalesce && !entries_.empty()) {
        entries_.back() = extent;
    } else if (entries_.empty() || entries_.back() != extent) {
        entries_.push_back(extent);
        if (entries_.size() > 100) {
            entries_.erase(entries_.begin());
        }
    }
    index_ = entries_.size() - 1;
}

std::optional<Extent> ExtentHistory::previous() {
    if (!can_previous()) {
        return std::nullopt;
    }
    --index_;
    return entries_[index_];
}

std::optional<Extent> ExtentHistory::next() {
    if (!can_next()) {
        return std::nullopt;
    }
    ++index_;
    return entries_[index_];
}

// ---------------------------------------------------------------------------
// Toolbar strip groups
// ---------------------------------------------------------------------------

const std::vector<std::vector<std::string>>& toolbar_group_vocabulary() {
    static const std::vector<std::vector<std::string>> groups = {
        {"pan", "zoom_in", "zoom_out", "full_extent", "previous_extent",
         "next_extent", "refresh"},
        {"identify", "select", "select_rectangle", "measure_distance",
         "clear_selection", "select_all", "invert_selection"},
        {"toggle_editing", "save_edits", "rollback"},
        {"add_point", "add_line", "add_polygon", "add_rectangle",
         "add_circle", "add_ellipse", "add_arc", "add_regular_polygon",
         "add_sector", "move_feature", "vertex", "reshape", "add_ring",
         "add_part", "fault_cut", "boundary_reshape"},
        {"undo", "redo", "delete_selected", "duplicate_selected",
         "cut_features", "copy_features", "paste_features"},
        {"split", "merge", "explode_multipart", "collect_multipart",
         "delete_ring", "delete_part", "reverse_line", "simplify_feature",
         "smooth_feature", "offset_curve", "rotate_feature", "scale_feature",
         "snap_geometries", "trim_line", "extend_line", "fill_ring",
         "change_facies"},
        {"snapping", "avoid_intersections", "tracing", "vertex_scope",
         "topology", "cancel"},
    };
    return groups;
}

std::vector<std::vector<std::string>> toolbar_strip_groups(
    const std::vector<std::string>& registered_core_ids) {
    const std::set<std::string> core_set(registered_core_ids.begin(),
                                         registered_core_ids.end());
    std::vector<std::vector<std::string>> filtered;
    std::set<std::string> listed;
    for (const auto& group : toolbar_group_vocabulary()) {
        std::vector<std::string> row;
        for (const auto& action_id : group) {
            if (core_set.count(action_id)) {
                row.push_back(action_id);
                listed.insert(action_id);
            }
        }
        if (!row.empty()) {
            filtered.push_back(std::move(row));
        }
    }
    std::vector<std::string> leftovers;
    for (const auto& action_id : registered_core_ids) {
        if (!listed.count(action_id)) {
            leftovers.push_back(action_id);
        }
    }
    if (!leftovers.empty()) {
        filtered.push_back(std::move(leftovers));
    }
    return filtered;
}

// ---------------------------------------------------------------------------
// Tool-rebind decision
// ---------------------------------------------------------------------------

ToolRebind rebind_tool_after_layer_switch(
    const std::string& active_tool_action, bool has_authoring,
    const std::string& authoring_active_kind) {
    if (active_tool_action.empty()) {
        return ToolRebind::kNone;
    }
    if (active_tool_action == "pan" || active_tool_action == "zoom_in" ||
        active_tool_action == "zoom_out" ||
        active_tool_action == "measure_distance") {
        return ToolRebind::kKeep;
    }
    if (layer_bound_tool_actions().count(active_tool_action)) {
        return ToolRebind::kRebind;
    }
    const auto kind_it =
        kind_bound_tool_actions().find(active_tool_action);
    if (kind_it != kind_bound_tool_actions().end()) {
        if (!has_authoring || authoring_active_kind != kind_it->second) {
            return ToolRebind::kDeactivatePan;
        }
    }
    return ToolRebind::kKeep;
}

// ---------------------------------------------------------------------------
// Kind visibility authority chain (mapping_page._kind_visibility)
// ---------------------------------------------------------------------------

bool json_truthy(const Json& value) {
    if (value.is_null()) {
        return false;
    }
    if (value.is_boolean()) {
        return value.get<bool>();
    }
    if (value.is_number()) {
        return value.get<double>() != 0.0;
    }
    if (value.is_string()) {
        return !value.get<std::string>().empty();
    }
    if (value.is_array() || value.is_object()) {
        return !value.empty();
    }
    return false;
}

bool kind_visibility(bool has_registry_and_document,
                     const Json& registry_layer,
                     const Json& composition_entries,
                     const std::string& wanted_layer_id,
                     bool tree_visible) {
    if (has_registry_and_document) {
        // Live registry entry wins over everything.
        if (registry_layer.is_object()) {
            return json_truthy(
                field_value(registry_layer, "visible", Json(nullptr)));
        }
        // Persisted layer_state["composition"] entry for "<doc>:<kind>".
        if (composition_entries.is_array()) {
            for (const auto& entry : composition_entries) {
                if (!entry.is_object()) {
                    continue;
                }
                if (field_value_str(entry, "id", "") == wanted_layer_id &&
                    entry.contains("visible")) {
                    return json_truthy(entry.at("visible"));
                }
            }
        }
    }
    return tree_visible;
}

// ---------------------------------------------------------------------------
// Work-area map core
// ---------------------------------------------------------------------------

std::string pick_well_id(
    const std::pair<double, double>& click_screen,
    const std::vector<WellPickCandidate>& candidates, double radius_px) {
    std::string best_id;
    double best_dist = radius_px;
    for (const auto& candidate : candidates) {
        const double dx = candidate.screen_x - click_screen.first;
        const double dy = candidate.screen_y - click_screen.second;
        const double dist = std::sqrt(dx * dx + dy * dy);
        if (dist <= best_dist) {
            best_dist = dist;
            best_id = candidate.well_id;
        }
    }
    return best_id;
}

namespace {

bool is_well_layer_id(const std::string& layer_id) {
    return layer_id == kWorkareaWellsLayerId ||
           layer_id == kWorkareaWellsFlaggedLayerId;
}

}  // namespace

std::vector<WellFeature> well_candidates_from_snapshot(const Json& snapshot) {
    std::vector<WellFeature> wells;
    const Json layers = field_value(snapshot, "layers", Json::array());
    if (!layers.is_array()) {
        return wells;
    }
    for (const auto& layer : layers) {
        const std::string layer_id = field_value_str(layer, "id", "");
        if (!is_well_layer_id(layer_id)) {
            continue;
        }
        const Json features = field_value(layer, "features", Json::array());
        if (!features.is_array()) {
            continue;
        }
        for (const auto& feature : features) {
            const Json geometry =
                field_value(feature, "geometry", Json::object());
            if (!geometry.is_object() ||
                field_value_str(geometry, "type", "") != "Point") {
                continue;
            }
            const Json coords =
                field_value(geometry, "coordinates", Json::array());
            if (!coords.is_array() || coords.size() < 2) {
                continue;
            }
            WellFeature well;
            try {
                well.x = coords.at(0).get<double>();
                well.y = coords.at(1).get<double>();
            } catch (const Json::exception&) {
                continue;
            }
            const Json properties =
                field_value(feature, "properties", Json::object());
            well.well_id = field_value_str(properties, "well_id", "");
            well.feature = feature;
            wells.push_back(std::move(well));
        }
    }
    return wells;
}

Json well_feature_by_id(const Json& snapshot, const std::string& well_id) {
    if (well_id.empty()) {
        return Json(nullptr);
    }
    for (const auto& candidate : well_candidates_from_snapshot(snapshot)) {
        if (candidate.well_id == well_id) {
            return candidate.feature;
        }
    }
    return Json(nullptr);
}

std::optional<Extent> workarea_view_extent(const Json& snapshot,
                                           double margin_ratio) {
    const Json layers = field_value(snapshot, "layers", Json::array());
    if (!layers.is_array()) {
        return std::nullopt;
    }
    std::vector<Extent> populated;
    for (const auto& layer : layers) {
        const Json features = field_value(layer, "features", Json::array());
        if (!features.is_array() || features.empty()) {
            continue;
        }
        const Json extent = field_value(layer, "extent", Json(nullptr));
        if (!extent.is_array() || extent.size() < 4) {
            continue;
        }
        try {
            populated.push_back(Extent{extent.at(0).get<double>(),
                                       extent.at(1).get<double>(),
                                       extent.at(2).get<double>(),
                                       extent.at(3).get<double>()});
        } catch (const Json::exception&) {
            continue;
        }
    }
    if (populated.empty()) {
        return std::nullopt;
    }
    double xmin = populated.front()[0], ymin = populated.front()[1];
    double xmax = populated.front()[2], ymax = populated.front()[3];
    for (const auto& extent : populated) {
        xmin = std::min(xmin, extent[0]);
        ymin = std::min(ymin, extent[1]);
        xmax = std::max(xmax, extent[2]);
        ymax = std::max(ymax, extent[3]);
    }
    const double dx =
        std::max({xmax - xmin, std::abs(xmin) * 1e-3, 1e-6}) * margin_ratio;
    const double dy =
        std::max({ymax - ymin, std::abs(ymin) * 1e-3, 1e-6}) * margin_ratio;
    return Extent{xmin - dx, ymin - dy, xmax + dx, ymax + dy};
}

Json workarea_overlay_state(const std::string& title, bool show_legend,
                            const Json& selected_feature) {
    Json elements = Json::array();
    elements.push_back("比例尺");
    elements.push_back("指北针");
    if (!title.empty()) {
        elements.push_back("标题栏");
    }
    if (show_legend) {
        elements.push_back("图例");
    }
    Json legend = Json::array();
    for (const auto& [label, color] : workarea_legend_items()) {
        legend.push_back(Json{{"label", label}, {"color", color}});
    }
    Json state = Json{{"decorations",
                       Json{{"title", title},
                            {"elements", std::move(elements)},
                            {"legend_items", std::move(legend)}}}};
    if (selected_feature.is_object()) {
        state["selected_features"] = Json::array({selected_feature});
    }
    return state;
}

Extent well_zoom_extent(double x, double y, const Extent& view_extent) {
    const double half = std::max(
        {(view_extent[2] - view_extent[0]) / 2.0,
         (view_extent[3] - view_extent[1]) / 2.0, 1.0});
    const double span = half * 0.2;
    return Extent{x - span, y - span, x + span, y + span};
}

Json domain_signature(const Json& project) {
    const Json wells = field_value(project, "wells", Json::array());
    const Json surveys =
        field_value(project, "seismic_surveys", Json::array());
    const Json links =
        field_value(project, "entity_asset_links", Json::array());
    const Json entities =
        field_value(project, "geological_entities", Json::array());
    const Json workarea = field_value(project, "workarea", Json::object());
    const Json coordinate = field_value(project, "coordinate", Json::object());

    Json well_rows = Json::array();
    if (wells.is_array()) {
        for (const auto& well : wells) {
            well_rows.push_back(Json::array(
                {field_value(well, "id", Json(nullptr)),
                 field_value(well, "name", Json(nullptr)),
                 field_value(well, "uwi", Json(nullptr)),
                 field_value(well, "aliases", Json::array()),
                 field_value(well, "surface_x", Json(nullptr)),
                 field_value(well, "surface_y", Json(nullptr)),
                 field_value(well, "coordinate_status", Json(nullptr)),
                 field_value(well, "project_x", Json(nullptr)),
                 field_value(well, "project_y", Json(nullptr)),
                 field_value(well, "spatial_scope", Json(nullptr))}));
        }
    }
    Json survey_rows = Json::array();
    if (surveys.is_array()) {
        for (const auto& survey : surveys) {
            const Json extent =
                field_value(survey, "extent", Json(nullptr));
            survey_rows.push_back(Json::array(
                {field_value(survey, "id", Json(nullptr)),
                 field_value(survey, "name", Json(nullptr)),
                 field_value(survey, "crs", Json(nullptr)),
                 extent.is_array() && !extent.empty()}));
        }
    }
    Json entity_ids = Json::array();
    if (entities.is_array()) {
        for (const auto& entity : entities) {
            entity_ids.push_back(field_value(entity, "id", Json(nullptr)));
        }
    }
    const Json boundary = field_value(workarea, "boundary", Json(nullptr));
    return Json::array(
        {wells.is_array() ? wells.size() : 0,
         std::move(well_rows), std::move(survey_rows),
         std::move(entity_ids),
         links.is_array() ? links.size() : 0,
         field_value_str(coordinate, "project_crs", ""),
         boundary.is_array() && !boundary.empty()});
}

// ---------------------------------------------------------------------------
// Preview payload normalization (viz.mapping_helpers)
// ---------------------------------------------------------------------------

Json close_ring(const Json& ring) {
    Json pts = Json::array();
    if (!ring.is_array()) {
        return pts;
    }
    for (const auto& point : ring) {
        if (!point.is_array() || point.size() < 2) {
            continue;
        }
        try {
            pts.push_back(Json::array(
                {point.at(0).get<double>(), point.at(1).get<double>()}));
        } catch (const Json::exception&) {
            continue;
        }
    }
    if (!pts.empty() && pts.front() != pts.back()) {
        pts.push_back(pts.front());
    }
    return pts;
}

namespace {

Json normalize_rings(const Json& coordinates) {
    Json rings = Json::array();
    if (!coordinates.is_array()) {
        return rings;
    }
    for (const auto& ring : coordinates) {
        if (!ring.is_array()) {
            continue;
        }
        rings.push_back(close_ring(ring));
    }
    return rings;
}

bool rings_valid(const Json& rings) {
    if (!rings.is_array() || rings.empty()) {
        return false;
    }
    for (const auto& ring : rings) {
        if (!ring.is_array() || ring.size() < 4) {
            return false;
        }
    }
    return true;
}

Json facies_properties(const Json& raw) {
    Json props = field_value(raw, "properties", Json::object());
    if (!props.is_object()) {
        props = Json::object();
    }
    std::string name = field_value_str(raw, "name", "");
    if (name.empty()) {
        name = field_value_str(raw, "facies", "");
    }
    if (name.empty()) {
        name = field_value_str(raw, "label", "");
    }
    if (!props.contains("name")) {
        props["name"] = name;
    }
    if (!props.contains("facies")) {
        // Python: props.get("name") or name — falsy values fall back.
        const Json existing = field_value(props, "name", Json(nullptr));
        const bool falsy = existing.is_null() ||
            (existing.is_string() && existing.get<std::string>().empty()) ||
            (existing.is_boolean() && !existing.get<bool>()) ||
            (existing.is_number() && existing.get<double>() == 0.0);
        props["facies"] = falsy ? Json(name) : existing;
    }
    return props;
}

}  // namespace

Json normalize_geojson_geometry(const Json& geometry) {
    if (!geometry.is_object()) {
        return Json(nullptr);
    }
    const std::string type = field_value_str(geometry, "type", "");
    const Json coordinates =
        field_value(geometry, "coordinates", Json(nullptr));
    if (type == "Polygon" && coordinates.is_array()) {
        const Json rings = normalize_rings(coordinates);
        if (!rings_valid(rings)) {
            return Json(nullptr);
        }
        return Json{{"type", "Polygon"}, {"coordinates", rings}};
    }
    if (type == "MultiPolygon" && coordinates.is_array()) {
        Json polygons = Json::array();
        for (const auto& polygon : coordinates) {
            if (!polygon.is_array()) {
                return Json(nullptr);
            }
            const Json rings = normalize_rings(polygon);
            if (!rings_valid(rings)) {
                return Json(nullptr);
            }
            polygons.push_back(rings);
        }
        if (polygons.empty()) {
            return Json(nullptr);
        }
        return Json{{"type", "MultiPolygon"}, {"coordinates", polygons}};
    }
    return Json(nullptr);
}

Json facies_to_geojson(const Json& raw) {
    if (!raw.is_object()) {
        return Json(nullptr);
    }
    if (field_value_str(raw, "type", "") == "Feature" &&
        field_value(raw, "geometry", Json(nullptr)).is_object()) {
        Json feature = Json{{"type", "Feature"},
                            {"properties", facies_properties(raw)},
                            {"geometry",
                             field_value(raw, "geometry", Json::object())}};
        const Json id = field_value(raw, "id", Json(nullptr));
        if (!id.is_null()) {
            feature["id"] = id;
        }
        return feature;
    }
    const Json geometry = field_value(raw, "geometry", Json(nullptr));
    if (geometry.is_object()) {
        const Json normalized = normalize_geojson_geometry(geometry);
        if (!normalized.is_null()) {
            Json feature = Json{{"type", "Feature"},
                                {"properties", facies_properties(raw)},
                                {"geometry", normalized}};
            const Json id = field_value(raw, "id", Json(nullptr));
            if (!id.is_null()) {
                feature["id"] = id;
            }
            return feature;
        }
    }
    // Raw coordinates form: GeoJSON Polygon [[[x,y],...]] -> ring is
    // coordinates[0]; editor ring [[x,y],...] -> ring is coordinates itself.
    const Json coordinates =
        field_value(raw, "coordinates", Json(nullptr));
    if (coordinates.is_array() && !coordinates.empty()) {
        const Json& first = coordinates.at(0);
        const bool nested = first.is_array() && !first.empty() &&
                            first.at(0).is_array();
        const Json rings =
            Json::array({close_ring(nested ? first : coordinates)});
        if (rings_valid(rings)) {
            Json feature =
                Json{{"type", "Feature"},
                     {"properties", facies_properties(raw)},
                     {"geometry",
                      Json{{"type", "Polygon"}, {"coordinates", rings}}}};
            const Json id = field_value(raw, "id", Json(nullptr));
            if (!id.is_null()) {
                feature["id"] = id;
            }
            return feature;
        }
    }
    return Json(nullptr);
}

Json well_to_lnglat(const Json& raw) {
    if (!raw.is_object()) {
        return Json(nullptr);
    }
    double lng = 0.0;
    double lat = 0.0;
    const Json coordinates =
        field_value(raw, "coordinates", Json(nullptr));
    const Json raw_lng = field_value(raw, "lng", Json(nullptr));
    const Json raw_lat = field_value(raw, "lat", Json(nullptr));
    try {
        if (coordinates.is_array()) {
            if (coordinates.size() < 2) {
                return Json(nullptr);
            }
            lng = coordinates.at(0).get<double>();
            lat = coordinates.at(1).get<double>();
        } else if (!raw_lng.is_null() && !raw_lat.is_null()) {
            lng = raw_lng.get<double>();
            lat = raw_lat.get<double>();
        } else {
            const Json x = field_value(raw, "x",
                                       field_value(raw, "lon", Json(0.0)));
            const Json y = field_value(raw, "y",
                                       field_value(raw, "lat", Json(0.0)));
            lng = x.get<double>();
            lat = y.get<double>();
        }
    } catch (const Json::exception&) {
        return Json(nullptr);
    }
    std::string name = field_value_str(raw, "name", "");
    if (name.empty()) {
        name = field_value_str(raw, "well_name", "");
    }
    return Json{{"name", name}, {"lng", lng}, {"lat", lat}};
}

Json preview_payload_from_document(const Json& document) {
    Json features = Json::array();
    Json wells = Json::array();
    std::string period;
    if (!document.is_object()) {
        return Json{{"features", features},
                    {"wells", wells},
                    {"period", period}};
    }
    const Json raw_polygons =
        field_value(document, "facies_polygons", Json::array());
    if (raw_polygons.is_array()) {
        for (const auto& raw : raw_polygons) {
            const Json feature = facies_to_geojson(
                raw.is_object() ? raw : Json::object());
            if (!feature.is_null()) {
                features.push_back(feature);
            }
        }
    }
    const Json raw_wells =
        field_value(document, "well_overlays", Json::array());
    if (raw_wells.is_array()) {
        for (const auto& raw : raw_wells) {
            const Json well = well_to_lnglat(
                raw.is_object() ? raw : Json::object());
            if (!well.is_null()) {
                wells.push_back(well);
            }
        }
    }
    period = field_value_str(document, "linked_target_horizon", "");
    return Json{{"features", std::move(features)},
                {"wells", std::move(wells)},
                {"period", period}};
}

Json preview_payload_from_features(const Json& features,
                                   const std::string& period_name) {
    Json facies_out = Json::array();
    Json wells_out = Json::array();
    if (features.is_array()) {
        for (const auto& record : features) {
            if (!record.is_object()) {
                continue;
            }
            const std::string kind = field_value_str(record, "kind", "");
            if (kind == "facies") {
                const Json feature = facies_to_geojson(record);
                if (!feature.is_null()) {
                    facies_out.push_back(feature);
                }
            } else if (kind == "well") {
                const Json well = well_to_lnglat(record);
                if (!well.is_null()) {
                    wells_out.push_back(well);
                }
            }
        }
    }
    return Json{{"features", std::move(facies_out)},
                {"wells", std::move(wells_out)},
                {"period", period_name}};
}

std::set<std::string> removed_layer_ids(const Json& document) {
    std::set<std::string> ids;
    const Json state = field_value(document, "layer_state", Json::object());
    const Json removed = field_value(state, "removed_layer_ids",
                                     Json::array());
    if (!removed.is_array()) {
        return ids;
    }
    for (const auto& value : removed) {
        if (value.is_string()) {
            ids.insert(value.get<std::string>());
        } else if (value.is_number_integer()) {
            ids.insert(std::to_string(value.get<long long>()));
        } else if (value.is_number_unsigned()) {
            ids.insert(std::to_string(value.get<unsigned long long>()));
        } else if (!value.is_null()) {
            ids.insert(value.dump());
        }
    }
    return ids;
}

}  // namespace pwb::ui_map
