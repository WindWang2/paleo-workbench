#pragma once

// pwb::mapping — CRS-aware geometry measures, a faithful C++ port of
// paleo_workbench/mapping/geological_pipeline/geometry_units.py (V6 §15
// P0-10; full-conversion task 17). Frozen against the Python oracle
// (tools/oracle/generate_crs_units_fixtures.py, "kernel" section —
// generated with pyproj import blocked, the same dependency profile as
// this kernel):
//
//   * is_geographic_crs collapses the workflow crs_policy three-state
//     (True/False/nullopt) to bool — an unknown CRS is NOT geographic, so
//     labels fall to the "{crs}-unit²" branch and are never dressed up
//     as a ≈m² approximation;
//   * under a geographic CRS, areas/lengths in raw square degrees /
//     degrees are meaningless: the measures are rescaled from the
//     geometry's mean latitude into an honestly-labelled local-scale
//     ≈m²/≈m approximation, always with an explicit warning. Python
//     repr(crs) appears verbatim inside the warning (None → "None");
//   * an undeclared CRS keeps the raw CRS-axis measure labelled
//     "unknown-unit²"/"unknown-unit" with a warning — never metres.
//
// Rings are closed (first point repeated last) exactly like the Python
// shoelace core: the last-to-first edge is NOT added implicitly.
// Qt-free, Python-free, numpy-free, pyproj-free.

#include <optional>
#include <string>
#include <vector>

#include <pwb/mapping/contouring.hpp>      // Polyline, polyline_length
#include <pwb/mapping/polygonization.hpp>  // Ring, shoelace_area

namespace pwb::mapping {

inline constexpr double kMetresPerDegreeLat = 111320.0;

// Python: bool(crs_policy.crs_is_geographic(...)) — nullopt → false.
bool is_geographic_crs(const std::optional<std::string>& crs);

// "deg²" / "{crs}-unit²" (stripped declaration, not normalized) /
// "unknown-unit²".
std::string area_unit_label(const std::optional<std::string>& crs);

struct AreaWithUnit {
    double area = 0.0;
    std::string unit_label;
    std::optional<std::string> warning;
};

struct LengthWithUnit {
    double length = 0.0;
    std::string unit_label;
    std::optional<std::string> warning;
};

// (area, unit_label, warning) for one coordinate ring: shoelace in CRS
// axes; geographic CRS rescales by (111320·cos(mean_lat))·111320.
AreaWithUnit ring_area_with_unit(const Ring& ring,
                                 const std::optional<std::string>& crs);

// (length, unit_label, warning) for one polyline: planar CRS-axes sum,
// geographic CRS rescales dx by 111320·cos(mean_lat) and dy by 111320.
LengthWithUnit polyline_length_with_unit(
    const Polyline& vertices, const std::optional<std::string>& crs);

}  // namespace pwb::mapping
