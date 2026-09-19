// CONV-27 — implementation of the color ramp registry.
// See color_ramps.hpp for the ported Python contract.
#include <pwb/cartography/color_ramps.hpp>

#include <cmath>
#include <cctype>
#include <cstdio>
#include <mutex>
#include <stdexcept>
#include <string>

#include <algorithm>

namespace pwb::cartography {
namespace {

int hex_val(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

// Python round(): half-to-even. nearbyint honours the default FP rounding
// mode (FE_TONEAREST = half-to-even), unlike std::round (half-away).
int py_round_half_even(double value) {
    return static_cast<int>(std::nearbyint(value));
}

int clamp_channel(int value) {
    if (value < 0) return 0;
    if (value > 255) return 255;
    return value;
}

// Python str.lower() on ASCII names; ramp names are ASCII vocabulary.
std::string ascii_lower(const std::string& text) {
    std::string out = text;
    for (char& c : out) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return out;
}

std::vector<std::pair<std::string, ColorRamp>>& registry() {
    static std::vector<std::pair<std::string, ColorRamp>> instance = [] {
        std::vector<std::pair<std::string, ColorRamp>> ramps;
        auto add = [&ramps](const char* name,
                            std::vector<ColorStop> stops) {
            ramps.push_back({name, ColorRamp{name, std::move(stops)}});
        };
        // Definition order matches Python _BUILTIN_RAMPS exactly.
        add("viridis", {
            {0.0, "#440154"}, {0.25, "#3b528b"}, {0.5, "#21918c"},
            {0.75, "#5ec962"}, {1.0, "#fde725"},
        });
        add("plasma", {
            {0.0, "#0d0887"}, {0.25, "#6a00a8"}, {0.5, "#b12a90"},
            {0.75, "#e16462"}, {1.0, "#fca636"},
        });
        add("magma", {
            {0.0, "#000004"}, {0.25, "#51127c"}, {0.5, "#b73779"},
            {0.75, "#fc8961"}, {1.0, "#fcfdbf"},
        });
        add("coolwarm", {
            {0.0, "#3b4cc0"}, {0.5, "#dddddd"}, {1.0, "#b40426"},
        });
        add("jet", {
            {0.0, "#00007f"}, {0.25, "#007fff"}, {0.5, "#7fff7f"},
            {0.75, "#ff7f00"}, {1.0, "#7f0000"},
        });
        add("porosity", {
            {0.0, "#2c7bb6"}, {0.25, "#abd9e9"}, {0.5, "#ffffbf"},
            {0.75, "#fdae61"}, {1.0, "#d7191c"},
        });
        add("permeability", {
            {0.0, "#313695"}, {0.25, "#74add1"}, {0.5, "#e0f3f8"},
            {0.75, "#fee090"}, {1.0, "#d73027"},
        });
        add("thickness", {
            {0.0, "#f7fcf5"}, {0.25, "#c7e9c0"}, {0.5, "#74c476"},
            {0.75, "#31a354"}, {1.0, "#006d2c"},
        });
        add("sand_thickness", {
            {0.0, "#f7fbff"}, {0.25, "#fed976"}, {0.5, "#feb24c"},
            {0.75, "#fd8d3c"}, {1.0, "#b10026"},
        });
        add("toc", {
            {0.0, "#f7f7f7"}, {0.33, "#cccccc"}, {0.66, "#969696"},
            {1.0, "#252525"},
        });
        add("water_depth", {
            {0.0, "#ffffcc"}, {0.25, "#a1dab4"}, {0.5, "#41b6c4"},
            {0.75, "#2c7fb8"}, {1.0, "#253494"},
        });
        return ramps;
    }();
    return instance;
}

ColorRamp* find_ramp(const std::string& key) {
    auto& ramps = registry();
    for (auto& entry : ramps) {
        if (entry.first == key) return &entry.second;
    }
    return nullptr;
}

// D-7: the registry is a function-local static; writes serialize here.
std::mutex& registry_mutex() {
    static std::mutex instance;
    return instance;
}

}  // namespace

std::array<int, 4> hex_to_rgba(const std::string& hex_color) {
    // Python: s = hex_str.strip().lstrip("#")
    std::string s;
    std::size_t start = 0;
    while (start < hex_color.size() &&
           std::isspace(static_cast<unsigned char>(hex_color[start]))) {
        ++start;
    }
    std::size_t end = hex_color.size();
    while (end > start &&
           std::isspace(static_cast<unsigned char>(hex_color[end - 1]))) {
        --end;
    }
    s = hex_color.substr(start, end - start);
    // Python lstrip("#") strips every leading '#'.
    while (!s.empty() && s.front() == '#') s.erase(s.begin());

    static constexpr int kGray[4] = {128, 128, 128, 255};
    auto groups = [&s]() -> std::array<int, 4> {
        std::size_t rgb_len = 0;
        if (s.size() == 3) {
            rgb_len = 3;
        } else if (s.size() == 6) {
            rgb_len = 6;
        } else if (s.size() != 8) {
            return {kGray[0], kGray[1], kGray[2], kGray[3]};
        }
        // Parse the 2-digit channel groups; any invalid character falls back
        // to gray exactly like the Python int(..., 16) ValueError path.
        // int(x, 16) accepts an optional leading sign per NON-OVERLAPPING
        // slice: s[0:2]="+4" -> 4, s[2:4]="40" -> 64 (a sign + single digit
        // is a valid slice; digits never bleed across slice bounds).
        auto parse_group = [&s](std::size_t digit_index,
                                std::size_t group_len) -> int {
            auto hex_digit_at = [&s](std::size_t index) -> int {
                if (index >= s.size()) return -1;
                return hex_val(s[index]);
            };
            if (group_len == 1) {
                // 3-digit form: double each character.
                int hi = hex_digit_at(digit_index);
                if (hi < 0) return -1;
                return hi * 16 + hi;
            }
            std::size_t pos = digit_index;
            const std::size_t end = digit_index + group_len;
            int sign = 1;
            if (pos < end && pos < s.size() &&
                (s[pos] == '+' || s[pos] == '-')) {
                if (s[pos] == '-') sign = -1;
                ++pos;
            }
            const int hi = hex_digit_at(pos);
            if (hi < 0) return -1;
            if (pos + 1 >= end) return sign * hi;  // sign + single digit
            const int lo = hex_digit_at(pos + 1);
            if (lo < 0) return -1;
            return sign * (hi * 16 + lo);
        };
        int r, g, b, a;
        if (rgb_len == 3) {
            r = parse_group(0, 1);
            g = parse_group(1, 1);
            b = parse_group(2, 1);
            if (r < 0 || g < 0 || b < 0) return {kGray[0], kGray[1], kGray[2], kGray[3]};
            return {r, g, b, 255};
        }
        r = parse_group(0, 2);
        g = parse_group(2, 2);
        b = parse_group(4, 2);
        if (r < 0 || g < 0 || b < 0) return {kGray[0], kGray[1], kGray[2], kGray[3]};
        if (s.size() == 8) {
            a = parse_group(6, 2);
            if (a < 0) return {kGray[0], kGray[1], kGray[2], kGray[3]};
            return {r, g, b, a};
        }
        return {r, g, b, 255};
    }();
    return groups;
}

std::string rgba_to_hex(int r, int g, int b, int a) {
    r = clamp_channel(r);
    g = clamp_channel(g);
    b = clamp_channel(b);
    a = clamp_channel(a);
    char buf[10];
    if (a == 255) {
        std::snprintf(buf, sizeof(buf), "#%02x%02x%02x", r, g, b);
    } else {
        std::snprintf(buf, sizeof(buf), "#%02x%02x%02x%02x", r, g, b, a);
    }
    return buf;
}

bool py_isclose(double a, double b, double rel_tol, double abs_tol) {
    if (std::isnan(a) && std::isnan(b)) return true;  // not hit: callers guard
    double diff = std::fabs(a - b);
    return diff <= std::max(rel_tol * std::max(std::fabs(a), std::fabs(b)),
                            abs_tol);
}

std::string ColorRamp::evaluate(double t) const {
    if (!std::isfinite(t)) return nodata_color;
    if (stops.empty()) {
        // Python __post_init__ substitutes black -> white; aggregate init
        // bypasses it, so guard here (const method, local copy).
        return ColorRamp{name, {}, nodata_color}
            .evaluate_clamped(t);
    }
    return evaluate_clamped(t);
}

std::string ColorRamp::evaluate_clamped(double t) const {
    t = std::max(0.0, std::min(1.0, t));
    if (stops.size() == 1) return stops[0].color;

    if (t <= stops.front().position) return stops.front().color;
    if (t >= stops.back().position) return stops.back().color;

    for (std::size_t i = 0; i + 1 < stops.size(); ++i) {
        const ColorStop& s0 = stops[i];
        const ColorStop& s1 = stops[i + 1];
        if (s0.position <= t && t <= s1.position) {
            double span = s1.position - s0.position;
            double factor = span > 1e-12 ? (t - s0.position) / span : 0.0;
            auto c0 = hex_to_rgba(s0.color);
            auto c1 = hex_to_rgba(s1.color);
            // Same arithmetic order as Python: channel deltas scaled then
            // added, rounded half-to-even per channel.
            int r = py_round_half_even(c0[0] + (c1[0] - c0[0]) * factor);
            int g = py_round_half_even(c0[1] + (c1[1] - c0[1]) * factor);
            int b = py_round_half_even(c0[2] + (c1[2] - c0[2]) * factor);
            int a = py_round_half_even(c0[3] + (c1[3] - c0[3]) * factor);
            return rgba_to_hex(r, g, b, a);
        }
    }
    return stops.back().color;
}

std::string ColorRamp::evaluate_value(double value, double vmin,
                                      double vmax) const {
    if (!std::isfinite(value) || !std::isfinite(vmin) || !std::isfinite(vmax)) {
        return nodata_color;
    }
    if (py_isclose(vmin, vmax)) return evaluate(0.5);
    double t = (value - vmin) / (vmax - vmin);
    return evaluate(t);
}

std::vector<std::array<int, 4>> ColorRamp::sample_table(int count) const {
    count = std::max(2, count);
    std::vector<std::array<int, 4>> table;
    table.reserve(static_cast<std::size_t>(count));
    for (int i = 0; i < count; ++i) {
        double t = static_cast<double>(i) / static_cast<double>(count - 1);
        table.push_back(hex_to_rgba(evaluate(t)));
    }
    return table;
}

Json ColorRamp::to_dict() const {
    Json data = Json::object();
    data["name"] = name;
    Json stops_json = Json::array();
    for (const ColorStop& stop : stops) {
        Json entry = Json::object();
        entry["position"] = stop.position;
        entry["color"] = stop.color;
        stops_json.push_back(std::move(entry));
    }
    data["stops"] = std::move(stops_json);
    data["nodata_color"] = nodata_color;
    return data;
}

ColorRamp ColorRamp::from_dict(const Json& data) {
    if (!data.is_object()) return get_color_ramp("viridis");
    // str(x) coercion mirroring Python's str() for scalar JSON leaves.
    auto py_str = [](const Json& value) -> std::string {
        if (value.is_string()) return value.get<std::string>();
        if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
        if (value.is_number_integer()) {
            return std::to_string(value.get<long long>());
        }
        if (value.is_number_float()) {
            double v = value.get<double>();
            char buf[40];
            std::snprintf(buf, sizeof(buf), "%g", v);
            return buf;
        }
        return value.dump();
    };
    ColorRamp ramp;
    // name = str(data.get("name") or "custom") — ANY falsy value (None,
    // "", 0, 0.0, False) falls back to "custom".
    if (data.contains("name") && !data["name"].is_null()) {
        const Json& raw = data["name"];
        const bool falsy = raw.is_string()
                               ? raw.get<std::string>().empty()
                           : raw.is_boolean() ? !raw.get<bool>()
                           : raw.is_number_integer()
                               ? raw.get<long long>() == 0
                           : raw.is_number_float()
                               ? raw.get<double>() == 0.0
                               : false;
        ramp.name = falsy ? "custom" : py_str(raw);
    } else {
        ramp.name = "custom";
    }
    if (data.contains("stops") && data["stops"].is_array()) {
        for (const Json& item : data["stops"]) {
            if (!item.is_object()) continue;  // non-Mapping entries skipped
            ColorStop stop;
            auto position_it = item.find("position");
            if (position_it != item.end()) {
                // float(None) raises TypeError; float(<str>) may succeed.
                if (position_it->is_null()) {
                    throw std::invalid_argument(
                        "float() argument must be a number, not 'NoneType'");
                }
                if (position_it->is_number()) {
                    stop.position = position_it->is_number_integer()
                                        ? static_cast<double>(
                                              position_it->get<long long>())
                                        : position_it->get<double>();
                } else if (position_it->is_string()) {
                    const std::string text =
                        position_it->get<std::string>();
                    std::size_t consumed = 0;
                    try {
                        double parsed = std::stod(text, &consumed);
                        while (consumed < text.size() &&
                               std::isspace(
                                   static_cast<unsigned char>(
                                       text[consumed]))) {
                            ++consumed;
                        }
                        if (consumed != text.size()) {
                            throw std::invalid_argument(text);
                        }
                        stop.position = parsed;
                    } catch (const std::invalid_argument&) {
                        throw std::invalid_argument(
                            "could not convert string to float: " + text);
                    } catch (const std::out_of_range&) {
                        throw std::invalid_argument(
                            "could not convert string to float: " + text);
                    }
                } else {
                    throw std::invalid_argument(
                        "float() argument must be a number");
                }
            }
            auto color_it = item.find("color");
            if (color_it != item.end() && !color_it->is_null()) {
                stop.color = py_str(*color_it);  // str(16711680) is a valid
                                                 // 8-digit hex string
            } else {
                stop.color = "#000000";
            }
            ramp.stops.push_back(std::move(stop));
        }
    }
    if (data.contains("nodata_color") && !data["nodata_color"].is_null()) {
        ramp.nodata_color = py_str(data["nodata_color"]);
    }
    ramp.apply_defaults();
    return ramp;
}

ColorRamp get_color_ramp(const std::string& name) {
    static const std::string kFallback = "viridis";
    const std::string key = ascii_lower(name);
    {
        // Registry reads are stable once built; guard against concurrent
        // register_color_ramp writers (D-7).
        std::lock_guard<std::mutex> guard(registry_mutex());
        if (ColorRamp* hit = find_ramp(key)) return *hit;
        if (ColorRamp* fallback = find_ramp(kFallback)) return *fallback;
    }
    // Unreachable: viridis is always present.
    throw std::runtime_error("color ramp registry missing viridis");
}

void register_color_ramp(const ColorRamp& ramp) {
    std::lock_guard<std::mutex> guard(registry_mutex());
    auto& ramps = registry();
    const std::string key = ascii_lower(ramp.name);
    for (auto& entry : ramps) {
        if (entry.first == key) {
            entry.second = ramp;  // replace in place (keeps insertion order)
            return;
        }
    }
    ramps.push_back({key, ramp});
}

std::vector<std::string> list_color_ramps() {
    std::lock_guard<std::mutex> guard(registry_mutex());
    std::vector<std::string> names;
    names.reserve(registry().size());
    for (const auto& entry : registry()) names.push_back(entry.first);
    return names;
}

}  // namespace pwb::cartography
