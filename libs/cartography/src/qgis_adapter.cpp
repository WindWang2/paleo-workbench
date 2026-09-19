// CONV-27 — implementation of the QGIS bridge payload adapter.
// See qgis_adapter.hpp for the ported contracts (D-5).
#include <pwb/cartography/qgis_adapter.hpp>

#include <algorithm>
#include <cmath>
#include <optional>
#include <stdexcept>

namespace pwb::cartography {

Json scalar_renderer_payload(const ScalarStyleSpec& spec,
                             const ScalarRendererStats& stats,
                             const std::string& crs) {
    // encode_scalar_renderer_xml: finite filter, min/max fallbacks, the
    // degenerate-span widening, then classify + ramp items.
    std::vector<double> finite = finite_values(stats.values);
    double vmin = 0.0;
    double vmax = 1.0;
    if (stats.min.has_value()) {
        vmin = *stats.min;
    } else if (!finite.empty()) {
        vmin = *std::min_element(finite.begin(), finite.end());
    }
    if (stats.max.has_value()) {
        vmax = *stats.max;
    } else if (!finite.empty()) {
        vmax = *std::max_element(finite.begin(), finite.end());
    }
    if (vmax <= vmin) vmax = vmin + 1.0;  // NaN max keeps NaN (parity)

    const ClassifiedBreaks classified =
        classify_breaks(spec, finite, vmin, vmax, std::nullopt);
    const ColorRamp ramp = get_color_ramp(spec.ramp_name);
    const std::string mode =
        spec.mode == "classified" ? "classified" : "continuous";
    std::vector<Json> items = ramp_items_for_spec(spec, ramp, vmin, vmax,
                                                  mode, classified.breaks);

    Json payload = Json::object();
    payload["ramp_name"] = spec.ramp_name;
    payload["mode"] = spec.mode;
    Json items_json = Json::array();
    for (Json& item : items) items_json.push_back(std::move(item));
    payload["items"] = std::move(items_json);
    payload["min"] = vmin;
    payload["max"] = vmax;
    payload["opacity"] = spec.opacity;
    payload["nodata_transparent"] = spec.nodata_transparent;
    payload["unit_label"] = spec.unit_label;
    payload["colorbar_title"] = spec.colorbar_title;
    payload["crs"] = crs;
    Json labels = Json::array();
    for (const std::string& label : classified.labels) {
        labels.push_back(label);
    }
    payload["labels"] = std::move(labels);
    return payload;
}

Json legacy_renderer_style(const VectorStyle& style) {
    // The flat dict the bridge's legacy_style_to_renderer_xml parses: same
    // keys plus the renderer_kind/classification_field aliases.
    Json data = style.to_dict();
    data["renderer_kind"] = style.renderer;
    data["classification_field"] = style.field;
    if (style.labels.has_value()) {
        const TextStyle& labels = *style.labels;
        Json label_data = Json::object();
        label_data["field"] = labels.field;
        label_data["size"] = labels.size;
        label_data["color"] = labels.color;
        label_data["font_family"] = labels.font_family;
        label_data["bold"] = labels.bold;
        label_data["halo_color"] = labels.halo_color;
        label_data["halo_width"] = labels.halo_width;
        label_data["visible"] = labels.visible;
        label_data["rotation_field"] = labels.rotation_field;
        label_data["size_field"] = labels.size_field;
        label_data["color_field"] = labels.color_field;
        label_data["buffer_color"] = labels.buffer_color;
        data["labels"] = std::move(label_data);
    }
    return data;
}

Json symbol_renderer_spec(const std::string& symbol_id) {
    const GeologicalSymbolDef& symbol = symbol_by_id(symbol_id);
    Json spec = Json::object();
    std::string kind = "single";
    if (symbol.renderer_hint.is_object()) {
        auto it = symbol.renderer_hint.find("renderer_kind");
        if (it != symbol.renderer_hint.end() && it->is_string()) {
            kind = it->get<std::string>();
        }
    }
    spec["renderer_kind"] = kind;
    // renderer_hint "field" may be JSON null (single symbols) — the bridge
    // wire wants a string, Python hands None straight through.
    Json classification_field = "";
    if (symbol.renderer_hint.is_object()) {
        auto field_it = symbol.renderer_hint.find("field");
        if (field_it != symbol.renderer_hint.end() && field_it->is_string()) {
            classification_field = field_it->get<std::string>();
        }
    }
    spec["classification_field"] = std::move(classification_field);
    if (kind == "categorized") {
        // The bridge's categorized path consumes classification_field +
        // categories (value/color/label triples); rules+expression are the
        // rule-based renderer's vocabulary, so emit the fallback style's
        // categories verbatim.
        Json categories = Json::array();
        for (const StyleCategory& category : symbol.legacy_fallback.categories) {
            Json wire = Json::object();
            wire["value"] = category.value;
            wire["color"] = category.fill;
            wire["label"] = category.label;
            categories.push_back(std::move(wire));
        }
        spec["categories"] = std::move(categories);
    }
    spec["legacy_style"] = symbol.legacy_fallback.to_dict();
    return spec;
}

Json flatten_qgis_style(const Json& style) {
    // Python builds `dict(style)` up front: non-Mapping payloads raise.
    if (!style.is_object()) {
        throw std::invalid_argument(
            "flatten_qgis_style expects a style object");
    }
    Json result = style;
    // Copy the payload values out BEFORE mutating `result` — insertion can
    // reallocate the ordered_map storage and invalidate iterators.
    std::optional<std::string> renderer_xml;
    std::optional<std::string> labeling_xml;
    auto payload_it = result.find("qgis_style");
    if (payload_it != result.end() && payload_it->is_object()) {
        auto renderer_it = payload_it->find("renderer_xml");
        if (renderer_it != payload_it->end() && renderer_it->is_string()) {
            renderer_xml = renderer_it->get<std::string>();
        }
        auto labeling_it = payload_it->find("labeling_xml");
        if (labeling_it != payload_it->end() && labeling_it->is_string()) {
            labeling_xml = labeling_it->get<std::string>();
        }
    }
    auto promote = [&result](const std::optional<std::string>& xml,
                             const char* key) {
        if (!xml.has_value()) return;
        // strip() emptiness check — Python str.strip().
        bool blank = true;
        for (char c : *xml) {
            if (!std::isspace(static_cast<unsigned char>(c))) blank = false;
        }
        if (!blank) result[key] = *xml;
    };
    promote(renderer_xml, "renderer_xml");
    promote(labeling_xml, "labeling_xml");
    auto labels_it = result.find("labels");
    if (labels_it != result.end() && labels_it->is_object()) {
        Json labels = *labels_it;
        auto size_it = labels.find("size");
        if (size_it != labels.end() && size_it->is_number()) {
            const double size = size_it->is_number_integer()
                                    ? static_cast<double>(size_it->get<long long>())
                                    : size_it->get<double>();
            labels["size"] = size * (72.0 / 96.0);
        }
        if (labels.find("buffer") == labels.end()) {
            auto halo_width_it = labels.find("halo_width");
            if (halo_width_it != labels.end() && halo_width_it->is_number()) {
                const double halo_width =
                    halo_width_it->is_number_integer()
                        ? static_cast<double>(halo_width_it->get<long long>())
                        : halo_width_it->get<double>();
                // Python: labels.get("halo_width") is truthy — nonzero.
                if (halo_width != 0.0) {
                    labels["buffer"] = halo_width * (25.4 / 96.0);
                }
            }
        }
        auto buffer_color_it = labels.find("buffer_color");
        bool has_buffer_color =
            buffer_color_it != labels.end() && buffer_color_it->is_string() &&
            !buffer_color_it->get<std::string>().empty();
        if (!has_buffer_color) {
            auto halo_color_it = labels.find("halo_color");
            if (halo_color_it != labels.end() && halo_color_it->is_string() &&
                !halo_color_it->get<std::string>().empty()) {
                std::string halo = halo_color_it->get<std::string>();
                labels["buffer_color"] = std::move(halo);
            }
        }
        result["labels"] = std::move(labels);
    }
    result.erase("qgis_style");
    return result;
}

void QgisStylePayload::validate() const {
    bool blank = true;
    for (char c : renderer_xml) {
        if (!std::isspace(static_cast<unsigned char>(c))) blank = false;
    }
    if (blank) {
        throw std::invalid_argument("renderer_xml payload is required");
    }
    if (schema_version != kQgisStyleSchemaVersion) {
        throw std::invalid_argument(
            "unsupported qgis_style schema version " +
            std::to_string(schema_version));
    }
}

QgisStylePayload QgisStylePayload::bumped() const {
    QgisStylePayload next = *this;
    next.revision = revision + 1;
    return next;
}

Json QgisStylePayload::to_dict() const {
    Json data = Json::object();
    data["schema_version"] = schema_version;
    data["renderer_xml"] = renderer_xml;
    data["labeling_xml"] = labeling_xml;
    data["name"] = name;
    Json tags_json = Json::array();
    for (const std::string& tag : tags) tags_json.push_back(tag);
    data["tags"] = std::move(tags_json);
    data["revision"] = revision;
    return data;
}

std::optional<QgisStylePayload> QgisStylePayload::from_dict(const Json& data) {
    if (!data.is_object()) return std::nullopt;
    auto renderer_it = data.find("renderer_xml");
    if (renderer_it == data.end() || !renderer_it->is_string()) {
        return std::nullopt;
    }
    QgisStylePayload payload;
    payload.renderer_xml = renderer_it->get<std::string>();
    // Python from_dict: a blank renderer_xml payload is invalid -> None.
    {
        bool blank = true;
        for (char c : payload.renderer_xml) {
            if (!std::isspace(static_cast<unsigned char>(c))) blank = false;
        }
        if (blank) return std::nullopt;
    }
    auto labeling_it = data.find("labeling_xml");
    if (labeling_it != data.end() && labeling_it->is_string()) {
        payload.labeling_xml = labeling_it->get<std::string>();
    }
    auto name_it = data.find("name");
    if (name_it != data.end() && name_it->is_string()) {
        payload.name = name_it->get<std::string>();
    }
    auto tags_it = data.find("tags");
    if (tags_it != data.end() && tags_it->is_array()) {
        for (const Json& tag : *tags_it) {
            if (tag.is_string()) payload.tags.push_back(tag.get<std::string>());
        }
    }
    auto revision_it = data.find("revision");
    if (revision_it != data.end() && revision_it->is_number_integer()) {
        // Python: revision = max(1, int(data.get("revision") or 1)).
        payload.revision =
            std::max(1LL, revision_it->get<long long>());
    }
    auto version_it = data.find("schema_version");
    if (version_it != data.end() && version_it->is_number_integer()) {
        payload.schema_version = version_it->get<long long>();
    }
    // Python __post_init__ runs on construction: a foreign schema version
    // raises (not None) exactly like this.
    try {
        payload.validate();
    } catch (const std::invalid_argument&) {
        throw;
    }
    return payload;
}

}  // namespace pwb::cartography
