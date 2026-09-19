#include "pwb/closure_review/review_qc_core.hpp"

#include <pwb/mapping/polygonization.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <iterator>
#include <map>
#include <optional>
#include <set>
#include <utility>

namespace pwb::closure_review {

namespace {

using domain::Json;
using ui_data_core::MapRing;

const Json& empty_array() {
    static const Json value = Json::array();
    return value;
}

// root[key] when present-and-array, else a shared empty array.
const Json& section_array(const Json& root, const char* key) {
    const auto it = root.find(key);
    if (it != root.end() && it->is_array()) {
        return *it;
    }
    return empty_array();
}

Json* mutable_section_array(Json& root, const char* key) {
    const auto it = root.find(key);
    if (it != root.end() && it->is_array()) {
        return &*it;
    }
    return nullptr;
}

std::string string_or_empty(const Json& value) {
    return value.is_string() ? value.get<std::string>() : std::string();
}

std::string field_string(const Json& object, const char* key) {
    if (!object.is_object()) {
        return {};
    }
    const auto it = object.find(key);
    return it != object.end() ? string_or_empty(*it) : std::string();
}

// getattr(obj, key, default) parity: missing/null → the fallback.
Json field_or(const Json& object, const char* key, Json fallback) {
    if (object.is_object()) {
        const auto it = object.find(key);
        if (it != object.end() && !it->is_null()) {
            return *it;
        }
    }
    return fallback;
}

// Python str() of a JSON scalar for issue ids / refs.
std::string scalar_to_string(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_number_integer())
        return std::to_string(value.get<long long>());
    if (value.is_number_float()) {
        // Python str(1.5) = "1.5" (repr-based); ids/refs only need a
        // stable readable token.
        return value.dump();
    }
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    return {};
}

std::string display_id(const Json& object, const char* key_a,
                       const char* key_b) {
    const std::string a = field_string(object, key_a);
    return a.empty() ? field_string(object, key_b) : a;
}

// Python str.strip() (whitespace) for the horizon gates.
std::string strip_copy(const std::string& text) {
    const auto is_space = [](unsigned char c) {
        return std::isspace(c) != 0;
    };
    auto begin = text.begin();
    while (begin != text.end() && is_space(static_cast<unsigned char>(*begin))) {
        ++begin;
    }
    auto end = text.end();
    while (end != begin && is_space(static_cast<unsigned char>(*(end - 1)))) {
        --end;
    }
    return std::string(begin, end);
}

Json push_issue(Json& issues, IssueSpec spec) {
    issues.push_back(make_issue(spec));
    return issues.back();
}

// ---- geometry helpers --------------------------------------------------------

// _facies_ring parity: the exterior ring of a facies record, accepting bare
// rings, [[x,y],...] coordinates, and the GeoJSON {"geometry": Polygon}
// shape.
std::optional<MapRing> facies_ring(const Json& poly) {
    const auto coords_it = poly.find("coordinates");
    if (coords_it != poly.end() && coords_it->is_array() &&
        !coords_it->empty()) {
        const Json& first = (*coords_it)[0];
        if (first.is_number()) {
            return ui_data_core::ring_to_pts(*coords_it);
        }
        if (first.is_array() && !first.empty() && first[0].is_number()) {
            return ui_data_core::ring_to_pts(*coords_it);
        }
        if (first.is_array()) {
            return ui_data_core::ring_to_pts(first);
        }
        return std::nullopt;
    }
    const auto geom_it = poly.find("geometry");
    if (geom_it != poly.end() && geom_it->is_object()) {
        const auto type_it = geom_it->find("type");
        if (type_it != geom_it->end() && *type_it == "Polygon") {
            const auto rings_it = geom_it->find("coordinates");
            if (rings_it != geom_it->end() && rings_it->is_array() &&
                !rings_it->empty() && (*rings_it)[0].is_array()) {
                return ui_data_core::ring_to_pts((*rings_it)[0]);
            }
        }
    }
    return std::nullopt;
}

// _ring_to_polygon_geometry parity: float-pair coords, closed ring.
Json ring_to_polygon_geometry(const MapRing& ring) {
    Json coords = Json::array();
    for (const auto& point : ring) {
        coords.push_back(Json::array({point[0], point[1]}));
    }
    if (!coords.empty()) {
        const Json& front = coords.front();
        const Json& back = coords.back();
        if (front[0] != back[0] || front[1] != back[1]) {
            coords.push_back(front);
        }
    }
    Json geometry = Json::object();
    geometry["type"] = "Polygon";
    geometry["coordinates"] = Json::array({coords});
    return geometry;
}

// geoviz validate_ring parity (the ui_data_core port): does this ring
// self-intersect?
bool ring_self_intersects(const MapRing& ring) {
    const Json issues = ui_data_core::validate_ring(ring);
    for (const auto& issue : issues) {
        if (issue.is_object() &&
            field_string(issue, "code") == "self_intersection") {
            return true;
        }
    }
    return false;
}

// mapping-kernel ring for the centroid facade.
std::optional<mapping::Ring> to_kernel_ring(const Json& ring_json) {
    if (!ring_json.is_array() || ring_json.empty() ||
        !ring_json[0].is_array()) {
        return std::nullopt;
    }
    const MapRing ring = ui_data_core::ring_to_pts(ring_json);
    if (ring.size() < 3) {
        return std::nullopt;
    }
    mapping::Ring points;
    points.reserve(ring.size());
    for (const auto& point : ring) {
        points.push_back(mapping::Point{point[0], point[1]});
    }
    return points;
}

// _flatten_coords parity: [x, y] or nested lists → point list.
std::vector<std::pair<double, double>> flatten_coords(const Json& coords) {
    std::vector<std::pair<double, double>> out;
    if (!coords.is_array()) {
        return out;
    }
    if (coords.size() >= 2) {
        bool all_numbers = true;
        for (const auto& value : coords) {
            if (!value.is_number()) {
                all_numbers = false;
                break;
            }
        }
        if (all_numbers) {
            out.emplace_back(coords[0].get<double>(),
                             coords[1].get<double>());
            return out;
        }
    }
    for (const auto& item : coords) {
        auto nested = flatten_coords(item);
        out.insert(out.end(), nested.begin(), nested.end());
    }
    return out;
}

std::string format_xy(double x, double y) {
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "(%.2f, %.2f)", x, y);
    return buffer;
}

