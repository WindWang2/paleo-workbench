#pragma once

// Port of paleo_workbench/mapping/map_styles.py (UI-13).
//
// VectorStyle is the layer-level style authority consumed by composite
// templates (GEO_TEMPLATES), snapshot serialization and the render
// backends. Stroke width / marker size / label size are logical pixels at
// 96 dpi — renderers scale by dpi/96.
//
// Qt-free; serialization uses pwb::domain::Json.

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

// Named cartographic line patterns for geological map features.
namespace line_pattern {
inline constexpr const char* kSolid = "solid";
inline constexpr const char* kDash = "dash";
inline constexpr const char* kDot = "dot";
inline constexpr const char* kDashDot = "dash_dot";
// 断层线: the classic long-dash fault trace used on paleogeographic maps.
inline constexpr const char* kFault = "fault";
// 地层界线: heavier weight expressed via stroke_width; pattern solid.
inline constexpr const char* kBoundary = "boundary";
}  // namespace line_pattern

// LinePattern.dash_pattern(width) parity — Qt dash units (multiples of
// pen width); unknown/solid patterns return an empty vector.
std::vector<double> line_pattern_dash_pattern(const std::string& pattern,
                                              double width);

// Point symbol vocabulary including standard well markers.
namespace marker_symbol {
inline constexpr const char* kCircle = "circle";
inline constexpr const char* kSquare = "square";
inline constexpr const char* kTriangle = "triangle";
inline constexpr const char* kDiamond = "diamond";
inline constexpr const char* kCross = "cross";
inline constexpr const char* kStar = "star";
// 井符号: ring with a centre dot, the standard well location mark.
inline constexpr const char* kWell = "well";
}  // namespace marker_symbol

// Label placement style consumed by labeling-capable backends.
struct TextStyle {
    std::string field;
    double size = 9.0;
    std::string color = "#f8f9fa";
    std::string font_family;
    bool bold = false;
    std::string halo_color = "#182431";
    double halo_width = 1.0;
    bool visible = true;
    // #1052: per-feature data-defined overrides honoured by the QGIS PAL
    // backend — attribute FIELD names; "" disables each override.
    std::string rotation_field;
    std::string size_field;
    std::string color_field;
    // #1102: explicit buffer (halo) colour; "" falls back to halo_color
    // on the QGIS wire.
    std::string buffer_color;

    Json to_dict() const;
    // Tolerant parse (unknown keys ignored).
    static TextStyle from_dict(const Json& data);

    bool operator==(const TextStyle&) const = default;
};

// One layer-level vector style with per-feature renderer settings.
struct VectorStyle {
    std::string fill = "#6c8ebf";
    std::string stroke = "#26364d";
    double stroke_width = 1.0;
    std::string line_pattern = line_pattern::kSolid;
    std::string marker = marker_symbol::kCircle;
    double marker_size = 6.0;
    // Renderer classification (honoured by the QGIS backend).
    std::string renderer = "single";
    std::string field;
    // (value, fill, label)
    std::vector<std::tuple<std::string, std::string, std::string>> categories;
    // (lo, hi, fill, label)
    std::vector<std::tuple<double, double, std::string, std::string>> ranges;
    // Per-category SVG pattern overlay (category value → pattern id).
    std::vector<std::pair<std::string, std::string>> fill_patterns;
    std::optional<TextStyle> labels;

    Json to_dict() const;
    // Tolerant parse (unknown keys ignored; established wire forms of
    // categories/ranges/fill_patterns all accepted).
    static VectorStyle from_dict(const Json& data);

    bool operator==(const VectorStyle&) const = default;
};

// Named presets — values intentionally match the Python STYLE_LIBRARY so
// existing projects render unchanged. Returned by const reference.
const std::map<std::string, VectorStyle>& style_library();

// default_style_for(kind) parity — unknown kinds fall back to "facies".
const VectorStyle& default_style_for(const std::string& kind);

// style_dict_revision parity: cheap stable content hash of a style dict.
int64_t style_dict_revision(const Json& style);

}  // namespace pwb::ui_composite
