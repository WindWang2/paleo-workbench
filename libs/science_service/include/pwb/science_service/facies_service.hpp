#pragma once

// pwb::science_service — well facies surface service (CONV-28): typed
// envelope over the frozen representative_facies kernel cluster (CONV-10):
//   representative_facies(regions, horizon) — per-well interval voting;
//   spatial_point_features / point_features — GeoJSON point descriptors;
//   point_to_surface_features — nearest-neighbour class grid + polygonize.
// The well-registry glue (well_xy / _points_from_intervals) stays host-side:
// the request carries already-resolved well facies points and/or a
// prediction result summary dict.

#include <pwb/mapping/representative_facies.hpp>
#include <pwb/science/algorithm.hpp>
#include <pwb/science/outcome.hpp>

#include <stop_token>

#include <array>
#include <optional>
#include <string>
#include <vector>

#include "envelope.hpp"
#include "limits.hpp"

namespace pwb::science_service {

struct FaciesSurfaceRequest {
    // Well facies points (already resolved by the host). Each entry:
    // {"x", "y", "facies", "well_id"?, "well_name"?, "probability"?,
    //  "thickness"?, "task_id"?} — non-parsing entries are dropped by the
    // kernel filters, never errors.
    pwb::domain::Json well_points = pwb::domain::Json::array();
    // Optional prediction result summary dict (spatial features / interval
    // records) for task_regions + spatial_point_features.
    pwb::domain::Json result_summary = pwb::domain::Json(nullptr);
    // Horizon substring filter for representative_facies ("" = no filter).
    std::string horizon;
    // Spatial extent: given, or derived from the points (padded bbox).
    std::optional<std::array<double, 4>> extent;
    int grid_n = 80;
    // Grid-level clip ring ([[x, y], ...]); <4 finite vertices = no clip.
    std::optional<std::vector<std::array<double, 2>>> clip_ring;
    std::string crs;
    std::string task_id;
};

struct FaciesSurfaceResult {
    ScienceEnvelope envelope;
    std::optional<pwb::mapping::RepresentativeFacies> representative;
    std::vector<pwb::mapping::WellFaciesPoint> points;
    // GeoJSON feature pairs (geometry, properties).
    std::vector<std::pair<pwb::domain::Json, pwb::domain::Json>> point_layer;
    std::vector<std::pair<pwb::domain::Json, pwb::domain::Json>> surface_layer;
    std::array<double, 4> extent{0.0, 0.0, 1.0, 1.0};
};

class FaciesSurfaceService {
public:
    explicit FaciesSurfaceService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    [[nodiscard]] science::Result<FaciesSurfaceResult> run(
        const FaciesSurfaceRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

}  // namespace pwb::science_service
