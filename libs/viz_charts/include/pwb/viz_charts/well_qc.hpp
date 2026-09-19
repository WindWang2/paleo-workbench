// Pure mathematical quality controls for well-table values — port of
// geoviz_plots/analytics/well_qc.py.
#pragma once

#include <cmath>
#include <optional>
#include <string>
#include <vector>

namespace pwb::viz_charts {

// median(|x - median(x)|) over finite values; empty → NaN.
double median_absolute_deviation(const std::vector<double>& values);

// Modified z-scores = 0.6745 * (x - median) / MAD over finite samples;
// non-finite inputs keep NaN. MAD == 0 keeps the signal: median-equal
// samples score 0, finite deviations score ±inf (sign preserved).
std::vector<double> modified_z_scores(const std::vector<double>& values);

// (ratio, flag): None inputs → (nullopt, "ok"); non-finite / Ht <= 0 /
// Hs < 0 / Hs > Ht → (nullopt, "invalid_ratio"); else (Hs/Ht, "ok").
std::pair<std::optional<double>, std::string> compute_sand_ratio(
    std::optional<double> sand_thickness, std::optional<double> total_thickness);

}  // namespace pwb::viz_charts