// ---- basic rule collectors (workflow/qc.py _collect_issues parity) -----

bool is_contour_line_feature(const Json& feature) {
    if (field_string(feature, "role") == "contour") {
        return true;
    }
    const auto props_it = feature.find("properties");
    if (props_it == feature.end() || !props_it->is_object()) {
        return false;
    }
    const Json& props = *props_it;
    return field_string(props, "role") == "contour" ||
           field_string(props, "constraint_role") == "contour";
}

int count_contour_lines(const Json& document) {
    int n = 0;
    for (const auto& feature : section_array(document, "line_features")) {
        if (feature.is_object() && is_contour_line_feature(feature)) {
            ++n;
        }
    }
    return n;
}

Json collect_basic_issues(const Json& root, const Json& document) {
    Json issues = Json::array();
    const std::string doc_id = field_string(document, "id");
    const std::string map_ref = "map:" + doc_id;

    // 1) Target horizon (map-level, no geometry). Python:
    //    not (document.linked_target_horizon or "").strip()
    const auto horizon_it = document.find("linked_target_horizon");
    std::string horizon;
    if (horizon_it != document.end() && horizon_it->is_string()) {
        horizon = horizon_it->get<std::string>();
    }
    horizon = strip_copy(horizon);
    if (horizon.empty()) {
        push_issue(issues,
                   {.rule = "target_horizon_present",
                    .severity = "error",
                    .message = "古地理图未关联目标层位",
                    .feature_id = doc_id,
                    .feature_kind = "map",
                    .ref = map_ref});
    }

    // 2–3) Facies presence + per-polygon geometry.
    const Json& facies = section_array(document, "facies_polygons");
    if (facies.empty()) {
        push_issue(issues,
                   {.rule = "facies_polygons_present",
                    .severity = "warning",
                    .message = "古地理图尚无相带多边形",
                    .feature_id = doc_id,
                    .feature_kind = "map",
                    .ref = map_ref});
    } else {
        for (const auto& poly : facies) {
            if (!poly.is_object()) {
                push_issue(issues,
                           {.rule = "facies_geometry_valid",
                            .severity = "error",
                            .message = "相带记录格式无效",
                            .feature_kind = "facies",
                            .ref = map_ref});
                continue;
            }
            const std::string fid = display_id(poly, "id", "name");
            const std::string label = fid.empty() ? std::string("?") : fid;
            const std::string feature_ref =
                fid.empty() ? map_ref : map_ref + "/facies/" + fid;
            const auto ring = facies_ring(poly);
            if (!ring || ring->size() < 3) {
                push_issue(issues,
                           {.rule = "facies_geometry_valid",
                            .severity = "error",
                            .message = "相带 " + label + " 顶点不足或缺少坐标",
                            .feature_id = fid,
                            .feature_kind = "facies",
                            .ref = feature_ref});
                continue;
            }
            if (ring_self_intersects(*ring)) {
                push_issue(issues,
                           {.rule = "facies_geometry_valid",
                            .severity = "error",
                            .message = "相带 " + label + " 自相交",
                            .feature_id = fid,
                            .feature_kind = "facies",
                            .geometry = ring_to_polygon_geometry(*ring),
                            .ref = feature_ref,
                            .extra = Json{{"code", "self_intersection"}}});
            }
        }
    }

    // 4) Well overlays.
    if (section_array(document, "well_overlays").empty()) {
        push_issue(issues,
                   {.rule = "well_overlays_present",
                    .severity = "warning",
                    .message = "图面无井位叠加，编图证据不足",
                    .feature_id = doc_id,
                    .feature_kind = "map",
                    .ref = map_ref});
    }

    // 5) Contour isolines.
    if (count_contour_lines(document) == 0) {
        push_issue(
            issues,
            {.rule = "contour_lines_present",
             .severity = "warning",
             .message = "尚无等值线（ContourDraft）线要素，建议从制备生成初稿",
             .feature_id = doc_id,
             .feature_kind = "map",
             .ref = map_ref});
    }

    // 6) WellTable QC: one spatial issue per flagged sample.
    for (const auto& table : section_array(root, "well_tables")) {
        if (!table.is_object()) {
            continue;
        }
        const std::string table_h = field_string(table, "target_horizon");
        if (!horizon.empty() && !table_h.empty() && table_h != horizon) {
            continue;
        }
        const std::string table_id = field_string(table, "id");
        for (const auto& row : section_array(table, "rows")) {
            if (!row.is_object()) {
                continue;
            }
            const auto flag_it = row.find("qc_flag");
            const std::string flag =
                flag_it != row.end() ? string_or_empty(*flag_it) : "ok";
            if (flag.empty() || flag == "ok") {
                continue;
            }
            const std::string wid = display_id(row, "well_id", "name");
            Json geometry = Json();  // null unless x/y are numeric
            const auto x_it = row.find("x");
            const auto y_it = row.find("y");
            if (x_it != row.end() && y_it != row.end() &&
                x_it->is_number() && y_it->is_number()) {
                geometry = Json{{"type", "Point"},
                                {"coordinates",
                                 Json::array({*x_it, *y_it})}};
            }
            const std::string display_name =
                field_string(row, "name").empty() ? wid
                                                  : field_string(row, "name");
            Json extra = Json::object();
            extra["qc_flag"] = flag;
            const auto z_it = row.find("qc_z_star");
            extra["qc_z_star"] = z_it != row.end() ? *z_it : Json();
            push_issue(
                issues,
                {.rule = "well_table_qc_clean",
                 .severity = "warning",
                 .message = "井点 " + display_name + " 质控=" + flag,
                 .feature_id = wid,
                 .feature_kind = "well",
                 .geometry = geometry,
                 .ref = wid.empty() ? "well_table:" + table_id
                                    : "well_table:" + table_id + "/" + wid,
                 .extra = extra});
        }
    }

    return issues;
}

