// joint_types.cpp — TimeDepthTable + OrthogonalSliceState (models.py).
#include "pwb/geo3d_viz/joint/joint_types.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::geo3d_viz::joint {

namespace {
double interp_sorted(const std::vector<double>& xp,
                     const std::vector<double>& fp, double x) {
    // xp strictly increasing (validated); np.interp parity, caller masks
    // the outside range to NaN.
    if (x <= xp.front()) return fp.front();
    if (x >= xp.back()) return fp.back();
    const auto it = std::upper_bound(xp.begin(), xp.end(), x);
    const std::size_t hi = static_cast<std::size_t>(it - xp.begin());
    const std::size_t lo = hi - 1;
    const double t = (x - xp[lo]) / (xp[hi] - xp[lo]);
    return fp[lo] + t * (fp[hi] - fp[lo]);
}
}  // namespace

TimeDepthTable::TimeDepthTable(std::string well_name,
                               std::vector<double> time_ms,
                               std::vector<double> md_m)
    : well_name_(std::move(well_name)),
      time_ms_(std::move(time_ms)),
      md_m_(std::move(md_m)) {
    if (time_ms_.size() != md_m_.size()) {
        throw std::invalid_argument(
            "time_ms and md_m must have the same length");
    }
    if (time_ms_.size() < 2) {
        throw std::invalid_argument(
            "TimeDepthTable requires at least two samples");
    }
    for (double t : time_ms_) {
        if (!std::isfinite(t)) {
            throw std::invalid_argument(
                "TimeDepthTable[" + well_name_ + "]: non-finite time/MD "
                "samples");
        }
    }
    for (double m : md_m_) {
        if (!std::isfinite(m)) {
            throw std::invalid_argument(
                "TimeDepthTable[" + well_name_ + "]: non-finite time/MD "
                "samples");
        }
    }
    // np.interp requires strictly increasing xp; both directions are
    // used, so both axes must be monotonic (physical T-D data always is).
    for (std::size_t i = 1; i < md_m_.size(); ++i) {
        if (md_m_[i] <= md_m_[i - 1]) {
            throw std::invalid_argument(
                "TimeDepthTable[" + well_name_ +
                "]: md_m must be strictly increasing");
        }
    }
    for (std::size_t i = 1; i < time_ms_.size(); ++i) {
        if (time_ms_[i] <= time_ms_[i - 1]) {
            throw std::invalid_argument(
                "TimeDepthTable[" + well_name_ +
                "]: time_ms must be strictly increasing");
        }
    }
}

double TimeDepthTable::interp(const std::vector<double>& xp,
                              const std::vector<double>& fp,
                              double x) const {
    // V6 §8: NaN outside the calibrated range — the old edge-value clamp
    // fabricated a constant tail; callers must treat NaN as "not
    // calibrated here" (truncate/skip), never as a number.
    if (x < xp.front() || x > xp.back()) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    return interp_sorted(xp, fp, x);
}

double TimeDepthTable::md_to_time_ms(double md) const {
    return interp(md_m_, time_ms_, md);
}

double TimeDepthTable::time_ms_to_md(double twt) const {
    return interp(time_ms_, md_m_, twt);
}

std::vector<double> TimeDepthTable::md_to_time_ms(
    const std::vector<double>& md) const {
    std::vector<double> out;
    out.reserve(md.size());
    for (double m : md) out.push_back(md_to_time_ms(m));
    return out;
}

std::vector<double> TimeDepthTable::time_ms_to_md(
    const std::vector<double>& twt) const {
    std::vector<double> out;
    out.reserve(twt.size());
    for (double t : twt) out.push_back(time_ms_to_md(t));
    return out;
}

OrthogonalSliceState::OrthogonalSliceState(
    std::optional<std::int64_t> il, std::optional<std::int64_t> xl,
    std::vector<TimeSliceState> slices, std::optional<double> active_ms,
    double opacity)
    : inline_index(il),
      crossline_index(xl),
      time_slices(std::move(slices)),
      active_time_ms(active_ms),
      time_opacity(opacity) {
    if (time_slices.size() > kMaxTimeSlices) {
        throw std::invalid_argument("time_slices cannot contain more than " +
                                    std::to_string(kMaxTimeSlices) +
                                    " items");
    }
    if (!(time_opacity >= 0.0 && time_opacity <= 1.0)) {
        throw std::invalid_argument("time_opacity must be between 0 and 1");
    }
    if (active_time_ms.has_value() && !std::isfinite(*active_time_ms)) {
        throw std::invalid_argument("active_time_ms must be finite");
    }
}

}  // namespace pwb::geo3d_viz::joint
