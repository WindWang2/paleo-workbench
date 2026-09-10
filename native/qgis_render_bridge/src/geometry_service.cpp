#include "geometry_service.hpp"

#include <cmath>
#include <iterator>

#include <qgsgeometry.h>
#include <qgsgeometryengine.h>
#include <qgsjsonutils.h>
#include <qgslinestring.h>
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

std::string geometry_validate(const std::string& geometry) {
    // validateGeometry 在该版本非 const（style_codec save 同款约束），取副本。
    QgsGeometry source = parse(geometry, "validate input");
    QVector<QgsGeometry::Error> errors;
    // GEOS 引擎：与 Shapely/GEOS 校验语义一致（TopologyService 的 QGIS
    // 优先路径）；QgisInternal 会补 QGIS 专有检查（环闭合等），留给宿主
    // 的 Python 侧语义层做差异化报告。
    source.validateGeometry(errors, Qgis::GeometryValidationEngine::Geos);
    QString json = QStringLiteral("[");
    bool first = true;
    for (const QgsGeometry::Error& error : errors) {
        if (!first) json += QStringLiteral(",");
        first = false;
        QString where;
        const QgsPointXY at = error.where();
        if (std::isfinite(at.x()) && std::isfinite(at.y())) {
            where = QStringLiteral("[%1,%2]")
                        .arg(QString::number(at.x(), 'g', 12),
                             QString::number(at.y(), 'g', 12));
        } else {
            where = QStringLiteral("null");
        }
        QString message = error.what();
        message.replace(QLatin1String("\\"), QLatin1String("\\\\"))
            .replace(QLatin1String("\""), QLatin1String("\\\""));
        json += QStringLiteral("{\"where\":%1,\"message\":\"%2\"}").arg(where, message);
    }
    json += QStringLiteral("]");
    return json.toStdString();
}

std::string geometry_reshape(const std::string& geometry,
                             const std::string& reshape_line) {
    QgsGeometry source = parse(geometry, "reshape input");
    QgsGeometry line = parse(reshape_line, "reshape line");
    if (line.type() != Qgis::GeometryType::Line) {
        throw GeometryServiceError("reshape line must be a LineString");
    }
    const QgsLineString* ls = qgsgeometry_cast<const QgsLineString*>(line.constGet());
    if (ls == nullptr) {
        throw GeometryServiceError("reshape line must be a single LineString");
    }
    // reshapeGeometry 非 const：在副本上执行（source 保持入参语义）。
    QgsGeometry target = source;
    const Qgis::GeometryOperationResult result = target.reshapeGeometry(*ls);
    switch (result) {
        case Qgis::GeometryOperationResult::Success:
            break;
        case Qgis::GeometryOperationResult::InvalidInputGeometryType:
            throw GeometryServiceError("reshape target geometry type is invalid");
        case Qgis::GeometryOperationResult::NothingHappened:
            throw GeometryServiceError("reshape line does not intersect the target geometry");
        default:
            throw GeometryServiceError("reshape failed");
    }
    if (target.isNull() || target.isEmpty() || target.equals(source)) {
        throw GeometryServiceError("reshape produced no changed geometry");
    }
    return serialize_geometry(target);
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

std::string geometry_add_part(const std::string& geometry, const std::string& part) {
    QgsGeometry source = parse(geometry, "add_part input");
    QgsGeometry partGeometry = parse(part, "add_part part");
    if (partGeometry.isEmpty()) {
        throw GeometryServiceError("add_part part geometry is empty");
    }
    // addPart 语义在多部件容器上定义：单部件输入显式升多部件（结果确定性，
    // 不依赖 QGIS 内部隐式转换分支）。
    if (source.constGet() != nullptr && !source.isMultipart()) {
        if (!source.convertToMultiType()) {
            throw GeometryServiceError("add_part requires a convertible geometry type");
        }
    }
    QgsGeometry target = source;
    const Qgis::GeometryOperationResult result = target.addPart(partGeometry);
    if (result != Qgis::GeometryOperationResult::Success) {
        throw GeometryServiceError("add_part failed (geometry operation result " +
                                   std::to_string(static_cast<int>(result)) + ")");
    }
    return serialize_geometry(target);
}

std::string geometry_delete_part(const std::string& geometry, int part_index) {
    QgsGeometry source = parse(geometry, "delete_part input");
    if (!source.isMultipart()) {
        throw GeometryServiceError("delete_part requires a multipart geometry");
    }
    if (part_index < 0 || part_index >= source.constGet()->partCount()) {
        throw GeometryServiceError("delete_part index outside the geometry parts");
    }
    QgsGeometry target = source;
    if (!target.deletePart(part_index)) {
        throw GeometryServiceError("delete_part failed");
    }
    if (target.isEmpty()) {
        throw GeometryServiceError("delete_part would empty the geometry");
    }
    return serialize_geometry(target);
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
