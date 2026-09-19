#pragma once

// VIZ-B — well-seismic calibration: time-depth conversion and alignment.
// Verbatim port of geoviz_well_tie/calibration.py. All interpolation is
// np.interp semantics: piecewise-linear over ascending anchors, values
// outside the table clamp to the ENDPOINT value (never extrapolate).
// Deliberately NOT the WLE TimeDepthRelationship (strictly-monotonic +
// linear-slope extrapolation) — different contract, see scope.md §2.2.

#include <stdexcept>
#include <vector>

namespace pwb::viz::well_tie {

class WellTieCalibration {
  public:
    // Throws std::invalid_argument on length mismatch. A strictly
    // descending depths array (merged LAS exports) is internally reversed
    // (#117). Ascending order is canonical; arbitrary inner disorder is
    // caller-owned (np.interp would produce garbage too).
    WellTieCalibration(std::vector<double> depths_m,
                       std::vector<double> twt_ms);

    [[nodiscard]] const std::vector<double>& depths() const {
        return depths_;
    }
    [[nodiscard]] const std::vector<double>& twt() const { return twt_; }

    // np.interp(depth, depths, twt) — clamped at both ends; NaN in -> NaN.
    [[nodiscard]] double depth_to_twt(double depth) const;
    // np.interp(twt, twt, depths) — same semantics on the inverse axis.
    [[nodiscard]] double twt_to_depth(double twt) const;

    // Resample a log (sampled at depths()) onto a regular TWT grid
    // arange(t0_ms, twt[-1] + dt_ms, dt_ms) via depth↔twt round trip.
    // Returns float32-amplitude values (double storage keeps NaN parity).
    [[nodiscard]] std::vector<double> resample_to_twt(
        const std::vector<double>& log_values, double dt_ms,
        double t0_ms = 0.0) const;

    // Integrate sonic (µs/m) into a TWT table: non-finite depth/sonic
    // sample pairs are masked first (#117), a descending depth array is
    // reversed, then trapezoidal OWT: twt[i] = 2 * cumsum(dz * mean(sonic))
    // / 1000 (µs → ms, one-way → two-way). Throws on length mismatch or
    // fewer than two finite samples.
    [[nodiscard]] static WellTieCalibration from_sonic(
        const std::vector<double>& depths_m,
        const std::vector<double>& sonic_us_m);

  private:
    std::vector<double> depths_;
    std::vector<double> twt_;
};

// Resample trace values from an irregular TWT grid onto the seismic
// volume's regular grid i*dt_ms + t0_ms (i = 0..n_samples-1). Values
// OUTSIDE the source range are ZERO-filled (left=0, right=0 — different
// from the clamp semantics above). Returns float32-amplitude values.
[[nodiscard]] std::vector<double> resample_to_seismic_grid(
    const std::vector<double>& values, const std::vector<double>& src_twt,
    double dt_ms, double t0_ms, int n_samples);

// Bulk depth offset; returns a new array.
[[nodiscard]] std::vector<double> shift_depths(
    const std::vector<double>& depths, double depth_shift);

}  // namespace pwb::viz::well_tie
