#pragma once

// pwb::mapping — directional-trend interpolation kernel, a faithful C++
// port of
//   geo-viz-engine/packages/geoviz_plots/geoviz_plots/interpolation/
//     directional.py
// (anisotropic Gaussian kernel weights over the sample set; nearest-sample
// fallback when the weight total underflows; chunked cell evaluation as a
// bounded-memory bound).
//
// Numerical contract (Python semantics kept exactly):
//   * azimuth_to_rad — math.radians(fmod-positive azimuth % 360.0);
//   * rotate_to_uv — u = dx*sin + dy*cos, v = dx*cos - dy*sin;
//   * _scaled_axes — dimensionless a/b scaled by the mean finite pairwise
//     sample distance (issue #112), computed in 1024-row blocks with the
//     pair counted once (col > row); summation order and block boundaries
//     preserved (the block partial sums feed the total in block order);
//   * directional_weights — exp(-(d/a)^2) * q * b_i, non-finite → 0,
//     clamped >= 0;
//   * _sample_arrays — equal-length + q/b_i length validation, then the
//     finite(x,y,z) index mask applied to all five arrays;
//   * weight sums use numpy-compatible pairwise summation (np.sum over
//     contiguous float64 rows) so cell values track the oracle to ~ulp;
//   * cells whose weight total is <= 1e-15 take the nearest sample's value
//     (np.argmin = lowest index on ties).
//
// Deliberate simplification vs numpy: np.hypot / np.exp ride libm — ulp
// differences vs the platform numpy builds are possible.
// Qt-free, Python-free, numpy-free.

#include <cstddef>
#include <vector>

namespace pwb::mapping {

// math.radians(float(azimuth_deg) % 360.0) with Python's sign convention
// for % (result takes the divisor's sign; here normalized into [0, 360)).
double azimuth_to_rad(double azimuth_deg);

// (u, v) for a single offset; the elementwise numpy pair.
std::pair<double, double> rotate_to_uv(double dx, double dy,
                                       double azimuth_deg);

// _positive_axis: raises std::invalid_argument("<name> must be a finite
// positive value") when not finite or <= 0; returns the value otherwise.
double positive_axis(double value, const char* name);

// _mean_pairwise_distance: mean finite pairwise Euclidean distance among
// the samples (each pair once), accumulated in 1024-row blocks exactly as
// the Python loop. 0.0 for < 2 points or when no finite pair exists.
double mean_pairwise_distance(const std::vector<double>& xs,
                              const std::vector<double>& ys);

// _scaled_axes: a/b scaled by the mean pairwise sample span; degenerate
// spans keep the raw axes.
std::pair<double, double> scaled_axes(double a, double b,
                                      const std::vector<double>& xs,
                                      const std::vector<double>& ys);

// directional_weights for one distance / q / b_i triple (scalar kernel
// core): exp(-d^2) * q * b_i, non-finite -> 0, clamped >= 0.
double directional_weight(double distance, double q, double b_i);

// _sample_arrays result: finite-masked x/y/z plus q and b_i (all ones when
// the caller passes none). Length mismatches raise std::invalid_argument
// with the Python texts.
struct DirectionalSamples {
    std::vector<double> x;
    std::vector<double> y;
    std::vector<double> z;
    std::vector<double> q;
    std::vector<double> b_i;
};

DirectionalSamples directional_sample_arrays(
    const std::vector<double>& xs, const std::vector<double>& ys,
    const std::vector<double>& zs, const std::vector<double>* q,
    const std::vector<double>* b_i);

// trend_value_at: single-location directional trend. NaN when the finite
// sample set is empty; nearest-sample fallback when the weight total is
// <= 1e-15.
double trend_value_at(double x0, double y0, const std::vector<double>& xs,
                      const std::vector<double>& ys,
                      const std::vector<double>& zs, double azimuth_deg = 0.0,
                      double a = 1.0, double b = 0.4,
                      const std::vector<double>* q = nullptr,
                      const std::vector<double>* b_i = nullptr);

// directional_trend_grid: row-major (len(grid_y) x len(grid_x)) grid;
// NaN cells when the sample set is empty or an axis is empty. The
// 16384-cell chunk bound is kept (memory bound only — values are
// chunk-order independent by construction).
std::vector<double> directional_trend_grid(
    const std::vector<double>& xs, const std::vector<double>& ys,
    const std::vector<double>& zs, const std::vector<double>& grid_x,
    const std::vector<double>& grid_y, double azimuth_deg = 0.0,
    double a = 1.0, double b = 0.4, const std::vector<double>* q = nullptr,
    const std::vector<double>* b_i = nullptr,
    int max_cells_per_chunk = 16384);

}  // namespace pwb::mapping
