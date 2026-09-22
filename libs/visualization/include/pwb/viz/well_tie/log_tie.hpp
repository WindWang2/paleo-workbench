#pragma once

#include <functional>
#include <string>
#include <vector>

namespace pwb::viz::well_tie {

struct LogTieCurve {
    std::vector<double> depth_m;
    std::vector<double> values;
    std::string unit;
};

struct LogTieInput {
    LogTieCurve sonic;
    LogTieCurve density;
    // Optional checkshot anchors; otherwise integrate the sonic log.
    std::vector<double> checkshot_depth_m;
    std::vector<double> checkshot_twt_ms;
    std::vector<double> seismic;
    double t0_ms = 0.0;
    double dt_ms = 2.0;
    double frequency_hz = 30.0;
    double initial_shift_ms = 0.0;
    double max_shift_ms = 200.0;
};

struct LogTieResult {
    std::vector<double> synthetic;
    double correlation = 0.0;
    double shift_ms = 0.0;
    std::size_t overlap_samples = 0;
    std::string warning;
};

// Align independent log depth axes, normalize units, resample impedance on
// the actual seismic time axis, convolve, and correlate only measured overlap.
// Invalid/constant inputs throw; cancellation is checked during the lag scan.
LogTieResult tie_logs_to_seismic(const LogTieInput& input,
                               const std::function<bool()>& cancelled = {});

}  // namespace pwb::viz::well_tie