// ---- extended collectors (workflow/map_qa_rules.py parity) --------------

Json collect_layer_crs_issues(const Json& root, const Json& document) {
    Json issues = Json::array();
    const std::string map_crs = field_string(document, "map_crs");
    if (map_crs.empty()) {
        push_issue(
            issues,
            {.rule = "crs_undeclared",
             .severity = "warning",
             .message = "图面未声明 CRS——按契约这是合法但需显式确认的状态",
             .ref = field_string(document, "id")});
    }
    for (const auto& layer : section_array(root, "user_vector_layers")) {
        if (!layer.is_object()) {
            continue;
        }
        const std::string layer_crs = field_string(layer, "crs");
        const std::string layer_name = field_string(layer, "name");
        if (layer_crs.empty()) {
            push_issue(issues,
                       {.rule = "crs_undeclared",
                        .severity = "warning",
                        .message = "图层 " + layer_name + " 未声明 CRS",
                        .feature_kind = "layer",
                        .ref = field_string(layer, "id")});
        } else if (!map_crs.empty() && layer_crs != map_crs) {
            push_issue(issues,
                       {.rule = "crs_mismatch",
                        .severity = "error",
                        .message = "图层 " + layer_name + " CRS " + layer_crs +
                                   " 与图面 CRS " + map_crs + " 不一致",
                        .feature_kind = "layer",
                        .ref = field_string(layer, "id")});
        }
    }
    return issues;
}

// _renderer_class_issues parity: a categorized style must cover the values
// actually present in its field.
Json collect_renderer_class_issues(const Json& root, const Json& document) {
    Json issues = Json::array();

    auto check_style = [&](const Json& style, const Json& features,
                           const std::string& default_field,
                           const std::string& label, const std::string& ref,
                           const std::string& kind) {
        if (!style.is_object() ||
            field_string(style, "renderer") != "categorized") {
            return;
        }
        std::string field_name = field_string(style, "field");
        if (field_name.empty()) {
            field_name = default_field;
        }
        if (field_name.empty()) {
            return;
        }
        std::set<std::string> categories;
        const auto cats_it = style.find("categories");
        if (cats_it != style.end() && cats_it->is_array()) {
            for (const auto& category : *cats_it) {
                if (category.is_array() && !category.empty() &&
                    !category[0].is_null()) {
                    categories.insert(scalar_to_string(category[0]));
                }
            }
        } else if (cats_it != style.end() && cats_it->is_object()) {
            for (auto it = cats_it->begin(); it != cats_it->end(); ++it) {
                categories.insert(it.key());
            }
        }
        std::set<std::string> present;
        for (const auto& feature : features) {
            if (!feature.is_object()) {
                continue;
            }
            const auto props_it = feature.find("properties");
            if (props_it == feature.end() || !props_it->is_object()) {
                continue;
            }
            const auto value_it = props_it->find(field_name);
            if (value_it != props_it->end() && !value_it->is_null()) {
                present.insert(scalar_to_string(*value_it));
            }
        }
        std::vector<std::string> missing;
        std::set_difference(present.begin(), present.end(),
                            categories.begin(), categories.end(),
                            std::back_inserter(missing));
        if (missing.empty()) {
            return;
        }
        std::string joined;
        for (const auto& value : missing) {
            if (!joined.empty()) {
                joined += ", ";
            }
            joined += "'" + value + "'";
        }
        Json extra = Json::object();
        extra["missing_classes"] = Json(missing);
        extra["field"] = field_name;
        push_issue(issues,
                   {.rule = "class_renderer_mismatch",
                    .severity = "warning",
                    .message = label + "分类样式缺少字段 " + field_name +
                               " 的值 {" + joined + "}（" +
                               std::to_string(missing.size()) +
                               " 项无法按样式呈现）",
                    .feature_kind = kind,
                    .ref = ref,
                    .extra = extra});
    };

    for (const auto& layer : section_array(root, "user_vector_layers")) {
        if (!layer.is_object()) {
            continue;
        }
        check_style(field_or(layer, "style", Json()),
                    section_array(layer, "features"), "",
                    "图层 " + field_string(layer, "name") + " ",
                    field_string(layer, "id"), "layer");
    }
    // The facies surface: facies_style vs the facies_name values present.
    Json facies_features = Json::array();
    for (const auto& poly : section_array(document, "facies_polygons")) {
        if (!poly.is_object()) {
            continue;
        }
        Json wrapped = Json::object();
        const auto props_it = poly.find("properties");
        if (props_it != poly.end() && props_it->is_object() &&
            json_truthy(*props_it)) {
            wrapped["properties"] = *props_it;
        } else {
            const auto name_it = poly.find("facies_name");
            wrapped["properties"] =
                Json::object({{"facies_name",
                               name_it != poly.end() ? *name_it : Json()}});
        }
        facies_features.push_back(wrapped);
    }
    check_style(field_or(document, "facies_style", Json()), facies_features,
                "facies_name", "相带面 ", field_string(document, "id"),
                "facies");
    return issues;
}

