// Qt-free color ramp registry (CONV-27).
//
// Port of paleo_workbench/mapping/color_ramps.py: the 11 builtin ramps
// (viridis/plasma/magma/coolwarm/jet + the geological factor ramps
// porosity/permeability/thickness/sand_thickness/toc/water_depth), the
// evaluate/evaluate_value/sample_table contract and the versioned JSON
// document. Python semantics preserved:
//   * _hex_to_rgb gray (128,128,128,255) fallback for malformed colors;
//   * evaluate clamps and interpolates with half-to-even rounding
//     (Python round() -> std::nearbyint under FE_TONEAREST);
//   * evaluate_value degenerate span via math.isclose (rel_tol=1e-9,
//     abs_tol=0.0);
//   * the registry is insertion-ordered with lowercased keys and falls
//     back to viridis for unknown names.
#pragma once

#include <pwb/domain/json.hpp>

#include <array>
#include <string>
#include <utility>
#include <vector>

namespace pwb::cartography {

using Json = pwb::domain::Json;

struct ColorStop {
    double position = 0.0;  // [0, 1]
    std::string color;      // '#RRGGBB' or '#RRGGBBAA'
};

struct ColorRamp {
    std::string name;
    std::vector<ColorStop> stops;
    std::string nodata_color = "#00000000";

    // Python __post_init__: empty stops become black -> white.
    void apply_defaults() {
        if (stops.empty()) {
            stops = {ColorStop{0.0, "#000000"}, ColorStop{1.0, "#ffffff"}};
        }
    }

    // Sample the ramp at normalized t in [0, 1]; non-finite -> nodata color.
    std::string evaluate(double t) const;

  private:
    // The Python-body of evaluate (clamping + interpolation); evaluate()
    // applies the empty-stops default first.
    std::string evaluate_clamped(double t) const;

  public:
    // Sample by data value and bounds; non-finite inputs -> nodata color.
    std::string evaluate_value(double value, double vmin, double vmax) const;
    // RGBA LUT (count entries, each {r,g,b,a} in [0,255]); count < 2 -> 2.
    std::vector<std::array<int, 4>> sample_table(int count = 256) const;

    Json to_dict() const;
    // Tolerant parse: non-object payload -> viridis registry entry (the
    // Python from_dict contract calls get_color_ramp there).
    static ColorRamp from_dict(const Json& data);
};

// RGBA parse of the hex vocabulary accepted by Python _hex_to_rgb
// (3/6/8 digit groups, optional '#', whitespace stripped, malformed -> gray).
std::array<int, 4> hex_to_rgba(const std::string& hex_color);
// Minimal clamped '#rrggbb[aa]' form produced by Python _rgb_to_hex.
std::string rgba_to_hex(int r, int g, int b, int a = 255);

// math.isclose(a, b) with the Python defaults (rel_tol=1e-9, abs_tol=0.0).
bool py_isclose(double a, double b, double rel_tol = 1e-9, double abs_tol = 0.0);

// ---- registry ---------------------------------------------------------------

// Resolve by name (case-insensitive); unknown names resolve to viridis.
ColorRamp get_color_ramp(const std::string& name);
// Insert/replace in the insertion-ordered registry under the lowercased name.
void register_color_ramp(const ColorRamp& ramp);
// Available ramp names in registry insertion order.
std::vector<std::string> list_color_ramps();

}  // namespace pwb::cartography
