// CONV-27 — implementation of the vector/label style value types.
// See vector_style.hpp for the ported Python contract and the D-6 note.
#include <pwb/cartography/vector_style.hpp>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <stdexcept>
#include <utility>

namespace pwb::cartography {
namespace {

std::string json_scalar_to_str(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_null()) return "None";
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number_integer()) return std::to_string(value.get<long long>());
    if (value.is_number_float()) {
        double v = value.get<double>();
        char buf[40];
        std::snprintf(buf, sizeof(buf), "%g", v);
        return buf;
    }
    return value.dump();
}

double json_scalar_to_double(const Json& value) {
    if (value.is_number()) {
        return value.is_number_integer()
                   ? static_cast<double>(value.get<long long>())
                   : value.get<double>();
    }
    // Python float("1.5") accepts numeric strings; bool coerces.
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_string()) {
        const std::string text = value.get<std::string>();
        try {
            std::size_t consumed = 0;
            double parsed = std::stod(text, &consumed);
            // Python float() rejects trailing garbage.
            while (consumed < text.size() &&
                   std::isspace(static_cast<unsigned char>(text[consumed]))) {
                ++consumed;
            }
            if (consumed != text.size()) throw std::invalid_argument(text);
            return parsed;
        } catch (const std::exception&) {
            throw std::invalid_argument("could not convert string to float: " + text);
        }
    }
    throw std::invalid_argument("float() argument must be a number");
}

}  // namespace

std::vector<double> dash_pattern(LinePattern pattern) {
    switch (pattern) {
        case LinePattern::Dash: return {4.0, 2.0};
        case LinePattern::Dot: return {1.0, 2.0};
        case LinePattern::DashDot: return {4.0, 2.0, 1.0, 2.0};
        case LinePattern::Fault: return {6.0, 2.0};
        case LinePattern::Solid:
        case LinePattern::Boundary: return {};
    }
    return {};
}

std::string line_pattern_value(LinePattern pattern) {
    switch (pattern) {
        case LinePattern::Solid: return "solid";
        case LinePattern::Dash: return "dash";
        case LinePattern::Dot: return "dot";
        case LinePattern::DashDot: return "dash_dot";
        case LinePattern::Fault: return "fault";
        case LinePattern::Boundary: return "boundary";
    }
    return "solid";
}

std::optional<LinePattern> line_pattern_from_value(const std::string& value) {
    if (value == "solid") return LinePattern::Solid;
    if (value == "dash") return LinePattern::Dash;
    if (value == "dot") return LinePattern::Dot;
    if (value == "dash_dot") return LinePattern::DashDot;
    if (value == "fault") return LinePattern::Fault;
    if (value == "boundary") return LinePattern::Boundary;
    return std::nullopt;
}

std::string marker_symbol_value(MarkerSymbol symbol) {
    switch (symbol) {
        case MarkerSymbol::Circle: return "circle";
        case MarkerSymbol::Square: return "square";
        case MarkerSymbol::Triangle: return "triangle";
        case MarkerSymbol::Diamond: return "diamond";
        case MarkerSymbol::Cross: return "cross";
        case MarkerSymbol::Star: return "star";
        case MarkerSymbol::Well: return "well";
    }
    return "circle";
}

std::optional<MarkerSymbol> marker_symbol_from_value(const std::string& value) {
    if (value == "circle") return MarkerSymbol::Circle;
    if (value == "square") return MarkerSymbol::Square;
    if (value == "triangle") return MarkerSymbol::Triangle;
    if (value == "diamond") return MarkerSymbol::Diamond;
    if (value == "cross") return MarkerSymbol::Cross;
    if (value == "star") return MarkerSymbol::Star;
    if (value == "well") return MarkerSymbol::Well;
    return std::nullopt;
}

Json TextStyle::to_dict() const {
    Json data = Json::object();
    data["field"] = field;
    data["size"] = size;
    data["color"] = color;
    data["font_family"] = font_family;
    data["bold"] = bold;
    data["halo_color"] = halo_color;
    data["halo_width"] = halo_width;
    data["visible"] = visible;
    data["rotation_field"] = rotation_field;
    data["size_field"] = size_field;
    data["color_field"] = color_field;
    data["buffer_color"] = buffer_color;
    return data;
}

