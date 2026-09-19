// Fence section model and shared amplitude strip extraction (#60–#61) —
// port of geoviz_well_seismic_3d/fence.py @ 08851951. The along-fence
// index always means uniform arc length (#51) — never vertex-index
// fractions, which misalign on unequal-length segments.
#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "registration.hpp"
#include "volume_access.hpp"

namespace pwb::geo3d_viz::joint {

// Named polyline fence in survey XY (metres). id defaults to a random
// 12-hex string (Python uuid4().hex[:12]); pass an explicit id for
// deterministic tests/persistence.
struct FenceSection {
    std::string name;
    std::vector<std::array<double, 2>> vertices_xy;
    bool visible = true;
    std::string id;

    FenceSection(std::string fence_name,
                 std::vector<std::array<double, 2>> vertices,
                 std::string fence_id = "");
};

// One amplitude strip shared by the 3D curtain and the 2D VD view.
struct FenceExtraction {
    std::string fence_id;
    std::vector<float> amplitude;   // n_along * n_sample, row-major
    std::vector<double> arc_length_m;  // n_along
    std::vector<double> sample_axis;   // n_sample, active-domain units

    std::int64_t n_along() const {
        return static_cast<std::int64_t>(arc_length_m.size());
    }
    std::int64_t n_sample() const {
        return static_cast<std::int64_t>(sample_axis.size());
    }
};

// Equal arc-length resample of a fence polyline: (n_along, 2) XY
// positions at uniform cumulative distance.
std::vector<std::array<double, 2>> sample_fence_polyline(
    const std::vector<std::array<double, 2>>& vertices_xy,
    std::int64_t n_along);

// Sample the volume along the fence polyline; the single result shared by
// 3D and 2D consumers. registration is preferred when the cube is a
// preview (indices scale to the loaded shape). Legacy il/xl parameters
// remain for tests. The dense fast path materialises nothing for
// source-backed volumes (slice_inline per distinct column).
FenceExtraction extract_fence_strip(
    const IVolumeAccess& volume, const FenceSection& fence,
    const SurveySpec& survey, std::int64_t n_along = 128,
    const std::optional<std::vector<double>>& sample_axis = std::nullopt,
    const VolumeRegistration* registration = nullptr);

// Polyline through well surface positions (≥ 2 wells required).
std::vector<std::array<double, 2>> well_to_well_path(
    const std::vector<std::array<double, 2>>& well_xy);

}  // namespace pwb::geo3d_viz::joint
