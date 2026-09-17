#pragma once

// pwb::mapping — distance/CRS policy leaf, a faithful C++ port of
// paleo_workbench/workflow/crs_policy.py (full-conversion plan M7 first
// slice). Frozen against tools/oracle/generate_crs_policy_fixtures.py.
//
// C++ has no pyproj. After the builtin geographic-id table and the
// projected-exception list, crs_is_geographic returns nullopt — the same
// result as Python's `except Exception: return None` path (pyproj missing
// or id unparsable). Unknown ids are never guessed.
//
// interpolate_factor records policy + annotation on FactorGrid.
// Qt-free, Python-free, numpy-free, pyproj-free.

#include <optional>
#include <string>
#include <string_view>

namespace pwb::mapping {

inline constexpr const char* kPolicyPlanar = "planar";
inline constexpr const char* kPolicyPlanarDegrees = "planar_degrees";
inline constexpr const char* kPolicyProjected = "projected";
inline constexpr const char* kPolicyUndeclared = "undeclared";

inline constexpr std::string_view kDistancePolicies[] = {
    kPolicyPlanar, kPolicyPlanarDegrees, kPolicyProjected,
};

// True/False when axis units are known from the builtin table;
// nullopt when crs is empty/null or the id is unknown (no pyproj).
std::optional<bool> crs_is_geographic(const std::optional<std::string>& crs);

struct DistancePolicy {
    std::string policy;
    std::optional<std::string> crs;
    std::optional<bool> axes_known;
    std::string annotation;
    std::optional<std::string> warning;
};

// Raises std::invalid_argument with the Python ValueError message when
// distance_policy is non-empty and not in kDistancePolicies.
DistancePolicy resolve_distance_policy(
    const std::optional<std::string>& crs,
    const std::optional<std::string>& distance_policy = std::nullopt);

}  // namespace pwb::mapping
