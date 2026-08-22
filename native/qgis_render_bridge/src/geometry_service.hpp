#pragma once

/// QGIS-backed vector geometry service.
///
/// Professional GIS operations run through vendored QgsGeometry/QgsGeometryEngine
/// implementations.  The service is stateless and pure-computing: inputs are
/// GeoJSON geometry JSON strings, outputs are GeoJSON geometry JSON strings
/// (QgsGeometry::asJson), so results can flow straight into Paleo
/// VectorEditSession commands without a second geometry DTO.

#include <array>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::qgis_render {

/// Thrown for invalid input geometry or failed operations.
struct GeometryServiceError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

std::string geometry_union(const std::vector<std::string>& geometries);
std::vector<std::string> geometry_split_by_line(const std::string& geometry,
                                                const std::string& cutter);
std::string geometry_intersection(const std::string& a, const std::string& b);
std::string geometry_difference(const std::string& a, const std::string& b);
std::string geometry_symdifference(const std::string& a, const std::string& b);
std::string geometry_buffer(const std::string& geometry, double distance,
                            int segments);
std::string geometry_offset_curve(const std::string& line, double distance);
std::string geometry_simplify(const std::string& geometry, double tolerance);
std::string geometry_smooth(const std::string& geometry, unsigned int iterations,
                            double offset);
std::string geometry_densify(const std::string& geometry, double interval);
std::string geometry_make_valid(const std::string& geometry);
bool geometry_is_valid(const std::string& geometry);
std::vector<std::string> geometry_multipart_to_singlepart(const std::string& geometry);
std::string geometry_singlepart_to_multipart(const std::vector<std::string>& geometries);
std::string geometry_clip(const std::string& geometry, const std::array<double, 4>& extent);

}  // namespace pwb::qgis_render