Json collect_extent_issues(const Json& root, const Json& document,
                           const Json* map_extent) {
    Json issues = Json::array();
    // The extent comes from the caller, or the document's view_state; with
    // neither, out-of-bound checks are impossible and are skipped rather
    // than guessed (the coverage map records the skip).
    Json extent = Json();
    if (map_extent != nullptr && json_truthy(*map_extent)) {
        extent = *map_extent;
    } else {
        const auto view_it = document.find("view_state");
        if (view_it != document.end() && view_it->is_object()) {
            const auto extent_it = view_it->find("extent");
            if (extent_it != view_it->end() && json_truthy(*extent_it)) {
                extent = *extent_it;
            }
        }
    }
    if (!extent.is_array() || extent.size() != 4) {
        return issues;
    }
    if (!std::all_of(extent.begin(), extent.end(),
                     [](const Json& v) { return v.is_number(); })) {
        return issues;
    }
    const double xmin = extent[0].get<double>();
    const double ymin = extent[1].get<double>();
    const double xmax = extent[2].get<double>();
    const double ymax = extent[3].get<double>();
    const auto out_of_bound = [&](double x, double y) {
        return x < xmin || x > xmax || y < ymin || y > ymax;
    };
    const std::string doc_id = field_string(document, "id");

    for (const auto& layer : section_array(root, "user_vector_layers")) {
        if (!layer.is_object()) {
            continue;
        }
        const std::string layer_id = field_string(layer, "id");
        for (const auto& feature : section_array(layer, "features")) {
            if (!feature.is_object()) {
                continue;
            }
            const auto geom_it = feature.find("geometry");
            if (geom_it == feature.end() || !geom_it->is_object()) {
                continue;
            }
            const auto coords_it = geom_it->find("coordinates");
            if (coords_it == geom_it->end()) {
                continue;
            }
            for (const auto& point : flatten_coords(*coords_it)) {
                if (out_of_bound(point.first, point.second)) {
                    push_issue(issues,
                               {.rule = "out_of_bound_feature",
                                .severity = "warning",
                                .message = "要素坐标 " +
                                           format_xy(point.first,
                                                     point.second) +
                                           " 超出图面范围",
                                // Python keys layer features by id only
                                // (map_qa_rules.py:195).
                                .feature_id = scalar_to_string(field_or(
                                    feature, "id", Json())),
                                .feature_kind = "layer",
                                .geometry = *geom_it,
                                .ref = layer_id});
                    break;  // one issue per feature is enough to locate it
                }
            }
        }
    }
    for (const auto& entry : {std::pair<const char*, const char*>{
                                  "facies", "facies_polygons"},
                              {"line", "line_features"}}) {
        const std::string kind = entry.first;
        const Json& payload = section_array(document, entry.second);
        for (std::size_t index = 0; index < payload.size(); ++index) {
            const Json& feature = payload[index];
            if (!feature.is_object()) {
                continue;
            }
            const auto geom_it = feature.find("geometry");
            if (geom_it == feature.end() || !geom_it->is_object()) {
                continue;
            }
            const auto coords_it = geom_it->find("coordinates");
            if (coords_it == geom_it->end() || !json_truthy(*coords_it)) {
                continue;
            }
            for (const auto& point : flatten_coords(*coords_it)) {
                if (out_of_bound(point.first, point.second)) {
                    const auto fid_it = feature.find("feature_id");
                    const auto id_it = feature.find("id");
                    std::string feature_id;
                    if (fid_it != feature.end() && !fid_it->is_null()) {
                        feature_id = scalar_to_string(*fid_it);
                    } else if (id_it != feature.end() && !id_it->is_null()) {
                        feature_id = scalar_to_string(*id_it);
                    } else {
                        feature_id = kind + "_" + std::to_string(index);
                    }
                    push_issue(issues,
                               {.rule = "out_of_bound_feature",
                                .severity = "warning",
                                .message = "要素坐标 " +
                                           format_xy(point.first,
                                                     point.second) +
                                           " 超出图面范围",
                                .feature_id = feature_id,
                                .feature_kind = kind,
                                .geometry = *geom_it,
                                .ref = doc_id});
                    break;
                }
            }
        }
    }
    return issues;
}

