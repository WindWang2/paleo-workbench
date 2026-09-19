#pragma once

// VIZ-B — sonic slowness unit normalization.
// Verbatim port of geoviz_well_tie/sonic_units.py (WL-9 / #406): metadata
// first, numeric heuristic only as fallback, and the heuristic NEVER runs
// silently — a warning string is returned for the caller to surface.

#include <optional>
#include <string>
#include <vector>

namespace pwb::viz::well_tie {

// µs/ft -> µs/m factor (feet per metre).
inline constexpr double kUsFtToUsM = 3.28084;

enum class SonicUnit {
    us_per_m,
    us_per_ft,
};

// Return the canonical unit for a LAS curve unit string, or nullopt for
// empty/unknown. Handles case variants and micro-sign spellings ("US/M",
// "µs/m", "USF", "US/FT", separator-less "usft"/"usecft"/"microsecft").
[[nodiscard]] std::optional<SonicUnit> canonical_sonic_unit(
    const std::string& unit);

struct NormalizedSonic {
    std::vector<double> values;  // µs/m
    SonicUnit resolved = SonicUnit::us_per_m;
    std::optional<std::string> warning;  // set iff the heuristic ran
};

// Return (sonic in µs/m, resolved unit, warning).
// - unit resolves to µs/m: values unchanged.
// - unit resolves to µs/ft: values scaled by kUsFtToUsM.
// - unit missing/unknown: legacy numeric heuristic (median of |sonic| < 150
//   => treat as µs/ft and scale); the warning string is always set in that
//   case (Python parity: never silently).
[[nodiscard]] NormalizedSonic normalize_sonic_units(
    const std::vector<double>& sonic, const std::optional<std::string>& unit);

}  // namespace pwb::viz::well_tie
