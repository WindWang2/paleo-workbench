#include <pwb/ui_composite/qgis/qgis_geometry.hpp>

// The vendored QgsGeometry kernel set — the same TU the render bridge
// compiles (GeoJSON string in → GeoJSON string out). Reuse over a
// second engine: the Python geometry_service facade calls exactly
// these functions through the pybind surface.
#include <geometry_service.hpp>

#include <qgsgeometry.h>
#include <qgsjsonutils.h>

#include <algorithm>
#include <cmath>
#include <functional>
#include <stdexcept>
#include <utility>

#include <pwb/ui_data_core/map_edit_geometry.hpp>

namespace pwb::ui_composite::qgis {

namespace {

std::string dump(const Json& value) { return value.dump(); }

Json parse_geojson(const std::string& text) {
    return Json::parse(text);
}

QgsGeometry to_qgs(const Json& geometry, const char* what) {
    QgsGeometry result = QgsJsonUtils::geometryFromGeoJson(
        QString::fromStdString(dump(geometry)));
    if (result.isNull()) {
        throw std::invalid_argument(std::string("invalid ") + what +
                                    " geometry");
    }
    return result;
}

bool polygonal(const Json& geometry) {
    const std::string type =
        geometry.value("type", Json("")).get<std::string>();
    return type == "Polygon" || type == "MultiPolygon";
}

bool linear(const Json& geometry) {
    const std::string type =
        geometry.value("type", Json("")).get<std::string>();
    return type == "LineString" || type == "MultiLineString";
}

bool has_coordinates(const Json& geometry) {
    const auto it = geometry.find("coordinates");
    return it != geometry.end() && it->is_array() && !it->empty();
}

// Order-preserving dedupe (Python dict.fromkeys parity).
std::vector<std::string> dedupe(const std::vector<std::string>& ids) {
    std::vector<std::string> out;
    for (const auto& id : ids) {
        if (std::find(out.begin(), out.end(), id) == out.end())
            out.push_back(id);
    }
    return out;
}

// -- pure-Json kernels (shapely-affinity / coordinate transforms) ----

// Walk coordinate arrays; apply fn to every leaf [x, y(, z...)] point.
// A node is a point iff it is a non-empty array of numbers; anything
// else recurses per child. Returns a new Json (input untouched —
// Python deepcopy parity).
Json transform_points(const Json& node,
                    const std::function<void(std::vector<double>&)>& fn) {
    if (!node.is_array() || node.empty()) return node;
    if (node.front().is_number()) {
        std::vector<double> point;
        point.reserve(node.size());
        for (const Json& v : node) point.push_back(v.get<double>());
        if (point.size() >= 2) fn(point);
        Json out = Json::array();
        for (double v : point) out.push_back(v);
        return out;
    }
    Json out = Json::array();
    for (const Json& child : node)
        out.push_back(transform_points(child, fn));
    return out;
}

Json affine(const Json& geometry, const std::function<void(double&, double&)>& fn) {
    Json out = geometry;
    auto it = out.find("coordinates");
    if (it == out.end()) return out;
    *it = transform_points(*it, [&fn](std::vector<double>& p) {
        if (p.size() >= 2) fn(p[0], p[1]);
    });
    return out;
}

// reverse_geometry helpers — byte-faithful to the Python _rev_points /
// _walk pair (including the extra closing vertex a closed ring gains).
Json rev_points(const Json& points) {
    Json out = Json::array();
    for (auto it = points.rbegin(); it != points.rend(); ++it)
        out.push_back(*it);
    if (points.size() >= 2 && points.front() == points.back() &&
        !out.empty()) {
        // 原环闭合：反转后仍须闭合（新首 = 新尾）——Python appends the
        // new first point once more; the extra vertex is preserved.
        Json closed = Json::array();
        closed.push_back(out.front());
        for (size_t i = 1; i < out.size(); ++i) closed.push_back(out[i]);
        closed.push_back(out.front());
        return closed;
    }
    return out;
}

Json walk_reverse(const Json& node) {
    if (!node.is_array() || node.empty()) return node;
    const Json& first = node.front();
    if (first.is_number()) return node;  // bare point row
    if (first.is_array() && !first.empty() && first.front().is_number())
        return rev_points(node);  // ring / line vertex list
    Json out = Json::array();
    for (const Json& child : node) out.push_back(walk_reverse(child));
    return out;
}

// extend_line_to_boundary: per-part endpoint extension (Python
// _extend_one parity). Extends tip along the end-segment direction by
// max_extend, intersects the ray with the boundary's boundary (falling
// back to the boundary itself — shapely Point has no boundary), and
// replaces the tip with the nearest hit coordinate; no hit keeps it.
Json extend_part(const Json& coords, const QgsGeometry& boundary_geom,
                 double max_extend) {
    if (coords.size() < 2) return coords;
    Json out = coords;
    for (int end : {0, 1}) {
        const Json& tip = end == 0 ? out.front() : out.back();
        const Json& nxt =
            end == 0 ? out.at(1) : out.at(out.size() - 2);
        const double tx = tip.at(0).get<double>();
        const double ty = tip.at(1).get<double>();
        const double dx = tx - nxt.at(0).get<double>();
        const double dy = ty - nxt.at(1).get<double>();
        const double length = std::hypot(dx, dy);
        if (length <= 0.0) continue;
        const double rx = tx + dx / length * max_extend;
        const double ry = ty + dy / length * max_extend;
        const QgsGeometry ray = QgsGeometry::fromPolylineXY(
            {QgsPointXY(tx, ty), QgsPointXY(rx, ry)});
        const QgsGeometry hit = ray.intersection(boundary_geom);
        if (hit.isNull() || hit.isEmpty()) continue;
        // Nearest hit vertex to the tip (Python iterates hit coords).
        std::optional<MapPoint> nearest;
        double best = 0.0;
        QgsVertexIterator vertices = hit.vertices();
        while (vertices.hasNext()) {
            const QgsPointXY p = vertices.next();
            const double dist =
                std::hypot(p.x() - tx, p.y() - ty);
            if (!nearest.has_value() || dist < best) {
                best = dist;
                nearest = MapPoint{p.x(), p.y()};
            }
        }
        if (!nearest.has_value()) continue;
        Json tip_out = tip;
        tip_out[0] = (*nearest)[0];
        tip_out[1] = (*nearest)[1];
        if (end == 0)
            out[0] = tip_out;
        else
            out[out.size() - 1] = tip_out;
    }
    return out;
}

}  // namespace

// ---------------------------------------------------------------------------
// QgisCompositeGeometryOps
// ---------------------------------------------------------------------------

std::string QgisCompositeGeometryOps::merge_selected_polygons(
    VectorEditSession& session, const std::vector<std::string>& ids_in) {
    const std::vector<std::string> ids = dedupe(ids_in);
    if (ids.size() < 2) {
        throw std::invalid_argument(
            "select at least two polygons to merge");
    }
    std::vector<VectorFeature> features;
    features.reserve(ids.size());
    for (const auto& id : ids) features.push_back(session.feature(id));
    for (const auto& feature : features) {
        if (!polygonal(feature.geometry)) {
            throw std::invalid_argument(
                "only polygon features can be merged");
        }
    }
    for (const auto& feature : features) {
        if (!has_coordinates(feature.geometry)) {
            throw std::invalid_argument(
                "selected polygons cannot form a valid merged polygon");
        }
    }
    std::vector<std::string> inputs;
    inputs.reserve(features.size());
    for (const auto& feature : features)
        inputs.push_back(dump(feature.geometry));
    const Json merged_geom =
        parse_geojson(pwb::qgis_render::geometry_union(inputs));
    // QGIS path parity: a non-polygonal/empty union is the same
    // rejection the shapely fallback reports (bridge failure surfaces
    // through the exception, never a silent bad write).
    if (!polygonal(merged_geom) || !has_coordinates(merged_geom)) {
        throw std::invalid_argument(
            "selected polygons cannot form a valid merged polygon");
    }
    const std::string feature_id =
        ui_data_core::new_feature_id("merge");
    VectorFeature merged(feature_id, merged_geom,
                         features.front().attributes);
    session.merge_features(ids, merged);
    return feature_id;
}

std::vector<std::string> QgisCompositeGeometryOps::split_polygon_by_line(
    VectorEditSession& session, const std::string& polygon_id,
    const VectorFeature& line_feature) {
    const VectorFeature& polygon_feature = session.feature(polygon_id);
    if (!polygonal(polygon_feature.geometry)) {
        throw std::invalid_argument("split target must be a polygon");
    }
    if (!linear(line_feature.geometry)) {
        throw std::invalid_argument("split cutter must be a line");
    }
    const std::vector<std::string> pieces_text =
        pwb::qgis_render::geometry_split_by_line(
            dump(polygon_feature.geometry), dump(line_feature.geometry));
    std::vector<Json> pieces;
    for (const auto& text : pieces_text) {
        Json piece = parse_geojson(text);
        if (polygonal(piece) && has_coordinates(piece))
            pieces.push_back(std::move(piece));
    }
    if (pieces.size() < 2) {
        throw std::invalid_argument(
            "the cutter does not split the selected polygon");
    }
    std::vector<VectorFeature> replacements;
    replacements.reserve(pieces.size());
    for (const Json& piece : pieces) {
        replacements.emplace_back(ui_data_core::new_feature_id("split"),
                                  piece, polygon_feature.attributes);
    }
    session.split_feature(polygon_id, replacements);
    std::vector<std::string> out;
    out.reserve(replacements.size());
    for (const auto& feature : replacements)
        out.push_back(feature.feature_id);
    return out;
}

Json QgisCompositeGeometryOps::make_geometry_valid(const Json& geometry) {
    // geometry_service.make_geometry_valid: non-object/non-polygonal
    // input passes through untouched (dict-in/dict-out contract).
    if (!geometry.is_object() || !polygonal(geometry)) return geometry;
    return parse_geojson(
        pwb::qgis_render::geometry_make_valid(dump(geometry)));
}

std::vector<Json> QgisCompositeGeometryOps::multipart_to_singlepart(
    const Json& geometry) {
    const std::vector<std::string> parts =
        pwb::qgis_render::geometry_multipart_to_singlepart(
            dump(geometry));
    std::vector<Json> out;
    out.reserve(parts.size());
    for (const auto& text : parts) out.push_back(parse_geojson(text));
    return out;
}

Json QgisCompositeGeometryOps::singlepart_to_multipart(
    const std::vector<Json>& geometries) {
    std::vector<std::string> inputs;
    inputs.reserve(geometries.size());
    for (const Json& g : geometries) inputs.push_back(dump(g));
    return parse_geojson(
        pwb::qgis_render::geometry_singlepart_to_multipart(inputs));
}

Json QgisCompositeGeometryOps::trim_line(const Json& geometry,
                                       const Json& boundary,
                                       const std::string& keep) {
    // Python trim_line computes intersection regardless of ``keep``
    // (the "outside" branch is unimplemented upstream) — byte-faithful.
    (void)keep;
    Json result;
    try {
        result = parse_geojson(
            pwb::qgis_render::geometry_intersection(dump(geometry),
                                                    dump(boundary)));
    } catch (const pwb::qgis_render::GeometryServiceError&) {
        // Bridge raises on empty intersection; Python shapely returns
        // an empty geometry which the caller maps to the same rejection.
        throw std::invalid_argument("trim produced no line segments");
    }
    if (!linear(result)) {
        throw std::invalid_argument("trim produced no line segments");
    }
    return result;
}

Json QgisCompositeGeometryOps::extend_line_to_boundary(
    const Json& geometry, const Json& boundary, double max_extend) {
    const std::string type =
        geometry.value("type", Json("")).get<std::string>();
    if (type != "LineString" && type != "MultiLineString") {
        throw std::invalid_argument("extend supports lines only");
    }
    QgsGeometry target = to_qgs(boundary, "boundary");
    // Topological boundary via the abstract geometry (polygon → ring
    // lines). NULLPTR-able for some types (Point) — shapely parity
    // falls back to the target itself as the hit surface.
    QgsGeometry target_boundary;
    if (target.constGet() != nullptr) {
        target_boundary = QgsGeometry(target.constGet()->boundary());
    }
    if (target_boundary.isNull() || target_boundary.isEmpty()) {
        target_boundary = target;
    }
    Json out = geometry;
    if (type == "LineString") {
        out["coordinates"] = extend_part(geometry.at("coordinates"),
                                         target_boundary, max_extend);
    } else {
        Json parts = Json::array();
        for (const Json& part : geometry.at("coordinates")) {
            parts.push_back(
                extend_part(part, target_boundary, max_extend));
        }
        out["coordinates"] = std::move(parts);
    }
    return out;
}

Json QgisCompositeGeometryOps::reverse_geometry(const Json& geometry) {
    const std::string type =
        geometry.value("type", Json("")).get<std::string>();
    Json out = geometry;
    auto it = out.find("coordinates");
    if (it == out.end()) return out;
    if (type == "LineString" || type == "MultiLineString") {
        Json reversed = Json::array();
        if (type == "LineString") {
            for (auto rit = it->rbegin(); rit != it->rend(); ++rit)
                reversed.push_back(*rit);
        } else {
            for (const Json& part : *it) {
                Json piece = Json::array();
                for (auto rit = part.rbegin(); rit != part.rend(); ++rit)
                    piece.push_back(*rit);
                reversed.push_back(std::move(piece));
            }
        }
        *it = std::move(reversed);
    } else if (type == "Polygon" || type == "MultiPolygon") {
        *it = walk_reverse(*it);
    }
    return out;
}

Json QgisCompositeGeometryOps::simplify(const Json& geometry,
                                        double tolerance) {
    return parse_geojson(
        pwb::qgis_render::geometry_simplify(dump(geometry), tolerance));
}

Json QgisCompositeGeometryOps::smooth(const Json& geometry,
                                      int iterations, double offset) {
    return parse_geojson(pwb::qgis_render::geometry_smooth(
        dump(geometry), static_cast<unsigned int>(iterations), offset));
}

Json QgisCompositeGeometryOps::offset_curve(const Json& geometry,
                                            double distance) {
    return parse_geojson(
        pwb::qgis_render::geometry_offset_curve(dump(geometry),
                                                distance));
}

Json QgisCompositeGeometryOps::rotate(const Json& geometry,
                                      double angle_degrees,
                                      const MapPoint& origin) {
    // shapely affinity.rotate: degrees CCW around origin.
    const double rad = angle_degrees * M_PI / 180.0;
    const double cos_a = std::cos(rad);
    const double sin_a = std::sin(rad);
    const double ox = origin[0];
    const double oy = origin[1];
    return affine(geometry, [cos_a, sin_a, ox, oy](double& x, double& y) {
        const double dx = x - ox;
        const double dy = y - oy;
        x = ox + cos_a * dx - sin_a * dy;
        y = oy + sin_a * dx + cos_a * dy;
    });
}

Json QgisCompositeGeometryOps::scale(const Json& geometry, double xfact,
                                     double yfact,
                                     const MapPoint& origin) {
    // shapely affinity.scale around origin.
    const double ox = origin[0];
    const double oy = origin[1];
    return affine(geometry, [xfact, yfact, ox, oy](double& x, double& y) {
        x = ox + xfact * (x - ox);
        y = oy + yfact * (y - oy);
    });
}

MapPoint QgisCompositeGeometryOps::union_centroid(
    const std::vector<Json>& geoms) {
    std::vector<std::string> inputs;
    inputs.reserve(geoms.size());
    for (const Json& g : geoms) inputs.push_back(dump(g));
    const QgsGeometry combined = QgsJsonUtils::geometryFromGeoJson(
        QString::fromStdString(
            pwb::qgis_render::geometry_union(inputs)));
    if (combined.isNull()) {
        throw std::invalid_argument("union produced no geometry");
    }
    const QgsGeometry centroid = combined.centroid();
    if (centroid.isNull() || centroid.isEmpty()) {
        throw std::invalid_argument("union produced no centroid");
    }
    const QgsPointXY point = centroid.asPoint();
    return {point.x(), point.y()};
}

std::optional<Json> QgisCompositeGeometryOps::reshape(
    const Json& target, const Json& line) {
    try {
        return parse_geojson(pwb::qgis_render::geometry_reshape(
            dump(target), dump(line)));
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

std::optional<Json> QgisCompositeGeometryOps::add_part(
    const Json& target, const Json& part) {
    try {
        return parse_geojson(pwb::qgis_render::geometry_add_part(
            dump(target), dump(part)));
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

std::optional<Json> QgisCompositeGeometryOps::delete_part(
    const Json& geometry, int part_index) {
    try {
        return parse_geojson(pwb::qgis_render::geometry_delete_part(
            dump(geometry), part_index));
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

// ---------------------------------------------------------------------------
// TopologyService validator seams
// ---------------------------------------------------------------------------

std::vector<std::string> qgis_validate_geometry(const Json& geometry) {
    // The bridge returns [{"where": ..., "message": ...}] — the
    // Python validate_records consumes entry["message"] verbatim.
    try {
        const Json entries =
            parse_geojson(pwb::qgis_render::geometry_validate(
                dump(geometry)));
        std::vector<std::string> messages;
        if (entries.is_array()) {
            for (const Json& entry : entries) {
                messages.push_back(entry.value(
                    "message", Json("invalid geometry"))
                                       .get<std::string>());
            }
        }
        return messages;
    } catch (const std::exception& exc) {
        // Parse failure surfaces as one error entry — the bridge path
        // never throws across the seam (a raise would read as
        // engine-absent and silently downgrade the check).
        return {std::string("invalid geometry: ") + exc.what()};
    }
}

std::vector<std::vector<std::string>> qgis_validate_geometries(
    const std::vector<Json>& geometries) {
    std::vector<std::vector<std::string>> out;
    out.reserve(geometries.size());
    for (const Json& geometry : geometries)
        out.push_back(qgis_validate_geometry(geometry));
    return out;
}

Json qgis_repair_geometry(const Json& geometry) {
    try {
        return parse_geojson(
            pwb::qgis_render::geometry_make_valid(dump(geometry)));
    } catch (const std::exception&) {
        return geometry;
    }
}

// ---------------------------------------------------------------------------
// Install
// ---------------------------------------------------------------------------

void install_geometry_engine(CompositeEditController& controller) {
    controller.set_geometry_ops(
        std::make_shared<QgisCompositeGeometryOps>());
    controller.topology().set_validate_fn(&qgis_validate_geometry);
    controller.topology().set_validate_many_fn(&qgis_validate_geometries);
}

}  // namespace pwb::ui_composite::qgis
