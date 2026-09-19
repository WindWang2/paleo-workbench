#pragma once

// VIZ-B — legacy cross-correlation auto-tie evaluator (lag + residual).
// Verbatim port of geoviz_well_tie/tie_evaluator.py (deprecated in favour
// of auto_tie.hpp but kept as an independent output pair: normalized
// coefficient + amplitude residual on the lag-aligned overlap, #845/#117
// semantics). Prefer correlate_synthetic_to_trace in new code.

#include <vector>

namespace pwb::viz::well_tie {

struct CrossCorrelation {
    double max_r = 0.0;
    int lag = 0;  // positive = s1 (synthetic) moves later in time
};

// Truncates to the common length, nan_to_num's the inputs, divides by
// max(1e-6, n * std_a * std_b); early (0.0, 0) on empty or zero-std.
[[nodiscard]] CrossCorrelation compute_cross_correlation(
    const std::vector<double>& s1, const std::vector<double>& s2);

struct TieQuality {
    double r = 0.0;
    int lag = 0;
    // |synthetic - seismic| on the lag-aligned overlap segment
    // (seismic[i] differenced against synthetic[i - lag]).
    std::vector<double> residual;
};

[[nodiscard]] TieQuality evaluate_tie_quality(
    const std::vector<double>& synthetic,
    const std::vector<double>& seismic);

}  // namespace pwb::viz::well_tie
