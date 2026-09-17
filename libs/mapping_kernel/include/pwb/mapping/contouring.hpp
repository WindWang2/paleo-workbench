#pragma once

// pwb::mapping — contour extraction kernel, a faithful C++ port of
// paleo_workbench/mapping/geological_pipeline/contouring.py (the
// full-conversion plan's M6 first slice). Numerical behavior is frozen
// against the Python implementation via committed oracle fixtures
// (tools/oracle/generate_contour_fixtures.py):
//   * Marching Squares 16-case with linear edge interpolation and
//     center-average saddle disambiguation, NaN cells skipped;
//   * segment stitching whose traversal order reproduces Python dict
//     insertion order (first-inserted open endpoint starts, first-inserted
//     unused neighbor continues) — NOT a hash-map walk;
//   * Ramer-Douglas-Peucker and Chaikin smoothing bit-for-bit compatible;
//   * "nice" level ladder and linear-interpolation percentiles
//     (np.nanpercentile 'linear' semantics);
//   * math.isclose defaults (rel_tol=1e-9) and round(v, n) half-even.
// Qt-free, Python-free, numpy-free.

#include <array>
#include <cmath>
#include <optional>
#include <vector>

namespace pwb::mapping {

struct Grid {
    // z stored row-major: z[i * w + j], i = y index, j = x index.
    std::size_t w = 0;   // columns (x)
    std::size_t h = 0;   // rows (y)
    std::vector<double> grid_x;   // size w
    std::vector<double> grid_y;   // size h
    std::vector<double> grid_z;   // size w*h, NaN = nodata
};

using Point = std::array<double, 2>;
using Polyline = std::vector<Point>;

// Pleasant round levels within [vmin, vmax] (Python: nice ladder).
std::vector<double> nice_contour_levels(double vmin, double vmax,
                                        int target_count = 7);

// Linear-interpolation percentiles over finite cells (np.nanpercentile
// 'linear'), deduplicated via round(v, 6) and sorted.
std::vector<double> quantile_contour_levels(
    const Grid& grid,
    const std::vector<double>& quantiles = {0.1, 0.25, 0.5, 0.75, 0.9});

double polyline_length(const Polyline& points);

Polyline douglas_peucker(const Polyline& points, double tolerance);

Polyline chaikin_smooth(const Polyline& points, int iterations = 1);

// Full extraction: marching squares at one level, then stitch (+
// optional simplify/smooth). Public because the Python module exposes the
// same pieces for reuse.
std::vector<Polyline> marching_squares_contours(const Grid& grid,
                                                double level,
                                                double simplify_tol = 0.0,
                                                int smooth_iterations = 0);

// Python round(v, digits) — half-to-even at the decimal digit.
double round_to(double value, int digits);

// Python math.isclose defaults (rel_tol=1e-9, abs_tol=0).
bool is_close(double a, double b);

}  // namespace pwb::mapping
