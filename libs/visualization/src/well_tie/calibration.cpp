// PWB-V14-DATA-LINEAGE: std::to_string / std::invalid_argument
// were used without their headers (g++ pulled them in transitively).
#include <stdexcept>
#include <string>
#include <pwb/viz/well_tie/calibration.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::viz::well_tie {

namespace {

// np.interp(x, xp, fp) for a scalar x over ASCENDING xp: linear inside,
// clamp to fp.front()/fp.back() outside, NaN x -> NaN. Assumes xp size
// equals fp size and is non-empty.
double np_interp_scalar(double x, const std::vector<double>& xp,
                        const std::vector<double>& fp) {
    if (std::isnan(x)) return x;
    if (x <= xp.front()) return fp.front();
    if (x >= xp.back()) return fp.back();
    // Binary search for the bracketing interval.
    const auto it =
        std::lower_bound(xp.begin(), xp.end(), x);
    const std::size_t hi = static_cast<std::size_t>(it - xp.begin());
    const std::size_t lo = hi - 1;
    if (xp[hi] == xp[lo]) return fp[lo];
    const double t = (x - xp[lo]) / (xp[hi] - xp[lo]);
    return fp[lo] + t * (fp[hi] - fp[lo]);
}

// numpy astype(float32) — round the double to nearest float precision.
float to_float32(double v) { return static_cast<float>(v); }

}  // namespace

WellTieCalibration::WellTieCalibration(std::vector<double> depths_m,
                                       std::vector<double> twt_ms)
    : depths_(std::move(depths_m)), twt_(std::move(twt_ms)) {
    if (depths_.size() != twt_.size()) {
        throw std::invalid_argument(
            "depths_m and twt_ms must have same length, got " +
            std::to_string(depths_.size()) + " and " +
            std::to_string(twt_.size()));
    }
    if (depths_.size() > 1 && depths_.front() > depths_.back()) {
        std::reverse(depths_.begin(), depths_.end());
        std::reverse(twt_.begin(), twt_.end());
    }
}

double WellTieCalibration::depth_to_twt(double depth) const {
    return np_interp_scalar(depth, depths_, twt_);
}

double WellTieCalibration::twt_to_depth(double twt) const {
    return np_interp_scalar(twt, twt_, depths_);
}

std::vector<double> WellTieCalibration::resample_to_twt(
    const std::vector<double>& log_values, double dt_ms,
    double t0_ms) const {
    if (twt_.empty()) return {};
    const double t_max = twt_.back();
    // np.arange(t0, t_max + dt, dt): count = ceil((stop-start)/step).
    const double span = (t_max + dt_ms) - t0_ms;
    const std::size_t count =
        span <= 0.0
            ? 0
            : static_cast<std::size_t>(std::ceil(span / dt_ms - 1e-12));
    std::vector<double> out;
    out.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        const double twt_out = t0_ms + static_cast<double>(i) * dt_ms;
        const double depth = np_interp_scalar(twt_out, twt_, depths_);
        // Log values are sampled at depths_; same ascending table.
        out.push_back(to_float32(np_interp_scalar(depth, depths_, log_values)));
    }
    return out;
}

WellTieCalibration WellTieCalibration::from_sonic(
    const std::vector<double>& depths_m,
    const std::vector<double>& sonic_us_m) {
    if (depths_m.size() != sonic_us_m.size()) {
        throw std::invalid_argument(
            "depths_m and sonic_us_m must have same length, got " +
            std::to_string(depths_m.size()) + " and " +
            std::to_string(sonic_us_m.size()));
    }
    std::vector<double> depths;
    std::vector<double> sonic;
    depths.reserve(depths_m.size());
    sonic.reserve(sonic_us_m.size());
    for (std::size_t i = 0; i < depths_m.size(); ++i) {
        if (std::isfinite(depths_m[i]) && std::isfinite(sonic_us_m[i])) {
            depths.push_back(depths_m[i]);
            sonic.push_back(sonic_us_m[i]);
        }
    }
    if (depths.size() < 2) {
        throw std::invalid_argument(
            "from_sonic needs at least two finite depth/sonic samples, got " +
            std::to_string(depths.size()));
    }
    if (depths.front() > depths.back()) {
        std::reverse(depths.begin(), depths.end());
        std::reverse(sonic.begin(), sonic.end());
    }
    const std::size_t n = depths.size();
    std::vector<double> twt(n, 0.0);
    double cum_us = 0.0;
    for (std::size_t i = 1; i < n; ++i) {
        const double dz = depths[i] - depths[i - 1];
        const double owt_us =
            dz * (sonic[i - 1] + sonic[i]) / 2.0;
        cum_us += owt_us;
        twt[i] = 2.0 * cum_us / 1000.0;
    }
    return WellTieCalibration(std::move(depths), std::move(twt));
}

std::vector<double> resample_to_seismic_grid(
    const std::vector<double>& values, const std::vector<double>& src_twt,
    double dt_ms, double t0_ms, int n_samples) {
    if (src_twt.empty() || values.empty()) {
        return std::vector<double>(static_cast<std::size_t>(n_samples), 0.0);
    }
    // Python relies on np.interp's ValueError for mismatched sample arrays;
    // without this guard the bracketing below indexes values out of bounds.
    if (values.size() != src_twt.size()) {
        throw std::invalid_argument(
            "values and src_twt must have same length, got " +
            std::to_string(values.size()) + " and " +
            std::to_string(src_twt.size()));
    }
    // np.interp with left=0, right=0 — manual bracketing (src_twt may be
    // irregular but must be ascending; np.interp has the same requirement).
    std::vector<double> out;
    out.reserve(static_cast<std::size_t>(n_samples));
    for (int i = 0; i < n_samples; ++i) {
        const double target = static_cast<double>(i) * dt_ms + t0_ms;
        double value = 0.0;
        if (target < src_twt.front() || target > src_twt.back()) {
            value = 0.0;  // left/right zero-fill
        } else if (src_twt.size() == 1) {
            value = values.front();
        } else {
            const auto it =
                std::lower_bound(src_twt.begin(), src_twt.end(), target);
            const std::size_t hi =
                static_cast<std::size_t>(it - src_twt.begin());
            if (hi == 0) {
                value = values.front();
            } else {
                const std::size_t lo = hi - 1;
                if (src_twt[hi] == src_twt[lo]) {
                    value = values[lo];
                } else {
                    const double t =
                        (target - src_twt[lo]) / (src_twt[hi] - src_twt[lo]);
                    value = values[lo] + t * (values[hi] - values[lo]);
                }
            }
        }
        out.push_back(to_float32(value));
    }
    return out;
}

std::vector<double> shift_depths(const std::vector<double>& depths,
                                 double depth_shift) {
    std::vector<double> out;
    out.reserve(depths.size());
    for (double v : depths) out.push_back(v + depth_shift);
    return out;
}

}  // namespace pwb::viz::well_tie
