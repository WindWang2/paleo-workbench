#include <pwb/ui_composite/map_styles.hpp>

#include <algorithm>

namespace pwb::ui_composite {
namespace {

const Json* find(const Json& object, const char* key) {
    if (!object.is_object()) {
        return nullptr;
    }
    auto it = object.find(key);
    return it == object.end() ? nullptr : &*it;
}

std::string str_or(const Json& object, const char* key,
                   std::string fallback = {}) {
    const Json* value = find(object, key);
    if (value == nullptr || value->is_null()) {
        return fallback;
    }
    if (value->is_string()) {
        return value->get<std::string>();
    }
    if (value->is_number_integer()) {
        return std::to_string(value->get<long long>());
    }
    if (value->is_number()) {
        return std::to_string(value->get<double>());
    }
    if (value->is_boolean()) {
        return value->get<bool>() ? "True" : "False";
    }
    return fallback;
}

bool bool_or(const Json& object, const char* key, bool fallback) {
    const Json* value = find(object, key);
    if (value != nullptr && value->is_boolean()) {
        return value->get<bool>();
    }
    return fallback;
}

double num_or(const Json& object, const char* key, double fallback,
              double floor = -1e300) {
    const Json* value = find(object, key);
    if (value != nullptr && value->is_number()) {
        return std::max(floor, value->get<double>());
    }
    return fallback;
}

std::string known_line_pattern(const std::string& value,
                               const std::string& fallback) {
    static const char* kPatterns[] = {
        line_pattern::kSolid, line_pattern::kDash, line_pattern::kDot,
        line_pattern::kDashDot, line_pattern::kFault, line_pattern::kBoundary,
    };
    for (const char* pattern : kPatterns) {
        if (value == pattern) {
            return value;
        }
    }
    return fallback;
}

std::string known_marker(const std::string& value,
                         const std::string& fallback) {
    static const char* kMarkers[] = {
        marker_symbol::kCircle, marker_symbol::kSquare,
        marker_symbol::kTriangle, marker_symbol::kDiamond,
        marker_symbol::kCross,  marker_symbol::kStar,
        marker_symbol::kWell,
    };
    for (const char* marker : kMarkers) {
        if (value == marker) {
            return value;
        }
    }
    return fallback;
}

}  // namespace

std::vector<double> line_pattern_dash_pattern(const std::string& pattern,
                                              double width) {
    if (pattern == line_pattern::kDash) {
        return {4.0 * width, 2.0 * width};
    }
    if (pattern == line_pattern::kDot) {
        return {1.0 * width, 2.0 * width};
    }
    if (pattern == line_pattern::kDashDot) {
        return {4.0 * width, 2.0 * width, 1.0 * width, 2.0 * width};
    }
    if (pattern == line_pattern::kFault) {
        return {6.0 * width, 2.0 * width};
    }
    return {};
}

Json TextStyle::to_dict() const {
    return Json{
        {"field", field},
        {"size", size},
        {"color", color},
        {"font_family", font_family},
        {"bold", bold},
        {"halo_color", halo_color},
        {"halo_width", halo_width},
        {"visible", visible},
        {"rotation_field", rotation_field},
        {"size_field", size_field},
        {"color_field", color_field},
        {"buffer_color", buffer_color},
    };
}

TextStyle TextStyle::from_dict(const Json& data) {
    TextStyle style;
    if (!data.is_object()) {
        return style;
    }
    style.field = str_or(data, "field", style.field);
    style.color = str_or(data, "color", style.color);
    style.font_family = str_or(data, "font_family", style.font_family);
    style.halo_color = str_or(data, "halo_color", style.halo_color);
    style.rotation_field =
        str_or(data, "rotation_field", style.rotation_field);
    style.size_field = str_or(data, "size_field", style.size_field);
    style.color_field = str_or(data, "color_field", style.color_field);
    style.buffer_color = str_or(data, "buffer_color", style.buffer_color);
    style.size = num_or(data, "size", style.size);
    style.halo_width = num_or(data, "halo_width", style.halo_width);
    style.bold = bool_or(data, "bold", style.bold);
    style.visible = bool_or(data, "visible", style.visible);
    return style;
}

Json VectorStyle::to_dict() const {
    Json data = {
        {"fill", fill},
        {"stroke", stroke},
        {"stroke_width", stroke_width},
        {"line_pattern", line_pattern},
        {"marker", marker},
        {"marker_size", marker_size},
        {"renderer", renderer},
        {"field", field},
    };
    if (!categories.empty()) {
        Json entries = Json::array();
        for (const auto& [value, fill_color, label] : categories) {
            entries.push_back({value, fill_color, label});
        }
        data["categories"] = std::move(entries);
    }
    if (!ranges.empty()) {
        Json entries = Json::array();
        for (const auto& [lo, hi, fill_color, label] : ranges) {
            entries.push_back({lo, hi, fill_color, label});
        }
        data["ranges"] = std::move(entries);
    }
    if (!fill_patterns.empty()) {
        Json patterns = Json::object();
        for (const auto& [value, pattern_id] : fill_patterns) {
            patterns[value] = pattern_id;
        }
        data["fill_patterns"] = std::move(patterns);
    }
    if (labels.has_value()) {
        data["labels"] = labels->to_dict();
    }
    return data;
}

VectorStyle VectorStyle::from_dict(const Json& data) {
    VectorStyle style;
    if (!data.is_object()) {
        return style;
    }
    style.fill = str_or(data, "fill", style.fill);
    style.stroke = str_or(data, "stroke", style.stroke);
    style.stroke_width = num_or(data, "stroke_width", style.stroke_width, 0.0);
    style.marker_size = num_or(data, "marker_size", style.marker_size, 0.0);
    style.line_pattern =
        known_line_pattern(str_or(data, "line_pattern"), style.line_pattern);
    style.marker = known_marker(str_or(data, "marker"), style.marker);
    style.renderer = str_or(data, "renderer", style.renderer);
    style.field = str_or(data, "field", style.field);

    const Json* categories = find(data, "categories");
    if (categories != nullptr && categories->is_object()) {
        for (const auto& [key, value] : categories->items()) {
            style.categories.emplace_back(key,
                                          value.is_string()
                                              ? value.get<std::string>()
                                              : std::string{},
                                          std::string{});
        }
    } else if (categories != nullptr && categories->is_array()) {
        for (const Json& entry : *categories) {
            if (entry.is_array() && entry.size() >= 2) {
                style.categories.emplace_back(
                    entry[0].is_string() ? entry[0].get<std::string>()
                                         : std::string{},
                    entry[1].is_string() ? entry[1].get<std::string>()
                                         : std::string{},
                    entry.size() > 2 && entry[2].is_string()
                        ? entry[2].get<std::string>()
                        : std::string{});
            }
        }
    }

    const Json* ranges = find(data, "ranges");
    if (ranges != nullptr && ranges->is_array()) {
        for (const Json& entry : *ranges) {
            if (entry.is_array() && entry.size() >= 3) {
                if (entry[0].is_number() && entry[1].is_number()) {
                    style.ranges.emplace_back(
                        entry[0].get<double>(), entry[1].get<double>(),
                        entry[2].is_string() ? entry[2].get<std::string>()
                                             : std::string{},
                        entry.size() > 3 && entry[3].is_string()
                            ? entry[3].get<std::string>()
                            : std::string{});
                }
            } else if (entry.is_object()) {
                const Json* lo = find(entry, "min");
                if (lo == nullptr) {
                    lo = find(entry, "lo");
                }
                const Json* hi = find(entry, "max");
                if (hi == nullptr) {
                    hi = find(entry, "hi");
                }
                if (lo != nullptr && hi != nullptr && lo->is_number() &&
                    hi->is_number()) {
                    style.ranges.emplace_back(
                        lo->get<double>(), hi->get<double>(),
                        str_or(entry, "fill",
                               str_or(entry, "color", "#6c8ebf")),
                        str_or(entry, "label"));
                }
            }
        }
    }

    const Json* patterns = find(data, "fill_patterns");
    if (patterns != nullptr && patterns->is_object()) {
        for (const auto& [key, value] : patterns->items()) {
            style.fill_patterns.emplace_back(
                key, value.is_string() ? value.get<std::string>()
                                       : std::string{});
        }
    } else if (patterns != nullptr && patterns->is_array()) {
        for (const Json& entry : *patterns) {
            if (entry.is_array() && entry.size() >= 2 &&
                entry[0].is_string() && entry[1].is_string()) {
                style.fill_patterns.emplace_back(
                    entry[0].get<std::string>(), entry[1].get<std::string>());
            }
        }
    }

    const Json* labels = find(data, "labels");
    if (labels != nullptr && !labels->is_null()) {
        style.labels = TextStyle::from_dict(*labels);
    }
    return style;
}

const std::map<std::string, VectorStyle>& style_library() {
    static const std::map<std::string, VectorStyle> library = [] {
        std::map<std::string, VectorStyle> map;
        {
            VectorStyle facies;
            facies.fill = "#6c8ebf";
            facies.stroke = "#26364d";
            facies.stroke_width = 1.0;
            facies.labels = TextStyle{.field = "facies",
                                      .size = 9.0,
                                      .color = "#1f2937",
                                      .halo_color = "#f8f9fa",
                                      .halo_width = 1.0};
            map.emplace("facies", facies);
        }
        {
            VectorStyle well;
            well.fill = "#22b8a7";
            well.stroke = "#182431";
            well.marker = marker_symbol::kWell;
            well.marker_size = 7.0;
            well.labels = TextStyle{.field = "name",
                                    .size = 9.0,
                                    .color = "#1f2937",
                                    .halo_color = "#f8f9fa",
                                    .halo_width = 1.0};
            map.emplace("well", well);
        }
        {
            VectorStyle contour;
            contour.fill = "transparent";
            contour.stroke = "#f08c46";
            contour.stroke_width = 1.0;
            contour.labels = TextStyle{.field = "",
                                       .size = 8.0,
                                       .color = "#ffd8a8"};
            map.emplace("contour", contour);
        }
        {
            VectorStyle boundary;
            boundary.fill = "transparent";
            boundary.stroke = "#e8590c";
            boundary.stroke_width = 2.0;
            boundary.labels = TextStyle{.field = "name",
                                        .size = 9.0,
                                        .color = "#e8590c",
                                        .halo_color = "#f8f9fa",
                                        .halo_width = 1.0};
            map.emplace("formation_boundary", boundary);
        }
        {
            VectorStyle fault;
            fault.fill = "transparent";
            fault.stroke = "#e03131";
            fault.stroke_width = 2.0;
            fault.line_pattern = line_pattern::kFault;
            fault.labels = TextStyle{.field = "name",
                                     .size = 9.0,
                                     .color = "#c92a2a",
                                     .halo_color = "#f8f9fa",
                                     .halo_width = 1.0};
            map.emplace("fault", fault);
        }
        {
            VectorStyle line;
            line.fill = "transparent";
            line.stroke = "#f08c46";
            line.stroke_width = 2.0;
            map.emplace("line", line);
        }
        {
            VectorStyle annotation;
            annotation.fill = "#eff3f8";
            annotation.stroke = "#182431";
            annotation.marker = marker_symbol::kCircle;
            annotation.marker_size = 4.0;
            TextStyle labels;
            labels.field = "text";
            labels.size = 10.0;
            labels.color = "#f8f9fa";
            labels.rotation_field = "rotation";
            labels.size_field = "font_size";
            labels.color_field = "color";
            annotation.labels = labels;
            map.emplace("annotation", annotation);
        }
        {
            VectorStyle label;
            label.fill = "#eff3f8";
            label.stroke = "#182431";
            label.marker = marker_symbol::kCircle;
            label.marker_size = 4.0;
            map.emplace("label", label);
        }
        return map;
    }();
    return library;
}

const VectorStyle& default_style_for(const std::string& kind) {
    static const std::map<std::string, std::string> for_kind = {
        {"facies", "facies"},
        {"well", "well"},
        {"line", "line"},
        {"label", "label"},
        // #1052: annotation presets resolve through this map (labels +
        // per-feature data-defined bindings), never the facies fallback.
        {"annotation", "annotation"},
    };
    auto it = for_kind.find(kind);
    return style_library().at(it == for_kind.end() ? "facies" : it->second);
}

int64_t style_dict_revision(const Json& style) {
    // Cheap stable content hash — mirrors Python's recursive-tuple freeze:
    // dict keys sorted, sequences preserved, everything else by value.
    // std::hash composition is deterministic within a process; style dicts
    // are small so this stays well under a microsecond.
    struct Freeze {
        static void append(const Json& value, std::string& out) {
            if (value.is_object()) {
                std::vector<std::string> keys;
                keys.reserve(value.size());
                for (const auto& [key, item] : value.items()) {
                    keys.push_back(key);
                }
                std::sort(keys.begin(), keys.end());
                out += '{';
                for (const std::string& key : keys) {
                    out += key;
                    out += ':';
                    append(value.at(key), out);
                    out += ',';
                }
                out += '}';
                return;
            }
            if (value.is_array()) {
                out += '[';
                for (const Json& item : value) {
                    append(item, out);
                    out += ',';
                }
                out += ']';
                return;
            }
            out += value.dump();
        }
    };
    std::string frozen;
    if (!style.is_null()) {
        Freeze::append(style, frozen);
    }
    return static_cast<int64_t>(std::hash<std::string>{}(frozen));
}

}  // namespace pwb::ui_composite
