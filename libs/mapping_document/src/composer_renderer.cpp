#include <pwb/mapping_document/composer_renderer.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sstream>
#include <string>
#include <vector>

namespace pwb::mapping_document {
namespace {

// ---------------------------------------------------------------------------
// Python-compatible formatting / coercion helpers
// ---------------------------------------------------------------------------

// Python html.escape(s, quote=True): & < > " ' escaped.
std::string html_escape(const std::string& text) {
    std::string out;
    out.reserve(text.size() + 16);
    for (char c : text) {
        switch (c) {
            case '&': out += "&amp;"; break;
            case '<': out += "&lt;"; break;
            case '>': out += "&gt;"; break;
            case '"': out += "&quot;"; break;
            case '\'': out += "&#x27;"; break;
            default: out += c;
        }
    }
    return out;
}

// Python repr(float) / str(float): shortest round-trip; fixed notation with
// a ".0" tail inside [1e-4, 1e16), scientific outside (like CPython).
std::string py_float_repr(double v) {
    if (std::isnan(v)) return "nan";
    if (std::isinf(v)) return v < 0 ? "-inf" : "inf";
    const double a = std::fabs(v);
    const bool scientific = a != 0.0 && (a < 1e-4 || a >= 1e16);
    char buf[64];
    std::to_chars_result result{};
    if (scientific) {
        result = std::to_chars(buf, buf + sizeof(buf), v);
    } else {
        result = std::to_chars(buf, buf + sizeof(buf), v, std::chars_format::fixed);
    }
    std::string text(buf, result.ptr);
    if (!scientific && text.find('.') == std::string::npos) text += ".0";
    return text;
}

// Python str(value) for the scalar shapes composition properties carry.
std::string py_str_value(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_null()) return "None";
    if (value.is_number_integer()) {
        return std::to_string(value.get<long long>());
    }
    if (value.is_number_float()) return py_float_repr(value.get<double>());
    return value.dump();
}

// Python f"{v:.2f}".
std::string fmt2(double v) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.2f", v);
    return buf;
}

// Python f"{v:g}".
std::string fmt_g(double v) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%g", v);
    return buf;
}

// Python float(text) — full consumption required, like CPython.
bool parse_python_float(const std::string& text, double& out) {
    const char* begin = text.c_str();
    char* end = nullptr;
    errno = 0;
    const double value = std::strtod(begin, &end);
    if (end == begin) return false;
    while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r' || *end == '\v' ||
           *end == '\f') {
        ++end;
    }
    if (*end != '\0') return false;
    out = value;
    return true;
}

// Python `float(value)` with the ValueError/TypeError failure semantics;
// raises std::invalid_argument where Python would raise.
double py_float(const Json& value) {
    if (value.is_number()) return value.get<double>();
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_string()) {
        double parsed = 0.0;
        if (!parse_python_float(value.get<std::string>(), parsed)) {
            throw std::invalid_argument("could not convert string to float: '" +
                                        value.get<std::string>() + "'");
        }
        return parsed;
    }
    throw std::invalid_argument("float() argument must be a number or a string");
}

// Python `float(value or default)` — falsy (null/false/0/""/empty) falls back.
double py_or_float(const Json& value, double fallback) {
    if (value.is_null()) return fallback;
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : fallback;
    if (value.is_number()) {
        const double v = value.get<double>();
        return v == 0.0 ? fallback : v;
    }
    if (value.is_string()) {
        const std::string& text = value.get<std::string>();
        if (text.empty()) return fallback;
        return py_float(value);
    }
    return py_float(value);
}

// Python `str(value or "")` for optional label-ish properties.
std::string py_or_str(const Json& value, const std::string& fallback = "") {
    if (value.is_null()) return fallback;
    if (value.is_boolean()) return value.get<bool>() ? "True" : fallback;
    if (value.is_string()) {
        const std::string& text = value.get<std::string>();
        return text.empty() ? fallback : text;
    }
    if (value.is_number()) {
        const double v = value.get<double>();
        if (v == 0.0) return fallback;
        return py_str_value(value);
    }
    return py_str_value(value);
}

double finite_or(double value, double fallback) {
    return std::isfinite(value) ? value : fallback;
}

// Safe object-member read: a missing key yields a shared null JSON
// (Python dict.get(key) → None).
const Json& json_get(const Json& object, const std::string& key) {
    static const Json kNull = Json(nullptr);
    if (!object.is_object()) return kNull;
    auto it = object.find(key);
    return it == object.end() ? kNull : *it;
}

// Python str.strip() (ASCII whitespace, matching the map-text helpers).
void strip_in_place(std::string& text) {
    const char* kSpace = " \t\n\r\v\f";
    const std::size_t first = text.find_first_not_of(kSpace);
    if (first == std::string::npos) {
        text.clear();
        return;
    }
    const std::size_t last = text.find_last_not_of(kSpace);
    text = text.substr(first, last - first + 1);
}

// Python truthiness for JSON values (bool/None/number/string/empty
// containers).
bool py_truthy(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number_integer()) return value.get<long long>() != 0;
    if (value.is_number_float()) return value.get<double>() != 0.0;
    if (value.is_string()) return !value.get<std::string>().empty();
    if (value.is_array()) return !value.empty();
    if (value.is_object()) return !value.empty();
    return true;
}

// Python `x // 2` rendered with str(): ints stay ints, floats keep ".0".
std::string py_floor_half_str(const Json& value) {
    if (value.is_number_integer()) {
        const long long v = value.get<long long>();
        return std::to_string(v >= 0 ? v / 2 : -((-v + 1) / 2));
    }
    const double v = py_float(value);
    const double halved = std::floor(v / 2.0);
    return py_float_repr(halved);
}

// Python text.splitlines() (the line separators that occur in map text).
std::vector<std::string> py_splitlines(const std::string& text) {
    std::vector<std::string> lines;
    std::string current;
    for (std::size_t i = 0; i < text.size(); ++i) {
        const char c = text[i];
        if (c == '\n' || c == '\r' || c == '\v' || c == '\f') {
            lines.push_back(current);
            current.clear();
            if (c == '\r' && i + 1 < text.size() && text[i + 1] == '\n') ++i;
        } else {
            current += c;
        }
    }
    lines.push_back(current);
    return lines;
}

// Python isinstance(value, (int, float)) and not isinstance(value, bool).
bool py_is_number(const Json& value) {
    return value.is_number() && !value.is_boolean();
}

std::uint64_t fnv1a(const std::string& text) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (unsigned char c : text) {
        hash ^= c;
        hash *= 1099511628211ULL;
    }
    return hash;
}

// ---------------------------------------------------------------------------
// Render context (renderers.py RenderContext, MM units)
// ---------------------------------------------------------------------------

constexpr double kMmPerPx = 25.4 / 96.0;
constexpr double kPtPerPx = 72.0 / 96.0;

class MmContext {
public:
    MmContext(std::array<double, 4> extent, double width, double height,
              double x_offset, double y_offset)
        : extent_(extent), width_(width), height_(height), x_offset_(x_offset),
          y_offset_(y_offset) {}

    double scale_x() const {
        const double dx = extent_[2] - extent_[0];
        return dx > 0 ? width_ / dx : 1.0;
    }
    double scale_y() const {
        const double dy = extent_[3] - extent_[1];
        return dy > 0 ? height_ / dy : 1.0;
    }
    double to_target(double px) const { return px * kMmPerPx; }

    void world_to_screen(double x, double y, double& sx, double& sy) const {
        sx = x_offset_ + (x - extent_[0]) * scale_x();
        sy = y_offset_ + (extent_[3] - y) * scale_y();
    }

    // renderers.py RenderContext.dash_array for the MM regime.
    std::string dash_array(const std::string& pattern, double stroke_px) const {
        std::vector<double> units;
        if (pattern == "dash") units = {4.0, 2.0};
        else if (pattern == "dot") units = {1.0, 2.0};
        else if (pattern == "dash_dot") units = {4.0, 2.0, 1.0, 2.0};
        else if (pattern == "fault") units = {6.0, 2.0};
        else return "";
        std::string out;
        for (double u : units) {
            char buf[32];
            std::snprintf(buf, sizeof(buf), "%.2f", u * stroke_px * kMmPerPx);
            if (!out.empty()) out += ",";
            out += buf;
        }
        return out;
    }

private:
    std::array<double, 4> extent_;
    double width_;
    double height_;
    double x_offset_;
    double y_offset_;
};

// ---------------------------------------------------------------------------
// Read-only style view (map_styles.py VectorStyle subset consumed by the
// dict-layer vector path; cartography's VectorStyle stays the to_dict /
// from_dict authority — decision D-V14-04).
// ---------------------------------------------------------------------------

struct StyleView {
    std::string fill = "#6c8ebf";
    std::string stroke = "#26364d";
    double stroke_width = 1.0;
    std::string line_pattern = "solid";
    std::string marker = "circle";
    double marker_size = 6.0;
    std::string renderer;
    std::string field;
    std::vector<std::array<std::string, 3>> categories;  // value, fill, label
    struct RangeEntry {
        double lo = 0.0;
        double hi = 1.0;
        std::string fill;
        std::string label;
    };
    std::vector<RangeEntry> ranges;  // (lo, hi, fill, label)
    std::string label_field;
    double label_size = 9.0;
    std::string label_color = "#f8f9fa";
    std::string label_font;
    // Python: labels is Optional[TextStyle] — an ABSENT labels object
    // means no labels at all (not default labels).
    bool labels_visible = false;
    bool labels_present = false;

    static StyleView from_dict(const Json& data) {
        StyleView style;
        if (!data.is_object()) return style;
        if (data.contains("fill") && py_truthy(data["fill"])) {
            style.fill = py_str_value(data["fill"]);
        }
        if (data.contains("stroke") && py_truthy(data["stroke"])) {
            style.stroke = py_str_value(data["stroke"]);
        }
        if (data.contains("stroke_width") && !data["stroke_width"].is_null()) {
            try {
                style.stroke_width = std::max(0.0, py_float(data["stroke_width"]));
            } catch (const std::invalid_argument&) {
            }
        }
        if (data.contains("marker_size") && !data["marker_size"].is_null()) {
            try {
                style.marker_size = std::max(0.0, py_float(data["marker_size"]));
            } catch (const std::invalid_argument&) {
            }
        }
        if (data.contains("line_pattern") && py_truthy(data["line_pattern"])) {
            const std::string pattern = py_str_value(data["line_pattern"]);
            if (pattern == "solid" || pattern == "dash" || pattern == "dot" ||
                pattern == "dash_dot" || pattern == "fault" || pattern == "boundary") {
                style.line_pattern = pattern;
            }
        }
        if (data.contains("marker") && py_truthy(data["marker"])) {
            const std::string marker = py_str_value(data["marker"]);
            if (marker == "circle" || marker == "square" || marker == "triangle" ||
                marker == "diamond" || marker == "cross" || marker == "star" ||
                marker == "well") {
                style.marker = marker;
            }
        }
        if (data.contains("renderer") && !data["renderer"].is_null()) {
            style.renderer = py_str_value(data["renderer"]);
        }
        if (data.contains("field") && !data["field"].is_null()) {
            style.field = py_str_value(data["field"]);
        }
        // categories: {"value": color} mapping form or [value, fill, label]
        // list form (QGIS payload + persisted list shapes).
        if (data.contains("categories")) {
            const Json& raw = data["categories"];
            if (raw.is_object()) {
                for (auto it = raw.begin(); it != raw.end(); ++it) {
                    style.categories.push_back({it.key(), py_str_value(it.value()), ""});
                }
            } else if (raw.is_array()) {
                for (const Json& entry : raw) {
                    if (entry.is_array() && entry.size() >= 2) {
                        style.categories.push_back(
                            {py_str_value(entry[0]), py_str_value(entry[1]),
                             entry.size() > 2 ? py_str_value(entry[2]) : ""});
                    }
                }
            }
        }
        // ranges: list form [lo, hi, fill, label?] or mapping form.
        if (data.contains("ranges")) {
            const Json& raw = data["ranges"];
            if (raw.is_array()) {
                for (const Json& entry : raw) {
                    if (entry.is_array() && entry.size() >= 3) {
                        try {
                            StyleView::RangeEntry range;
                            range.lo = py_float(entry[0]);
                            range.hi = py_float(entry[1]);
                            range.fill = py_str_value(entry[2]);
                            range.label =
                                entry.size() > 3 ? py_str_value(entry[3]) : std::string();
                            style.ranges.push_back(std::move(range));
                        } catch (const std::invalid_argument&) {
                        }
                    } else if (entry.is_object()) {
                        try {
                            StyleView::RangeEntry range;
                            const double lo = entry.contains("min")   ? py_float(entry["min"])
                                              : entry.contains("lo") ? py_float(entry["lo"])
                                                                     : 0.0;
                            const double hi = entry.contains("max")   ? py_float(entry["max"])
                                              : entry.contains("hi") ? py_float(entry["hi"])
                                                                     : 1.0;
                            const Json& fill_value =
                                entry.contains("fill")    ? entry["fill"]
                                : entry.contains("color") ? entry["color"]
                                                          : Json("#6c8ebf");
                            const Json& label_value =
                                entry.contains("label") ? entry["label"] : Json("");
                            range.lo = lo;
                            range.hi = hi;
                            range.fill = py_str_value(fill_value);
                            range.label = py_str_value(label_value);
                            style.ranges.push_back(std::move(range));
                        } catch (const std::invalid_argument&) {
                        }
                    }
                }
            }
        }
        // labels: TextStyle subset (field/size/color/font_family/visible).
        if (data.contains("labels") && !data["labels"].is_null()) {
            const Json& labels = data["labels"];
            style.labels_present = true;
            if (labels.is_object()) {
                if (labels.contains("field") && !labels["field"].is_null()) {
                    style.label_field = py_str_value(labels["field"]);
                }
                if (labels.contains("size") && !labels["size"].is_null()) {
                    try {
                        style.label_size = py_float(labels["size"]);
                    } catch (const std::invalid_argument&) {
                    }
                }
                if (labels.contains("color") && !labels["color"].is_null()) {
                    style.label_color = py_str_value(labels["color"]);
                }
                if (labels.contains("font_family") && !labels["font_family"].is_null()) {
                    style.label_font = py_str_value(labels["font_family"]);
                }
                if (labels.contains("visible") && !labels["visible"].is_null()) {
                    style.labels_visible = py_truthy(labels["visible"]);
                } else {
                    // Python TextStyle default: visible=True.
                    style.labels_visible = true;
                }
            }
        }
        return style;
    }
};

