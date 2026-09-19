// UI-15 — Qt-free layer-properties payload semantics
// (map_layer_properties.py parity).

#include <pwb/ui_canvas/layer_properties_core.hpp>

#include <algorithm>
#include <cctype>

namespace pwb::ui_canvas {

namespace {

std::string trimmed(const std::string& value) {
    const auto first = std::find_if_not(
        value.begin(), value.end(),
        [](unsigned char c) { return std::isspace(c) != 0; });
    const auto last = std::find_if_not(
        value.rbegin(), value.rend(),
        [](unsigned char c) { return std::isspace(c) != 0; })
                          .base();
    if (first >= last) {
        return "";
    }
    return std::string(first, last);
}

Json build_labels(const PropertiesForm& form) {
    const std::string field = trimmed(form.label_field);
    if (field.empty()) {
        return Json::object();
    }
    return Json{{"field", field}, {"size", form.label_size}};
}

}  // namespace

Json build_properties_payload(const PropertiesForm& form) {
    const std::string name =
        trimmed(form.name).empty() ? form.layer_id : trimmed(form.name);
    const std::string crs = trimmed(form.crs);
    const Json labels = build_labels(form);

    if (form.is_scalar) {
        return Json{
            {"name", name},
            {"crs", crs},
            {"opacity", form.opacity},
            {"scalar_style",
             Json{{"color_ramp", form.color_ramp},
                  {"color_range",
                   Json::array({form.range_min, form.range_max})},
                  {"gamma", form.gamma},
                  {"nodata", form.nodata}}},
        };
    }

    if (form.qgis_symbology) {
        Json result{
            {"name", name},
            {"crs", crs},
            {"opacity", form.opacity},
        };
        if (!form.pending_qgis_style.is_null()) {
            result["qgis_style"] = form.pending_qgis_style;
        }
        // #929: the native symbology editor owns renderer payloads only —
        // Apply must carry through the layer's existing label config or
        // every OK click silently wipes it.
        const auto it = form.existing_style.find("labels");
        if (it != form.existing_style.end() && it->is_object() &&
            !it->empty()) {
            result["labels"] = *it;
        }
        return result;
    }

    Json style{
        {"fill", trimmed(form.fill)},
        {"stroke", trimmed(form.stroke)},
        {"stroke_width", form.stroke_width},
        {"line_pattern", form.line_pattern},
        {"marker", form.marker},
        {"marker_size", form.marker_size},
        {"renderer", form.renderer},
        {"field", trimmed(form.classification_field)},
        {"labels", labels},
    };
    const std::string classes = trimmed(form.classes_text);
    if (!classes.empty()) {
        try {
            const Json parsed = Json::parse(classes);
            if (form.renderer == "categorized" && parsed.is_object()) {
                style["categories"] = parsed;
            } else if (form.renderer == "graduated" && parsed.is_array()) {
                style["ranges"] = parsed;
            }
        } catch (const Json::parse_error&) {
            // Leave the current renderer classes unchanged — the host
            // applies a valid independent style change instead of
            // corrupting state (Python parity).
        }
    }
    return Json{
        {"name", name},
        {"crs", crs},
        {"opacity", form.opacity},
        {"style", std::move(style)},
    };
}

std::optional<std::string> classes_json_error(const PropertiesForm& form) {
    if (form.is_scalar || form.qgis_symbology) {
        return std::nullopt;
    }
    const std::string classes = trimmed(form.classes_text);
    if (classes.empty()) {
        return std::nullopt;
    }
    try {
        (void)Json::parse(classes);
    } catch (const Json::parse_error& exc) {
        return std::string("Invalid Classes JSON: ") + exc.what();
    }
    return std::nullopt;
}

}  // namespace pwb::ui_canvas
