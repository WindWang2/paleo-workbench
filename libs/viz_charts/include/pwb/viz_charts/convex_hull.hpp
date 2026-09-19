// Point-in-polygon ray casting and 2D convex hull — port of
// geoviz_plots/chart/convex_hull.py (SciPy Qhull replaced by a monotone
// chain with the same CCW vertex cycle; see the oracle tolerance notes).
#pragma once

#include <cstddef>
#include <vector>

namespace pwb::viz_charts {

struct Point2 {
    double x = 0.0;
    double y = 0.0;
};

// Ray-casting mask (#506 sign-preserving zero guard: horizontal edges use a
// 1e-30 denominator instead of flipping the sign). Fewer than 3 vertices →
// all-false. XOR accumulates crossings.
std::vector<bool> point_in_polygon_mask(const std::vector<double>& x,
                                        const std::vector<double>& y,
                                        const std::vector<Point2>& poly);

// Hull polygon in CCW order starting at the lexicographically smallest
// point (x, then y). NaN pairs are dropped first. Fewer than 3 finite
// points → the points themselves; degenerate (collinear/duplicate) input →
// lexsorted polyline (Python QhullError branch parity).
std::vector<Point2> compute_convex_hull(const std::vector<double>& x,
                                        const std::vector<double>& y);

}  // namespace pwb::viz_charts
