// UI-15 — Qt-free layer-properties payload semantics
// (map_layer_properties.py payload()/classes_json_error() frozen math).
//
// The Qt dialog collects widget values into PropertiesForm; these functions
// own the payload shape so the rules (labels carry-through #929, classes-JSON
// tolerance, scalar/legacy/qgis shapes) stay testable headless.
#pragma once

#include <optional>
#include <string>

#include <pwb/domain/json.hpp>

namespace pwb::ui_canvas {

using Json = pwb::domain::Json;

// Every editable value the dialog can produce (widget → struct, Qt-free).
struct PropertiesForm {
    // Identity (from the layer, not edited by payload shape).
    std::string layer_id;
    bool is_scalar = false;
    bool qgis_symbology = false;

    // General tab.
    std::string name;
    std::string crs;
    double opacity = 1.0;

    // Scalar symbology tab.
    std::string color_ramp = "default";
    double range_min = 0.0;
    double range_max = 1.0;
    double gamma = 1.0;
    std::string nodata = "transparent";

    // Legacy symbology tab (non-scalar, no QGIS bridge).
    std::string fill;
    std::string stroke;
    double stroke_width = 1.0;
    std::string line_pattern = "solid";
    std::string marker = "circle";
    double marker_size = 6.0;
    std::string renderer = "single";
    std::string classification_field;
    std::string classes_text;  // raw Classes (JSON) field

    // Labels tab.
    std::string label_field;
    double label_size = 10.0;

    // QGIS path: payload produced by the native symbology editor, applied
    // on Apply/OK (Json(nullptr) when absent).
    Json pending_qgis_style = Json(nullptr);
    // The layer's incoming style (for labels carry-through #929).
    Json existing_style = Json::object();
};

// payload() verbatim: scalar → {name, crs, opacity, scalar_style}; qgis →
// {name, crs, opacity, qgis_style?, labels?(carry-through)}; legacy →
// {name, crs, opacity, style{fill..renderer, field, labels, categories?|
// ranges?}}. A blank name falls back to layer_id. Classes JSON parse
// failures leave renderer classes unchanged (the host applies a valid
// independent change instead of corrupting state).
Json build_properties_payload(const PropertiesForm& form);

// classes_json_error() verbatim: nullopt for scalar/qgis paths or a blank
// field; "Invalid Classes JSON: <detail>" on parse failure.
std::optional<std::string> classes_json_error(const PropertiesForm& form);

}  // namespace pwb::ui_canvas
