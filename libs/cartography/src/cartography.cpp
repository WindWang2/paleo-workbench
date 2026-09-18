// CONV-27 — product API facade implementation.
#include <pwb/cartography/cartography.hpp>

#include <cmath>

namespace pwb::cartography {

Json validate_style(const Json& style) {
    Json report = Json::object();
    Json errors = Json::array();
    VectorStyle parsed;
    if (!style.is_object()) {
        errors.push_back("style payload must be an object");
        report["ok"] = false;
        report["errors"] = std::move(errors);
        report["normalized"] = parsed.to_dict();
        return report;
    }
    parsed = VectorStyle::from_dict(style);
    // Hard errors: numerics that renderers reject (negative sizes already
    // clamp in from_dict; opacity-like ranges do not exist on VectorStyle).
    if (parsed.stroke_width < 0.0 || !std::isfinite(parsed.stroke_width)) {
        errors.push_back("stroke_width must be a finite non-negative number");
    }
    if (parsed.marker_size < 0.0 || !std::isfinite(parsed.marker_size)) {
        errors.push_back("marker_size must be a finite non-negative number");
    }
    if (parsed.renderer != "single" && parsed.renderer != "categorized" &&
        parsed.renderer != "graduated") {
        Json message = "unknown renderer '" + parsed.renderer + "'";
        errors.push_back(std::move(message));
    }
    report["ok"] = errors.empty();
    report["errors"] = std::move(errors);
    report["normalized"] = parsed.to_dict();
    return report;
}

void apply_style(Json& style_payload, double& layer_opacity,
                 const std::string& preset_kind, const std::string& name) {
    if (preset_kind == "preset") {
        for (const auto& entry : style_library()) {
            if (entry.first == name) {
                Json binding = Json::object();
                StyleEntry style_entry{name, "", name, entry.second,
                                       std::move(binding), "", std::nullopt};
                apply_style_entry(style_payload, layer_opacity, style_entry);
                return;
            }
        }
        std::string listing;
        for (const auto& entry : style_library()) {
            if (!listing.empty()) listing += ", ";
            listing += "'" + entry.first + "'";
        }
        throw std::out_of_range("unknown style preset '" + name +
                                "'; available: [" + listing + "]");
    }
    if (preset_kind == "library") {
        const std::size_t dot = name.find('.');
        const std::string category = dot == std::string::npos ? "" : name.substr(0, dot);
        const std::string key = dot == std::string::npos ? "" : name.substr(dot + 1);
        const StyleEntry& entry = style_entry_lookup(category, key);
        apply_style_entry(style_payload, layer_opacity, entry);
        return;
    }
    throw std::invalid_argument("preset_kind must be 'preset' or 'library'");
}

Json style_preset_catalog() {
    Json catalog = Json::array();
    for (const auto& entry : style_library()) {
        Json row = Json::object();
        row["name"] = entry.first;
        row["style"] = entry.second.to_dict();
        catalog.push_back(std::move(row));
    }
    return catalog;
}

}  // namespace pwb::cartography