Json collect_data_health_issues(const Json& root) {
    Json issues = Json::array();
    std::map<std::string, const Json*> tables;
    for (const auto& table : section_array(root, "well_tables")) {
        if (table.is_object()) {
            tables[field_string(table, "id")] = &table;
        }
    }
    for (const auto& task : section_array(root, "factor_map_tasks")) {
        if (!task.is_object()) {
            continue;
        }
        const std::string table_id = field_string(task, "well_table_id");
        if (!table_id.empty()) {
            const auto it = tables.find(table_id);
            if (it != tables.end() &&
                section_array(*it->second, "rows").empty()) {
                push_issue(issues,
                           {.rule = "well_table_empty",
                            .severity = "warning",
                            .message = "因子 " +
                                       field_string(task, "factor_type") +
                                       " 引用的井表 " + table_id +
                                       " 无数据行",
                            .ref = field_string(task, "id")});
            }
        }
        const auto grid_it = task.find("grid_artifact_version_id");
        const bool has_grid = grid_it != task.end() && json_truthy(*grid_it);
        if (field_string(task, "status") == "complete" && !has_grid) {
            push_issue(issues,
                       {.rule = "stale_inputs",
                        .severity = "warning",
                        .message = "因子任务 " + field_string(task, "name") +
                                   " 已完成但无持久化栅格版本（重算后未保存？）",
                        .ref = field_string(task, "id")});
        }
    }
    std::set<std::string> known_refs;
    for (const char* kind : {"horizon_interpretations",
                             "correlation_interpretations",
                             "fault_interpretations"}) {
        for (const auto& ref : section_array(root, kind)) {
            const auto id_it = ref.find("id");
            if (id_it != ref.end()) {
                known_refs.insert(scalar_to_string(*id_it));
            }
        }
    }
    for (const auto& record : section_array(root, "map_products")) {
        if (!record.is_object()) {
            continue;
        }
        for (const auto& ref_id :
             section_array(record, "interpretation_refs")) {
            const std::string ref = scalar_to_string(ref_id);
            if (!known_refs.count(ref)) {
                Json extra = Json::object();
                extra["product"] = field_string(record, "product_name");
                push_issue(issues,
                           {.rule = "broken_external_reference",
                            .severity = "error",
                            .message = "产品 " +
                                       field_string(record, "product_name") +
                                       " 引用的解释 " + ref + " 不存在",
                            .feature_kind = "interpretation",
                            .ref = ref,
                            .extra = extra});
            }
        }
    }
    return issues;
}

Json collect_confidence_issues(const Json& confidence, double threshold) {
    if (!json_truthy(confidence)) {
        return Json::array();
    }
    const auto min_it = confidence.find("min");
    if (min_it == confidence.end() || !min_it->is_number()) {
        return Json::array();
    }
    const double minimum = min_it->get<double>();
    if (minimum >= threshold) {
        return Json::array();
    }
    const auto mean_it = confidence.find("mean");
    char min_buffer[32];
    char threshold_buffer[32];
    std::snprintf(min_buffer, sizeof(min_buffer), "%.2f", minimum);
    std::snprintf(threshold_buffer, sizeof(threshold_buffer), "%.2f",
                  threshold);
    Json extra = Json::object();
    extra["confidence_min"] = minimum;
    extra["confidence_mean"] =
        mean_it != confidence.end() ? *mean_it : Json();
    extra["threshold"] = threshold;
    Json issues = Json::array();
    push_issue(issues,
               {.rule = "low_confidence",
                .severity = "warning",
                .message = "融合最小置信度 " + std::string(min_buffer) +
                           " 低于阈值 " + std::string(threshold_buffer),
                .extra = extra});
    return issues;
}

Json collect_export_issues(const Json& export_report) {
    if (!json_truthy(export_report)) {
        return Json::array();
    }
    const std::string engine = field_string(export_report, "engine");
    const auto degraded_it = export_report.find("degraded");
    const bool degraded = degraded_it != export_report.end() &&
                          json_truthy(*degraded_it);
    if (engine != "fallback" && engine != "composer_fallback" && !degraded) {
        return Json::array();
    }
    std::string reason = field_string(export_report, "degraded_reason");
    if (reason.empty()) {
        reason = "未说明";
    }
    Json extra = Json::object();
    extra["degraded_reason"] = reason;
    Json issues = Json::array();
    push_issue(issues,
               {.rule = "export_fallback",
                .severity = "warning",
                .message = "成图导出使用了回退渲染器（" + reason +
                           "）——与屏显可能存在符号差异",
                .extra = extra});
    return issues;
}

Json extended_rule_coverage_map(const QcInputs& inputs) {
    Json coverage = Json::object();
    for (const char* rule : {"crs_undeclared", "crs_mismatch",
                             "class_renderer_mismatch", "well_table_empty",
                             "stale_inputs", "broken_external_reference"}) {
        coverage[rule] = Json{{"evaluated", true}, {"reason", ""}};
    }
    const bool has_extent =
        inputs.map_extent != nullptr && json_truthy(*inputs.map_extent);
    coverage["out_of_bound_feature"] =
        has_extent
            ? Json{{"evaluated", true}, {"reason", ""}}
            : Json{{"evaluated", false},
                   {"reason", "未提供图幅范围（map_extent）"}};
    const bool has_confidence = inputs.fusion_confidence != nullptr &&
                                json_truthy(*inputs.fusion_confidence);
    coverage["low_confidence"] =
        has_confidence
            ? Json{{"evaluated", true}, {"reason", ""}}
            : Json{{"evaluated", false}, {"reason", "未提供融合置信度数据"}};
    const bool has_export =
        inputs.export_report != nullptr && json_truthy(*inputs.export_report);
    coverage["export_fallback"] =
        has_export
            ? Json{{"evaluated", true}, {"reason", ""}}
            : Json{{"evaluated", false},
                   {"reason", "尚未执行导出（无导出报告）"}};
    return coverage;
}

}  // namespace

