#pragma once

// pwb::geomodel — domain-space measurement kernel, a faithful C++ port of
// paleo_workbench/viz/geomodel/measurements.py (G10, CONV-12). Frozen
// against tools/oracle/generate_geomodel_volume_fixtures.py:
//   * every measurement happens in domain coordinates; results carry the
//     unit (ADR-08) — no pixel-space conversion anywhere;
//   * thickness is bilinear on each grid; ANY NaN corner is a hard error
//     (fail-closed: thickness through a hole is unknown, never zero), with
//     the upper-corner clamp so edge picks interpolate the last cell;
//   * plane orientation is the smallest-eigenvector normal of the centred
//     picks (numpy SVD on the Python side; 3x3 Jacobi eigen solve here —
//     same direction up to solver noise, oracle tolerance 1e-6), z sign
//     normalized positive, dip = acos(|nz|), strike folded to [0, 180);
//   * _pts validation and format_result text are preserved verbatim.
// The Python object_id counter (measure:<kind>-<n>) is process state and is
// deliberately not frozen (ledger 12-decisions D3).
// Qt-free, Python-free, numpy-free.

#include <array>
#include <optional>
#include <string>
#include <vector>

#include <pwb/geomodel/builders.hpp>  // HorizonGrid, Vec3

namespace pwb::geomodel {

// The subset of MeasurementRecord the kernels produce and format_result
// consumes; every field the Python extra dict carries has a slot here.
struct MeasurementResult {
    std::string crs;               // recorded, never interpreted here
    std::string measurement_kind;  // point | distance | polyline |
                                   // vertical_difference | thickness |
                                   // plane_orientation
    std::vector<Vec3> points;
    std::optional<double> result;  // nullopt for "point"
    std::string unit = "m";
    // per-kind extra payload
    double extra_x = 0.0;
    double extra_y = 0.0;
    double extra_z = 0.0;
    int legs = 0;
    double dz = 0.0;
    std::string top_id;
    std::string base_id;
    double signed_dz = 0.0;
    double strike_deg = 0.0;
    double dip_deg = 0.0;
    double planarity_ratio = 0.0;
};

MeasurementResult point_coordinate(const Vec3& point, const std::string& crs,
                                   const std::string& unit = "m");

MeasurementResult distance(const Vec3& a, const Vec3& b,
                           const std::string& crs, const std::string& unit = "m");

MeasurementResult polyline_length(
    const std::vector<Vec3>& points, const std::string& crs,
    const std::string& unit = "m");

MeasurementResult vertical_difference(const Vec3& a, const Vec3& b,
                                      const std::string& crs,
                                      const std::string& unit = "m");

// Vertical thickness between top and base at world (x, y); throws with the
// Python message when the pick falls in a grid hole (NaN corner).
MeasurementResult thickness_at(double x, double y, const HorizonGrid& top,
                               const HorizonGrid& base,
                               const std::string& crs = "",
                               const std::string& unit = "");

MeasurementResult plane_orientation(const std::vector<Vec3>& points,
                                    const std::string& crs,
                                    const std::string& unit = "m");

// Human-readable, unit-explicit result line (Python text verbatim).
std::string format_result(const MeasurementResult& record);

}  // namespace pwb::geomodel