TextStyle TextStyle::from_dict(const Json& data) {
    TextStyle style;
    if (!data.is_object()) return style;
    auto string_key = [&](const char* key, std::string& target) {
        auto it = data.find(key);
        if (it != data.end() && !it->is_null()) {
            target = json_scalar_to_str(*it);
        }
    };
    auto double_key = [&](const char* key, double& target) {
        auto it = data.find(key);
        if (it == data.end() || it->is_null()) return;
        // Python try/except float(): conversion failures keep the default;
        // NaN parses and is applied verbatim (no filtering).
        try {
            target = json_scalar_to_double(*it);
        } catch (const std::exception&) {
        }
    };
    string_key("field", style.field);
    string_key("color", style.color);
    string_key("font_family", style.font_family);
    string_key("halo_color", style.halo_color);
    string_key("rotation_field", style.rotation_field);
    string_key("size_field", style.size_field);
    string_key("color_field", style.color_field);
    string_key("buffer_color", style.buffer_color);
    double_key("size", style.size);
    double_key("halo_width", style.halo_width);
    // Python bool(v): strings -> non-empty, numbers -> != 0, bools as-is.
    auto truthy = [](const Json& value) {
        if (value.is_string()) return !value.get<std::string>().empty();
        if (value.is_boolean()) return value.get<bool>();
        if (value.is_number_integer()) return value.get<long long>() != 0;
        if (value.is_number_float()) return value.get<double>() != 0.0;
        return true;  // containers/None already filtered by callers
    };
    if (auto it = data.find("bold"); it != data.end() && !it->is_null()) {
        style.bold = truthy(*it);
    }
    if (auto it = data.find("visible"); it != data.end() && !it->is_null()) {
        style.visible = truthy(*it);
    }
    return style;
}

Json VectorStyle::to_dict() const {
    Json data = Json::object();
    data["fill"] = fill;
    data["stroke"] = stroke;
    data["stroke_width"] = stroke_width;
    data["line_pattern"] = line_pattern_value(line_pattern);
    data["marker"] = marker_symbol_value(marker);
    data["marker_size"] = marker_size;
    data["renderer"] = renderer;
    data["field"] = field;
    if (!categories.empty()) {
        Json rows = Json::array();
        for (const StyleCategory& category : categories) {
            Json row = Json::array();
            row.push_back(category.value);
            row.push_back(category.fill);
            row.push_back(category.label);
            rows.push_back(std::move(row));
        }
        data["categories"] = std::move(rows);
    }
    if (!ranges.empty()) {
        Json rows = Json::array();
        for (const StyleRange& range : ranges) {
            Json row = Json::array();
            row.push_back(range.lo);
            row.push_back(range.hi);
            row.push_back(range.fill);
            row.push_back(range.label);
            rows.push_back(std::move(row));
        }
        data["ranges"] = std::move(rows);
    }
    if (!fill_patterns.empty()) {
        // Python dumps fill_patterns as an OBJECT (insertion order kept by
        // ordered_json); duplicate values collapse to the last pattern.
        Json rows = Json::object();
        for (const StyleFillPattern& pattern : fill_patterns) {
            rows[pattern.value] = pattern.pattern_id;
        }
        data["fill_patterns"] = std::move(rows);
    }
    if (labels.has_value()) {
        data["labels"] = labels->to_dict();
    }
    return data;
}