// ---- public API -------------------------------------------------------------

const std::vector<std::string>& basic_qc_rules() {
    static const std::vector<std::string> rules = {
        "target_horizon_present", "facies_polygons_present",
        "facies_geometry_valid",  "well_overlays_present",
        "contour_lines_present",  "well_table_qc_clean",
    };
    return rules;
}

const std::vector<std::string>& extended_qc_rules() {
    static const std::vector<std::string> rules = {
        "crs_undeclared",            "crs_mismatch",
        "class_renderer_mismatch",   "out_of_bound_feature",
        "well_table_empty",          "stale_inputs",
        "broken_external_reference", "low_confidence",
        "export_fallback",           "composition_incomplete",
    };
    return rules;
}

bool json_truthy(const domain::Json& value) {
    switch (value.type()) {
        case domain::Json::value_t::null:
        case domain::Json::value_t::discarded:
            return false;
        case domain::Json::value_t::boolean:
            return value.get<bool>();
        case domain::Json::value_t::string:
            return !value.get<std::string>().empty();
        case domain::Json::value_t::array:
        case domain::Json::value_t::object:
            return !value.empty();
        case domain::Json::value_t::number_integer:
            return value.get<long long>() != 0;
        case domain::Json::value_t::number_unsigned:
            return value.get<unsigned long long>() != 0;
        case domain::Json::value_t::number_float:
            return value.get<double>() != 0.0;
        default:
            return false;
    }
}

domain::Json make_issue(const IssueSpec& spec) {
    Json issue = Json::object();
    issue["rule"] = spec.rule;
    issue["severity"] = spec.severity;
    issue["message"] = spec.message;
    if (!spec.feature_id.empty()) {
        issue["feature_id"] = spec.feature_id;
    }
    if (!spec.feature_kind.empty()) {
        issue["feature_kind"] = spec.feature_kind;
    }
    if (!spec.ref.empty()) {
        issue["ref"] = spec.ref;
    }
    if (json_truthy(spec.geometry)) {
        issue["geometry"] = spec.geometry;
        const Json centroid = issue_locate_point(spec.geometry);
        if (json_truthy(centroid)) {
            issue["centroid"] = centroid;
        }
    }
    if (spec.extra.is_object()) {
        for (auto it = spec.extra.begin(); it != spec.extra.end(); ++it) {
            issue[it.key()] = it.value();
        }
    }
    return issue;
}

domain::Json issue_locate_point(const domain::Json& geometry) {
    // 面积质心优先（V8 M4 契约：面/多面统一面积质心）；退化面
    // （面积≈0，facade fail-closed ValueError）兜底顶点均值；畸形/无坐
    // 标几何按“无定位点”处理（fail-open：定位缺失不掩盖问题本身）。
    if (!geometry.is_object()) {
        return Json();
    }
    const auto coords_it = geometry.find("coordinates");
    if (coords_it == geometry.end() || !coords_it->is_array()) {
        return Json();
    }
    const std::string type = field_string(geometry, "type");
    if (type == "Point") {
        const auto flat = flatten_coords(*coords_it);
        if (flat.size() == 1) {
            return Json::array({flat[0].first, flat[0].second});
        }
        return Json();
    }
    auto locate_from_ring = [](const mapping::Ring& ring) -> Json {
        // mapping_kernel::ring_centroid returns the FIRST VERTEX for
        // degenerate rings; the qc contract falls back to the vertex MEAN
        // (workflow/qc.py _vertex_mean_locate_point) — mirror that here.
        if (std::fabs(2.0 * mapping::signed_area(ring)) <= 1e-12) {
            if (ring.empty()) {
                return Json();
            }
            double sx = 0.0;
            double sy = 0.0;
            for (const auto& point : ring) {
                sx += point[0];
                sy += point[1];
            }
            return Json::array({sx / static_cast<double>(ring.size()),
                                sy / static_cast<double>(ring.size())});
        }
        const mapping::Point centroid = mapping::ring_centroid(ring);
        if (std::isfinite(centroid[0]) && std::isfinite(centroid[1])) {
            return Json::array({centroid[0], centroid[1]});
        }
        return Json();
    };
    // Ring-shaped coordinates: Polygon exterior / bare ring.
    if (auto ring = to_kernel_ring(*coords_it)) {
        return locate_from_ring(*ring);
    }
    // Generic ring descent — bare ring → Polygon shell ([[ring]]) →
    // MultiPolygon ([[ [ring] ]]): the first level that yields a valid
    // ring (≥3 [x,y] pairs) locates the issue (facade centroid parity:
    // 面/多面统一取第一个外环).
    const Json* levels[3] = {&(*coords_it), nullptr, nullptr};
    if (!coords_it->empty() && (*coords_it)[0].is_array()) {
        levels[1] = &(*coords_it)[0];
        if (!(*coords_it)[0].empty() && (*coords_it)[0][0].is_array()) {
            levels[2] = &(*coords_it)[0][0];
        }
    }
    for (const Json* level : levels) {
        if (level == nullptr) {
            continue;
        }
        if (auto ring = to_kernel_ring(*level)) {
            return locate_from_ring(*ring);
        }
    }
    return Json();
}

