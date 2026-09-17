#pragma once

// pwb::mapping — spatial interpolation kernel, a faithful C++ port of
// paleo_workbench/mapping/geological_pipeline/interpolator.py (full-conversion
// plan M6, second slice). Numerical behavior is frozen against the Python
// implementation via committed oracle fixtures
// (tools/oracle/generate_interpolator_fixtures.py):
//   * Dataset extent padding (10% of span, min 0.01; collinear axis → 0.05)
//     and validate() messages, math.isclose defaults (rel_tol=1e-9);
//   * np.linspace endpoint=True float64 axes, meshgrid 'xy' / C-order ravel;
//   * IDW: power weighting on max(dist, 1e-12), exact-hit last-wins, NaN
//     nodata when min_neighbors is unmet; all-neighbour path when k==N and
//     no radius; otherwise brute-force kNN with the same contract as
//     scipy.spatial.cKDTree (unique-distance neighbour sets);
//   * Ordinary Kriging numpy-grid-OLS fallback (_pure_numpy_kriging):
//     coincident-sample mean merge, empirical variogram + closed-form
//     partial sill, spherical/exponential/gaussian models, augmented OK
//     solve with scaled-ridge fallback. The geoviz WLS engine is a
//     different estimator and is NOT this kernel.
//   * User-boundary even-odd ray-cast domain mask (geometry_planar).
//   * D5 distance policy: interpolate_factor annotates the result via
//     resolve_distance_policy (dataset CRS = InterpolateOptions.crs).
// Qt-free, Python-free, numpy-free, scipy-free.

#include <pwb/mapping/contouring.hpp>

#include <array>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace pwb::mapping {

struct SamplePoint {
    double x = 0.0;
    double y = 0.0;
    double value = 0.0;
    std::string qc_flag = "ok";
};

struct InterpolateOptions {
    std::string method = "idw";  // idw | kriging | ordinary_kriging | ok
    int grid_n = 50;
    double power = 2.0;
    std::optional<int> max_neighbors;
    std::optional<double> search_radius;
    int min_neighbors = 1;
    std::string variogram_model = "spherical";
    std::vector<Point> boundary;  // empty = no domain mask
    // Dataset CRS (Python GeologicalFactorDataset.crs). Empty → undeclared;
    // interpolate_factor passes it to resolve_distance_policy as None.
    std::string crs;
    std::string distance_policy = "planar";
};

struct GridStatistics {
    double min = std::numeric_limits<double>::quiet_NaN();
    double max = std::numeric_limits<double>::quiet_NaN();
    double mean = std::numeric_limits<double>::quiet_NaN();
    double std = std::numeric_limits<double>::quiet_NaN();
    int valid_count = 0;
    int total_count = 0;
};

struct FactorGrid {
    std::vector<double> grid_x;
    std::vector<double> grid_y;
    std::vector<float> grid_z;        // row-major, |y| * |x|, NaN = nodata
    std::vector<float> variance_grid; // empty for IDW; else same layout
    std::string algorithm_id;
    std::string method;
    std::string model;
    std::string variogram_fit;
    double power = 2.0;
    double range = 0.0;
    double sill = 0.0;
    double nugget = 0.0;
    int grid_n = 0;
    int n_samples = 0;
    int duplicates_merged = 0;
    int variogram_bins = 0;
    int domain_masked_cells = 0;
    int min_neighbors = 1;
    std::optional<int> max_neighbors;
    std::optional<double> search_radius;
    std::string distance_policy;
    std::string distance_policy_annotation;
    GridStatistics statistics;
};

// Finite-cell stats in float64 (numpy mean/std ddof=0). All-nodata → NaN
// min/max/mean/std, valid_count=0, total_count=size.
GridStatistics grid_statistics(const std::vector<float>& grid_z);

// numpy.linspace(start, stop, num, dtype=float64, endpoint=True).
std::vector<double> linspace(double start, double stop, int num);

// GeologicalFactorDataset.extent — (xmin, ymin, xmax, ymax) of ALL points
// (invalid QC included). Empty → (0, 0, 1, 1).
std::array<double, 4> dataset_extent(const std::vector<SamplePoint>& points);

// Points kept by GeologicalFactorDataset.valid_points.
std::vector<SamplePoint> valid_points(const std::vector<SamplePoint>& points);

// GeologicalFactorDataset.validate() on the valid subset.
std::vector<std::string> validate_dataset(
    const std::vector<SamplePoint>& points);

// Coincident-sample mean merge (kriging singular-matrix guard).
struct DedupResult {
    std::vector<double> x;
    std::vector<double> y;
    std::vector<double> z;
    int duplicates = 0;
};
DedupResult deduplicate_samples(const std::vector<double>& x,
                                const std::vector<double>& y,
                                const std::vector<double>& z,
                                double tol = 1e-9);

// Standardized two-parameter semivariance (effective range r).
std::vector<double> model_semivariance(const std::vector<double>& h,
                                       double nugget, double psill, double r,
                                       const std::string& model);

// Top-level dispatcher. Raises std::invalid_argument with the Python
// validate() joined message when the sample set is unusable.
FactorGrid interpolate_factor(const std::vector<SamplePoint>& points,
                              const InterpolateOptions& options);

}  // namespace pwb::mapping
