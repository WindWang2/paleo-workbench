#include <pwb/viz/well_tie/synthetic.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

#include <pwb/viz/well_tie/wavelet.hpp>

namespace pwb::viz::well_tie {

std::vector<float> compute_reflectivity(const std::vector<double>& sonic,
                                        const std::vector<double>& density) {
    if (sonic.size() != density.size()) {
        throw std::invalid_argument(
            "compute_reflectivity: sonic and density must have the same "
            "length");
    }
    const std::size_t n = sonic.size();
    if (n < 2) return {};
    std::vector<double> impedance(n);
    for (std::size_t i = 0; i < n; ++i) {
        impedance[i] = (1.0e6 / sonic[i]) * density[i];
    }
    std::vector<float> reflectivity(n - 1);
    for (std::size_t i = 0; i + 1 < n; ++i) {
        const double denom = impedance[i] + impedance[i + 1];
        // np.where(|denom| < 1e-12, 1e-12, denom) — unconditional positive
        // replacement (NOT sign-preserving).
        const double guarded = std::abs(denom) < 1e-12 ? 1e-12 : denom;
        reflectivity[i] = static_cast<float>(
            (impedance[i + 1] - impedance[i]) / guarded);
    }
    return reflectivity;
}

std::vector<float> generate_synthetic(const std::vector<float>& reflectivity,
                                      const std::vector<float>& wavelet) {
    const std::size_t n_ref = reflectivity.size();
    if (n_ref == 0) return {};
    const std::size_t m = wavelet.size();
    // np.convolve(..., "same") centre offset; both Python branches (direct
    // and pad-when-wavelet-longer) reduce to this single expression.
    const std::size_t offset = (m - 1) / 2;
    std::vector<float> synthetic(n_ref);
    for (std::size_t i = 0; i < n_ref; ++i) {
        double acc = 0.0;
        for (std::size_t j = 0; j < n_ref; ++j) {
            const std::ptrdiff_t k =
                static_cast<std::ptrdiff_t>(offset + i - j);
            if (k >= 0 && k < static_cast<std::ptrdiff_t>(m)) {
                acc += static_cast<double>(reflectivity[j]) *
                       static_cast<double>(wavelet[static_cast<std::size_t>(k)]);
            }
        }
        synthetic[i] = static_cast<float>(acc);
    }
    return synthetic;
}

std::vector<float> generate_synthetic_twt(
    const std::vector<float>& reflectivity,
    const SyntheticTwtOptions& options) {
    const double dt_sec = options.dt_ms / 1000.0;
    const long long n_ref = static_cast<long long>(reflectivity.size());
    // min(81, max(21, n_ref | 1)) — forced odd so 'same' convolution stays
    // zero-phase (#117).
    const long long n_wavelet =
        std::min<long long>(81, std::max<long long>(21, n_ref | 1));
    std::vector<float> w;
    if (options.wavelet_type == "ormsby") {
        w = ormsby_wavelet(static_cast<int>(n_wavelet), dt_sec, options.f1,
                           options.f2, options.f3, options.f4);
    } else {
        w = ricker_wavelet(static_cast<int>(n_wavelet), dt_sec,
                           options.peak_freq);
    }
    return generate_synthetic(reflectivity, w);
}

namespace {

// Python 3 round() — round-half-to-EVEN (banker's rounding), not
// std::llround's half-away-from-zero.
long long py_round(double value) {
    const double floor_v = std::floor(value);
    const double diff = value - floor_v;
    if (diff > 0.5) return static_cast<long long>(floor_v) + 1;
    if (diff < 0.5) return static_cast<long long>(floor_v);
    // Exactly .5: to even.
    const long long f = static_cast<long long>(floor_v);
    return (f % 2 == 0) ? f : f + 1;
}

// Fill NaN gaps by linear interpolation over the sample index; edge NaNs
// take the nearest finite value; all-NaN returns unchanged (#117).
std::vector<double> interpolate_nan(const std::vector<double>& values) {
    const std::size_t n = values.size();
    std::vector<bool> good(n, false);
    bool any_good = false;
    bool all_good = true;
    for (std::size_t i = 0; i < n; ++i) {
        good[i] = std::isfinite(values[i]);
        any_good = any_good || good[i];
        all_good = all_good && good[i];
    }
    if (all_good || !any_good) return values;
    std::vector<double> out(n);
    // np.interp over index positions of the good samples (clamp at edges).
    std::size_t prev = 0;
    bool have_prev = false;
    for (std::size_t i = 0; i < n; ++i) {
        if (good[i]) {
            out[i] = values[i];
            prev = i;
            have_prev = true;
            continue;
        }
        // Find next good index.
        std::size_t next = i;
        while (next < n && !good[next]) ++next;
        if (!have_prev) {
            // Leading NaN run: nearest finite is the next good one (np.interp
            // clamps to fp[0]); fill once next is known — handled below.
            out[i] = values[next < n ? next : i];
            continue;
        }
        if (next >= n) {
            out[i] = values[prev];  // trailing run clamps to last good
            continue;
        }
        const double t = static_cast<double>(i - prev) /
                         static_cast<double>(next - prev);
        out[i] = values[prev] + t * (values[next] - values[prev]);
    }
    return out;
}

}  // namespace

std::vector<float> synthetic_from_logs(
    const std::vector<double>& sonic, const std::vector<double>& density,
    const SyntheticFromLogsOptions& options) {
    if (sonic.size() <= 1) return {};

    std::vector<double> s = sonic;
    if (options.sonic_clip) {
        // np.clip keeps NaN as NaN.
        for (double& v : s) {
            if (std::isnan(v)) continue;
            v = std::clamp(v, options.sonic_clip->first,
                           options.sonic_clip->second);
        }
    }
    s = interpolate_nan(s);
    const std::vector<double> d = interpolate_nan(density);

    const std::vector<float> reflectivity = compute_reflectivity(s, d);
    // |1 keeps the aperture odd so 'same'-mode convolution stays zero-phase
    // for any half_length_s/dt_s combination (#117).
    const long long n_wavelet =
        (py_round(2.0 * options.half_length_s / options.dt_s) + 1) | 1;
    const std::vector<float> wavelet = ricker_wavelet(
        static_cast<int>(n_wavelet), options.dt_s, options.wavelet_freq);
    return generate_synthetic(reflectivity, wavelet);
}

}  // namespace pwb::viz::well_tie