std::string status_from_issues(const Json& issues) {
    bool warning = false;
    for (const auto& issue : issues) {
        std::string severity = issue.is_object()
                                   ? field_string(issue, "severity")
                                   : std::string();
        for (auto& c : severity) {
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
        if (severity == "error" || severity == "critical") {
            return "error";
        }
        if (severity == "warning") {
            warning = true;
        }
    }
    return warning ? "warning" : "pass";
}

domain::Json paleomap_documents_of(const Json& root) {
    return section_array(root, "paleomap_documents");
}

const Json* find_map_document(const Json& root, const std::string& doc_id) {
    // Iterate the SECTION BY REFERENCE — paleomap_documents_of() returns a
    // copy, and a pointer into that copy would dangle on return.
    const Json& docs = section_array(root, "paleomap_documents");
    for (const auto& doc : docs) {
        if (doc.is_object() && field_string(doc, "id") == doc_id) {
            return &doc;
        }
    }
    return nullptr;
}

domain::Json active_quality_reports_of(const Json& root) {
    const Json& runs = section_array(root, "compilation_runs");
    if (!runs.empty()) {
        const Json& run = runs.back();
        const auto report_it = run.find("active_quality_report_id");
        if (report_it != run.end() && report_it->is_string() &&
            !report_it->get<std::string>().empty()) {
            for (const auto& report :
                 section_array(root, "quality_reports")) {
                const auto id_it = report.find("id");
                if (id_it != report.end() && *id_it == *report_it) {
                    return Json::array({report});
                }
            }
        }
    }
    // Last report per linked map document (insertion order preserved).
    std::map<std::string, Json> by_map;
    std::vector<std::string> order;
    for (const auto& report : section_array(root, "quality_reports")) {
        const auto linked_it = report.find("linked_map_document_id");
        if (linked_it == report.end()) {
            continue;
        }
        const std::string linked = scalar_to_string(*linked_it);
        const auto it = by_map.find(linked);
        if (it == by_map.end()) {
            order.push_back(linked);
            by_map.emplace(linked, report);
        } else {
            it->second = report;
        }
    }
    Json result = Json::array();
    for (const auto& key : order) {
        result.push_back(by_map.at(key));
    }
    return result;
}

domain::Json geometry_cartographic_issues(const Json& /*root*/,
                                          const Json& map_document) {
    Json issues = Json::array();
    for (const auto& poly :
         section_array(map_document, "facies_polygons")) {
        if (!poly.is_object()) {
            continue;
        }
        const std::string fid = display_id(poly, "id", "name");
        const std::string label = fid.empty() ? std::string("?") : fid;
        const std::string doc_id = field_string(map_document, "id");
        const std::string feature_ref =
            fid.empty() ? doc_id : "map:" + doc_id + "/facies/" + fid;
        const auto coords_it = poly.find("coordinates");
        if (coords_it == poly.end() || !coords_it->is_array() ||
            coords_it->empty() || !(*coords_it)[0].is_array()) {
            continue;  // shape problems belong to the basic pass
        }
        const MapRing ring = ui_data_core::ring_to_pts(*coords_it);
        if (ring.size() < 3) {
            continue;  // vertex-count problems belong to the basic pass
        }
        auto push_cartographic = [&](const char* code,
                                     const std::string& message) {
            Json extra = Json::object();
            extra["code"] = code;
            push_issue(issues,
                       {.rule = std::string("cartographic_") + code,
                        .severity = "warning",
                        .message = "相带 " + label + "：" + message,
                        .feature_id = fid,
                        .feature_kind = "facies",
                        .ref = feature_ref,
                        .extra = extra});
        };
        // Unclosed exterior ring: the interoperable payload contract is a
        // closed ring (first vertex == last vertex).
        if (ring.front()[0] != ring.back()[0] ||
            ring.front()[1] != ring.back()[1]) {
            push_cartographic("unclosed_ring",
                              "外环未闭合（首末顶点不一致）");
        }
        // Duplicate consecutive vertices: degenerate edges corrupt area
        // and topology checks downstream.
        for (std::size_t i = 0; i + 1 < ring.size(); ++i) {
            if (ring[i][0] == ring[i + 1][0] &&
                ring[i][1] == ring[i + 1][1]) {
                push_cartographic("duplicate_vertices",
                                  "存在重复连续顶点（边 " +
                                      std::to_string(i) + "-" +
                                      std::to_string(i + 1) + "）");
                break;
            }
        }
        // Degenerate (zero-area) ring: collinear/identical vertices make
        // the polygon unrenderable and unmeasurable.
        mapping::Ring kernel_points;
        kernel_points.reserve(ring.size());
        for (const auto& p : ring) {
            kernel_points.push_back(mapping::Point{p[0], p[1]});
        }
        if (std::fabs(2.0 * mapping::signed_area(kernel_points)) <= 1e-12) {
            push_cartographic("degenerate_ring", "面为零（顶点共线或重合）");
        }
    }
    return issues;
}

domain::Json cartographic_issues(const Json& root, const Json& map_document,
                                 const CartographicQaDelegate* delegate) {
    if (delegate == nullptr || !static_cast<bool>(*delegate)) {
        // No delegate bound → the mapping-side rule set is unavailable.
        // Honest absence: the caller's coverage records the skip — never a
        // fabricated pass.
        return Json::array();
    }
    return (*delegate)(root, map_document);
}

domain::Result<domain::Json> run_map_qc_on_document(
    Json& root, const std::string& doc_id, const QcInputs& inputs,
    const CartographicQaDelegate* cartographic, const std::string& iso_now) {
    const Json* document = find_map_document(root, doc_id);
    if (document == nullptr) {
        return domain::DataError(domain::ErrorCode::NotFound,
                                 "unknown map document: " + doc_id);
    }

    Json issues = collect_basic_issues(root, *document);
    for (const auto& issue : collect_layer_crs_issues(root, *document)) {
        issues.push_back(issue);
    }
    for (const auto& issue :
         collect_renderer_class_issues(root, *document)) {
        issues.push_back(issue);
    }
    for (const auto& issue :
         collect_extent_issues(root, *document, inputs.map_extent)) {
        issues.push_back(issue);
    }
    for (const auto& issue : collect_data_health_issues(root)) {
        issues.push_back(issue);
    }
    for (const auto& issue : collect_confidence_issues(
             inputs.fusion_confidence != nullptr ? *inputs.fusion_confidence
                                                 : Json(),
             inputs.confidence_threshold)) {
        issues.push_back(issue);
    }
    for (const auto& issue : collect_export_issues(
             inputs.export_report != nullptr ? *inputs.export_report
                                             : Json())) {
        issues.push_back(issue);
    }
    // 编图侧检查委托：有绑定时与扩展收集器并跑（stage QA 的 compose 形态
    // 收敛进同一次 QC），问题同样可定位。
    for (const auto& issue :
         cartographic_issues(root, *document, cartographic)) {
        issues.push_back(issue);
    }

    const std::string status = status_from_issues(issues);

    // Upsert by linked_map_document_id (stable id — re-running QC for the
    // same map replaces the previous report so dashboards do not inflate).
    Json* reports = mutable_section_array(root, "quality_reports");
    if (reports == nullptr) {
        root["quality_reports"] = Json::array();
        reports = &root["quality_reports"];
    }
    Json* existing = nullptr;
    for (auto& report : *reports) {
        if (report.is_object() &&
            field_string(report, "linked_map_document_id") == doc_id) {
            existing = &report;
            break;
        }
    }

    // V8 M11: basic rules all evaluate; extended rules per inputs; coverage
    // makes every skip visible with its reason.
    Json rule_status = Json::object();
    for (const auto& rule : basic_qc_rules()) {
        rule_status[rule] = Json{{"evaluated", true}, {"reason", ""}};
    }
    const Json extended_coverage = extended_rule_coverage_map(inputs);
    for (auto it = extended_coverage.begin(); it != extended_coverage.end();
         ++it) {
        rule_status[it.key()] = it.value();
    }
    // 编图侧检查委托的诚实记账：委托未绑定时记为 skipped（含原因）。
    // 这不是 Python run_map_qc 的一部分（那边编图检查走 stage QA 委托），
    // 是本线合并委托问题后的可见性扩展，键名固定以便消费方识别。
    rule_status["cartographic_side_checks"] =
        cartographic != nullptr && static_cast<bool>(*cartographic)
            ? Json{{"evaluated", true}, {"reason", ""}}
            : Json{{"evaluated", false},
                   {"reason", "编图侧检查委托未绑定"}};
    int evaluated = 0;
    int skipped = 0;
    for (auto it = rule_status.begin(); it != rule_status.end(); ++it) {
        const auto entry_it = it->find("evaluated");
        if (entry_it != it->end() && entry_it->is_boolean() &&
            entry_it->get<bool>()) {
            ++evaluated;
        } else {
            ++skipped;
        }
    }

    Json report = Json::object();
    report["id"] =
        existing != nullptr ? field_string(*existing, "id")
                            : ui_data_core::new_feature_id("qc");
    report["linked_map_document_id"] = doc_id;
    Json rules = Json::array();
    for (const auto& rule : basic_qc_rules()) {
        rules.push_back(rule);
    }
    for (const auto& rule : extended_qc_rules()) {
        rules.push_back(rule);
    }
    report["rules"] = rules;
    report["issues"] = issues;
    report["status"] = status;
    report["generated_at"] = iso_now;
    // Provenance marker: the catalog qc-DataRun registration is the catalog
    // line's surface; until it lands the report records the honest default
    // instead of claiming a run that does not exist.
    report["provenance_registered"] = false;
    report["rule_status"] = rule_status;
    report["coverage"] = Json{{"evaluated", evaluated}, {"skipped", skipped}};

    if (existing != nullptr) {
        *existing = report;
    } else {
        reports->push_back(report);
    }

    // Bind the active compilation run (qc.py parity: the last run wins).
    Json* runs = mutable_section_array(root, "compilation_runs");
    if (runs != nullptr && !runs->empty()) {
        Json& run = runs->back();
        run["active_quality_report_id"] = report["id"];
        run["active_paleomap_document_id"] = doc_id;
        run["updated_at"] = iso_now;
    }
    return report;
}

}  // namespace pwb::closure_review
