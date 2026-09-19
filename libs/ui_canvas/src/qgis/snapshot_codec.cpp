// UI-15 — QGIS snapshot codec (bindings.cpp parse_layers /
// legacy_style_to_renderer_xml / renderer_info parity).

#include <pwb/ui_canvas/qgis/snapshot_codec.hpp>

#include <stdexcept>

#include <qgis.h>
#include <qgsrendercontext.h>
#include <qgsrenderer.h>

#include "style_codec.hpp"

namespace pwb::ui_canvas::qgis {

namespace {

const Json& require_object(const Json& data, const char* what) {
    if (!data.is_object()) {
        throw std::invalid_argument(std::string(what) + " must be a dict");
    }
    return data;
}

std::string req_string(const Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_string()) {
        throw std::invalid_argument(std::string("layer.") + key +
                                    " must be a string");
    }
    return it->get<std::string>();
}

double req_double(const Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_number()) {
        throw std::invalid_argument(std::string("layer.") + key +
                                    " must be a number");
    }
    return it->get<double>();
}

bool req_bool(const Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_boolean()) {
        throw std::invalid_argument(std::string("layer.") + key +
                                    " must be a bool");
    }
    return it->get<bool>();
}

std::uint64_t req_u64(const Json& data, const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || !it->is_number_unsigned()) {
        // Accept non-negative signed ints too (Python int parity).
        if (it != data.end() && it->is_number_integer() &&
            it->get<long long>() >= 0) {
            return static_cast<std::uint64_t>(it->get<long long>());
        }
        throw std::invalid_argument(std::string("layer.") + key +
                                    " must be an unsigned int");
    }
    return it->get<std::uint64_t>();
}

std::string opt_string(const Json& data, const char* key) {
    const auto it = data.find(key);
    return (it != data.end() && it->is_string()) ? it->get<std::string>()
                                                 : "";
}

double opt_double(const Json& data, const char* key, double fallback) {
    const auto it = data.find(key);
    return (it != data.end() && it->is_number()) ? it->get<double>()
                                                 : fallback;
}

// style["categories"] can be a dict {value: color} OR a list of
// [value, color, label?] triples — parse_layers reads the dict form;
// legacy_style_to_renderer_xml accepts both. Handle both for parity.
void parse_categories(const Json& raw,
                      std::vector<pwb::qgis_render::CategorySpec>& out) {
    if (raw.is_object()) {
        for (auto it = raw.begin(); it != raw.end(); ++it) {
            out.push_back({it.key(),
                           it.value().is_string()
                               ? it.value().get<std::string>()
                               : "",
                           it.key()});
        }
        return;
    }
    if (!raw.is_array()) {
        return;
    }
    for (const Json& item : raw) {
        if (!item.is_array() || item.size() < 2) {
            continue;
        }
        out.push_back({item.at(0).is_string()
                           ? item.at(0).get<std::string>()
                           : "",
                       item.at(1).is_string()
                           ? item.at(1).get<std::string>()
                           : "",
                       item.size() > 2 && item.at(2).is_string()
                           ? item.at(2).get<std::string>()
                           : ""});
    }
}

// style["ranges"]: list of dicts {lower, upper, color, label?}
// (parse_layers) or flat [lower, upper, color, label?] sequences
// (legacy_style_to_renderer_xml). Handle both.
void parse_ranges(const Json& raw,
                  std::vector<pwb::qgis_render::RangeSpec>& out) {
    if (!raw.is_array()) {
        return;
    }
    for (const Json& item : raw) {
        if (item.is_object()) {
            out.push_back({item.value("lower", 0.0),
                           item.value("upper", 0.0),
                           opt_string(item, "color"),
                           opt_string(item, "label")});
            continue;
        }
        if (item.is_array() && item.size() >= 3) {
            out.push_back({item.at(0).get<double>(),
                           item.at(1).get<double>(),
                           item.at(2).is_string()
                               ? item.at(2).get<std::string>()
                               : "",
                           item.size() > 3 && item.at(3).is_string()
                               ? item.at(3).get<std::string>()
                               : ""});
        }
    }
}

