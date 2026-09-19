#include <pwb/ui_composite/qgis_layer_schema.hpp>

#include <map>
#include <stdexcept>

namespace pwb::ui_composite {
namespace {

// spec kind → QMetaType name used by QgsField (QVariant type name).
const std::map<std::string, std::string>& kind_to_qgs_type() {
    static const std::map<std::string, std::string> map = {
        {"text", "QString"},
        {"int", "qlonglong"},
        {"real", "double"},
        {"bool", "bool"},
        {"datetime", "QDateTime"},
    };
    return map;
}

// geometry_kind → QGIS provider geometry type names. Polygon mirrors as
// MultiPolygon so single/multi features share one WKB type.
const std::map<std::string, std::string>& geometry_type_names() {
    static const std::map<std::string, std::string> map = {
        {"point", "Point"},
        {"line", "LineString"},
        {"polygon", "MultiPolygon"},
        {"raster", "raster"},       // raster layers have no WKB type
        {"vector", "NoGeometry"},   // geometry decided per-layer
    };
    return map;
}

std::string editor_widget_for(const SpecField& field) {
    if (field.editor_widget.has_value()) {
        return *field.editor_widget;
    }
    if (!field.choices.empty()) {
        return "ValueMap";
    }
    if (field.kind == "bool") {
        return "CheckBox";
    }
    if (field.kind == "datetime") {
        return "DateTime";
    }
    if ((field.kind == "int" || field.kind == "real") &&
        field.value_range.has_value()) {
        return "Range";
    }
    return "TextEdit";
}

bool default_is_empty(const Json& value) {
    return value.is_null() || (value.is_string() && value.get<std::string>().empty());
}

}  // namespace

std::string qgis_geometry_type_name(const std::string& geometry_kind) {
    auto it = geometry_type_names().find(geometry_kind);
    if (it == geometry_type_names().end()) {
        throw std::invalid_argument("unknown geometry kind '" +
                                    geometry_kind + "'");
    }
    return it->second;
}

std::string qgs_field_type_for_kind(const std::string& kind) {
    auto it = kind_to_qgs_type().find(kind);
    if (it == kind_to_qgs_type().end()) {
        throw std::invalid_argument("unknown spec field kind '" + kind +
                                    "'");
    }
    return it->second;
}

Json fields_json_for_spec(const GeologicalLayerSpec& spec) {
    Json wire = Json::array();
    for (const SpecField& field : spec.fields) {
        Json entry = {
            {"name", field.name},
            {"type", qgs_field_type_for_kind(field.kind)},
            {"alias", field.label.empty() ? field.name : field.label},
            {"editor_widget", editor_widget_for(field)},
        };
        if (field.length.has_value()) {
            entry["length"] = *field.length;
        }
        if (field.precision.has_value()) {
            entry["precision"] = *field.precision;
        }
        Json constraints = Json::object();
        if (field.required) {
            constraints["not_null"] = true;
        }
        if (field.unique) {
            constraints["unique"] = true;
        }
        if (!field.expression.empty()) {
            constraints["expression"] = field.expression;
        }
        if (!constraints.empty()) {
            entry["constraints"] = std::move(constraints);
        }
        if (!field.choices.empty()) {
            Json map = Json::object();
            for (const std::string& choice : field.choices) {
                map[choice] = choice;
            }
            entry["domain"] = {{"map", std::move(map)}};
        } else if (field.value_range.has_value()) {
            entry["domain"] = {
                {"range",
                 {field.value_range->first, field.value_range->second}},
            };
        }
        if (!default_is_empty(field.default_value)) {
            entry["default"] = field.default_value;
        }
        wire.push_back(std::move(entry));
    }
    return wire;
}

Json schema_wire_for_role(const std::string& role_value) {
    const GeologicalLayerSpec& spec = spec_for_role(role_value);
    Json wire = {
        {"role", spec.role},
        {"geometry_kind", spec.geometry_kind},
        {"qgis_geometry_type", qgis_geometry_type_name(spec.geometry_kind)},
        {"fields", fields_json_for_spec(spec)},
    };
    if (spec.geometry_kind == "raster") {
        wire["raster"] = true;
    }
    if (spec.renderer_binding.has_value()) {
        const RendererBinding& binding = *spec.renderer_binding;
        wire["renderer_binding"] = {
            {"style_id", binding.style_id},
            {"renderer_kind", binding.renderer_kind},
            {"field",
             binding.field.has_value() ? Json(*binding.field)
                                       : Json(nullptr)},
        };
    }
    return wire;
}

}  // namespace pwb::ui_composite
