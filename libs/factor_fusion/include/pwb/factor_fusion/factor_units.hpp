#pragma once

// C++ port of paleo_workbench/workflow/factor_units.py (CONV-24).
// FACTOR_DEFAULTS / FACTOR_FAMILIES are generated tables
// (src/factor_units_data.inc); normalize_factor_key needs the Unicode
// lower() map (src/units_lower_map.inc). Derived-rule provenance constants
// ride along verbatim.

#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::factor_fusion {

// Decision-D11 derived-factor provenance markers (verbatim).
inline constexpr const char* kDerivedSandRatioRule = "sand_ratio = H_s / H_t";
inline constexpr const char* kDerivedFormationThicknessRule =
    "formation_thickness = base_depth - top_depth";

// strip().lower() — empty/falsy input yields "".
std::string normalize_factor_key(std::string_view factor_name);

// Canonical unit / color ramp; nullopt when the mnemonic is unknown (units
// are never guessed).
std::optional<std::string> unit_for_factor(std::string_view factor_name);
std::optional<std::string> color_ramp_for_factor(std::string_view factor_name);

// validate_factor_unit_against_values: declared-unit vs value-magnitude
// diagnostics. `values` are the raw float32 grid cells (NaN = nodata).
std::vector<std::string> validate_factor_unit_against_values(
    std::string_view factor_name, const std::optional<std::string>& unit,
    const std::vector<float>& values);

}  // namespace pwb::factor_fusion
