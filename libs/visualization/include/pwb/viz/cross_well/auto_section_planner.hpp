#pragma once

// VIZ-B — geometric planning for automatic well-section ordering.
// Port of geoviz_cross_well/auto_section_planner.py (numpy). Determinism
// note: numpy's SVD eigenvector sign is implementation-defined; the C++
// port fixes v1's sign (largest-|component| positive) and breaks
// projection ties by original index — recorded as a deliberate,
// documented hardening of the same ordering contract (scope.md §2).

#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::viz::cross_well {

struct WellCoord {
    std::string name;
    double lng = 0.0;
    double lat = 0.0;
};

// Thrown by the planners on missing coordinates / unknown method
// (Python ValueError parity).
class PlannerError : public std::runtime_error {
  public:
    explicit PlannerError(const std::string& message)
        : std::runtime_error(message) {}
};

enum class SectionPlanMethod { kPca, kNearestNeighbor };

SectionPlanMethod parse_plan_method(const std::string& method);

// <= 2 wells: identity order. Otherwise: centroid-center the (lng, lat)
// matrix, take the first principal axis via one-sided Jacobi SVD (2x2),
// fix the axis sign, project, stable-sort by (projection, index).
// Returns the permutation of indices (caller maps back to its objects).
[[nodiscard]] std::vector<std::size_t> plan_section_pca(
    const std::vector<WellCoord>& wells);

// PCA first to locate one extreme endpoint, then greedy nearest-
// neighbour (squared Euclidean on lng/lat, ties broken by first-seen
// order — Python dict iteration order parity). Same-well-name collapse
// is the caller's concern (Python folds duplicates in a dict).
[[nodiscard]] std::vector<std::size_t> plan_section_nearest_neighbor(
    const std::vector<WellCoord>& wells);

[[nodiscard]] std::vector<std::size_t> plan_section(
    const std::vector<WellCoord>& wells, const std::string& method = "pca");

}  // namespace pwb::viz::cross_well
