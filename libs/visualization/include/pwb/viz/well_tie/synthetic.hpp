#pragma once

// VIZ-B — reflectivity computation and synthetic seismogram generation.
// Verbatim port of geoviz_well_tie/synthetic.py (the canonical set exported
// by the package __init__). Units: sonic µs/m (slowness), density g/cm³,
// dt seconds here / milliseconds in generate_synthetic_twt, frequency Hz.
// NaN policy: compute_reflectivity propagates NaN; synthetic_from_logs
// fills NaN by linear interpolation over the sample index first (#117).

#include <optional>
#include <string>
#include <vector>

namespace pwb::viz::well_tie {

// R_i = (Z_{i+1} - Z_i) / (Z_{i+1} + Z_i), Z = (1e6/sonic) * density.
// Denominator |sum| < 1e-12 is replaced by +1e-12 unconditionally.
// Returns (N-1,) float32. Mismatched input lengths throw
// std::invalid_argument (numpy broadcast parity — never silent clipping).
[[nodiscard]] std::vector<float> compute_reflectivity(
    const std::vector<double>& sonic, const std::vector<double>& density);

// Convolve reflectivity with a wavelet ('same' mode, output length ==
// reflectivity length). Unified math (both numpy branches are equivalent):
//   out[i] = sum_j reflectivity[j] * wavelet[(M-1)/2 + i - j]  (int div,
//   out-of-range wavelet indices contribute 0). Empty reflectivity -> {}.
[[nodiscard]] std::vector<float> generate_synthetic(
    const std::vector<float>& reflectivity,
    const std::vector<float>& wavelet);

struct SyntheticTwtOptions {
    std::string wavelet_type = "ricker";  // "ormsby" (exact) else Ricker
    double dt_ms = 4.0;
    double peak_freq = 25.0;              // Ricker
    double f1 = 5.0;                      // Ormsby 5/10/40/50 Hz
    double f2 = 10.0;
    double f3 = 40.0;
    double f4 = 50.0;
};

// Unit-safe wrapper: dt in MILLISECONDS; wavelet length
// min(81, max(21, n_ref|1)) — forced odd (#117).
[[nodiscard]] std::vector<float> generate_synthetic_twt(
    const std::vector<float>& reflectivity, const SyntheticTwtOptions& options);

inline constexpr double kDefaultSonicClipMin = 10.0;    // µs/m
inline constexpr double kDefaultSonicClipMax = 1000.0;  // µs/m
inline constexpr double kDefaultWaveletHalfLengthS = 0.064;

struct SyntheticFromLogsOptions {
    double wavelet_freq = 30.0;   // Hz
    double dt_s = 0.002;          // seconds
    double half_length_s = kDefaultWaveletHalfLengthS;
    // (min, max) µs/m clamp before the velocity reciprocal; nullopt
    // disables. NaN survives np.clip (no-op for NaN).
    std::optional<std::pair<double, double>> sonic_clip =
        std::pair{kDefaultSonicClipMin, kDefaultSonicClipMax};
};

// One-call sonic+density → Ricker synthetic: clip → NaN-interpolate →
// reflectivity → ricker(n = (round(2*half/dt)+1)|1) → convolve.
// len(sonic) <= 1 -> {}; all-NaN input stays all-NaN.
[[nodiscard]] std::vector<float> synthetic_from_logs(
    const std::vector<double>& sonic, const std::vector<double>& density,
    const SyntheticFromLogsOptions& options = {});

}  // namespace pwb::viz::well_tie
