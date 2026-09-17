#pragma once

// pwb::mapping — nearest-neighbor class grid, a faithful C++ port of
// paleo_workbench/mapping/well_prediction_surface.nearest_neighbor_class_grid
// (full-conversion plan M6). Frozen against
// tools/oracle/generate_class_grid_fixtures.py:
//   * first-seen facies → int16 class ids (insertion order);
//   * nx = ny = max(2, grid_n); np.linspace endpoint=True;
//   * numpy.argmin on squared Euclidean distance (first-min / lowest index
//     on ties);
//   * optional clip via point_in_ring_scalar_inclusive (on-edge True) —
//     NOT the interpolator even-odd domain mask.
// Qt-free, Python-free, numpy-free.

#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/interpolator.hpp>  // linspace

#include <array>
#include <string>
#include <vector>

namespace pwb::mapping {

struct FaciesPoint {
    double x = 0.0;
    double y = 0.0;
    std::string facies;
};

struct ClassGrid {
    std::vector<double> grid_x;
    std::vector<double> grid_y;
    std::vector<float> grid_z;  // row-major, class id as float32; NaN if clipped
    std::vector<std::string> facies_names;
};

// Inclusive even-odd with on-edge test (geometry_planar,
// epsilon default 1e-9). Public so the oracle can pin the even-odd
// disagreement on a ring edge.
bool point_in_ring_inclusive(double x, double y, const std::vector<Point>& ring,
                             double epsilon = 1e-9);

// Raises std::invalid_argument with the Python message when points is empty.
ClassGrid nearest_neighbor_class_grid(
    const std::vector<FaciesPoint>& points,
    const std::array<double, 4>& extent,
    int grid_n = 80,
    const std::vector<Point>& clip_ring = {});

}  // namespace pwb::mapping