void parse_rules(const Json& raw,
                 std::vector<pwb::qgis_render::RuleSpec>& out) {
    if (!raw.is_array()) {
        return;
    }
    for (const Json& item : raw) {
        require_object(item, "style rule");
        pwb::qgis_render::RuleSpec rule;
        rule.name = opt_string(item, "name");
        rule.expression = opt_string(item, "expression");
        rule.label = opt_string(item, "label");
        rule.fill = opt_string(item, "fill");
        rule.stroke = opt_string(item, "stroke");
        rule.stroke_width = opt_double(item, "stroke_width", 1.0);
        rule.marker_size = opt_double(item, "marker_size", 6.0);
        out.push_back(std::move(rule));
    }
}

void parse_labels(const Json& labels, pwb::qgis_render::VectorLayerSpec& spec) {
    require_object(labels, "style labels");
    const auto visible_it = labels.find("visible");
    const bool visible = (visible_it == labels.end() ||
                          !visible_it->is_boolean() ||
                          visible_it->get<bool>());
    const std::string field = opt_string(labels, "field");
    // #922: explicit labels.visible=false hides labels even with a field.
    spec.labels_enabled = visible && !field.empty();
    spec.label_field = field;
    spec.label_font_family = opt_string(labels, "font_family");
    spec.label_size = opt_double(labels, "size", spec.label_size);
    const auto bold_it = labels.find("bold");
    if (bold_it != labels.end() && bold_it->is_boolean()) {
        spec.label_bold = bold_it->get<bool>();
    }
    const std::string color = opt_string(labels, "color");
    if (!color.empty()) {
        spec.label_color = color;
    }
    spec.label_buffer_size = opt_double(labels, "buffer", 0.0);
    spec.label_buffer_color = opt_string(labels, "buffer_color");
    // #1052: per-feature data-defined label styling.
    spec.label_rotation_field = opt_string(labels, "rotation_field");
    spec.label_size_field = opt_string(labels, "size_field");
    spec.label_color_field = opt_string(labels, "color_field");
}

// The style-dict → flat-spec-field mapping shared by parse_layers and the
// legacy migration entry point.
void apply_style_dict(const Json& style,
                      pwb::qgis_render::VectorLayerSpec& spec) {
    require_object(style, "layer style");
    const std::string fill = opt_string(style, "fill");
    if (!fill.empty()) spec.fill = fill;
    const std::string stroke = opt_string(style, "stroke");
    if (!stroke.empty()) spec.stroke = stroke;
    spec.stroke_width = opt_double(style, "stroke_width", spec.stroke_width);
    spec.marker_size = opt_double(style, "marker_size", spec.marker_size);
    const std::string marker = opt_string(style, "marker");
    if (!marker.empty()) spec.marker = marker;
    const std::string line_pattern = opt_string(style, "line_pattern");
    if (!line_pattern.empty()) spec.line_pattern = line_pattern;
    const std::string renderer = opt_string(style, "renderer");
    if (!renderer.empty()) spec.renderer_kind = renderer;
    spec.classification_field = opt_string(style, "field");
    spec.renderer_xml = opt_string(style, "renderer_xml");
    spec.labeling_xml = opt_string(style, "labeling_xml");
    const auto rules_it = style.find("rules");
    if (rules_it != style.end()) parse_rules(*rules_it, spec.rules);
    const auto categories_it = style.find("categories");
    if (categories_it != style.end()) {
        parse_categories(*categories_it, spec.categories);
    }
    const auto ranges_it = style.find("ranges");
    if (ranges_it != style.end()) parse_ranges(*ranges_it, spec.ranges);
    const auto labels_it = style.find("labels");
    if (labels_it != style.end() && labels_it->is_object()) {
        parse_labels(*labels_it, spec);
    }
}

pwb::qgis_render::FeatureSpec feature_spec_from_json(const Json& feature) {
    require_object(feature, "feature");
    pwb::qgis_render::FeatureSpec spec{
        req_string(feature, "id"),
        req_string(feature, "wkt"),
        {},
    };
    const auto attrs_it = feature.find("attributes");
    if (attrs_it != feature.end() && attrs_it->is_object()) {
        for (auto it = attrs_it->begin(); it != attrs_it->end(); ++it) {
            // Python str(key)/str(value) parity — Json scalars dump().
            const std::string value =
                it.value().is_string() ? it.value().get<std::string>()
                                       : it.value().dump();
            spec.attributes.emplace_back(it.key(), value);
        }
    }
    return spec;
}