VectorStyle VectorStyle::from_dict(const Json& data) {
    VectorStyle style;
    if (!data.is_object()) return style;
    auto get = [&data](const char* key) {
        return data.find(key);
    };
    // fill/stroke: str(v) when truthy (non-empty strings; numbers coerce
    // through str() like Python and parse as gray at render time).
    for (const char* key : {"fill", "stroke"}) {
        auto it = get(key);
        if (it == data.end() || it->is_null()) continue;
        const std::string value = json_scalar_to_str(*it);
        if (!value.empty()) {
            if (std::string(key) == "fill") style.fill = value;
            else style.stroke = value;
        }
    }
    // stroke_width / marker_size: max(0.0, float(v)); conversion failures
    // keep the default.
    for (const char* key : {"stroke_width", "marker_size"}) {
        auto it = get(key);
        if (it == data.end() || it->is_null()) continue;
        try {
            double parsed = std::max(0.0, json_scalar_to_double(*it));
            if (std::string(key) == "stroke_width") style.stroke_width = parsed;
            else style.marker_size = parsed;
        } catch (const std::exception&) {
        }
    }
    if (auto it = get("line_pattern");
        it != data.end() && it->is_string() && !it->get<std::string>().empty()) {
        if (auto parsed = line_pattern_from_value(it->get<std::string>())) {
            style.line_pattern = *parsed;
        }
    }
    if (auto it = get("marker");
        it != data.end() && it->is_string() && !it->get<std::string>().empty()) {
        if (auto parsed = marker_symbol_from_value(it->get<std::string>())) {
            style.marker = *parsed;
        }
    }
    for (const char* key : {"renderer", "field"}) {
        auto it = get(key);
        if (it != data.end() && !it->is_null()) {
            if (std::string(key) == "renderer") style.renderer = json_scalar_to_str(*it);
            else style.field = json_scalar_to_str(*it);
        }
    }
    if (auto it = get("categories"); it != data.end() && it->is_object()) {
        // Established QGIS payload form: {"value": "#color"} in key order.
        for (auto entry = it->begin(); entry != it->end(); ++entry) {
            style.categories.push_back(StyleCategory{
                entry.key(), json_scalar_to_str(entry.value()), ""});
        }
    } else if (auto it2 = get("categories"); it2 != data.end() && it2->is_array()) {
        for (const Json& entry : *it2) {
            if (!entry.is_array() || entry.size() < 2) continue;
            StyleCategory category;
            category.value = json_scalar_to_str(entry.at(0));
            category.fill = json_scalar_to_str(entry.at(1));
            category.label = entry.size() > 2 ? json_scalar_to_str(entry.at(2)) : "";
            style.categories.push_back(std::move(category));
        }
    }
    if (auto it = get("ranges"); it != data.end() && it->is_array()) {
        for (const Json& entry : *it) {
            if (entry.is_array() && entry.size() >= 3) {
                try {
                    StyleRange range;
                    range.lo = json_scalar_to_double(entry.at(0));
                    range.hi = json_scalar_to_double(entry.at(1));
                    range.fill = json_scalar_to_str(entry.at(2));
                    range.label = entry.size() > 3 ? json_scalar_to_str(entry.at(3)) : "";
                    style.ranges.push_back(std::move(range));
                } catch (const std::exception&) {
                    // Python skips unconvertible entries.
                }
            } else if (entry.is_object()) {
                try {
                    StyleRange range;
                    auto lo = entry.find("min");
                    if (lo == entry.end()) lo = entry.find("lo");
                    range.lo = lo != entry.end() ? json_scalar_to_double(*lo) : 0.0;
                    auto hi = entry.find("max");
                    if (hi == entry.end()) hi = entry.find("hi");
                    range.hi = hi != entry.end() ? json_scalar_to_double(*hi) : 1.0;
                    auto fill = entry.find("fill");
                    if (fill == entry.end()) fill = entry.find("color");
                    range.fill = fill != entry.end()
                                     ? json_scalar_to_str(*fill)
                                     : "#6c8ebf";
                    auto label = entry.find("label");
                    range.label = label != entry.end() ? json_scalar_to_str(*label) : "";
                    style.ranges.push_back(std::move(range));
                } catch (const std::exception&) {
                }
            }
        }
    }
    if (auto it = get("fill_patterns"); it != data.end()) {
        if (it->is_object()) {
            for (auto entry = it->begin(); entry != it->end(); ++entry) {
                style.fill_patterns.push_back(StyleFillPattern{
                    entry.key(), json_scalar_to_str(entry.value())});
            }
        } else if (it->is_array()) {
            for (const Json& entry : *it) {
                if (entry.is_array() && entry.size() >= 2) {
                    style.fill_patterns.push_back(StyleFillPattern{
                        json_scalar_to_str(entry.at(0)),
                        json_scalar_to_str(entry.at(1))});
                }
            }
        }
    }
    if (auto it = get("labels"); it != data.end() && !it->is_null()) {
        style.labels = TextStyle::from_dict(*it);
    }
    return style;
}

