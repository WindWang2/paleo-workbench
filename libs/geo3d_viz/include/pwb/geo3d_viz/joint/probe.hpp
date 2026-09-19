// Shared probe state for 2D↔3D↔slice linkage (#64) — port of
// geoviz_well_seismic_3d/probe.py @ 08851951.
#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "fence.hpp"
#include "survey.hpp"

namespace pwb::geo3d_viz::joint {

// Probe on the active fence: arc-length s and vertical z.
struct ProbeState {
    double s_m = 0.0;
    double z = 0.0;  // TWT ms or depth m depending on domain
    double x = 0.0;
    double y = 0.0;
    double il = 0.0;
    double xl = 0.0;
    std::string domain = "time";

    // Nearest orthogonal slice indices (il_idx, xl_idx, sample_idx).
    std::array<std::int64_t, 3> slice_indices(
        const SurveySpec* survey) const;
};

// Map arc-length along a fence polyline to world XY and IL/XL.
ProbeState probe_from_fence_s(double s_m, double z,
                              const std::vector<std::array<double, 2>>& vertices_xy,
                              const SurveySpec* survey,
                              const std::string& domain = "time");

}  // namespace pwb::geo3d_viz::joint
