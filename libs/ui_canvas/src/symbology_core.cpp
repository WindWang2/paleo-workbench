// UI-15 — Qt-free symbology-bridge semantics (map_symbology_bridge.py
// parity).

#include <pwb/ui_canvas/symbology_core.hpp>

#include <algorithm>
#include <set>

namespace pwb::ui_canvas {

namespace {

const std::set<std::string>& known_geometry_types() {
    static const std::set<std::string> kinds = {
        "Point",      "MultiPoint", "LineString",
        "MultiLineString", "Polygon", "MultiPolygon",
    };
    return kinds;
}

std::string json_str(const Json& object, const char* key,
                     const std::string& fallback = "") {
    if (!object.is_object()) {
        return fallback;
    }
    const auto it = object.find(key);
    if (it == object.end() || it->is_null()) {
        return fallback;
    }
    if (it->is_string()) {
        return it->get<std::string>();
    }
    if (it->is_number() || it->is_boolean()) {
        return it->dump();
    }
    return fallback;
}

}  // namespace

std::string geometry_type_for_features(const Json& features) {
    if (features.is_array()) {
        for (const Json& feature : features) {
            if (!feature.is_object()) {
                continue;
            }
            const auto geom = feature.find("geometry");
            if (geom == feature.end() || !geom->is_object()) {
                continue;
            }
            const auto type = geom->find("type");
            if (type != geom->end() && type->is_string() &&
                known_geometry_types().count(type->get<std::string>())) {
                return type->get<std::string>();
            }
        }
    }
    return "Polygon";
}

Json normalize_dialog_style(Json style,
                            const std::vector<std::string>& fields) {
    if (!style.is_object()) {
        style = Json::object();
    }
    // #937-2: categorized/graduated with no classifiable attribute opens an
    // empty dialog — downgrade to single-symbol legacy migration.
    std::string renderer_kind = json_str(style, "renderer");
    std::transform(renderer_kind.begin(), renderer_kind.end(),
                   renderer_kind.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    // strip
    const auto first = renderer_kind.find_first_not_of(" \t\n\r");
    const auto last = renderer_kind.find_last_not_of(" \t\n\r");
    renderer_kind = first == std::string::npos
                        ? ""
                        : renderer_kind.substr(first, last - first + 1);
    const std::string field = json_str(style, "field");
    const bool has_field = !field.empty() &&
                           field.find_first_not_of(" \t\n\r") !=
                               std::string::npos;
    const bool has_fields = !fields.empty();
    if ((renderer_kind == "categorized" || renderer_kind == "graduated") &&
        !has_fields && !has_field) {
        style["renderer"] = "single";
        style.erase("field");
        style.erase("categories");
        style.erase("ranges");
    }
    return style;
}

SymbologyRequest build_renderer_request(
    const std::string& title, const Json& features, const std::string& crs,
    const std::vector<std::string>& fields, const Json& style,
    const std::optional<pwb::cartography::QgisStylePayload>& payload,
    const std::optional<std::string>& legacy_migrated_xml) {
    SymbologyRequest request;
    request.title = title;
    request.geometry_type = geometry_type_for_features(features);
    request.crs = crs;
    request.field_names = fields;
    const std::string fill = json_str(style, "fill");
    request.fill = fill.empty() ? "#6c8ebf" : fill;
    const std::string stroke = json_str(style, "stroke");
    request.stroke = stroke.empty() ? "#26364d" : stroke;
    // float(style.get("stroke_width") or 1.0) parity — `or` treats 0/None
    // as falsy, so a zero width resolves to the default.
    const auto sw = style.find("stroke_width");
    if (sw != style.end() && sw->is_number() && sw->get<double>() != 0.0) {
        request.stroke_width = sw->get<double>();
    }
    const auto ms = style.find("marker_size");
    if (ms != style.end() && ms->is_number() && ms->get<double>() != 0.0) {
        request.marker_size = ms->get<double>();
    }
    if (payload.has_value()) {
        request.renderer_xml = payload->renderer_xml;
        if (!payload->labeling_xml.empty()) {
            request.labeling_xml = payload->labeling_xml;
        }
    } else {
        if (legacy_migrated_xml && !legacy_migrated_xml->empty()) {
            request.renderer_xml = *legacy_migrated_xml;
        }
        // #937-2 alternative: a featureful layer with a classification
        // field but no categories seeds values from the first feature's
        // properties so the native dialog doesn't open empty.
        if (request.renderer_xml.empty() && features.is_array() &&
            !features.empty() && !fields.empty()) {
            const std::string field = json_str(style, "field");
            if (!field.empty()) {
                for (const Json& feature : features) {
                    const auto props = feature.find("properties");
                    if (props == feature.end() || !props->is_object() ||
                        props->empty()) {
                        continue;
                    }
                    std::set<std::string> vals;
                    for (auto it = props->begin(); it != props->end();
                         ++it) {
                        if (!it->is_null()) {
                            if (it->is_string()) {
                                vals.insert(it->get<std::string>());
                            } else {
                                vals.insert(it->dump());
                            }
                        }
                    }
                    if (!vals.empty()) {
                        request.seed_values.assign(vals.begin(),
                                                   vals.end());
                        if (request.seed_values.size() > 8) {
                            request.seed_values.resize(8);
                        }
                    }
                    break;  // first feature with properties only
                }
            }
        }
    }
    return request;
}

Json apply_dialog_result(
    const std::optional<pwb::cartography::QgisStylePayload>& payload,
    const std::string& renderer_xml, const std::string& dialog_labeling_xml,
    double opacity) {
    if (renderer_xml.find_first_not_of(" \t\n\r") == std::string::npos) {
        throw SymbologyBridgeError(
            "the symbology editor returned an empty renderer");
    }
    std::string labeling_xml = dialog_labeling_xml;
    if (labeling_xml.empty() && payload.has_value()) {
        labeling_xml = payload->labeling_xml;
    }
    pwb::cartography::QgisStylePayload updated;
    updated.renderer_xml = renderer_xml;
    updated.labeling_xml = labeling_xml;
    if (payload.has_value()) {
        updated.name = payload->name;
        updated.tags = payload->tags;
        updated.revision = payload->revision + 1;
    } else {
        updated.revision = 1;
    }
    return Json{{"qgis_style", updated.to_dict()}, {"opacity", opacity}};
}

Json apply_symbol_result(
    const pwb::cartography::QgisStylePayload& payload,
    const std::string& renderer_xml, const std::string& dialog_labeling_xml) {
    if (renderer_xml.find_first_not_of(" \t\n\r") == std::string::npos) {
        throw SymbologyBridgeError(
            "the symbol editor returned an empty renderer");
    }
    pwb::cartography::QgisStylePayload updated;
    updated.renderer_xml = renderer_xml;
    updated.labeling_xml = dialog_labeling_xml.empty()
                               ? payload.labeling_xml
                               : dialog_labeling_xml;
    updated.name = payload.name;
    updated.tags = payload.tags;
    updated.revision = payload.revision + 1;
    return Json{{"qgis_style", updated.to_dict()}};
}

}  // namespace pwb::ui_canvas
