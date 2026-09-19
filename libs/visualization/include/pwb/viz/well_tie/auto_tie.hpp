#pragma once

// VIZ-B — auto-tie: cross-correlation bulk time-shift estimation.
// Verbatim port of geoviz_well_tie/auto_tie.py::correlate_synthetic_to_trace
// (the canonical entry point; the deprecated wrappers are not ported).

#include <utility>
#include <vector>

namespace pwb::viz::well_tie {

struct AutoTieResult {
    int shift_samples = 0;
    double correlation = 0.0;  // Pearson r over the best lag's overlap
};

// Full integer-lag scan of the sliding-window Pearson cross-correlation.
// Lag convention: positive shift = the synthetic should move LATER in
// time. Early exit (0, 0.0) when either input is empty, effectively
// constant (std < 1e-10 over the full length), or no lag reaches the
// minimum overlap max(2, min(n_s, n_t) / 4). argmax takes the FIRST
// maximum (numpy parity on ties); r is clamped to <= 1.0.
[[nodiscard]] AutoTieResult correlate_synthetic_to_trace(
    const std::vector<double>& synthetic,
    const std::vector<double>& seismic_trace);

}  // namespace pwb::viz::well_tie
