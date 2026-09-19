#include "pwb/ui_pages_mapedit/document_features.hpp"

#include "pwb/ui_data_core/json_util.hpp"

namespace pwb::ui_pages_mapedit {
namespace {

using ui_data_core::json_float;
using ui_data_core::json_get_string;
using ui_data_core::json_has;
using ui_data_core::json_truthy;

ui_data_core::FeatureIdFn id_fn(const ui_data_core::FeatureIdFn& ids) {
    return ids ? ids : [](std::string_view p) {
        return ui_data_core::new_feature_id(p);
    };
}

// ``obj.get(key)`` truthy — returns the member pointer only when truthy.
const domain::Json* truthy_member(const domain::Json& obj,
                                  std::string_view key) {
    const auto it = obj.find(std::string(key));
    return it != obj.end() && json_truthy(*it) ? &*it : nullptr;
}

const domain::Json& obj_or_empty(const domain::Json* value) {
    static const domain::Json empty = domain::Json::object();
    return (value != nullptr && value->is_object()) ? *value : empty;
}

}  // namespace

domain::Json normalize_facies(const domain::Json& raw,
                              const ui_data_core::FeatureIdFn& ids) {
    const auto make_id = id_fn(ids);
    auto [geometry_type, polygons] =
        ui_data_core::canonical_facies_geometry(raw);
    // canonical_coordinates = polygons[0] for Polygon else all polygons.
    domain::Json canonical_coordinates;
    if (geometry_type == "Polygon" && !polygons.empty()) {
        canonical_coordinates = ui_data_core::polygon_to_json(polygons[0]);
    } else {
        canonical_coordinates = ui_data_core::multipolygon_to_json(polygons);
    }
    const auto props_it = raw.find("properties");
    const auto& props = obj_or_empty(
        props_it != raw.end() && props_it->is_object() ? &*props_it : nullptr);

    // name = raw.name or raw.facies or raw.label or props.name or
    //        props.facies or props.label or "" — RAW keys first, then props.
    domain::Json name;
    for (const char* key : {"name", "facies", "label"}) {
        if (const auto* v = truthy_member(raw, key)) {
            name = *v;
            break;
        }
    }
    if (name.is_null()) {
        for (const char* key : {"name", "facies", "label"}) {
            if (const auto* v = truthy_member(props, key)) {
                name = *v;
                break;
            }
        }
    }

    domain::Json out = domain::Json::object();
    {
        // raw.id or props.id or props.region_id or new_feature_id("facies").
        const domain::Json* id_value = truthy_member(raw, "id");
        if (id_value == nullptr) {
            id_value = truthy_member(props, "id");
        }
        if (id_value == nullptr) {
            id_value = truthy_member(props, "region_id");
        }
        out["id"] = id_value != nullptr ? *id_value
                                        : domain::Json(make_id("facies"));
    }
    out["kind"] = "facies";
    out["name"] = name.is_null() ? domain::Json("") : name;
    out["coordinates"] =
        ui_data_core::compact_facies_coordinates(geometry_type, polygons);
    out["geometry_type"] = geometry_type;
    out["geometry"] = {{"type", geometry_type},
                       {"coordinates", std::move(canonical_coordinates)}};
    {
        // dict(raw.get("style") or props.get("style") or {}).
        const domain::Json* style = truthy_member(raw, "style");
        if (style == nullptr) {
            style = truthy_member(props, "style");
        }
        out["style"] = style != nullptr && style->is_object()
                           ? *style
                           : domain::Json::object();
    }
    {
        // facies = raw.facies or props.facies or name; keep when truthy.
        const domain::Json* facies = truthy_member(raw, "facies");
        if (facies == nullptr) {
            facies = truthy_member(props, "facies");
        }
        if (facies == nullptr && !name.is_null() && json_truthy(name)) {
            facies = &name;
        }
        if (facies != nullptr) {
            out["facies"] = *facies;
        }
    }
    for (const char* key : {"probability", "region_id"}) {
        const auto it = raw.find(std::string(key));
        if (it != raw.end() && !it->is_null()) {
            out[key] = *it;
            continue;
        }
        const auto pit = props.find(std::string(key));
        if (pit != props.end() && !pit->is_null()) {
            out[key] = *pit;
        }
    }
    if (!props.empty()) {
        domain::Json kept = domain::Json::object();
        for (const auto& [k, v] : props.items()) {
            if (k != "style") {
                kept[k] = v;
            }
        }
        if (!kept.empty()) {
            out["properties"] = std::move(kept);
        }
    }
    return out;
}

domain::Json normalize_well(const domain::Json& raw,
                            const ui_data_core::FeatureIdFn& ids) {
    const auto make_id = id_fn(ids);
    std::optional<double> x, y;
    const auto coords_it = raw.find("coordinates");
    const domain::Json* coords =
        coords_it != raw.end() && coords_it->is_array() ? &*coords_it
                                                        : nullptr;
    if (coords != nullptr && coords->size() >= 2) {
        const auto cx = json_float((*coords)[0]);
        const auto cy = json_float((*coords)[1]);
        if (cx && cy) {
            x = *cx;
            y = *cy;
        }
    }
    if (!x || !y) {
        // Scalar families, never cross-paired (audit #1150).
        for (const auto& family :
             {std::pair{"x", "y"}, std::pair{"lng", "lat"},
              std::pair{"lon", "lat"}}) {
            const auto sx = raw.find(std::string(family.first));
            const auto sy = raw.find(std::string(family.second));
            if (sx == raw.end() || sy == raw.end() || sx->is_null() ||
                sy->is_null()) {
                continue;
            }
            const auto fx = json_float(*sx);
            const auto fy = json_float(*sy);
            if (fx && fy) {
                x = *fx;
                y = *fy;
                break;
            }
        }
    }
    if ((!x || !y) && coords != nullptr && coords->size() == 1) {
        if (const auto fx = json_float((*coords)[0])) {
            x = *fx;
        }
    }
    const std::string status = (x && y) ? "ok" : "invalid";
    domain::Json out = domain::Json::object();
    {
        const auto it = raw.find("id");
        out["id"] = it != raw.end() && json_truthy(*it)
                        ? *it
                        : domain::Json(make_id("well"));
    }
    out["kind"] = "well";
    {
        std::string name;
        for (const char* key : {"name", "well_name"}) {
            const auto it = raw.find(std::string(key));
            if (it != raw.end() && json_truthy(*it)) {
                name = ui_data_core::python_str(*it);
                break;
            }
        }
        out["name"] = name;
    }
    out["coordinates"] = {x.value_or(0.0), y.value_or(0.0)};
    out["coordinate_status"] = status;
    return out;
}

domain::Json normalize_line(const domain::Json& raw,
                            const ui_data_core::FeatureIdFn& ids) {
    const auto make_id = id_fn(ids);
    domain::Json out = domain::Json::object();
    {
        const auto it = raw.find("id");
        out["id"] = it != raw.end() && json_truthy(*it)
                        ? *it
                        : domain::Json(make_id("line"));
    }
    out["kind"] = "line";
    {
        const auto it = raw.find("name");
        out["name"] =
            it != raw.end() && json_truthy(*it)
                ? ui_data_core::python_str(*it)
                : std::string();
    }
    const auto it = raw.find("coordinates");
    out["coordinates"] =
        it != raw.end() && it->is_array() ? *it : domain::Json::array();
    return out;
}

std::optional<domain::Json> normalize_label(
    const domain::Json& raw, const ui_data_core::FeatureIdFn& ids) {
    const auto make_id = id_fn(ids);
    double ax = 0.0, ay = 0.0;
    if (json_has(raw, "anchor")) {
        const auto& anchor = raw["anchor"];
        if (!anchor.is_array() || anchor.size() < 2) {
            return std::nullopt;  // Python ValueError branch
        }
        const auto fx = json_float(anchor[0]);
        const auto fy = json_float(anchor[1]);
        if (!fx || !fy) {
            return std::nullopt;  // float() ValueError → skip
        }
        ax = *fx;
        ay = *fy;
    } else {
        const auto itx = raw.find("x");
        const auto ity = raw.find("y");
        const auto fx = itx != raw.end() ? json_float(*itx)
                                        : std::optional<double>(0.0);
        const auto fy = ity != raw.end() ? json_float(*ity)
                                        : std::optional<double>(0.0);
        if (!fx || !fy) {
            return std::nullopt;
        }
        ax = *fx;
        ay = *fy;
    }
    std::string text;
    for (const char* key : {"text", "name"}) {
        const auto it = raw.find(std::string(key));
        if (it != raw.end() && json_truthy(*it)) {
            text = ui_data_core::python_str(*it);
            break;
        }
    }
    domain::Json out = domain::Json::object();
    {
        const auto it = raw.find("id");
        out["id"] = it != raw.end() && json_truthy(*it)
                        ? *it
                        : domain::Json(make_id("label"));
    }
    out["kind"] = "label";
    out["name"] = text;
    out["coordinates"] = {ax, ay};
    out["text"] = text;
    return out;
}

std::vector<domain::Json> features_from_document(
    const domain::Json& doc, const ui_data_core::FeatureIdFn& ids) {
    std::vector<domain::Json> out;
    if (!doc.is_object()) {
        return out;
    }
    auto append_each = [&](const char* key,
                           const std::function<std::optional<domain::Json>(
                               const domain::Json&)>& normalize) {
        const auto it = doc.find(std::string(key));
        if (it == doc.end() || !it->is_array()) {
            return;
        }
        for (const auto& raw : *it) {
            if (!raw.is_object()) {
                continue;
            }
            try {
                if (auto record = normalize(raw)) {
                    out.push_back(std::move(*record));
                }
            } catch (...) {
                continue;  // Python logger.warning + continue parity
            }
        }
    };
    append_each("facies_polygons", [&](const domain::Json& raw) {
        return std::optional<domain::Json>(normalize_facies(raw, ids));
    });
    append_each("well_overlays", [&](const domain::Json& raw) {
        return std::optional<domain::Json>(normalize_well(raw, ids));
    });
    append_each("line_features", [&](const domain::Json& raw) {
        return std::optional<domain::Json>(normalize_line(raw, ids));
    });
    append_each("label_features", [&](const domain::Json& raw) {
        return normalize_label(raw, ids);
    });
    return out;
}

}  // namespace pwb::ui_pages_mapedit
