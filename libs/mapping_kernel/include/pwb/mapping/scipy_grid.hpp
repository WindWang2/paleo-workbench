#pragma once

// pwb::mapping — SciPy-griddata-equivalent interpolation family, a C++
// port of
//   geo-viz-engine/packages/geoviz_plots/geoviz_plots/interpolation/
//     scipy_grid.py
// Backends:
//   "linear"  — Delaunay triangulation + barycentric per-triangle eval
//               (scipy.interpolate.LinearNDInterpolator).
//   "cubic"   — Clough-Tocher piecewise-cubic C1 patches over a Delaunay
//               triangulation with scipy's global least-squares gradient
//               estimation (CloughTocher2DInterpolator, rescale=False).
//   "nearest" — nearest-sample interpolation (NearestNDInterpolator).
//   "rbf"     — scipy.interpolate.Rbf(function="multiquadric", smooth=0)
//               dense solve + evaluation.
//
// Oracle semantics preserved:
//   * NaN-only sample filtering (~np.isnan — inf propagates);
//   * fewer than three filtered samples -> all-NaN grid (any method);
//   * mask_convex_hull: cells outside the 2D convex hull of the filtered
//     samples -> NaN (scipy ConvexHull vertices, boundary inclusive);
//     hull construction failure (collinear sets) skips masking;
//   * triangulation/solve failures (QhullError / LinAlgError equivalents)
//     fall back to "nearest" and report fallback="nearest" +
//     requested_method=<original> (scipy's interp_status contract);
//   * degenerate RBF scaling (zero-extent sample set) raises instead of
//     falling back — the oracle's ZeroDivisionError escapes its handler.
//
// Known bit-parity limits (documented): the internal triangulation is a
// Bowyer-Watson Delaunay rather than Qhull — co-circular/duplicate inputs
// may triangulate differently (mirrored diagonals); the Gauss-Seidel
// neighbour order and libm transcendentals can differ at ~ulp level;
// nearest-tie selection is lowest-index vs cKDTree's unspecified order.

#include <string>
#include <vector>

namespace pwb::mapping {

// geoviz _grid_axes: per-axis np.linspace(min-pad, max+pad, max(2, n)),
// pad = 0.05 * extent (extent 0 -> 1.0). Returns (grid_x, grid_y).
std::pair<std::vector<double>, std::vector<double>> interpolation_grid_axes(
    const std::vector<double>& xs, const std::vector<double>& ys,
    int grid_n);

struct ScipyGridResult {
    // Row-major grid over (grid_y outer, grid_x inner); NaN outside the
    // convex hull when masking applies.
    std::vector<double> grid_z;
    // interp_status semantics: set when the requested backend degraded.
    std::string fallback;          // "nearest" when a fallback ran
    std::string requested_method;  // echoes the requested method on fallback
};

// method: "linear" | "cubic" | "nearest" | "rbf".
// Throws std::invalid_argument for an unknown method; std::runtime_error
// for the RBF zero-extent scaling error (ZeroDivisionError equivalent).
ScipyGridResult interpolate_scipy_grid(
    const std::vector<double>& xs, const std::vector<double>& ys,
    const std::vector<double>& zs, const std::vector<double>& grid_x,
    const std::vector<double>& grid_y, const std::string& method,
    bool mask_convex_hull = true);

}  // namespace pwb::mapping
