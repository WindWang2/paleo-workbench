#pragma once

// pwb::mapping — raster polygonization kernel, a faithful C++ port of
// paleo_workbench/mapping.geological_pipeline.polygonization (full-conversion
// plan M6, third slice). Numerical behavior is frozen against the Python
// implementation via committed oracle fixtures
// (tools/oracle/generate_polygonization_fixtures.py):
//   * shoelace / signed area (open last-to-first omitted; rings are closed)
//     and area-centroid with math.isclose(area2, 0, abs_tol=1e-12) fallback
//     to the first vertex;
//   * axis-aligned collinear simplify (isclose abs_tol=1e-9, same-direction
//     dx1*dx2>0 / dy1*dy2>0 only);
//   * cell-edge tracing with Python-dict insertion order + list-append
//     adjacency; walk starts in segment enumerate order; available[0] is
//     the first unused neighbor. NOT a std::map walk;
//   * pt_key = round to 6 decimals (same as contouring);
//   * closed-loop test len>=4 and isclose abs_tol=1e-5; signed area >0
//     exterior (CCW), <0 hole, ~0 skip (abs_tol=1e-12);
//   * hole assignment: bbox prefilter, even-odd vertex majority vote,
//     votes > best_votes (strict, smallest-area exterior wins ties);
//     unmatched holes reversed and promoted (holes_promoted_to_exterior);
//   * facies class_grid int16: zeros, then class_grid[z >= th] =
//     min(idx+1, n_names-1); default thresholds 0.333/0.666 of span.
//
// Shapely repair_invalid_geometry (make_valid / orient) and clip-to-ring
// are NOT ported. The oracle monkeypatches repair to identity.
// Qt-free, Python-free, numpy-free.

#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/interpolator.hpp>

#include <cstdint>
#include <optional>
#include <utility>
#include <vector>

namespace pwb::mapping {

using Ring = std::vector<Point>;

struct Polygon {
    Ring exterior;
    std::vector<Ring> holes;
};

struct PolygonizeQc {
    int holes_promoted_to_exterior = 0;
};

struct FactorPolygonizeResult {
    double level = 0.0;
    std::vector<Polygon> polygons;
    PolygonizeQc qc;
};

double shoelace_area(const Ring& ring);
double signed_area(const Ring& ring);
Point ring_centroid(const Ring& ring);
Ring simplify_collinear_ring(const Ring& ring);

// Python generate_facies_polygon_layer default: equal vmin/vmax → [vmin],
// else vmin + span*{0.333, 0.666}. math.isclose defaults on equality.
std::vector<double> default_class_thresholds(double vmin, double vmax);

// sorted(set(float(t) for t in thresholds))
std::vector<double> unique_sorted_thresholds(const std::vector<double>& thresholds);

// n_classes == len(facies_names). Thresholds applied in given order.
std::vector<std::int16_t> classify_grid(const Grid& grid,
                                        const std::vector<double>& thresholds,
                                        int n_classes);

std::pair<std::vector<Polygon>, PolygonizeQc>
polygonize_class(const Grid& grid,
                 const std::vector<std::int16_t>& class_grid,
                 int target_class);

std::vector<Polygon> filter_small_polygons(const std::vector<Polygon>& geoms,
                                           double min_area);

// Median of finite cells when level is omitted (numpy.median even-n mean).
FactorPolygonizeResult polygonize_factor_grid(
    const Grid& grid, std::optional<double> level = std::nullopt);

FactorPolygonizeResult polygonize_factor_grid(
    const FactorGrid& grid, std::optional<double> level = std::nullopt);

}  // namespace pwb::mapping
