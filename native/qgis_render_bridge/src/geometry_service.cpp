#include "geometry_service.hpp"

#include <iterator>

#include <qgsgeometry.h>
#include <qgsgeometryengine.h>
#include <qgsjsonutils.h>
#include <qgsrectangle.h>
#include <qgsvertexid.h>

namespace pwb::qgis_render {
namespace {

QgsGeometry parse(const std::string& json_or_wkt, const char* what) {
    // Inputs are GeoJSON geometry JSON strings produced by this service or
    // host GeoJSON payloads; bare WKT is accepted for operator convenience.
    const QString text = QString::fromStdString(json_or_wkt).trimmed();
    QgsGeometry geometry;
    if (text.startsWith('{')) {
        geometry = QgsJsonUtils::geometryFromGeoJson(text);
    }
    if (geometry.isNull()) {
        geometry = QgsGeometry::fromWkt(text);
    }
    if (geometry.isNull()) {
        throw GeometryServiceError(std::string("invalid ") + what + " geometry");
    }
    return geometry;
}

std::string serialize_geometry(const QgsGeometry& geometry) {
    if (geometry.isNull() || geometry.isEmpty()) {
        throw GeometryServiceError("operation produced an empty geometry");
    }
    const QString json = geometry.asJson(17);
    if (json.isEmpty()) {
        throw GeometryServiceError("operation result could not be serialized");
    }
    return json.toStdString();
}

QgsPointSequence line_vertices(const QgsGeometry& line) {
    QgsPointSequence points;
    QgsVertexIterator vertices = line.vertices();
    while (vertices.hasNext()) {
        points.append(vertices.next());
    }
    return points;
}

}  // namespace

std::string geometry_union(const std::vector<std::string>& geometries) {
    if (geometries.empty()) {
        throw GeometryServiceError("union requires at least one geometry");
    }
    QgsGeometry combined = parse(geometries.front(), "union input");
    for (std::size_t index = 1; index < geometries.size(); ++index) {
        const QgsGeometry next = parse(geometries[index], "union input");
        combined = combined.combine(next);
        if (combined.isNull()) {
            throw GeometryServiceError("union failed");
        }
    }
    return serialize_geometry(combined);
}

std::vector<std::string> geometry_split_by_line(const std::string& geometry,
                                                const std::string& cutter) {
    QgsGeometry target = parse(geometry, "split target");
    const QgsGeometry line = parse(cutter, "split cutter");
    if (line.type() != Qgis::GeometryType::Line) {
        throw GeometryServiceError("split cutter must be a line");
    }
    QVector<QgsGeometry> new_geometries;
    QgsPointSequence topology_test_points;
    const Qgis::GeometryOperationResult result = target.splitGeometry(
        line_vertices(line), new_geometries, false, topology_test_points, true, true
    );
    if (result != Qgis::GeometryOperationResult::Success || new_geometries.isEmpty()) {
        throw GeometryServiceError("the cutter does not split the geometry");
    }
    std::vector<std::string> pieces;
    pieces.push_back(serialize_geometry(target));
    for (const QgsGeometry& piece : new_geometries) {
        if (!piece.isNull() && !piece.isEmpty()) {
            pieces.push_back(serialize_geometry(piece));
        }
    }
    return pieces;
}

std::string geometry_intersection(const std::string& a, const std::string& b) {
    return serialize_geometry(parse(a, "first").intersection(parse(b, "second")));
}

std::string geometry_difference(const std::string& a, const std::string& b) {
    return serialize_geometry(parse(a, "first").difference(parse(b, "second")));
}

std::string geometry_symdifference(const std::string& a, const std::string& b) {
    return serialize_geometry(parse(a, "first").symDifference(parse(b, "second")));
}

std::string geometry_buffer(const std::string& geometry, const double distance,
                            const int segments) {
    return serialize_geometry(parse(geometry, "buffer input").buffer(distance, segments));
}

std::string geometry_offset_curve(const std::string& line, const double distance) {
    QgsGeometry geometry = parse(line, "offset input");
    if (geometry.type() != Qgis::GeometryType::Line) {
        throw GeometryServiceError("offset curve requires a line geometry");
    }
    return serialize_geometry(geometry.offsetCurve(distance, 8, Qgis::JoinStyle::Round, 2.0));
}

std::string geometry_simplify(const std::string& geometry, const double tolerance) {
    return serialize_geometry(parse(geometry, "simplify input").simplify(tolerance));
}

std::string geometry_smooth(const std::string& geometry, const unsigned int iterations,
                            const double offset) {
    return serialize_geometry(parse(geometry, "smooth input").smooth(iterations, offset));
}

std::string geometry_densify(const std::string& geometry, const double interval) {
    if (interval <= 0.0) {
        throw GeometryServiceError("densify interval must be positive");
    }
    return serialize_geometry(parse(geometry, "densify input").densifyByDistance(interval));
}

std::string geometry_make_valid(const std::string& geometry) {
    QgsGeometry fixed = parse(geometry, "make valid input").makeValid();
    if (fixed.isNull()) {
        throw GeometryServiceError("make valid failed");
    }
    return serialize_geometry(fixed);
}

bool geometry_is_valid(const std::string& geometry) {
    return parse(geometry, "validity input").isGeosValid();
}

std::vector<std::string> geometry_multipart_to_singlepart(const std::string& geometry) {
    QgsGeometry source = parse(geometry, "explode input");
    if (source.constGet()->partCount() <= 1 && source.asGeometryCollection().size() <= 1) {
        return {serialize_geometry(source)};
    }
    std::vector<std::string> parts;
    for (const QgsGeometry& part : source.asGeometryCollection()) {
        if (!part.isNull() && !part.isEmpty()) {
            parts.push_back(serialize_geometry(part));
        }
    }
    if (parts.empty()) {
        throw GeometryServiceError("explode produced no parts");
    }
    return parts;
}

std::string geometry_singlepart_to_multipart(const std::vector<std::string>& geometries) {
    QVector<QgsGeometry> parts;
    parts.reserve(static_cast<int>(geometries.size()));
    for (const std::string& item : geometries) {
        parts.append(parse(item, "collect input"));
    }
    if (parts.isEmpty()) {
        throw GeometryServiceError("collect requires at least one geometry");
    }
    return serialize_geometry(QgsGeometry::collectGeometry(parts));
}

std::string geometry_clip(const std::string& geometry,
                          const std::array<double, 4>& extent) {
    const QgsRectangle rectangle(extent[0], extent[1], extent[2], extent[3]);
    if (rectangle.isEmpty()) {
        throw GeometryServiceError("clip extent is empty");
    }
    return serialize_geometry(parse(geometry, "clip input").intersection(QgsGeometry::fromRect(rectangle)));
}

}  // namespace pwb::qgis_render