const std::vector<std::pair<std::string, VectorStyle>>& style_library() {
    static const std::vector<std::pair<std::string, VectorStyle>> instance =
        [] {
            std::vector<std::pair<std::string, VectorStyle>> library;
            auto add = [&library](const char* name, VectorStyle style) {
                library.push_back(std::make_pair(std::string(name),
                                                 std::move(style)));
            };
            // Definition order matches Python STYLE_LIBRARY exactly (V12
            // label bindings included).
            {
                VectorStyle s;
                s.fill = "#6c8ebf";
                s.stroke = "#26364d";
                s.stroke_width = 1.0;
                TextStyle labels;
                labels.field = "facies";
                labels.size = 9.0;
                labels.color = "#1f2937";
                labels.halo_color = "#f8f9fa";
                labels.halo_width = 1.0;
                s.labels = labels;
                add("facies", std::move(s));
            }
            {
                VectorStyle s;
                s.fill = "#22b8a7";
                s.stroke = "#182431";
                s.marker = MarkerSymbol::Well;
                s.marker_size = 7.0;
                TextStyle labels;
                labels.field = "name";
                labels.size = 9.0;
                labels.color = "#1f2937";
                labels.halo_color = "#f8f9fa";
                labels.halo_width = 1.0;
                s.labels = labels;
                add("well", std::move(s));
            }
            {
                VectorStyle s;
                s.fill = "transparent";
                s.stroke = "#f08c46";
                s.stroke_width = 1.0;
                TextStyle labels;
                labels.field = "";
                labels.size = 8.0;
                labels.color = "#ffd8a8";
                s.labels = labels;
                add("contour", std::move(s));
            }
            {
                VectorStyle s;
                s.fill = "transparent";
                s.stroke = "#e8590c";
                s.stroke_width = 2.0;
                s.line_pattern = LinePattern::Solid;
                TextStyle labels;
                labels.field = "name";
                labels.size = 9.0;
                labels.color = "#e8590c";
                labels.halo_color = "#f8f9fa";
                labels.halo_width = 1.0;
                s.labels = labels;
                add("formation_boundary", std::move(s));
            }
            {
                VectorStyle s;
                s.fill = "transparent";
                s.stroke = "#e03131";
                s.stroke_width = 2.0;
                s.line_pattern = LinePattern::Fault;
                TextStyle labels;
                labels.field = "name";
                labels.size = 9.0;
                labels.color = "#c92a2a";
                labels.halo_color = "#f8f9fa";
                labels.halo_width = 1.0;
                s.labels = labels;
                add("fault", std::move(s));
            }
            {
                VectorStyle s;
                s.fill = "transparent";
                s.stroke = "#f08c46";
                s.stroke_width = 2.0;
                add("line", std::move(s));
            }
            {
                VectorStyle s;
                s.fill = "#eff3f8";
                s.stroke = "#182431";
                s.marker = MarkerSymbol::Circle;
                s.marker_size = 4.0;
                TextStyle labels;
                labels.field = "text";
                labels.size = 10.0;
                labels.color = "#f8f9fa";
                labels.rotation_field = "rotation";
                labels.size_field = "font_size";
                labels.color_field = "color";
                s.labels = labels;
                add("annotation", std::move(s));
            }
            {
                VectorStyle s;
                s.fill = "#eff3f8";
                s.stroke = "#182431";
                s.marker = MarkerSymbol::Circle;
                s.marker_size = 4.0;
                add("label", std::move(s));
            }
            return library;
        }();
    return instance;
}


const VectorStyle& default_style_for(const std::string& kind) {
    // _STYLE_FOR_KIND routes facies/well/line/label/annotation; everything
    // else falls back to the facies preset.
    const auto& library = style_library();
    const std::string* preset_name = &kind;
    static const std::string kFallback = "facies";
    if (kind != "facies" && kind != "well" && kind != "line" &&
        kind != "label" && kind != "annotation") {
        preset_name = &kFallback;
    }
    for (const auto& entry : library) {
        if (entry.first == *preset_name) return entry.second;
    }
    return library.front().second;
}

long long style_dict_revision(const Json& style) {
    // D-6: stable FNV-1a-64 over the canonical freeze serialization. The
    // freeze maps objects to sorted (key, value) pairs — the same shape
    // Python's freeze() builds before hashing.
    struct Freeze {
        static std::string apply(const Json& value) {
            if (value.is_object()) {
                std::vector<std::pair<std::string, std::string>> pairs;
                for (auto entry = value.begin(); entry != value.end(); ++entry) {
                    pairs.push_back({entry.key(), apply(entry.value())});
                }
                std::sort(pairs.begin(), pairs.end());
                std::string out = "m{";
                for (const auto& pair : pairs) {
                    out += pair.first + ":" + pair.second + ",";
                }
                return out + "}";
            }
            if (value.is_array()) {
                std::string out = "a(";
                for (const Json& item : value) out += apply(item) + ",";
                return out + ")";
            }
            if (value.is_boolean()) return value.get<bool>() ? std::string("b1")
                                                             : std::string("b0");
            if (value.is_null()) return std::string("n");
            if (value.is_number_integer()) {
                // Python freeze() keeps int/float distinct through hash
                // equality quirks; the C++ token encodes the JSON type
                // explicitly.
                return "i" + std::to_string(value.get<long long>());
            }
            if (value.is_number_float()) {
                char buf[40];
                std::snprintf(buf, sizeof(buf), "%a", value.get<double>());
                return std::string("f") + buf;
            }
            return "s" + value.get<std::string>();
        }
    };
    const std::string canonical =
        style.is_object() || style.is_array() ? Freeze::apply(style)
                                              : Freeze::apply(Json::object());
    std::uint64_t hash = 1469598103934665603ull;
    for (unsigned char byte : canonical) {
        hash ^= byte;
        hash *= 1099511628211ull;
    }
    return static_cast<long long>(hash);
}

}  // namespace pwb::cartography
