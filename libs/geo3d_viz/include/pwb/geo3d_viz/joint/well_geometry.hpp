// Head→bottom well trajectories projected into the active vertical domain
// — port of geoviz_well_seismic_3d/well_geometry.py @ 08851951. In Time
// domain Z is TWT (ms) from the TD table; in Depth domain it is that TWT
// pushed through the scene's depth transform. Wells without a TD table
// return only the wellhead point with a warning — MD is an along-path
// parameter and is never substituted for a seismic vertical coordinate.
#pragma once

#include <array>
#include <optional>
#include <vector>

#include "depth_transform.hpp"
#include "joint_types.hpp"

namespace pwb::geo3d_viz::joint {

inline constexpr std::size_t kDefaultTrajectorySamples = 32;

// XY where a trajectory crosses the horizontal plane z. Null when the
// path does not reach that plane.
std::optional<std::pair<double, double>> pierce_xy_at_z(
    const std::vector<std::array<double, 3>>& points, double z,
    double atol = 1e-6);

WellTrajectory3D project_well_trajectory(
    const WellHead& well, VerticalDomain domain,
    const TimeDepthTable* td, std::size_t n_samples = kDefaultTrajectorySamples,
    const DepthTransformState* depth_transform = nullptr);

// Offset a log curve sideways off a well path for a 3D "curve beside the
// well" track: at each station the offset direction is the horizontal
// normal to the trajectory tangent ((-ty, tx, 0)); perfectly vertical
// wells fall back to +X. Raises when curve_values is shorter than the
// path. (Promoted from well_seismic.py WellCurve3DGenerator.)
std::vector<std::array<float, 3>> offset_curve_along_trajectory(
    const std::vector<std::array<float, 3>>& well_path,
    const std::vector<float>& curve_values, float scale = 0.1f);

// 3D wiggle-track polyline for a synthetic seismogram beside a well: the
// trace is linearly resampled to the station count and deflects each
// station laterally; NaN/inf amplitudes clamp to zero.
std::vector<std::array<float, 3>> build_synthetic_seismogram_overlay(
    const std::vector<std::array<float, 3>>& well_path,
    const std::vector<float>& synthetic_trace, float scale = 1.0f);

}  // namespace pwb::geo3d_viz::joint