// One dict layer materialised from JSON (renderers.py route 3:
// VectorMapLayer(id, name, layer_type, extent, features, style)).
struct DictLayer {
    std::string id;
    std::string name;
    std::string layer_type;
    std::array<double, 4> extent{0.0, 0.0, 0.0, 0.0};
    Json features = Json::array();
    Json style = Json::object();
};

// renderers.py RendererRegistry.resolve for the dict-layer path (the only
// layer class the JSON route materialises).
enum class LayerRendererKind {
    Single, Categorized, Graduated, Well, Annotation, Unsupported
};

LayerRendererKind resolve_renderer(const DictLayer& layer, const StyleView& style) {
    const std::string ltype = [&] {
        std::string out = layer.layer_type;
        std::transform(out.begin(), out.end(), out.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return out;
    }();
    // Python RendererRegistry.resolve (renderers.py 776-798): specialised
    // layer types first, then the style renderer keyword, then ranges, then
    // the layer type, then single. well / well_point / annotation / label
    // have real renderers that only need `features` — exactly the shape the
    // dict-layer route materialises — so they are supported. grid /
    // scalar_grid / contour need grid data a VectorMapLayer does not carry
    // and are refused (Python's GridRenderer also returns "" for them).
    if (ltype == "grid" || ltype == "scalar_grid" || ltype == "contour") {
        return LayerRendererKind::Unsupported;
    }
    if (ltype == "well" || ltype == "well_point") return LayerRendererKind::Well;
    if (ltype == "annotation" || ltype == "label") return LayerRendererKind::Annotation;
    std::string style_renderer = style.renderer;
    std::transform(style_renderer.begin(), style_renderer.end(), style_renderer.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (!style_renderer.empty() && style_renderer != "single") {
        if (style_renderer == "categorized" || style_renderer == "facies") {
            return LayerRendererKind::Categorized;
        }
        if (style_renderer == "graduated") return LayerRendererKind::Graduated;
        if (style_renderer == "well" || style_renderer == "well_point") {
            return LayerRendererKind::Well;
        }
        if (style_renderer == "annotation" || style_renderer == "label") {
            return LayerRendererKind::Annotation;
        }
    }
    if (layer.style.is_object() && layer.style.contains("ranges") &&
        py_truthy(layer.style["ranges"])) {
        return LayerRendererKind::Graduated;
    }
    if (ltype == "facies") return LayerRendererKind::Categorized;
    return LayerRendererKind::Single;
}

// Feature geometry coordinate helpers.
std::vector<std::pair<double, double>> ring_points(const Json& ring) {
    std::vector<std::pair<double, double>> pts;
    if (!ring.is_array()) return pts;
    for (const Json& p : ring) {
        if (p.is_array() && p.size() >= 2) {
            try {
                pts.emplace_back(py_float(p[0]), py_float(p[1]));
            } catch (const std::invalid_argument&) {
            }
        }
    }
    return pts;
}

std::string points_attr(const std::vector<std::pair<double, double>>& pts,
                        const MmContext& ctx) {
    std::string out;
    for (const auto& [wx, wy] : pts) {
        double sx = 0.0;
        double sy = 0.0;
        ctx.world_to_screen(wx, wy, sx, sy);
        if (!out.empty()) out += " ";
        out += fmt2(sx) + "," + fmt2(sy);
    }
    return out;
}

// Feature properties lookup (feature["properties"]).
const Json* feature_props(const Json& feature) {
    if (!feature.is_object()) return nullptr;
    auto it = feature.find("properties");
    if (it == feature.end() || !it->is_object()) return nullptr;
    return &*it;
}

// ---------------------------------------------------------------------------
// The renderer (renderer.py MapComposerRenderer)
// ---------------------------------------------------------------------------

// renderers.py WellSymbolRenderer.render_svg (dict-layer route).
std::vector<std::string> well_layer_fragments(const DictLayer& layer,
                                              const MmContext& ctx,
                                              const StyleView& style) {
    std::vector<std::string> parts;
    for (const Json& feat : layer.features) {
        if (!feat.is_object()) continue;
        auto geom_it = feat.find("geometry");
        if (geom_it == feat.end() || !geom_it->is_object()) continue;
        const Json& geom = *geom_it;
        auto coords_it = geom.find("coordinates");
        if (coords_it == geom.end() || !coords_it->is_array() ||
            coords_it->size() < 2) {
            continue;
        }
        double wx = 0.0;
        double wy = 0.0;
        try {
            wx = py_float((*coords_it)[0]);
            wy = py_float((*coords_it)[1]);
        } catch (const std::invalid_argument&) {
            continue;
        }
        double sx = 0.0;
        double sy = 0.0;
        ctx.world_to_screen(wx, wy, sx, sy);
        const double r = ctx.to_target(std::max(1.5, style.marker_size / 2.0));
        parts.push_back(
            "<circle cx=\"" + fmt2(sx) + "\" cy=\"" + fmt2(sy) + "\" r=\"" +
            fmt2(r) + "\" fill=\"#ffffff\" stroke=\"" + style.stroke +
            "\" stroke-width=\"" + fmt2(ctx.to_target(1)) + "\"/>"
            "<circle cx=\"" +
            fmt2(sx) + "\" cy=\"" + fmt2(sy) + "\" r=\"" +
            fmt2(std::max(ctx.to_target(0.8), r * 0.4)) + "\" fill=\"" +
            style.fill + "\" stroke=\"none\"/>");
        // Well name (+ optional value) label.
        const Json* props = feature_props(feat);
        std::string well_name;
        if (props != nullptr) {
            if (props->contains("name")) well_name = py_or_str((*props)["name"]);
            else if (props->contains("well")) well_name = py_or_str((*props)["well"]);
        }
        strip_in_place(well_name);
        std::string value_suffix;
        if (props != nullptr && props->contains("value") &&
            py_is_number((*props)["value"])) {
            char buf[32];
            std::snprintf(buf, sizeof(buf), " (%.2f)", (*props)["value"].get<double>());
            value_suffix = buf;
        }
        const std::string display_text = well_name + value_suffix;
        if (!display_text.empty() && style.labels_visible) {
            parts.push_back(
                "<text x=\"" + fmt2(sx + r + ctx.to_target(3)) + "\" y=\"" +
                fmt2(sy + ctx.to_target(3)) + "\" font-family=\"" +
                ((style.labels_present && !style.label_font.empty())
                     ? style.label_font
                     : "Arial") +
                "\" font-size=\"" + fmt2(ctx.to_target(style.label_size)) +
                "\" fill=\"" + style.label_color + "\">" +
                html_escape(display_text) + "</text>");
        }
    }
    return parts;
}

// renderers.py AnnotationRenderer.render_svg (dict-layer route).
std::vector<std::string> annotation_layer_fragments(const DictLayer& layer,
                                                    const MmContext& ctx,
                                                    const StyleView& style) {
    std::vector<std::string> parts;
    for (const Json& feat : layer.features) {
        if (!feat.is_object()) continue;
        auto geom_it = feat.find("geometry");
        if (geom_it == feat.end() || !geom_it->is_object()) continue;
        const Json& geom = *geom_it;
        const std::string gtype =
            py_or_str(geom.contains("type") ? geom["type"] : Json(nullptr));
        auto coords_it = geom.find("coordinates");
        if (coords_it == geom.end() || !coords_it->is_array()) continue;
        const Json& coords = *coords_it;
        const Json* props = feature_props(feat);

        auto prop_or_style = [&](const char* key, const std::string& fallback) {
            if (props != nullptr && props->contains(key)) {
                const std::string text = py_or_str((*props)[key]);
                if (!text.empty()) return text;
            }
            return fallback;
        };
        auto prop_float_or = [&](const char* key, double fallback) {
            if (props != nullptr && props->contains(key)) {
                try {
                    const double v = py_or_float((*props)[key], fallback);
                    return v;
                } catch (const std::invalid_argument&) {
                    return fallback;
                }
            }
            return fallback;
        };

        std::string text;
        if (props != nullptr) {
            if (props->contains("text")) text = py_or_str((*props)["text"]);
            else if (props->contains("label")) text = py_or_str((*props)["label"]);
            else if (props->contains("name")) text = py_or_str((*props)["name"]);
        }
        strip_in_place(text);
        // Python: props font_size → props size → style.labels.size (9.0) →
        // 10.0 when the style carries no labels object at all.
        const double font_size =
            prop_float_or("font_size",
                          prop_float_or("size", style.labels_present
                                                  ? style.label_size
                                                  : 10.0));
        const std::string color = prop_or_style(
            "color", style.labels_present ? style.label_color : style.stroke);
        const std::string font_family =
            prop_or_style("font_family",
                          (style.labels_present && !style.label_font.empty())
                              ? style.label_font
                              : "Arial, sans-serif");
        const bool bold = props != nullptr && props->contains("bold")
                              ? py_truthy((*props)["bold"])
                              : false;
        const std::string font_weight = bold ? "bold" : "normal";
        double rotation = 0.0;
        if (props != nullptr && props->contains("rotation")) {
            try {
                rotation = py_or_float((*props)["rotation"], 0.0);
            } catch (const std::invalid_argument&) {
                rotation = 0.0;
            }
        }
        const std::string escaped_text = text.empty() ? "" : html_escape(text);

        if (gtype == "Point" && coords.size() >= 2) {
            double wx = 0.0;
            double wy = 0.0;
            try {
                wx = py_float(coords[0]);
                wy = py_float(coords[1]);
            } catch (const std::invalid_argument&) {
                continue;
            }
            double sx = 0.0;
            double sy = 0.0;
            ctx.world_to_screen(wx, wy, sx, sy);
            std::string transform_attr;
            if (rotation != 0.0) {
                char buf[80];
                std::snprintf(buf, sizeof(buf), "rotate(%.1f %.2f %.2f)", rotation,
                              sx, sy);
                transform_attr = " transform=\"" + std::string(buf) + "\"";
            }
            const bool show_marker =
                props != nullptr && props->contains("show_marker")
                    ? py_truthy((*props)["show_marker"])
                    : false;
            if (style.marker_size > 0 && style.fill != "transparent" && show_marker) {
                const double r = ctx.to_target(std::max(1.0, style.marker_size / 2.0));
                parts.push_back("<circle cx=\"" + fmt2(sx) + "\" cy=\"" + fmt2(sy) +
                                "\" r=\"" + fmt2(r) + "\" fill=\"" + style.fill +
                                "\" stroke=\"" + style.stroke +
                                "\" stroke-width=\"" + fmt2(ctx.to_target(0.5)) +
                                "\"/>");
            }
            if (!escaped_text.empty()) {
                parts.push_back("<text x=\"" + fmt2(sx) + "\" y=\"" + fmt2(sy) +
                                "\" font-family=\"" + font_family +
                                "\" font-size=\"" + fmt2(ctx.to_target(font_size)) +
                                "\" font-weight=\"" + font_weight + "\" fill=\"" +
                                color + "\"" + transform_attr + ">" + escaped_text +
                                "</text>");
            }
        } else if (gtype == "LineString" && !coords.empty()) {
            const std::string pts = points_attr(ring_points(coords), ctx);
            if (!pts.empty()) {
                parts.push_back("<polyline points=\"" + pts +
                                "\" fill=\"none\" stroke=\"" + color +
                                "\" stroke-width=\"" +
                                fmt2(ctx.to_target(style.stroke_width)) + "\"/>");
            }
            if (!escaped_text.empty() && coords.size() >= 2) {
                const std::size_t mid = coords.size() / 2;
                double mx = 0.0;
                double my = 0.0;
                try {
                    const Json& mid_point = coords[mid];
                    if (mid_point.is_array() && mid_point.size() >= 2) {
                        ctx.world_to_screen(py_float(mid_point[0]),
                                            py_float(mid_point[1]), mx, my);
                    }
                } catch (const std::invalid_argument&) {
                }
                std::string transform_attr;
                if (rotation != 0.0) {
                    char buf[80];
                    std::snprintf(buf, sizeof(buf), "rotate(%.1f %.2f %.2f)", rotation,
                                  mx, my);
                    transform_attr = " transform=\"" + std::string(buf) + "\"";
                }
                parts.push_back("<text x=\"" + fmt2(mx) + "\" y=\"" + fmt2(my) +
                                "\" font-family=\"" + font_family +
                                "\" font-size=\"" + fmt2(ctx.to_target(font_size)) +
                                "\" font-weight=\"" + font_weight + "\" fill=\"" +
                                color + "\" text-anchor=\"middle\"" + transform_attr +
                                ">" + escaped_text + "</text>");
            }
        }
    }
    return parts;
}

class ComposerRenderer {
public:
    explicit ComposerRenderer(const ComposerRenderSeams& seams) : seams_(seams) {}

    std::string render_to_svg(const Composition& doc) {
        const double w_px = doc.width_mm * 3.7795275591;
        const double h_px = doc.height_mm * 3.7795275591;
        std::vector<std::string> parts;
        parts.push_back(
            "<svg xmlns=\"http://www.w3.org/2000/svg\" "
            "xmlns:xlink=\"http://www.w3.org/1999/xlink\" viewBox=\"0 0 " +
            py_float_repr(doc.width_mm) + " " + py_float_repr(doc.height_mm) +
            "\" width=\"" + py_float_repr(w_px) + "px\" height=\"" +
            py_float_repr(h_px) + "px\">");
        parts.push_back("<rect width=\"" + py_float_repr(doc.width_mm) +
                        "\" height=\"" + py_float_repr(doc.height_mm) +
                        "\" fill=\"#ffffff\" stroke=\"#333333\" stroke-width=\"0.5\"/>");

        const ComposerElement* main_map = nullptr;
        for (const auto& elem : doc.elements) {
            if (elem.element_type == "main_map" && elem.visible) {
                main_map = &elem;
                break;
            }
        }

        for (const auto& elem : doc.elements) {
            if (!elem.visible) continue;
            parts.push_back(render_element(elem, main_map));
            if (elem.locked) parts.push_back(locked_marker(elem));
        }
        parts.push_back("</svg>");
        return join(parts);
    }

private:
    // ---- properties accessors (Python .get semantics) ---------------------
    static const Json& prop(const ComposerElement& elem, const std::string& key) {
        static const Json kNull = Json(nullptr);
        if (!elem.properties.is_object()) return kNull;
        auto it = elem.properties.find(key);
        return it == elem.properties.end() ? kNull : *it;
    }
    static bool has_prop(const ComposerElement& elem, const std::string& key) {
        return elem.properties.is_object() && elem.properties.contains(key);
    }

    // ---- element dispatch (renderer.py _render_element_svg) ---------------
    std::string render_element(const ComposerElement& elem,
                               const ComposerElement* main_map) {
        const std::string& t = elem.element_type;
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;

        if (t == "main_map") return render_main_map(elem);
        if (t == "title") {
            const std::string title_text = html_escape(py_str_value(
                prop(elem, "text").is_null() ? Json("古地理图") : prop(elem, "text")));
            return "<g id=\"" + elem.id + "\"><text x=\"" + py_float_repr(x + w / 2) +
                   "\" y=\"" + py_float_repr(y + h - 2) +
                   "\" font-family=\"SimSun, Times New Roman, sans-serif\" font-size=\"8\""
                   " font-weight=\"bold\" fill=\"#000000\" text-anchor=\"middle\">" +
                   title_text + "</text></g>";
        }
        if (t == "north_arrow") {
            const double cx = x + w / 2;
            return "<g id=\"" + elem.id + "\"><polygon points=\"" +
                   py_float_repr(cx) + "," + py_float_repr(y) + " " +
                   py_float_repr(x + w) + "," + py_float_repr(y + h) + " " +
                   py_float_repr(cx) + "," + py_float_repr(y + h * 0.75) + " " +
                   py_float_repr(x) + "," + py_float_repr(y + h) +
                   "\" fill=\"#000000\" stroke=\"#000000\" stroke-width=\"0.2\"/>"
                   "<text x=\"" +
                   py_float_repr(cx) + "\" y=\"" + py_float_repr(y - 1) +
                   "\" font-family=\"Arial, sans-serif\" font-size=\"4\""
                   " font-weight=\"bold\" fill=\"#000000\" text-anchor=\"middle\">N</text></g>";
        }
        if (t == "scale_bar") {
            const Json& length = has_prop(elem, "length_km") ? prop(elem, "length_km")
                                                             : Json(50);
            return "<g id=\"" + elem.id + "\"><rect x=\"" + py_float_repr(x) +
                   "\" y=\"" + py_float_repr(y + h / 2 - 1) + "\" width=\"" +
                   py_float_repr(w) + "\" height=\"2\" fill=\"#000000\"/><rect x=\"" +
                   py_float_repr(x) + "\" y=\"" + py_float_repr(y + h / 2 - 1) +
                   "\" width=\"" + py_float_repr(w / 2) +
                   "\" height=\"2\" fill=\"#ffffff\" stroke=\"#000000\""
                   " stroke-width=\"0.2\"/><text x=\"" +
                   py_float_repr(x) + "\" y=\"" + py_float_repr(y + h - 1) +
                   "\" font-family=\"Arial, sans-serif\" font-size=\"3\""
                   " fill=\"#000000\" text-anchor=\"start\">0</text><text x=\"" +
                   py_float_repr(x + w / 2) + "\" y=\"" + py_float_repr(y + h - 1) +
                   "\" font-family=\"Arial, sans-serif\" font-size=\"3\""
                   " fill=\"#000000\" text-anchor=\"middle\">" +
                   py_floor_half_str(length) + "</text><text x=\"" +
                   py_float_repr(x + w) + "\" y=\"" + py_float_repr(y + h - 1) +
                   "\" font-family=\"Arial, sans-serif\" font-size=\"3\""
                   " fill=\"#000000\" text-anchor=\"end\">" +
                   py_str_value(length) + " km</text></g>";
        }
        if (t == "legend" || t == "facies_legend") return render_legend(elem, main_map);
        if (t == "text" || t == "strat_labels") return render_text(elem);
        if (t == "image") return render_image(elem);
        if (t == "inset_map") return render_inset_map(elem);
        if (t == "stat_chart") return render_stat_chart(elem);
        if (t == "metadata") return render_metadata(elem);
        if (t == "colorbar") return render_colorbar(elem);
        if (t == "grid") return render_grid(elem);
        if (t == "annotation") return render_annotation(elem);
        if (t == "timescale") return render_timescale(elem);
        if (t == "neatline") return render_neatline(elem);
        if (t == "datasource") return render_datasource(elem);
        if (t == "time_credits") return render_time_credits(elem);
        if (t == "fault_symbols") return render_fault_symbols(elem);
        if (t == "lithology_legend") return render_lithology_legend(elem);
        if (t == "subtitle") {
            // Python: str(elem.properties.get("text", "")) — the default
            // applies only when the key is ABSENT; a present falsy value
            // renders (0 → "0", None → "None").
            const std::string subtitle_text =
                html_escape(has_prop(elem, "text") ? py_str_value(prop(elem, "text"))
                                                   : "");
            const double font_size = py_or_float(prop(elem, "font_size"), 5.0);
            return "<g id=\"" + elem.id + "\"><text x=\"" + py_float_repr(x + w / 2) +
                   "\" y=\"" + py_float_repr(y + h - 1) +
                   "\" font-family=\"SimSun, Times New Roman, sans-serif\" font-size=\"" +
                   py_float_repr(font_size) +
                   "\" fill=\"#333333\" text-anchor=\"middle\">" + subtitle_text +
                   "</text></g>";
        }
        if (t == "well_legend") {
            if (!py_truthy(prop(elem, "items"))) return placeholder(elem);
            return render_legend(elem, main_map);
        }
        if (t == "profile") {
            if (!py_truthy(prop(elem, "section_ref"))) {
                return placeholder(elem, "剖面（未绑定数据）");
            }
            return render_inset_map(elem);
        }
        // Unknown element type: honest dashed frame (never fabricated).
        return "<rect id=\"" + elem.id + "\" x=\"" + py_float_repr(x) + "\" y=\"" +
               py_float_repr(y) + "\" width=\"" + py_float_repr(w) + "\" height=\"" +
               py_float_repr(h) + "\" fill=\"none\" stroke=\"#cccccc\""
               " stroke-dasharray=\"1,1\"/>";
    }

    // ---- shared pieces ----------------------------------------------------
    static std::string placeholder(const ComposerElement& elem,
                                   const std::string& label = "") {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        const std::string text = label.empty() ? "" : html_escape(label);
        const std::string label_svg =
            text.empty()
                ? ""
                : "<text x=\"" + py_float_repr(x + w / 2) + "\" y=\"" +
                      py_float_repr(y + h / 2) +
                      "\" font-family=\"sans-serif\" font-size=\"4\" fill=\"#999999\""
                      " text-anchor=\"middle\">" +
                      text + "</text>";
        return "<g id=\"" + elem.id + "\" data-placeholder=\"true\"><rect x=\"" +
               py_float_repr(x) + "\" y=\"" + py_float_repr(y) + "\" width=\"" +
               py_float_repr(w) + "\" height=\"" + py_float_repr(h) +
               "\" fill=\"none\" stroke=\"#cccccc\" stroke-dasharray=\"1,1\"/>" +
               label_svg + "</g>";
    }

    static std::string locked_marker(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        return "<g data-locked=\"true\" data-element=\"" + elem.id +
               "\"><path d=\"M " + fmt2(x) + " " + fmt2(y) + " L " + fmt2(x + 4.2) + " " +
               fmt2(y) + " L " + fmt2(x) + " " + fmt2(y + 4.2) +
               " Z\" fill=\"#2f6fab\" fill-opacity=\"0.65\"/></g>";
    }

    // renderer.py _multiline_text_svg
    static std::string multiline_text(const std::string& elem_id, double x, double y,
                                      double w, double h, const std::string& text,
                                      double font_size, const std::string& color = "#000000",
                                      const std::string& align = "left") {
        const std::string anchor =
            align == "center" ? "middle" : (align == "right" ? "end" : "start");
        const double tx = align == "center" ? x + w / 2 : (align == "right" ? x + w : x);
        std::vector<std::string> lines = py_splitlines(text);
        if (lines.empty()) lines.push_back("");
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem_id + "\">");
        for (std::size_t i = 0; i < lines.size(); ++i) {
            const double ly = y + font_size + static_cast<double>(i) * font_size * 1.35;
            if (ly > y + h + 0.01) break;
            parts.push_back("<text x=\"" + fmt2(tx) + "\" y=\"" + fmt2(ly) +
                            "\" font-family=\"SimSun, Arial, sans-serif\" font-size=\"" +
                            py_float_repr(font_size) + "\" fill=\"" + color +
                            "\" text-anchor=\"" + anchor + "\">" +
                            html_escape(lines[i]) + "</text>");
        }
        parts.push_back("</g>");
        return join(parts);
    }

    // Python "\n".join(parts) — a separator between parts, never a trailing
    // newline after the last one.
    static std::string join(const std::vector<std::string>& parts) {
        std::string out;
        for (std::size_t i = 0; i < parts.size(); ++i) {
            if (i != 0) out += "\n";
            out += parts[i];
        }
        return out;
    }

    std::string render_text(const ComposerElement& elem) {
        const std::string text = py_or_str(prop(elem, "text"));
        const double font_size = py_or_float(prop(elem, "font_size"), 4.0);
        const std::string color = py_or_str(prop(elem, "color"), "#000000");
        const std::string align = py_or_str(prop(elem, "align"), "left");
        return multiline_text(elem.id, elem.x_mm, elem.y_mm, elem.width_mm,
                              elem.height_mm, text, font_size, color, align);
    }

    std::string render_neatline(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        const double line_width =
            std::max(0.05, py_or_float(prop(elem, "line_width_mm"), 0.8));
        const std::string color = py_or_str(prop(elem, "color"), "#000000");
        const bool double_line = py_truthy(prop(elem, "double_line"));
        const double gap = std::max(0.5, py_or_float(prop(elem, "inner_gap_mm"), 1.5));
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        parts.push_back("<rect x=\"" + fmt2(x) + "\" y=\"" + fmt2(y) + "\" width=\"" +
                        fmt2(w) + "\" height=\"" + fmt2(h) + "\" fill=\"none\" stroke=\"" +
                        html_escape(color) + "\" stroke-width=\"" + fmt2(line_width) + "\"/>");
        if (double_line) {
            parts.push_back("<rect x=\"" + fmt2(x + gap) + "\" y=\"" + fmt2(y + gap) +
                            "\" width=\"" + fmt2(std::max(0.5, w - 2 * gap)) +
                            "\" height=\"" + fmt2(std::max(0.5, h - 2 * gap)) +
                            "\" fill=\"none\" stroke=\"" + html_escape(color) +
                            "\" stroke-width=\"" +
                            fmt2(std::min(0.4, line_width * 0.5)) + "\"/>");
        }
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_datasource(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        const std::string title = py_or_str(prop(elem, "title"), "数据来源");
        const std::string text = py_or_str(prop(elem, "text"));
        const double font_size = py_or_float(prop(elem, "font_size"), 2.8);
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        parts.push_back("<text x=\"" + fmt2(x) + "\" y=\"" +
                        fmt2(y + font_size + 0.6) +
                        "\" font-family=\"SimSun, Arial\" font-size=\"" +
                        fmt2(font_size + 0.4) +
                        "\" font-weight=\"bold\" fill=\"#000000\">" +
                        html_escape(title) + "</text>");
        const double rule_y = y + 2 * font_size + 1.4;
        parts.push_back("<line x1=\"" + fmt2(x) + "\" y1=\"" + fmt2(rule_y) +
                        "\" x2=\"" + fmt2(x + w) + "\" y2=\"" + fmt2(rule_y) +
                        "\" stroke=\"#666666\" stroke-width=\"0.15\"/>");
        parts.push_back(multiline_text(elem.id + "_body", x, rule_y + 0.4, w,
                                       std::max(0.0, h - (rule_y - y)), text,
                                       font_size));
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_time_credits(const ComposerElement& elem) {
        const std::string text = py_or_str(prop(elem, "text"));
        const double font_size = py_or_float(prop(elem, "font_size"), 2.6);
        return multiline_text(elem.id, elem.x_mm, elem.y_mm, elem.width_mm,
                              elem.height_mm, text, font_size, "#333333", "right");
    }

    std::string render_timescale(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        const Json& raw_stages = prop(elem, "stages");
        std::vector<const Json*> stages;
        if (raw_stages.is_array()) {
            for (const Json& s : raw_stages) {
                if (s.is_object()) stages.push_back(&s);
            }
        }
        if (stages.empty()) {
            return "<g id=\"" + elem.id + "\"><rect x=\"" + fmt2(x) + "\" y=\"" +
                   fmt2(y) + "\" width=\"" + fmt2(w) + "\" height=\"" + fmt2(h) +
                   "\" fill=\"none\" stroke=\"#cccccc\" stroke-dasharray=\"1,1\"/>"
                   "<text x=\"" +
                   fmt2(x + w / 2) + "\" y=\"" + fmt2(y + h / 2) +
                   "\" font-family=\"SimSun, Arial\" font-size=\"2.6\""
                   " fill=\"#999999\" text-anchor=\"middle\">年代地层（未配置 stages）</text></g>";
        }
        std::vector<double> weights;
        weights.reserve(stages.size());
        for (const Json* stage : stages) {
            double start = 0.0;
            double end = 0.0;
            const Json& raw_start = json_get(*stage, "start");
            if (!raw_start.is_null()) {
                try {
                    start = py_float(raw_start);
                } catch (const std::invalid_argument&) {
                    start = 0.0;
                }
            }
            const Json& raw_end = json_get(*stage, "end");
            if (!raw_end.is_null()) {
                try {
                    end = py_float(raw_end);
                } catch (const std::invalid_argument&) {
                    end = 0.0;
                }
            }
            const double span = end - start;
            weights.push_back(span > 0 ? span : 1.0);
        }
        double total = 0.0;
        for (double weight : weights) total += weight;
        const double bar_h = std::min(h * 0.55, 6.0);
        const double bar_y = y + (h - bar_h - 3.2) / 2;
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        double cx = x;
        for (std::size_t i = 0; i < stages.size(); ++i) {
            const double seg_w = w * weights[i] / total;
            const std::string color = py_or_str(json_get(*stages[i], "color"), "#b0bec5");
            parts.push_back("<rect x=\"" + fmt2(cx) + "\" y=\"" + fmt2(bar_y) +
                            "\" width=\"" + fmt2(seg_w) + "\" height=\"" + fmt2(bar_h) +
                            "\" fill=\"" + html_escape(color) +
                            "\" stroke=\"#37474f\" stroke-width=\"0.15\"/>");
            const std::string label = py_or_str(json_get(*stages[i], "label"));
            if (!label.empty()) {
                parts.push_back("<text x=\"" + fmt2(cx + seg_w / 2) + "\" y=\"" +
                                fmt2(bar_y + bar_h + 2.8) +
                                "\" font-family=\"SimSun, Arial\" font-size=\"2.4\""
                                " fill=\"#000000\" text-anchor=\"middle\">" +
                                html_escape(label) + "</text>");
            }
            cx += seg_w;
        }
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_fault_symbols(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const std::string title = py_or_str(prop(elem, "title"), "断层符号");
        const Json& raw_items = prop(elem, "items");
        std::vector<const Json*> items;
        if (raw_items.is_array()) {
            for (const Json& it : raw_items) {
                if (it.is_object()) items.push_back(&it);
            }
        }
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        parts.push_back("<text x=\"" + fmt2(x) + "\" y=\"" + fmt2(y + 4.2) +
                        "\" font-family=\"SimSun, Arial\" font-size=\"3.4\""
                        " font-weight=\"bold\" fill=\"#000000\">" +
                        html_escape(title) + "</text>");
        const double item_h = 5.2;
        const double sample_len = std::min(12.0, w * 0.35);
        for (std::size_t idx = 0; idx < items.size(); ++idx) {
            const double iy = y + 7.0 + static_cast<double>(idx) * item_h;
            std::string pattern =
                py_or_str(json_get(*items[idx], "pattern"), "solid");
            std::transform(pattern.begin(), pattern.end(), pattern.begin(),
                           [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            std::string dash;
            if (pattern == "dash") dash = "2.4,1.2";
            else if (pattern == "dot") dash = "0.6,0.9";
            else if (pattern == "dashdot") dash = "2.8,1.0,0.6,1.0";
            else if (pattern == "fault") dash = "3.2,1.2";
            const std::string dash_attr = dash.empty() ? "" : " stroke-dasharray=\"" + dash + "\"";
            parts.push_back("<line x1=\"" + fmt2(x + 2.0) + "\" y1=\"" + fmt2(iy) +
                            "\" x2=\"" + fmt2(x + 2.0 + sample_len) + "\" y2=\"" +
                            fmt2(iy) + "\" stroke=\"#1a1a1a\" stroke-width=\"0.55\"" +
                            dash_attr + "/>");
            const std::string label = py_or_str(json_get(*items[idx], "label"));
            parts.push_back("<text x=\"" + fmt2(x + 2.0 + sample_len + 2.5) + "\" y=\"" +
                            fmt2(iy + 0.9) + "\" font-family=\"SimSun, Arial\""
                            " font-size=\"2.6\" fill=\"#000000\">" +
                            html_escape(label) + "</text>");
        }
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_lithology_legend(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const std::string title = py_or_str(prop(elem, "title"), "岩性图例");
        const Json& raw_items = prop(elem, "items");
        std::vector<const Json*> items;
        if (raw_items.is_array()) {
            for (const Json& it : raw_items) {
                if (it.is_object()) items.push_back(&it);
            }
        }
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        parts.push_back("<text x=\"" + fmt2(x) + "\" y=\"" + fmt2(y + 4.6) +
                        "\" font-family=\"SimSun, Arial\" font-size=\"3.6\""
                        " font-weight=\"bold\" fill=\"#000000\">" +
                        html_escape(title) + "</text>");
        const double item_h = 6.0;
        const double swatch_w = 9.0;
        const double swatch_h = 3.6;
        for (std::size_t idx = 0; idx < items.size(); ++idx) {
            const double iy = y + 7.0 + static_cast<double>(idx) * item_h;
            const std::string color = py_or_str(json_get(*items[idx], "color"), "#cfd8dc");
            std::string pattern = py_or_str(json_get(*items[idx], "pattern"));
            std::transform(pattern.begin(), pattern.end(), pattern.begin(),
                           [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            parts.push_back("<rect x=\"" + fmt2(x + 3.0) + "\" y=\"" + fmt2(iy) +
                            "\" width=\"" + fmt2(swatch_w) + "\" height=\"" +
                            fmt2(swatch_h) + "\" fill=\"" + html_escape(color) +
                            "\" stroke=\"#333333\" stroke-width=\"0.15\"/>");
            if (pattern == "dots" || pattern == "lines" || pattern == "crosshatch") {
                // Deterministic pattern id (Python hash() is process-random).
                const std::string seed =
                    elem.id + "|" + pattern + "|" + std::to_string(idx);
                const std::string pat_id =
                    "lith_" + std::to_string(fnv1a(seed) % 100000);
                std::string tile;
                std::string size_text;
                if (pattern == "dots") {
                    tile = "<circle cx=\"0.5\" cy=\"0.5\" r=\"0.22\" fill=\"#00000088\"/>"
                           "<circle cx=\"1.5\" cy=\"1.5\" r=\"0.22\" fill=\"#00000088\"/>";
                    size_text = "2.0";
                } else if (pattern == "lines") {
                    tile = "<line x1=\"0\" y1=\"1.6\" x2=\"1.6\" y2=\"0\""
                           " stroke=\"#00000077\" stroke-width=\"0.18\"/>";
                    size_text = "1.6";
                } else {
                    tile = "<line x1=\"0\" y1=\"1.4\" x2=\"1.4\" y2=\"0\""
                           " stroke=\"#00000077\" stroke-width=\"0.15\"/>"
                           "<line x1=\"0\" y1=\"0\" x2=\"1.4\" y2=\"1.4\""
                           " stroke=\"#00000077\" stroke-width=\"0.15\"/>";
                    size_text = "1.4";
                }
                parts.push_back("<defs><pattern id=\"" + pat_id + "\" width=\"" +
                                size_text + "\" height=\"" + size_text +
                                "\" patternUnits=\"userSpaceOnUse\">" + tile +
                                "</pattern></defs>");
                parts.push_back("<rect x=\"" + fmt2(x + 3.0) + "\" y=\"" + fmt2(iy) +
                                "\" width=\"" + fmt2(swatch_w) + "\" height=\"" +
                                fmt2(swatch_h) + "\" fill=\"url(#" + pat_id + ")\"/>");
            }
            const std::string label = py_or_str(json_get(*items[idx], "label"));
            parts.push_back("<text x=\"" + fmt2(x + 3.0 + swatch_w + 2.5) + "\" y=\"" +
                            fmt2(iy + 2.7) + "\" font-family=\"SimSun, Arial\""
                            " font-size=\"2.8\" fill=\"#000000\">" +
                            html_escape(label) + "</text>");
        }
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_annotation(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        const std::string text = py_or_str(prop(elem, "text"));
        const double font_size = py_or_float(prop(elem, "font_size"), 3.5);
        const bool leader = has_prop(elem, "leader") ? py_truthy(prop(elem, "leader")) : true;
        const double anchor_x = x + w;
        const double anchor_y = y + h;
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        if (leader) {
            parts.push_back("<line x1=\"" + fmt2(anchor_x) + "\" y1=\"" +
                            fmt2(anchor_y) + "\" x2=\"" + fmt2(x + w * 0.2) + "\" y2=\"" +
                            fmt2(y + h * 0.35) + "\" stroke=\"#555555\""
                            " stroke-width=\"0.2\"/>");
            parts.push_back("<circle cx=\"" + fmt2(anchor_x) + "\" cy=\"" +
                            fmt2(anchor_y) + "\" r=\"0.5\" fill=\"#555555\"/>");
        }
        parts.push_back("<text x=\"" + fmt2(x) + "\" y=\"" + fmt2(y + font_size) +
                        "\" font-family=\"SimSun, Arial, sans-serif\" font-size=\"" +
                        py_float_repr(font_size) + "\" fill=\"#111111\">" +
                        html_escape(text) + "</text>");
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_grid(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        const double spacing = std::max(2.0, py_or_float(prop(elem, "spacing_mm"), 20.0));
        const std::string color = py_or_str(prop(elem, "color"), "#9aa4b2");
        const double width_mm = py_or_float(prop(elem, "line_width_mm"), 0.2);
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        // Structural guard: a pathological width must not turn the frame
        // into a multi-gigabyte string (prompt scale budget).
        const int kMaxGridLines = 20000;
        int lines = 0;
        double gx = x + spacing;
        while (gx < x + w - 0.01 && lines < kMaxGridLines) {
            ++lines;
            parts.push_back("<line x1=\"" + fmt2(gx) + "\" y1=\"" + fmt2(y) + "\" x2=\"" +
                            fmt2(gx) + "\" y2=\"" + fmt2(y + h) + "\" stroke=\"" +
                            color + "\" stroke-width=\"" + py_float_repr(width_mm) +
                            "\" stroke-dasharray=\"1.5,1\"/>");
            gx += spacing;
        }
        lines = 0;
        double gy = y + spacing;
        while (gy < y + h - 0.01 && lines < kMaxGridLines) {
            ++lines;
            parts.push_back("<line x1=\"" + fmt2(x) + "\" y1=\"" + fmt2(gy) + "\" x2=\"" +
                            fmt2(x + w) + "\" y2=\"" + fmt2(gy) + "\" stroke=\"" +
                            color + "\" stroke-width=\"" + py_float_repr(width_mm) +
                            "\" stroke-dasharray=\"1.5,1\"/>");
            gy += spacing;
        }
        parts.push_back("<rect x=\"" + fmt2(x) + "\" y=\"" + fmt2(y) + "\" width=\"" +
                        fmt2(w) + "\" height=\"" + fmt2(h) + "\" fill=\"none\""
                        " stroke=\"#444444\" stroke-width=\"0.35\"/>");
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_image(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        std::string href;
        if (py_truthy(prop(elem, "image_data_png_b64"))) {
            href = "data:image/png;base64," +
                   py_str_value(prop(elem, "image_data_png_b64"));
        } else if (py_truthy(prop(elem, "image_path"))) {
            href = py_str_value(prop(elem, "image_path"));
        }
        if (href.empty()) {
            return "<g id=\"" + elem.id + "\"><rect x=\"" + fmt2(x) + "\" y=\"" +
                   fmt2(y) + "\" width=\"" + fmt2(w) + "\" height=\"" + fmt2(h) +
                   "\" fill=\"#f2f4f7\" stroke=\"#999999\" stroke-width=\"0.2\"/>"
                   "<text x=\"" +
                   fmt2(x + w / 2) + "\" y=\"" + fmt2(y + h / 2) +
                   "\" font-family=\"Arial\" font-size=\"3.4\" fill=\"#777777\""
                   " text-anchor=\"middle\">图像占位（未绑定）</text></g>";
        }
        return "<g id=\"" + elem.id + "\"><image x=\"" + fmt2(x) + "\" y=\"" +
               fmt2(y) + "\" width=\"" + fmt2(w) + "\" height=\"" + fmt2(h) +
               "\" xlink:href=\"" + html_escape(href) +
               "\" preserveAspectRatio=\"xMidYMid meet\"/></g>";
    }

    // renderer.py _render_inset_map_svg
    std::string render_inset_map(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        parts.push_back("<rect x=\"" + fmt2(x) + "\" y=\"" + fmt2(y) + "\" width=\"" +
                        fmt2(w) + "\" height=\"" + fmt2(h) +
                        "\" fill=\"#ffffff\" stroke=\"#444444\" stroke-width=\"0.35\"/>");
        parts.push_back("<text x=\"" + fmt2(x + 2) + "\" y=\"" + fmt2(y + 4.4) +
                        "\" font-family=\"SimSun, Arial\" font-size=\"3.2\""
                        " fill=\"#333333\">附图</text>");
        if (seams_.frame_content) {
            ComposerRenderSeams::FrameContent content = seams_.frame_content(elem);
            if (content.bound) {
                if (!content.png_b64.empty()) {
                    parts.push_back("<image x=\"" + fmt2(x) + "\" y=\"" + fmt2(y) +
                                    "\" width=\"" + fmt2(w) + "\" height=\"" + fmt2(h) +
                                    "\" xlink:href=\"data:image/png;base64," +
                                    content.png_b64 +
                                    "\" preserveAspectRatio=\"xMidYMid meet\"/>");
                }
                for (const std::string& fragment : content.svg_fragments) {
                    if (!fragment.empty()) parts.push_back(fragment);
                }
            }
        }
        const Json& locator = prop(elem, "locator_rect");
        if (locator.is_array() && locator.size() == 4) {
            const double lx = py_float(locator[0]);
            const double ly = py_float(locator[1]);
            const double lw = py_float(locator[2]);
            const double lh = py_float(locator[3]);
            parts.push_back("<rect x=\"" + fmt2(x + lx * w) + "\" y=\"" +
                            fmt2(y + ly * h) + "\" width=\"" + fmt2(lw * w) +
                            "\" height=\"" + fmt2(lh * h) + "\" fill=\"none\""
                            " stroke=\"#d84315\" stroke-width=\"0.4\"/>");
        }
        parts.push_back("<rect x=\"" + fmt2(x) + "\" y=\"" + fmt2(y) + "\" width=\"" +
                        fmt2(w) + "\" height=\"" + fmt2(h) + "\" fill=\"none\""
                        " stroke=\"#444444\" stroke-width=\"0.35\"/>");
        parts.push_back("</g>");
        return join(parts);
    }

    // ------------------------------------------------------------------
    // 统计图（renderer.py B6 charts）
    // ------------------------------------------------------------------

    static std::vector<std::string> chart_colors(const ComposerElement& elem) {
        static const char* kDefault[] = {"#4c78a8", "#f58518", "#e45756",
                                         "#72b7b2", "#54a24b", "#eeca3b"};
        std::vector<std::string> colors;
        const Json& raw = prop(elem, "colors");
        if (raw.is_array()) {
            for (const Json& c : raw) {
                const std::string text = py_or_str(c);
                const bool blank = text.find_first_not_of(" \t\n\r\v\f") == std::string::npos;
                if (!blank) colors.push_back(text);
            }
            if (!colors.empty()) return colors;
        }
        for (const char* c : kDefault) colors.push_back(c);
        return colors;
    }

    static void series_entries(const Json& series, std::vector<std::string>& labels,
                               std::vector<double>& values) {
        if (!series.is_array()) return;
        for (const Json& entry : series) {
            if (!entry.is_object()) continue;
            labels.push_back(entry.contains("label") ? py_str_value(json_get(entry, "label"))
                                                        : "");
            const Json& raw_value = json_get(entry, "value");
            double value = 0.0;
            try {
                const double parsed = py_or_float(raw_value, 0.0);
                value = finite_or(parsed, 0.0);
            } catch (const std::invalid_argument&) {
                value = 0.0;
            }
            values.push_back(value);
        }
    }

    static void floats(const Json& raw, std::vector<double>& out) {
        if (!raw.is_array()) return;
        for (const Json& v : raw) {
            if (!py_is_number(v)) continue;
            const double parsed = v.get<double>();
            if (!std::isfinite(parsed)) continue;
            out.push_back(finite_or(parsed, 0.0));
        }
    }

    // renderer.py _xy_series
    static void xy_series(const Json& series, std::vector<double>& xs,
                          std::vector<double>& ys, std::vector<std::string>& labels,
                          bool& x_is_value) {
        if (series.is_object()) {
            floats(series.contains("x") ? series["x"] : Json::array(), xs);
            floats(series.contains("y") ? series["y"] : Json::array(), ys);
            const std::size_t count = std::min(xs.size(), ys.size());
            xs.resize(count);
            ys.resize(count);
            labels.assign(count, "");
            x_is_value = true;
            return;
        }
        if (series.is_array()) {
            std::vector<const Json*> entries;
            for (const Json& s : series) {
                if (s.is_object()) entries.push_back(&s);
            }
            bool all_points = !entries.empty();
            for (const Json* s : entries) {
                const bool x_number = s->contains("x") && py_is_number((*s)["x"]);
                const bool y_number = s->contains("y") && py_is_number((*s)["y"]);
                if (!x_number || !y_number) {
                    all_points = false;
                    break;
                }
            }
            if (all_points) {
                for (const Json* s : entries) {
                    xs.push_back((*s)["x"].get<double>());
                    ys.push_back((*s)["y"].get<double>());
                    labels.push_back(s->contains("label") ? py_or_str(json_get(*s, "label"))
                                                        : "");
                }
                x_is_value = true;
                return;
            }
            series_entries(series, labels, ys);
            xs.resize(ys.size());
            for (std::size_t i = 0; i < xs.size(); ++i) {
                xs[i] = static_cast<double>(i);
            }
            x_is_value = false;
            return;
        }
        x_is_value = false;
    }

    static double hole_ratio(const ComposerElement& elem) {
        double hole = 0.55;
        if (elem.properties.is_object() && elem.properties.contains("hole_ratio")) {
            try {
                hole = py_float(elem.properties["hole_ratio"]);
            } catch (const std::invalid_argument&) {
                return 0.55;
            }
        }
        if (!std::isfinite(hole)) return 0.55;
        return std::min(0.9, std::max(0.0, hole));
    }

    static void histogram_data(const ComposerElement& elem, std::vector<double>& values,
                               int& bins) {
        const Json& series = prop(elem, "series");
        Json raw_values = Json::array();
        Json raw_bins = Json(nullptr);
        if (series.is_object()) {
            raw_values = series.contains("values") ? series["values"] : Json::array();
            if (series.contains("bins") && py_truthy(series["bins"])) {
                raw_bins = series["bins"];
            } else if (has_prop(elem, "bins") && py_truthy(prop(elem, "bins"))) {
                raw_bins = prop(elem, "bins");
            } else {
                raw_bins = Json(10);
            }
        } else {
            raw_values = has_prop(elem, "values") ? prop(elem, "values") : Json::array();
            raw_bins = (has_prop(elem, "bins") && py_truthy(prop(elem, "bins")))
                           ? prop(elem, "bins")
                           : Json(10);
        }
        if (raw_values.is_array()) {
            for (const Json& value : raw_values) {
                if (!py_is_number(value)) continue;
                const double parsed = value.get<double>();
                if (!std::isfinite(parsed)) continue;
                values.push_back(parsed);
            }
        }
        try {
            const double parsed = py_or_float(raw_bins, 10.0);
            int parsed_bins = static_cast<int>(parsed);
            if (parsed_bins < 0 || static_cast<double>(parsed_bins) != parsed) {
                // Python int() truncates toward zero.
                parsed_bins = static_cast<int>(parsed);
            }
            bins = std::max(2, std::min(60, parsed_bins));
        } catch (const std::invalid_argument&) {
            bins = 10;
        }
    }

    static void polar(double cx, double cy, double r, double angle_deg, double& x,
                      double& y) {
        const double rad = angle_deg * 3.14159265358979323846 / 180.0;
        x = cx + r * std::sin(rad);
        y = cy - r * std::cos(rad);
    }

    static std::string chart_placeholder(double x, double y, double w, double h) {
        return "<text x=\"" + fmt2(x + w / 2) + "\" y=\"" + fmt2(y + h / 2) +
               "\" font-family=\"SimSun, Arial\" font-size=\"3.0\" fill=\"#888888\""
               " text-anchor=\"middle\">统计图（无数据）</text>";
    }

    static void draw_axes(std::vector<std::string>& parts, double px, double py,
                          double pw, double ph) {
        parts.push_back("<line x1=\"" + fmt2(px) + "\" y1=\"" + fmt2(py) + "\" x2=\"" +
                        fmt2(px) + "\" y2=\"" + fmt2(py + ph) +
                        "\" stroke=\"#444444\" stroke-width=\"0.2\"/>");
        parts.push_back("<line x1=\"" + fmt2(px) + "\" y1=\"" + fmt2(py + ph) +
                        "\" x2=\"" + fmt2(px + pw) + "\" y2=\"" + fmt2(py + ph) +
                        "\" stroke=\"#444444\" stroke-width=\"0.2\"/>");
    }

    static double abs_max_or_one(const std::vector<double>& values) {
        double vmax = 0.0;
        for (double v : values) vmax = std::max(vmax, std::fabs(v));
        return vmax != 0.0 ? vmax : 1.0;
    }

    static void draw_bar(std::vector<std::string>& parts, double px, double py,
                         double pw, double ph, const std::vector<std::string>& labels,
                         const std::vector<double>& values,
                         const std::vector<std::string>& colors,
                         const std::string& units) {
        const double vmax = abs_max_or_one(values);
        const double bar_w = pw / std::max<std::size_t>(1, values.size()) * 0.7;
        const double gap = pw / std::max<std::size_t>(1, values.size());
        for (std::size_t i = 0; i < values.size(); ++i) {
            const double bar_h = ph * std::fabs(values[i]) / vmax;
            const double bx = px + static_cast<double>(i) * gap + (gap - bar_w) / 2;
            const double by = py + ph - bar_h;
            parts.push_back("<rect x=\"" + fmt2(bx) + "\" y=\"" + fmt2(by) +
                            "\" width=\"" + fmt2(bar_w) + "\" height=\"" +
                            fmt2(std::max(0.2, bar_h)) + "\" fill=\"" +
                            colors[i % colors.size()] +
                            "\" stroke=\"#333333\" stroke-width=\"0.15\"/>");
            if (i < labels.size() && !labels[i].empty()) {
                parts.push_back("<text x=\"" + fmt2(bx + bar_w / 2) + "\" y=\"" +
                                fmt2(py + ph + 3.0) +
                                "\" font-family=\"Arial\" font-size=\"2.2\""
                                " fill=\"#333333\" text-anchor=\"middle\">" +
                                html_escape(labels[i]) + "</text>");
            }
        }
        parts.push_back("<text x=\"" + fmt2(px + pw) + "\" y=\"" + fmt2(py - 0.6) +
                        "\" font-family=\"Arial\" font-size=\"2.2\" fill=\"#555555\""
                        " text-anchor=\"end\">" +
                        fmt_g(vmax) + html_escape(units) + "</text>");
    }

    static void draw_hbar(std::vector<std::string>& parts, double px, double py,
                          double pw, double ph, const std::vector<std::string>& labels,
                          const std::vector<double>& values,
                          const std::vector<std::string>& colors) {
        const double vmax = abs_max_or_one(values);
        const double bar_h = ph / std::max<std::size_t>(1, values.size()) * 0.65;
        const double gap = ph / std::max<std::size_t>(1, values.size());
        for (std::size_t i = 0; i < values.size(); ++i) {
            const double bar_w = pw * std::fabs(values[i]) / vmax * 0.8;
            const double by = py + static_cast<double>(i) * gap + (gap - bar_h) / 2;
            parts.push_back("<rect x=\"" + fmt2(px) + "\" y=\"" + fmt2(by) +
                            "\" width=\"" + fmt2(std::max(0.2, bar_w)) + "\" height=\"" +
                            fmt2(bar_h) + "\" fill=\"" + colors[i % colors.size()] +
                            "\" stroke=\"#333333\" stroke-width=\"0.15\"/>");
            if (i < labels.size() && !labels[i].empty()) {
                parts.push_back("<text x=\"" + fmt2(px - 0.8) + "\" y=\"" +
                                fmt2(by + bar_h / 2 + 0.8) +
                                "\" font-family=\"Arial\" font-size=\"2.2\""
                                " fill=\"#333333\" text-anchor=\"end\">" +
                                html_escape(labels[i]) + "</text>");
            }
        }
    }

    static void draw_line(std::vector<std::string>& parts, double px, double py,
                          double pw, double ph, const std::vector<double>& xs,
                          const std::vector<double>& ys,
                          const std::vector<std::string>& labels,
                          const std::vector<std::string>& colors,
                          const std::string& units, bool scatter, bool x_is_value) {
        const double vmax = abs_max_or_one(ys);
        draw_axes(parts, px, py, pw, ph);
        auto mx_of = [&](std::size_t i) -> double {
            if (x_is_value) {
                double xmin = xs.empty() ? 0.0 : xs[0];
                double xmax = xs.empty() ? 0.0 : xs[0];
                for (double v : xs) {
                    xmin = std::min(xmin, v);
                    xmax = std::max(xmax, v);
                }
                const double span = xmax - xmin;
                if (span <= 0.0) return px + pw / 2.0;
                return px + (xs[i] - xmin) / span * pw;
            }
            const double step = pw / std::max<std::size_t>(1, ys.size());
            return px + static_cast<double>(i) * step + step / 2.0;
        };
        std::vector<std::pair<double, double>> pts;
        pts.reserve(ys.size());
        for (std::size_t i = 0; i < ys.size(); ++i) {
            pts.emplace_back(mx_of(i), py + ph - std::fabs(ys[i]) / vmax * ph);
        }
        if (scatter) {
            for (const auto& [mx, my] : pts) {
                parts.push_back("<circle cx=\"" + fmt2(mx) + "\" cy=\"" + fmt2(my) +
                                "\" r=\"0.9\" fill=\"" + colors[0] +
                                "\" stroke=\"#333333\" stroke-width=\"0.1\"/>");
            }
        } else {
            std::string polyline;
            for (const auto& [mx, my] : pts) {
                if (!polyline.empty()) polyline += " ";
                polyline += fmt2(mx) + "," + fmt2(my);
            }
            parts.push_back("<polyline points=\"" + polyline +
                            "\" fill=\"none\" stroke=\"" + colors[0] +
                            "\" stroke-width=\"0.5\"/>");
            for (const auto& [mx, my] : pts) {
                parts.push_back("<circle cx=\"" + fmt2(mx) + "\" cy=\"" + fmt2(my) +
                                "\" r=\"0.55\" fill=\"" + colors[0] + "\"/>");
            }
        }
        for (std::size_t i = 0; i < pts.size(); ++i) {
            if (i < labels.size() && !labels[i].empty()) {
                parts.push_back("<text x=\"" + fmt2(pts[i].first) + "\" y=\"" +
                                fmt2(py + ph + 3.0) + "\" font-family=\"Arial\""
                                " font-size=\"2.2\" fill=\"#333333\""
                                " text-anchor=\"middle\">" +
                                html_escape(labels[i]) + "</text>");
            }
        }
        parts.push_back("<text x=\"" + fmt2(px + pw) + "\" y=\"" + fmt2(py - 0.6) +
                        "\" font-family=\"Arial\" font-size=\"2.2\" fill=\"#555555\""
                        " text-anchor=\"end\">" +
                        fmt_g(vmax) + html_escape(units) + "</text>");
        if (x_is_value) {
            double xmin = xs.empty() ? 0.0 : xs[0];
            double xmax = xs.empty() ? 0.0 : xs[0];
            for (double v : xs) {
                xmin = std::min(xmin, v);
                xmax = std::max(xmax, v);
            }
            parts.push_back("<text x=\"" + fmt2(px) + "\" y=\"" + fmt2(py + ph + 3.0) +
                            "\" font-family=\"Arial\" font-size=\"2.0\""
                            " fill=\"#555555\" text-anchor=\"start\">" +
                            fmt_g(xmin) + "</text>");
            parts.push_back("<text x=\"" + fmt2(px + pw) + "\" y=\"" +
                            fmt2(py + ph + 3.0) + "\" font-family=\"Arial\""
                            " font-size=\"2.0\" fill=\"#555555\" text-anchor=\"end\">" +
                            fmt_g(xmax) + "</text>");
        }
    }

    static void draw_pie(std::vector<std::string>& parts, double x, double y, double w,
                         double h, bool has_title, const std::vector<std::string>& labels,
                         const std::vector<double>& values,
                         const std::vector<std::string>& colors, double hole_ratio) {
        const double top_pad = has_title ? 8.0 : 3.0;
        const double cx = x + w / 2;
        const double cy = y + top_pad + (h - top_pad) / 2;
        const double r = std::max(3.0, std::min(w, h - top_pad) / 2 - 2.0);
        double total = 0.0;
        for (double v : values) total += v;
        double angle = 0.0;
        std::vector<std::string> texts;
        for (std::size_t i = 0; i < values.size(); ++i) {
            const double span = 360.0 * values[i] / total;
            const double a0 = angle;
            const double a1 = angle + span;
            const std::string& color = colors[i % colors.size()];
            if (values.size() == 1 || span >= 359.99) {
                parts.push_back("<circle cx=\"" + fmt2(cx) + "\" cy=\"" + fmt2(cy) +
                                "\" r=\"" + fmt2(r) + "\" fill=\"" + color +
                                "\" stroke=\"#333333\" stroke-width=\"0.15\"/>");
            } else {
                double x0 = 0.0;
                double y0 = 0.0;
                double x1 = 0.0;
                double y1 = 0.0;
                polar(cx, cy, r, a0, x0, y0);
                polar(cx, cy, r, a1, x1, y1);
                const int large = (a1 - a0) > 180.0 ? 1 : 0;
                parts.push_back("<path d=\"M " + fmt2(cx) + " " + fmt2(cy) + " L " +
                                fmt2(x0) + " " + fmt2(y0) + " A " + fmt2(r) + " " +
                                fmt2(r) + " 0 " + std::to_string(large) + " 1 " +
                                fmt2(x1) + " " + fmt2(y1) + " Z\" fill=\"" + color +
                                "\" stroke=\"#ffffff\" stroke-width=\"0.2\"/>");
            }
            const double pct = span / 360.0 * 100.0;
            const double mid = (a0 + a1) / 2.0;
            double lx = 0.0;
            double ly = 0.0;
            polar(cx, cy, r * 0.62, mid, lx, ly);
            char pct_buf[32];
            std::snprintf(pct_buf, sizeof(pct_buf), "%.0f", pct);
            texts.push_back("<text x=\"" + fmt2(lx) + "\" y=\"" + fmt2(ly + 0.8) +
                            "\" font-family=\"Arial\" font-size=\"2.2\""
                            " fill=\"#111111\" text-anchor=\"middle\">" +
                            std::string(pct_buf) + "%</text>");
            if (i < labels.size() && !labels[i].empty()) {
                double tx = 0.0;
                double ty = 0.0;
                polar(cx, cy, r + 2.6, mid, tx, ty);
                const std::string anchor =
                    tx > cx ? "start" : (tx < cx ? "end" : "middle");
                texts.push_back("<text x=\"" + fmt2(tx) + "\" y=\"" + fmt2(ty + 0.8) +
                                "\" font-family=\"SimSun, Arial\" font-size=\"2.2\""
                                " fill=\"#333333\" text-anchor=\"" + anchor + "\">" +
                                html_escape(labels[i]) + "</text>");
            }
            angle = a1;
        }
        if (hole_ratio > 0.01) {
            const double hole_r = r * hole_ratio;
            parts.push_back("<circle cx=\"" + fmt2(cx) + "\" cy=\"" + fmt2(cy) +
                            "\" r=\"" + fmt2(hole_r) +
                            "\" fill=\"#ffffff\" stroke=\"#333333\""
                            " stroke-width=\"0.15\"/>");
        }
        for (const std::string& text : texts) parts.push_back(text);
    }

    static void draw_rose(std::vector<std::string>& parts, double x, double y, double w,
                          double h, bool has_title, const std::vector<const Json*>& entries,
                          const std::vector<std::string>& colors) {
        const double top_pad = has_title ? 8.0 : 3.0;
        const double cx = x + w / 2;
        const double cy = y + top_pad + (h - top_pad) / 2;
        const double r_max = std::max(3.0, std::min(w, h - top_pad) / 2 - 5.0);
        std::vector<double> values;
        for (const Json* entry : entries) {
            double raw_value = 0.0;
            const Json& value = json_get(*entry, "value");
            try {
                const double parsed = py_or_float(value, 0.0);
                raw_value = std::fabs(finite_or(parsed, 0.0));
            } catch (const std::invalid_argument&) {
                raw_value = 0.0;
            }
            values.push_back(raw_value);
        }
        const double vmax = abs_max_or_one(values);
        parts.push_back("<circle cx=\"" + fmt2(cx) + "\" cy=\"" + fmt2(cy) + "\" r=\"" +
                        fmt2(r_max) + "\" fill=\"none\" stroke=\"#999999\""
                        " stroke-width=\"0.12\"/>");
        parts.push_back("<circle cx=\"" + fmt2(cx) + "\" cy=\"" + fmt2(cy) + "\" r=\"" +
                        fmt2(r_max / 2) + "\" fill=\"none\" stroke=\"#bbbbbb\""
                        " stroke-width=\"0.1\"/>");
        parts.push_back("<line x1=\"" + fmt2(cx - r_max) + "\" y1=\"" + fmt2(cy) +
                        "\" x2=\"" + fmt2(cx + r_max) + "\" y2=\"" + fmt2(cy) +
                        "\" stroke=\"#bbbbbb\" stroke-width=\"0.1\"/>");
        parts.push_back("<line x1=\"" + fmt2(cx) + "\" y1=\"" + fmt2(cy - r_max) +
                        "\" x2=\"" + fmt2(cx) + "\" y2=\"" + fmt2(cy + r_max) +
                        "\" stroke=\"#bbbbbb\" stroke-width=\"0.1\"/>");
        const double default_span = 360.0 / std::max<std::size_t>(1, entries.size());
        for (std::size_t i = 0; i < entries.size(); ++i) {
            double center_angle = 0.0;
            if (entries[i]->contains("angle_deg")) {
                try {
                    center_angle =
                        finite_or(py_or_float(json_get(*entries[i], "angle_deg"), 0.0),
                                  static_cast<double>(i) * default_span);
                } catch (const std::invalid_argument&) {
                    center_angle = static_cast<double>(i) * default_span;
                }
            } else {
                center_angle = static_cast<double>(i) * default_span;
            }
            double span = default_span;
            if (entries[i]->contains("angle_span")) {
                try {
                    span = finite_or(
                        py_or_float(json_get(*entries[i], "angle_span"), default_span),
                        default_span);
                } catch (const std::invalid_argument&) {
                    span = default_span;
                }
            }
            span = std::min(std::max(span, 0.0), 360.0);
            const double r_i = r_max * values[i] / vmax;
            if (r_i <= 0.01) continue;
            const double a0 = center_angle - span / 2.0;
            const double a1 = center_angle + span / 2.0;
            double x0 = 0.0;
            double y0 = 0.0;
            double x1 = 0.0;
            double y1 = 0.0;
            polar(cx, cy, r_i, a0, x0, y0);
            polar(cx, cy, r_i, a1, x1, y1);
            const int large = (a1 - a0) > 180.0 ? 1 : 0;
            parts.push_back("<path d=\"M " + fmt2(cx) + " " + fmt2(cy) + " L " +
                            fmt2(x0) + " " + fmt2(y0) + " A " + fmt2(r_i) + " " +
                            fmt2(r_i) + " 0 " + std::to_string(large) + " 1 " + fmt2(x1) +
                            " " + fmt2(y1) + " Z\" fill=\"" + colors[i % colors.size()] +
                            "\" fill-opacity=\"0.85\" stroke=\"#333333\""
                            " stroke-width=\"0.12\"/>");
            const std::string label = py_or_str(json_get(*entries[i], "label"));
            if (!label.empty()) {
                double tx = 0.0;
                double ty = 0.0;
                polar(cx, cy, r_max + 2.4, center_angle, tx, ty);
                parts.push_back("<text x=\"" + fmt2(tx) + "\" y=\"" + fmt2(ty + 0.8) +
                                "\" font-family=\"SimSun, Arial\" font-size=\"2.2\""
                                " fill=\"#333333\" text-anchor=\"middle\">" +
                                html_escape(label) + "</text>");
            }
        }
    }

    static void draw_histogram(std::vector<std::string>& parts, double px, double py,
                               double pw, double ph, const std::vector<double>& values,
                               int bins) {
        double vmin = values.front();
        double vmax = values.front();
        for (double v : values) {
            vmin = std::min(vmin, v);
            vmax = std::max(vmax, v);
        }
        if (vmax <= vmin) {
            vmin -= 0.5;
            vmax += 0.5;
        }
        const double width = (vmax - vmin) / static_cast<double>(bins);
        std::vector<long long> counts(static_cast<std::size_t>(bins), 0);
        for (double value : values) {
            const long long idx = static_cast<long long>((value - vmin) / width);
            const long long clamped = std::min<long long>(bins - 1, std::max<long long>(0, idx));
            counts[static_cast<std::size_t>(clamped)] += 1;
        }
        long long max_count = 0;
        for (long long c : counts) max_count = std::max(max_count, c);
        if (max_count == 0) max_count = 1;
        draw_axes(parts, px, py, pw, ph);
        const double bar_w = pw / static_cast<double>(bins) * 0.88;
        for (int i = 0; i < bins; ++i) {
            const double bx = px + static_cast<double>(i) * (pw / bins) +
                              (pw / bins - bar_w) / 2;
            const double bar_h = ph * static_cast<double>(counts[i]) / max_count;
            parts.push_back("<rect x=\"" + fmt2(bx) + "\" y=\"" +
                            fmt2(py + ph - bar_h) + "\" width=\"" + fmt2(bar_w) +
                            "\" height=\"" + fmt2(std::max(0.15, bar_h)) +
                            "\" fill=\"#4c78a8\" stroke=\"#2b5a86\""
                            " stroke-width=\"0.12\"/>");
            if (bins <= 12 && counts[i] > 0) {
                parts.push_back("<text x=\"" + fmt2(bx + bar_w / 2) + "\" y=\"" +
                                fmt2(py + ph - bar_h - 0.5) +
                                "\" font-family=\"Arial\" font-size=\"1.9\""
                                " fill=\"#333333\" text-anchor=\"middle\">" +
                                std::to_string(counts[i]) + "</text>");
            }
        }
        parts.push_back("<text x=\"" + fmt2(px + pw) + "\" y=\"" + fmt2(py - 0.6) +
                        "\" font-family=\"Arial\" font-size=\"2.2\" fill=\"#555555\""
                        " text-anchor=\"end\">" +
                        std::to_string(max_count) + "</text>");
        parts.push_back("<text x=\"" + fmt2(px) + "\" y=\"" + fmt2(py + ph + 3.0) +
                        "\" font-family=\"Arial\" font-size=\"2.0\" fill=\"#555555\""
                        " text-anchor=\"start\">" +
                        fmt_g(vmin) + "</text>");
        parts.push_back("<text x=\"" + fmt2(px + pw) + "\" y=\"" + fmt2(py + ph + 3.0) +
                        "\" font-family=\"Arial\" font-size=\"2.0\" fill=\"#555555\""
                        " text-anchor=\"end\">" +
                        fmt_g(vmax) + "</text>");
    }

    std::string render_stat_chart(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        std::string chart_type = [&] {
            std::string out = py_or_str(prop(elem, "chart_type"), "bar");
            std::transform(out.begin(), out.end(), out.begin(),
                           [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            return out;
        }();
        const std::string title = py_or_str(prop(elem, "title"));
        const Json& series = prop(elem, "series");
        const std::string units = py_or_str(prop(elem, "units"));
        const std::vector<std::string> colors = chart_colors(elem);
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        parts.push_back("<rect x=\"" + fmt2(x) + "\" y=\"" + fmt2(y) + "\" width=\"" +
                        fmt2(w) + "\" height=\"" + fmt2(h) +
                        "\" fill=\"#ffffff\" stroke=\"#666666\" stroke-width=\"0.25\"/>");
        if (!title.empty()) {
            parts.push_back("<text x=\"" + fmt2(x + w / 2) + "\" y=\"" + fmt2(y + 4.6) +
                            "\" font-family=\"SimSun, Arial\" font-size=\"3.4\""
                            " font-weight=\"bold\" fill=\"#000000\""
                            " text-anchor=\"middle\">" +
                            html_escape(title) + "</text>");
        }
        const double plot_x = x + 6.0;
        const double plot_y = y + 8.0;
        const double plot_w = std::max(4.0, w - 10.0);
        const double plot_h = std::max(4.0, h - 15.0);

        if (chart_type == "pie" || chart_type == "donut") {
            std::vector<std::string> labels;
            std::vector<double> values;
            series_entries(series, labels, values);
            std::vector<std::string> kept_labels;
            std::vector<double> kept_values;
            for (std::size_t i = 0; i < values.size(); ++i) {
                if (values[i] > 0.0) {
                    kept_labels.push_back(i < labels.size() ? labels[i] : "");
                    kept_values.push_back(values[i]);
                }
            }
            if (kept_values.empty()) {
                parts.push_back(chart_placeholder(x, y, w, h));
            } else {
                draw_pie(parts, x, y, w, h, !title.empty(), kept_labels, kept_values,
                         colors, chart_type == "donut" ? hole_ratio(elem) : 0.0);
            }
        } else if (chart_type == "histogram") {
            std::vector<double> values;
            int bins = 10;
            histogram_data(elem, values, bins);
            if (values.empty()) {
                parts.push_back(chart_placeholder(x, y, w, h));
            } else {
                draw_histogram(parts, plot_x, plot_y, plot_w, plot_h, values, bins);
            }
        } else if (chart_type == "rose") {
            std::vector<const Json*> entries;
            if (series.is_array()) {
                for (const Json& s : series) {
                    if (s.is_object()) entries.push_back(&s);
                }
            }
            if (entries.empty()) {
                parts.push_back(chart_placeholder(x, y, w, h));
            } else {
                draw_rose(parts, x, y, w, h, !title.empty(), entries, colors);
            }
        } else if (chart_type == "line" || chart_type == "scatter") {
            std::vector<double> xs;
            std::vector<double> ys;
            std::vector<std::string> labels;
            bool x_is_value = false;
            xy_series(series, xs, ys, labels, x_is_value);
            if (ys.empty()) {
                parts.push_back(chart_placeholder(x, y, w, h));
            } else {
                draw_line(parts, plot_x, plot_y, plot_w, plot_h, xs, ys, labels, colors,
                          units, chart_type == "scatter", x_is_value);
            }
        } else {
            // bar / hbar share the [{label, value}] series; unknown
            // chart_type renders as bar (forward compatibility).
            std::vector<std::string> labels;
            std::vector<double> values;
            series_entries(series, labels, values);
            if (values.empty()) {
                parts.push_back(chart_placeholder(x, y, w, h));
            } else if (chart_type == "hbar") {
                draw_hbar(parts, plot_x, plot_y, plot_w, plot_h, labels, values, colors);
            } else {
                draw_bar(parts, plot_x, plot_y, plot_w, plot_h, labels, values, colors,
                         units);
            }
        }
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_metadata(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        const Json& raw_fields = prop(elem, "fields");
        std::vector<std::pair<std::string, std::string>> fields;
        if (raw_fields.is_array()) {
            for (const Json& entry : raw_fields) {
                if (entry.is_array() && entry.size() >= 2) {
                    fields.emplace_back(py_str_value(entry[0]), py_str_value(entry[1]));
                }
            }
        }
        const double font_size = py_or_float(prop(elem, "font_size"), 3.0);
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        const long long per_column =
            std::max<long long>(1, static_cast<long long>(std::floor(h / (font_size * 1.6))));
        const std::size_t columns =
            std::max<std::size_t>(1,
                                  (fields.size() + static_cast<std::size_t>(per_column) - 1) /
                                      static_cast<std::size_t>(per_column));
        const double column_w = w / static_cast<double>(columns);
        for (std::size_t i = 0; i < fields.size(); ++i) {
            const std::size_t column = i / static_cast<std::size_t>(per_column);
            const std::size_t row = i % static_cast<std::size_t>(per_column);
            const double fx = x + static_cast<double>(column) * column_w;
            const double fy = y + font_size * (static_cast<double>(row) + 1.0) * 1.6;
            parts.push_back("<text x=\"" + fmt2(fx) + "\" y=\"" + fmt2(fy) +
                            "\" font-family=\"SimSun, Arial\" font-size=\"" +
                            py_float_repr(font_size) + "\" fill=\"#000000\">" +
                            html_escape(fields[i].first) + ": " +
                            html_escape(fields[i].second) + "</text>");
        }
        parts.push_back("<rect x=\"" + fmt2(x) + "\" y=\"" + fmt2(y) + "\" width=\"" +
                        fmt2(w) + "\" height=\"" + fmt2(h) + "\" fill=\"none\""
                        " stroke=\"#999999\" stroke-width=\"0.2\"/>");
        parts.push_back("</g>");
        return join(parts);
    }

    std::string render_colorbar(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        const std::string title = py_or_str(prop(elem, "title"));
        const double vmin = py_or_float(prop(elem, "min"), 0.0);
        const double vmax = py_or_float(prop(elem, "max"), 1.0);
        const Json& raw_stops = prop(elem, "stops");
        std::vector<std::pair<double, std::string>> stops;
        if (raw_stops.is_array()) {
            for (const Json& stop : raw_stops) {
                if (stop.is_array() && stop.size() >= 2) {
                    try {
                        stops.emplace_back(py_float(stop[0]), py_str_value(stop[1]));
                    } catch (const std::invalid_argument&) {
                    }
                }
            }
        }
        const bool discrete = has_prop(elem, "discrete") ? py_truthy(prop(elem, "discrete"))
                                                        : false;
        const double bar_w = std::min(10.0, w * 0.8);
        const double title_h = title.empty() ? 0.0 : 6.0;
        const double label_h = 10.0;
        const double bar_y = y + title_h;
        const double bar_h = std::max(4.0, h - title_h - label_h);
        std::vector<std::string> parts;
        parts.push_back("<g id=\"" + elem.id + "\">");
        const double bar_x = title.empty() ? x : x + 4.0;
        if (!title.empty()) {
            parts.push_back("<text x=\"" + fmt2(x - 1.2) + "\" y=\"" +
                            fmt2(bar_y + bar_h / 2) +
                            "\" font-family=\"SimSun, Arial\" font-size=\"3.2\""
                            " fill=\"#000000\" text-anchor=\"middle\" transform=\"rotate(-90 " +
                            fmt2(x - 1.2) + " " + fmt2(bar_y + bar_h / 2) + ")\">" +
                            html_escape(title) + "</text>");
        }
        if (stops.empty()) {
            const std::string ramp_name = py_or_str(prop(elem, "color_ramp"));
            if (!ramp_name.empty() && seams_.palette_stops) {
                ComposerRenderSeams::ColorStops ramp_stops;
                if (seams_.palette_stops(ramp_name, ramp_stops)) {
                    for (const auto& [pos, color] : ramp_stops) {
                        stops.emplace_back(pos, color);
                    }
                }
            }
        }
        if (stops.empty()) {
            stops = {{0.0, "#053061"}, {1.0, "#67001f"}};
        }
        if (discrete) {
            const std::size_t n = stops.size();
            const double seg_h = bar_h / std::max<std::size_t>(1, n);
            for (std::size_t i = 0; i < n; ++i) {
                parts.push_back("<rect x=\"" + fmt2(bar_x) + "\" y=\"" +
                                fmt2(bar_y + static_cast<double>(i) * seg_h) +
                                "\" width=\"" + fmt2(bar_w) + "\" height=\"" +
                                fmt2(seg_h + 0.02) + "\" fill=\"" + stops[i].second +
                                "\" stroke=\"#333333\" stroke-width=\"0.08\"/>");
            }
        } else {
            const std::string grad_id =
                "cbar_" + std::to_string(fnv1a(elem.id) % 100000);
            std::stable_sort(stops.begin(), stops.end(),
                             [](const std::pair<double, std::string>& a,
                                const std::pair<double, std::string>& b) {
                                 return a.first < b.first;
                             });
            std::string stops_svg;
            for (const auto& [pos, color] : stops) {
                char offset[32];
                std::snprintf(offset, sizeof(offset), "%.1f", pos * 100.0);
                stops_svg += "<stop offset=\"";
                stops_svg += offset;
                stops_svg += "%\" stop-color=\"";
                stops_svg += color;
                stops_svg += "\"/>";
            }
            parts.push_back("<defs><linearGradient id=\"" + grad_id +
                            "\" x1=\"0%\" y1=\"100%\" x2=\"0%\" y2=\"0%\">" + stops_svg +
                            "</linearGradient></defs>");
            parts.push_back("<rect x=\"" + fmt2(bar_x) + "\" y=\"" + fmt2(bar_y) +
                            "\" width=\"" + fmt2(bar_w) + "\" height=\"" + fmt2(bar_h) +
                            "\" fill=\"url(#" + grad_id + ")\" stroke=\"#333333\""
                            " stroke-width=\"0.2\"/>");
        }
        parts.push_back("<text x=\"" + fmt2(bar_x + bar_w + 1.5) + "\" y=\"" +
                        fmt2(bar_y + bar_h + 0.8) + "\" font-family=\"Arial\""
                        " font-size=\"2.4\" fill=\"#000000\">" +
                        fmt_g(vmin) + "</text>");
        parts.push_back("<text x=\"" + fmt2(bar_x + bar_w + 1.5) + "\" y=\"" +
                        fmt2(bar_y + 2.4) + "\" font-family=\"Arial\" font-size=\"2.4\""
                        " fill=\"#000000\">" +
                        fmt_g(vmax) + "</text>");
        parts.push_back("</g>");
        return join(parts);
    }

    // ------------------------------------------------------------------
    // Legend (renderer.py _render_legend_svg)
    // ------------------------------------------------------------------

    std::string render_legend(const ComposerElement& elem,
                              const ComposerElement* main_map) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        std::vector<ComposerLegendEntry> legend_items;

        // 1. Explicit items in properties.
        const Json& raw_items = prop(elem, "items");
        if (py_truthy(raw_items) && raw_items.is_array()) {
            for (const Json& it : raw_items) {
                if (!it.is_object()) continue;
                ComposerLegendEntry entry;
                entry.label = py_or_str(it.contains("label") ? it["label"] : Json(nullptr),
                                        "Item");
                entry.color =
                    py_or_str(it.contains("color") ? it["color"] : Json(nullptr), "#4fc3f7");
                entry.symbol_type =
                    py_or_str(it.contains("symbol_type") ? it["symbol_type"] : Json(nullptr),
                              "polygon");
                entry.stroke_color =
                    it.contains("stroke_color") ? py_or_str(it["stroke_color"], "#333333")
                                                : "#333333";
                entry.stroke_width =
                    it.contains("stroke_width") ? py_or_float(it["stroke_width"], 0.5) : 0.5;
                entry.gradient_stops =
                    it.contains("gradient_stops") ? it["gradient_stops"] : Json::array();
                legend_items.push_back(std::move(entry));
            }
        }

        // 2. Extract from the live main map when no explicit items.
        if (legend_items.empty() && main_map != nullptr && seams_.legend_entries) {
            legend_items = seams_.legend_entries(*main_map);
        }

        // 3. Documented defaults (Python's two hardcoded sample items).
        if (legend_items.empty()) {
            legend_items.push_back({"三角洲砂体", "#ffe082", "polygon", "#333333", 0.5, Json::array()});
            legend_items.push_back({"湖相泥岩", "#b0bec5", "polygon", "#333333", 0.5, Json::array()});
        }

        const double item_h = 6.0;
        const double req_h =
            std::max(h, 10.0 + static_cast<double>(legend_items.size()) * item_h);
        // Python uses one default for both LEGEND and FACIES_LEGEND (the
        // registry label 「沉积相图例」 is the add-menu label, not the
        // renderer default — the code comment in renderer.py is stale).
        const std::string legend_title = py_or_str(prop(elem, "title"), "图 例");
        std::vector<std::string> svg_lines;
        svg_lines.push_back("<g id=\"" + elem.id + "\">");
        svg_lines.push_back("<rect x=\"" + py_float_repr(x) + "\" y=\"" +
                            py_float_repr(y) + "\" width=\"" + py_float_repr(w) +
                            "\" height=\"" + py_float_repr(req_h) +
                            "\" fill=\"#ffffff\" stroke=\"#666666\" stroke-width=\"0.2\""
                            " fill-opacity=\"0.95\"/>");
        svg_lines.push_back("<text x=\"" + py_float_repr(x + 4) + "\" y=\"" +
                            py_float_repr(y + 5.5) +
                            "\" font-family=\"SimSun, Arial, sans-serif\" font-size=\"4\""
                            " font-weight=\"bold\" fill=\"#000000\">" +
                            html_escape(legend_title) + "</text>");
        const double swatch_mm = kMmPerPx;
        for (std::size_t idx = 0; idx < legend_items.size(); ++idx) {
            const ComposerLegendEntry& it = legend_items[idx];
            const double iy = y + 9.0 + static_cast<double>(idx) * item_h;
            const std::string escaped_label = html_escape(it.label);
            if (it.symbol_type == "gradient" && it.gradient_stops.is_array() &&
                !it.gradient_stops.empty()) {
                const std::string grad_id =
                    "grad_" + std::to_string(idx) + "_" +
                    std::to_string(fnv1a(it.label) % 10000);
                std::string stops_svg;
                for (const Json& stop : it.gradient_stops) {
                    if (!stop.is_array() || stop.size() < 2) continue;
                    try {
                        const double pos = py_float(stop[0]);
                        char offset[32];
                        std::snprintf(offset, sizeof(offset), "%.1f", pos * 100.0);
                        stops_svg += "<stop offset=\"";
                        stops_svg += offset;
                        stops_svg += "%\" stop-color=\"";
                        stops_svg += py_str_value(stop[1]);
                        stops_svg += "\"/>";
                    } catch (const std::invalid_argument&) {
                    }
                }
                svg_lines.push_back("<defs><linearGradient id=\"" + grad_id +
                                    "\" x1=\"0%\" y1=\"0%\" x2=\"100%\" y2=\"0%\">" +
                                    stops_svg + "</linearGradient></defs>");
                svg_lines.push_back("<rect x=\"" + py_float_repr(x + 4) + "\" y=\"" +
                                    py_float_repr(iy) + "\" width=\"14\" height=\"3\""
                                    " fill=\"url(#" + grad_id +
                                    ")\" stroke=\"#333333\" stroke-width=\"0.1\"/>");
                svg_lines.push_back("<text x=\"" + py_float_repr(x + 21) + "\" y=\"" +
                                    py_float_repr(iy + 2.5) +
                                    "\" font-family=\"SimSun, Arial, sans-serif\""
                                    " font-size=\"2.6\" fill=\"#000000\">" +
                                    escaped_label + "</text>");
            } else if (it.symbol_type == "line") {
                svg_lines.push_back(
                    "<line x1=\"" + py_float_repr(x + 4) + "\" y1=\"" +
                    py_float_repr(iy + 1.5) + "\" x2=\"" + py_float_repr(x + 10) +
                    "\" y2=\"" + py_float_repr(iy + 1.5) + "\" stroke=\"" + it.color +
                    "\" stroke-width=\"" +
                    fmt2(std::max(0.2, it.stroke_width * swatch_mm)) + "\"/>");
                svg_lines.push_back("<text x=\"" + py_float_repr(x + 13) + "\" y=\"" +
                                    py_float_repr(iy + 2.5) +
                                    "\" font-family=\"SimSun, Arial, sans-serif\""
                                    " font-size=\"2.8\" fill=\"#000000\">" +
                                    escaped_label + "</text>");
            } else if (it.symbol_type == "point") {
                svg_lines.push_back(
                    "<circle cx=\"" + py_float_repr(x + 7) + "\" cy=\"" +
                    py_float_repr(iy + 1.5) + "\" r=\"2\" fill=\"" + it.color +
                    "\" stroke=\"" + it.stroke_color + "\" stroke-width=\"" +
                    fmt2(std::max(0.1, it.stroke_width * swatch_mm)) + "\"/>");
                svg_lines.push_back("<text x=\"" + py_float_repr(x + 13) + "\" y=\"" +
                                    py_float_repr(iy + 2.5) +
                                    "\" font-family=\"SimSun, Arial, sans-serif\""
                                    " font-size=\"2.8\" fill=\"#000000\">" +
                                    escaped_label + "</text>");
            } else {
                svg_lines.push_back("<rect x=\"" + py_float_repr(x + 4) + "\" y=\"" +
                                    py_float_repr(iy) + "\" width=\"6\" height=\"3\""
                                    " fill=\"" + it.color + "\" stroke=\"" +
                                    it.stroke_color + "\" stroke-width=\"0.1\"/>");
                svg_lines.push_back("<text x=\"" + py_float_repr(x + 13) + "\" y=\"" +
                                    py_float_repr(iy + 2.5) +
                                    "\" font-family=\"SimSun, Arial, sans-serif\""
                                    " font-size=\"2.8\" fill=\"#000000\">" +
                                    escaped_label + "</text>");
            }
        }
        svg_lines.push_back("</g>");
        return join(svg_lines);
    }

    // ------------------------------------------------------------------
    // Main map (renderer.py _render_main_map_svg)
    // ------------------------------------------------------------------

    std::string render_main_map(const ComposerElement& elem) {
        const double x = elem.x_mm;
        const double y = elem.y_mm;
        const double w = elem.width_mm;
        const double h = elem.height_mm;
        std::vector<std::string> inner_svg;
        inner_svg.push_back("<rect x=\"" + py_float_repr(x) + "\" y=\"" +
                            py_float_repr(y) + "\" width=\"" + py_float_repr(w) +
                            "\" height=\"" + py_float_repr(h) +
                            "\" fill=\"#181c22\" stroke=\"#444444\" stroke-width=\"0.3\"/>");

        // Route 1/2: the host's live map document (via the frame seam).
        if (seams_.frame_content) {
            ComposerRenderSeams::FrameContent content = seams_.frame_content(elem);
            if (content.bound) {
                if (!content.png_b64.empty()) {
                    inner_svg.push_back("<image x=\"" + fmt2(x) + "\" y=\"" + fmt2(y) +
                                        "\" width=\"" + fmt2(w) + "\" height=\"" +
                                        fmt2(h) + "\" xlink:href=\"data:image/png;base64," +
                                        content.png_b64 +
                                        "\" preserveAspectRatio=\"xMidYMid meet\"/>");
                }
                for (const std::string& fragment : content.svg_fragments) {
                    if (!fragment.empty()) inner_svg.push_back(fragment);
                }
                return "<g id=\"" + elem.id + "\">\n" + join(inner_svg) + "\n</g>";
            }
        }

        // Route 3: pure-JSON dict layers with an explicit extent.
        const Json& layers = prop(elem, "layers");
        const Json& extent = prop(elem, "extent");
        const bool has_extent = extent.is_array() && extent.size() == 4;
        if (py_truthy(layers) && layers.is_array() && has_extent) {
            try {
                const MmContext ctx({py_float(extent[0]), py_float(extent[1]),
                                     py_float(extent[2]), py_float(extent[3])},
                                    w, h, x, y);
                for (const Json& lyr_dict : layers) {
                    if (!lyr_dict.is_object()) continue;
                    DictLayer layer;
                    layer.id = py_or_str(lyr_dict.contains("id") ? lyr_dict["id"] : Json(nullptr),
                                         "vlyr");
                    layer.name = py_or_str(lyr_dict.contains("name") ? lyr_dict["name"] : Json(nullptr),
                                           "Layer");
                    layer.layer_type =
                        py_or_str(lyr_dict.contains("layer_type") ? lyr_dict["layer_type"]
                                                                  : Json(nullptr),
                                  "vector");
                    layer.features =
                        lyr_dict.contains("features") ? lyr_dict["features"] : Json::array();
                    if (lyr_dict.contains("style") && py_truthy(lyr_dict["style"])) {
                        layer.style = lyr_dict["style"];
                    } else {
                        const std::string fallback_fill = lyr_dict.contains("color")
                                                              ? py_or_str(lyr_dict["color"],
                                                                          "#4fc3f7")
                                                              : "#4fc3f7";
                        layer.style = Json::object();
                        layer.style["fill"] = fallback_fill;
                        layer.style["stroke"] = "#222222";
                    }
                    const std::string rendered = render_dict_layer(layer, ctx);
                    if (!rendered.empty()) inner_svg.push_back(rendered);
                }
                return "<g id=\"" + elem.id + "\">\n" + join(inner_svg) + "\n</g>";
            } catch (const std::invalid_argument&) {
                // Python parity: a non-numeric extent still enters route 3
                // (the condition only checks presence/length); every layer
                // then renders nothing, so the frame stays dark and empty —
                // no placeholder text, no layers.
            }
        }

        // Unbound: dark frame + grey placeholder text (never fabricated).
        const std::string title = py_or_str(prop(elem, "title"), "主图画布 (Main Map Canvas)");
        inner_svg.push_back("<text x=\"" + py_float_repr(x + w / 2) + "\" y=\"" +
                            py_float_repr(y + h / 2) +
                            "\" font-family=\"Arial, sans-serif\" font-size=\"5\""
                            " fill=\"#888888\" text-anchor=\"middle\">" +
                            html_escape(title) + "</text>");
        return "<g id=\"" + elem.id + "\">\n" + join(inner_svg) + "\n</g>";
    }

    // renderers.py SingleSymbolRenderer / CategorizedRenderer /
    // GraduatedRenderer (SVG, MM context) for dict layers.
    static std::string render_dict_layer(const DictLayer& layer, const MmContext& ctx) {
        const StyleView style = StyleView::from_dict(layer.style);
        const LayerRendererKind kind = resolve_renderer(layer, style);
        if (kind == LayerRendererKind::Unsupported) return "";
        if (!layer.features.is_array() || layer.features.empty()) return "";

        std::vector<std::string> parts;
        parts.push_back("<g id=\"layer_" + layer.id + "\" opacity=\"1.00\">");
        // Well symbols and annotations are feature-shape renderers: they
        // take the whole feature list (renderers.py WellSymbolRenderer /
        // AnnotationRenderer).
        if (kind == LayerRendererKind::Well) {
            for (const std::string& fragment : well_layer_fragments(layer, ctx, style)) {
                parts.push_back(fragment);
            }
            parts.push_back("</g>");
            return join(parts);
        }
        if (kind == LayerRendererKind::Annotation) {
            for (const std::string& fragment :
                 annotation_layer_fragments(layer, ctx, style)) {
                parts.push_back(fragment);
            }
            parts.push_back("</g>");
            return join(parts);
        }
        for (const Json& feat : layer.features) {
            if (!feat.is_object()) continue;
            const Json* geom_it = feat.contains("geometry") ? &feat["geometry"] : nullptr;
            if (geom_it == nullptr || !geom_it->is_object()) continue;
            const Json& geom = *geom_it;
            const std::string gtype = py_or_str(geom.contains("type") ? geom["type"] : Json(nullptr));
            const Json& coords = geom.contains("coordinates") ? geom["coordinates"] : Json::array();
            const Json* props = feature_props(feat);

            auto emit_point = [&](double wx, double wy, const std::string& fill_color) {
                double sx = 0.0;
                double sy = 0.0;
                ctx.world_to_screen(wx, wy, sx, sy);
                const double r = ctx.to_target(std::max(1.0, style.marker_size / 2.0));
                if (style.marker == "well") {
                    parts.push_back(
                        "<circle cx=\"" + fmt2(sx) + "\" cy=\"" + fmt2(sy) + "\" r=\"" +
                        fmt2(r) + "\" fill=\"none\" stroke=\"" + style.stroke +
                        "\" stroke-width=\"" + fmt2(ctx.to_target(1)) + "\"/>"
                        "<circle cx=\"" +
                        fmt2(sx) + "\" cy=\"" + fmt2(sy) + "\" r=\"" +
                        fmt2(std::max(ctx.to_target(0.5), r * 0.4)) + "\" fill=\"" +
                        fill_color + "\" stroke=\"none\"/>");
                } else if (style.marker == "square") {
                    parts.push_back("<rect x=\"" + fmt2(sx - r) + "\" y=\"" + fmt2(sy - r) +
                                    "\" width=\"" + fmt2(r * 2) + "\" height=\"" +
                                    fmt2(r * 2) + "\" fill=\"" + fill_color +
                                    "\" stroke=\"" + style.stroke +
                                    "\" stroke-width=\"" + fmt2(ctx.to_target(0.5)) + "\"/>");
                } else {
                    parts.push_back("<circle cx=\"" + fmt2(sx) + "\" cy=\"" + fmt2(sy) +
                                    "\" r=\"" + fmt2(r) + "\" fill=\"" + fill_color +
                                    "\" stroke=\"" + style.stroke +
                                    "\" stroke-width=\"" + fmt2(ctx.to_target(0.5)) + "\"/>");
                }
                if (style.labels_visible && !style.label_field.empty()) {
                    std::string lbl_text;
                    if (props != nullptr) {
                        if (props->contains(style.label_field)) {
                            lbl_text = py_or_str((*props)[style.label_field]);
                        } else if (props->contains("name")) {
                            lbl_text = py_or_str((*props)["name"]);
                        }
                    }
                    strip_in_place(lbl_text);
                    const bool blank =
                        lbl_text.find_first_not_of(" \t\n\r\v\f") == std::string::npos;
                    if (!lbl_text.empty() && !blank) {
                        parts.push_back("<text x=\"" + fmt2(sx + r + ctx.to_target(2)) +
                                        "\" y=\"" + fmt2(sy + ctx.to_target(3)) +
                                        "\" font-family=\"" +
                                        (style.label_font.empty() ? "Arial"
                                                                 : style.label_font) +
                                        "\" font-size=\"" + fmt2(ctx.to_target(style.label_size)) +
                                        "\" fill=\"" + style.label_color + "\">" +
                                        html_escape(lbl_text) + "</text>");
                    }
                }
            };

            // renderers.py fill resolution: single → style.fill;
            // categorized → the category fill (style.fill when unmatched);
            // graduated → the matched range fill (style.fill when unmatched).
            auto resolve_fill = [&]() -> std::string {
                if (kind == LayerRendererKind::Categorized) {
                    const std::string field_name =
                        style.field.empty() ? "facies_name" : style.field;
                    std::string val_key;
                    if (props != nullptr) {
                        if (props->contains(field_name)) {
                            val_key = py_or_str((*props)[field_name]);
                        } else if (props->contains("facies")) {
                            val_key = py_or_str((*props)["facies"]);
                        } else if (props->contains("category")) {
                            val_key = py_or_str((*props)["category"]);
                        }
                    }
                    for (const auto& category : style.categories) {
                        if (category[0] == val_key) return category[1];
                    }
                } else if (kind == LayerRendererKind::Graduated) {
                    const std::string field_name =
                        style.field.empty() ? "value" : style.field;
                    const Json* raw = nullptr;
                    if (props != nullptr && props->contains(field_name) &&
                        !(*props)[field_name].is_null()) {
                        raw = &(*props)[field_name];
                    } else if (props != nullptr && props->contains("value") &&
                               !(*props)["value"].is_null()) {
                        raw = &(*props)["value"];
                    }
                    if (raw != nullptr) {
                        try {
                            const double v = py_float(*raw);
                            for (const auto& range : style.ranges) {
                                if (range.lo <= v && v <= range.hi) return range.fill;
                            }
                        } catch (const std::invalid_argument&) {
                        }
                    }
                }
                return style.fill;
            };

            auto emit_polyline = [&](const std::vector<std::pair<double, double>>& ring,
                                     const std::string& fill_color) {
                const std::string pts = points_attr(ring, ctx);
                if (pts.empty()) return;
                parts.push_back("<polygon points=\"" + pts + "\" fill=\"" + fill_color +
                                "\" stroke=\"" + style.stroke + "\" stroke-width=\"" +
                                fmt2(ctx.to_target(style.stroke_width)) + "\"/>");
            };

            if (gtype == "Polygon" && coords.is_array() && !coords.empty()) {
                emit_polyline(ring_points(coords[0]), resolve_fill());
            } else if (gtype == "MultiPolygon" && coords.is_array()) {
                for (const Json& poly : coords) {
                    if (!poly.is_array() || poly.empty()) continue;
                    emit_polyline(ring_points(poly[0]), resolve_fill());
                }
            } else if (gtype == "LineString" && coords.is_array()) {
                // Categorized/graduated layers draw lines in the resolved
                // fill colour; single-symbol layers use the stroke.
                const std::string stroke_color =
                    kind == LayerRendererKind::Single ? style.stroke : resolve_fill();
                const std::string pts = points_attr(ring_points(coords), ctx);
                if (!pts.empty()) {
                    const std::string dash = ctx.dash_array(style.line_pattern,
                                                             style.stroke_width);
                    const std::string dash_attr =
                        dash.empty() ? "" : " stroke-dasharray=\"" + dash + "\"";
                    parts.push_back("<polyline points=\"" + pts +
                                    "\" fill=\"none\" stroke=\"" + stroke_color +
                                    "\" stroke-width=\"" +
                                    fmt2(ctx.to_target(style.stroke_width)) + "\"" +
                                    dash_attr + "/>");
                }
            } else if (gtype == "Point" && coords.is_array() && coords.size() >= 2) {
                try {
                    emit_point(py_float(coords[0]), py_float(coords[1]), resolve_fill());
                } catch (const std::invalid_argument&) {
                }
            }
        }
        parts.push_back("</g>");
        return join(parts);
    }

    const ComposerRenderSeams& seams_;
};

}  // namespace

std::string render_composition_to_svg(const Composition& doc,
                                      const ComposerRenderSeams& seams) {
    ComposerRenderer renderer(seams);
    return renderer.render_to_svg(doc);
}

std::string reanchor_composition_svg(const std::string& svg, double width_mm,
                                     double height_mm) {
    // export.py _composition_svg: re-anchor the width/height attributes of
    // the first tag to physical millimetres (the viewBox stays mm).
    const std::size_t tag_end = svg.find('>');
    if (tag_end == std::string::npos) return svg;
    std::string head = svg.substr(0, tag_end);
    const std::string tail = svg.substr(tag_end);

    auto replace_attr = [](std::string& text, const std::string& name,
                           const std::string& value) {
        const std::string needle = name + "=\"";
        const std::size_t at = text.find(needle);
        if (at == std::string::npos) return;
        const std::size_t close = text.find('"', at + needle.size());
        if (close == std::string::npos) return;
        text.replace(at, close - at + 1, needle + value + "\"");
    };
    // Python f"{doc.width_mm}mm" — the float repr, so "297.0mm" (not "297mm").
    replace_attr(head, "width", py_float_repr(width_mm) + "mm");
    replace_attr(head, "height", py_float_repr(height_mm) + "mm");
    return head + tail;
}

}  // namespace pwb::mapping_document