Qgis::GeometryType geometry_type_for_name(const std::string& name) {
    if (name == "Point" || name == "MultiPoint") {
        return Qgis::GeometryType::Point;
    }
    if (name == "LineString" || name == "MultiLineString") {
        return Qgis::GeometryType::Line;
    }
    if (name == "Polygon" || name == "MultiPolygon") {
        return Qgis::GeometryType::Polygon;
    }
    return Qgis::GeometryType::Null;
}

}  // namespace

pwb::qgis_render::VectorLayerSpec layer_spec_from_json(const Json& data) {
    require_object(data, "layer");
    pwb::qgis_render::VectorLayerSpec spec;
    spec.id = req_string(data, "id");
    spec.name = req_string(data, "name");
    spec.crs = req_string(data, "crs");
    if (opt_string(data, "kind") == "raster") {
        spec.kind = pwb::qgis_render::VectorLayerSpec::Kind::Raster;
        spec.source_path = req_string(data, "source_path");
        spec.raster_renderer_xml = opt_string(data, "raster_renderer_xml");
    }
    const auto style_it = data.find("style");
    if (style_it != data.end() && style_it->is_object()) {
        apply_style_dict(*style_it, spec);
    }
    spec.data_revision = req_u64(data, "data_revision");
    spec.style_revision = req_u64(data, "style_revision");
    spec.visible = req_bool(data, "visible");
    // #929: scale visibility travels with the layer payload.
    const auto range_it = data.find("scale_range");
    if (range_it != data.end() && range_it->is_array() &&
        range_it->size() == 2) {
        spec.has_scale_range = true;
        spec.scale_range_min_denom = range_it->at(0).get<double>();
        spec.scale_range_max_denom = range_it->at(1).get<double>();
    }
    spec.opacity = req_double(data, "opacity");
    // #932: an incremental delta replaces the feature list.
    const auto delta_it = data.find("delta");
    if (delta_it != data.end() && delta_it->is_object()) {
        const Json& delta = *delta_it;
        pwb::qgis_render::VectorLayerSpec::FeatureDelta parsed;
        parsed.base_revision = req_u64(delta, "base_revision");
        const auto changed_it = delta.find("changed_features");
        if (changed_it != delta.end() && changed_it->is_array()) {
            for (const Json& feature : *changed_it) {
                parsed.changed.push_back(feature_spec_from_json(feature));
            }
        }
        const auto removed_it = delta.find("removed_ids");
        if (removed_it != delta.end() && removed_it->is_array()) {
            for (const Json& removed : *removed_it) {
                if (removed.is_string()) {
                    parsed.removed_ids.push_back(
                        removed.get<std::string>());
                }
            }
        }
        spec.delta = std::move(parsed);
    } else {
        const auto features_it = data.find("features");
        if (features_it != data.end() && features_it->is_array()) {
            for (const Json& feature : *features_it) {
                spec.features.push_back(feature_spec_from_json(feature));
            }
        }
    }
    return spec;
}

std::vector<pwb::qgis_render::VectorLayerSpec> layer_specs_from_json(
    const Json& layers) {
    std::vector<pwb::qgis_render::VectorLayerSpec> specs;
    if (!layers.is_array()) {
        throw std::invalid_argument("layers must be a list");
    }
    for (const Json& layer : layers) {
        specs.push_back(layer_spec_from_json(layer));
    }
    return specs;
}

std::string legacy_style_to_renderer_xml(const Json& style,
                                         const std::string& geometry_type) {
    pwb::qgis_render::VectorLayerSpec spec;
    spec.id = "migration";
    apply_style_dict(style, spec);
    auto renderer = pwb::qgis_render::build_renderer_from_spec(
        geometry_type_for_name(geometry_type), spec);
    if (!renderer) {
        return "";
    }
    return pwb::qgis_render::renderer_to_xml(*renderer);
}

Json renderer_info(const std::string& renderer_xml) {
    auto renderer = pwb::qgis_render::renderer_from_xml(renderer_xml);
    if (!renderer) {
        return Json();
    }
    QgsRenderContext context;
    return Json{{"type", renderer->type().toStdString()},
                {"symbol_count",
                 static_cast<int>(renderer->symbols(context).size())}};
}

}  // namespace pwb::ui_canvas::qgis
