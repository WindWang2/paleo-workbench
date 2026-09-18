// Qt-free vector/label style value types (CONV-27).
//
// Port of paleo_workbench/mapping/map_styles.py: the flat-dict wire
// vocabulary shared by the authoring document, the persistence layer and the
// QGIS bridge payload. Python semantics preserved:
//   * to_dict key order (fill, stroke, stroke_width, line_pattern, marker,
//     marker_size, renderer, field, [categories], [ranges],
//     [fill_patterns], [labels]); conditional keys only when non-empty;
//   * tolerant from_dict: QGIS {"value": color} map form of categories,
//     dict-form ranges (min/lo, max/hi, fill/color, label), invalid numerics
//     silently keep the default, unknown line_pattern/marker values ignored;
//   * the 8-entry STYLE_LIBRARY preset vocabulary and default_style_for.
// Deviation (D-6, documented): style_dict_revision uses a stable FNV-1a-64
// over the canonical freeze serialization instead of Python's process-salted
// hash(); it is a change-detection token, never persisted semantically.
#pragma once

#include <pwb/domain/json.hpp>

#include <optional>
#include <string>
#include <tuple>
#include <vector>

namespace pwb::cartography {

using Json = pwb::domain::Json;

enum class LinePattern {
    Solid,
    Dash,
    Dot,
    DashDot,
    Fault,
    Boundary,
};

// Qt dash units (multiples of pen width); solid/boundary -> empty tuple.
std::vector<double> dash_pattern(LinePattern pattern);

// The Python enum value strings; parse returns std::nullopt when unknown.
std::string line_pattern_value(LinePattern pattern);
std::optional<LinePattern> line_pattern_from_value(const std::string& value);

enum class MarkerSymbol {
    Circle,
    Square,
    Triangle,
    Diamond,
    Cross,
    Star,
    Well,
};

std::string marker_symbol_value(MarkerSymbol symbol);
std::optional<MarkerSymbol> marker_symbol_from_value(const std::string& value);

struct TextStyle {
    std::string field;
    double size = 9.0;
    std::string color = "#f8f9fa";
    std::string font_family;
    bool bold = false;
    std::string halo_color = "#182431";
    double halo_width = 1.0;
    bool visible = true;
    std::string rotation_field;
    std::string size_field;
    std::string color_field;
    std::string buffer_color;

    Json to_dict() const;
    // Tolerant parse: null/non-object -> defaults; string keys applied when
    // present and non-null; numeric keys applied when convertible; bold and
    // visible coerce through Python bool().
    static TextStyle from_dict(const Json& data);
};

struct StyleCategory {
    std::string value;
    std::string fill;
    std::string label;
};

struct StyleRange {
    double lo = 0.0;
    double hi = 0.0;
    std::string fill;
    std::string label;
};

struct StyleFillPattern {
    std::string value;
    std::string pattern_id;
};

struct VectorStyle {
    std::string fill = "#6c8ebf";
    std::string stroke = "#26364d";
    double stroke_width = 1.0;
    LinePattern line_pattern = LinePattern::Solid;
    MarkerSymbol marker = MarkerSymbol::Circle;
    double marker_size = 6.0;
    std::string renderer = "single";
    std::string field;
    std::vector<StyleCategory> categories;      // (value, fill, label)
    std::vector<StyleRange> ranges;             // (lo, hi, fill, label)
    std::vector<StyleFillPattern> fill_patterns;  // (value, pattern id)
    std::optional<TextStyle> labels;

    Json to_dict() const;
    // Tolerant parse of persisted/host style dicts (unknown keys ignored).
    static VectorStyle from_dict(const Json& data);
};

// Named presets (facies/well/contour/formation_boundary/fault/line/
// annotation/label) in definition order.
const std::vector<std::pair<std::string, VectorStyle>>& style_library();
// Preset for a compatibility layer kind; unknown kinds use the facies
// preset (Python default_style_for).
const VectorStyle& default_style_for(const std::string& kind);

// Stable change-detection token over a style dict (D-6: FNV-1a-64 of the
// canonical freeze; content-sensitive, order-insensitive for objects).
long long style_dict_revision(const Json& style);

}  // namespace pwb::cartography
