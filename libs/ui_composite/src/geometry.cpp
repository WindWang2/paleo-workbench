#include "pwb/ui_composite/geometry.hpp"

#include <cmath>
#include <cstdlib>
#include <limits>
#include <set>
#include <stdexcept>

namespace pwb::ui_composite {

namespace {

bool is_number(const Json& value) {
    return value.is_number() || value.is_boolean();
}

double number_value(const Json& value) {
    if (value.is_boolean())
        return value.get<bool>() ? 1.0 : 0.0;
    return value.get<double>();
}

// _point parity: [x, y] with >= 2 numeric items.
std::optional<MapPoint> as_point(const Json& value) {
    if (!value.is_array() || value.size() < 2)
        return std::nullopt;
    const Json& x = value[0];
    const Json& y = value[1];
    if (x.is_array() || y.is_array())
        return std::nullopt;
    if (!is_number(x) || !is_number(y))
        return std::nullopt;
    double px = number_value(x);
    double py = number_value(y);
    if (!std::isfinite(px) || !std::isfinite(py))
        return std::nullopt;
    return MapPoint{px, py};
}

bool ray_crosses(double x, double y, const MapRing& ring) {
    bool crosses = false;
    const size_t count = ring.size();
    for (size_t index = 0; index < count; ++index) {
        const double x1 = ring[index][0];
        const double y1 = ring[index][1];
        const double x2 = ring[(index + 1) % count][0];
        const double y2 = ring[(index + 1) % count][1];
        if ((y1 > y) != (y2 > y)) {
            const double t = (y - y1) / (y2 - y1);
            if (x < x1 + t * (x2 - x1))
                crosses = !crosses;
        }
    }
    return crosses;
}

void collect_vertices(const Json& node, std::vector<int> path,
                      std::vector<VertexVisit>& out) {
    if (auto point = as_point(node)) {
        out.push_back(VertexVisit{*point, std::move(path)});
        return;
    }
    if (!node.is_array())
        return;
    for (size_t index = 0; index < node.size(); ++index) {
        path.push_back(static_cast<int>(index));
        collect_vertices(node[index], path, out);
        path.pop_back();
    }
}

void walk_leaf_points(const Json& node, std::vector<MapPoint>& out) {
    if (!node.is_array())
        return;
    if (auto point = as_point(node)) {
        out.push_back(*point);
        return;
    }
    for (const auto& child : node)
        walk_leaf_points(child, out);
}

}  // namespace

double distance_to_segment(const MapPoint& point, const MapPoint& start,
                           const MapPoint& end) {
    const double px = point[0], py = point[1];
    const double x1 = start[0], y1 = start[1];
    const double x2 = end[0], y2 = end[1];
    const double dx = x2 - x1, dy = y2 - y1;
    const double norm = dx * dx + dy * dy;
    if (norm <= 1e-18)
        return std::hypot(px - x1, py - y1);
    const double t =
        std::max(0.0, std::min(1.0, ((px - x1) * dx + (py - y1) * dy) / norm));
    return std::hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

bool point_in_ring_scalar(double x, double y, const MapRing& ring) {
    return ray_crosses(x, y, ring);
}

bool point_in_ring_scalar_inclusive(double x, double y, const MapRing& ring,
                                    double epsilon) {
    if (ring.size() < 3)
        return false;
    double previous_x = ring.back()[0];
    double previous_y = ring.back()[1];
    bool inside = false;
    for (const auto& current : ring) {
        const double current_x = current[0];
        const double current_y = current[1];
        const double cross = (current_x - previous_x) * (y - previous_y) -
                             (current_y - previous_y) * (x - previous_x);
        const double segment_len =
            std::hypot(current_x - previous_x, current_y - previous_y);
        if (std::abs(cross) <= epsilon * std::max(1.0, segment_len) &&
            std::min(previous_x, current_x) - epsilon <= x &&
            x <= std::max(previous_x, current_x) + epsilon &&
            std::min(previous_y, current_y) - epsilon <= y &&
            y <= std::max(previous_y, current_y) + epsilon) {
            return true;
        }
        if ((current_y > y) != (previous_y > y)) {
            const double crossing_x =
                (previous_x - current_x) * (y - current_y) /
                    (previous_y - current_y) +
                current_x;
            if (x < crossing_x)
                inside = !inside;
        }
        previous_x = current_x;
        previous_y = current_y;
    }
    return inside;
}

bool point_in_polygon_scalar(const MapPoint& point, const Json& polygon) {
    const std::string geom_type =
        polygon.value("type", Json("")).get<std::string>();
    Json polygons = Json::array();
    if (geom_type == "Polygon") {
        polygons.push_back(polygon.value("coordinates", Json::array()));
    } else if (geom_type == "MultiPolygon") {
        polygons = polygon.value("coordinates", Json::array());
    } else {
        throw std::invalid_argument("point_in_polygon needs a polygon, got " +
                                    geom_type);
    }
    const double x = point[0], y = point[1];
    for (const auto& rings_value : polygons) {
        if (!rings_value.is_array() || rings_value.empty())
            continue;
        const MapRing exterior = pwb::ui_data_core::ring_to_pts(rings_value[0]);
        if (!ray_crosses(x, y, exterior))
            continue;
        bool in_hole = false;
        for (size_t hole = 1; hole < rings_value.size(); ++hole) {
            if (ray_crosses(x, y,
                            pwb::ui_data_core::ring_to_pts(rings_value[hole]))) {
                in_hole = true;
                break;
            }
        }
        if (!in_hole)
            return true;
    }
    return false;
}

std::optional<MapExtent> extent_of_coordinates(
    const std::vector<MapPoint>& coords) {
    double xmin = std::numeric_limits<double>::infinity();
    double ymin = std::numeric_limits<double>::infinity();
    double xmax = -std::numeric_limits<double>::infinity();
    double ymax = -std::numeric_limits<double>::infinity();
    bool has = false;
    for (const auto& coord : coords) {
        const double x = coord[0], y = coord[1];
        if (!std::isfinite(x) || !std::isfinite(y))
            continue;
        has = true;
        xmin = std::min(xmin, x);
        ymin = std::min(ymin, y);
        xmax = std::max(xmax, x);
        ymax = std::max(ymax, y);
    }
    if (!has)
        return std::nullopt;
    return MapExtent{xmin, ymin, xmax, ymax};
}

std::optional<MapExtent> extent_of_geometries(
    const std::vector<Json>& geometries) {
    std::vector<MapPoint> coords;
    for (const auto& geometry : geometries) {
        if (!geometry.is_object())
            continue;
        const auto it = geometry.find("coordinates");
        if (it == geometry.end())
            continue;
        walk_leaf_points(*it, coords);
    }
    return extent_of_coordinates(coords);
}

std::optional<double> json_as_float(const Json& value) {
    if (value.is_number())
        return value.get<double>();
    if (value.is_boolean())
        return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_string()) {
        const std::string text = value.get<std::string>();
        if (text.empty())
            return std::nullopt;
        char* end = nullptr;
        const double parsed = std::strtod(text.c_str(), &end);
        if (end == text.c_str())
            return std::nullopt;
        // Python float() accepts leading/trailing whitespace and rejects
        // trailing junk — require the whole (stripped) string to parse.
        while (*end == ' ' || *end == '\t')
            ++end;
        if (*end != '\0')
            return std::nullopt;
        return parsed;
    }
    return std::nullopt;
}

std::optional<MapPoint> json_point(const Json& value) {
    return as_point(value);
}

Json coords_to_lists(const Json& value) {
    return value;
}

std::vector<VertexVisit> ring_vertices(const Json& rings) {
    std::vector<VertexVisit> out;
    if (!rings.is_array())
        return out;
    for (size_t ring_index = 0; ring_index < rings.size(); ++ring_index) {
        const Json& ring = rings[ring_index];
        if (!ring.is_array())
            continue;
        for (size_t point_index = 0; point_index < ring.size();
             ++point_index) {
            if (auto point = as_point(ring[point_index])) {
                out.push_back(VertexVisit{
                    *point,
                    {static_cast<int>(ring_index),
                     static_cast<int>(point_index)}});
            }
        }
    }
    return out;
}

std::vector<std::pair<MapPoint, MapPoint>> geometry_segments(
    const Json& coordinates) {
    std::vector<MapPoint> points;
    walk_leaf_points(coordinates, points);
    std::vector<std::pair<MapPoint, MapPoint>> segments;
    for (size_t index = 0; index + 1 < points.size(); ++index)
        segments.emplace_back(points[index], points[index + 1]);
    return segments;
}

namespace {

double point_distance(const MapPoint& a, const MapPoint& b) {
    return std::hypot(a[0] - b[0], a[1] - b[1]);
}

bool polygon_hit(const MapPoint& point, const Json& coordinates,
                 double tolerance) {
    if (!coordinates.is_array())
        return false;
    auto inside = [](const MapPoint& pt, const Json& ring_value) {
        if (!ring_value.is_array())
            return false;
        MapRing vertices;
        for (const auto& node : ring_value) {
            if (auto p = as_point(node))
                vertices.push_back(*p);
        }
        if (vertices.size() < 3)
            return false;
        return point_in_ring_scalar(pt[0], pt[1], vertices);
    };
    if (!coordinates.empty() && inside(point, coordinates[0])) {
        for (size_t hole = 1; hole < coordinates.size(); ++hole) {
            if (inside(point, coordinates[hole]))
                return false;
        }
        return true;
    }
    for (const auto& visit : ring_vertices(coordinates)) {
        if (point_distance(point, visit.point) <= tolerance)
            return true;
    }
    return false;
}

}  // namespace

bool geometry_hit(const MapPoint& point, const Json& geometry,
                  double tolerance) {
    const std::string kind =
        geometry.value("type", Json("")).get<std::string>();
    const Json coordinates = geometry.value("coordinates", Json());
    if (kind == "Point") {
        if (auto p = as_point(coordinates))
            return point_distance(point, *p) <= tolerance;
        return false;
    }
    if (kind == "LineString" || kind == "MultiLineString") {
        for (const auto& [start, end] : geometry_segments(coordinates)) {
            if (distance_to_segment(point, start, end) <= tolerance)
                return true;
        }
        return false;
    }
    if (kind == "Polygon")
        return polygon_hit(point, coordinates, tolerance);
    if (kind == "MultiPolygon") {
        if (!coordinates.is_array())
            return false;
        for (const auto& poly : coordinates) {
            if (polygon_hit(point, poly, tolerance))
                return true;
        }
        return false;
    }
    return false;
}

bool geometry_equal(const Json& left, const Json& right) {
    const std::string left_type = left.value("type", Json("")).get<std::string>();
    const std::string right_type =
        right.value("type", Json("")).get<std::string>();
    if (left_type != right_type)
        return false;
    const Json left_coords =
        coords_to_lists(left.value("coordinates", Json()));
    const Json right_coords =
        coords_to_lists(right.value("coordinates", Json()));
    return left_coords == right_coords;
}

MapExtent union_extent(const MapExtent& left, const MapExtent& right) {
    return {std::min(left[0], right[0]), std::min(left[1], right[1]),
            std::max(left[2], right[2]), std::max(left[3], right[3])};
}

MapExtent feature_extent(const std::vector<Json>& features) {
    std::vector<Json> geometries;
    for (const auto& feature : features) {
        if (!feature.is_object())
            continue;
        const auto it = feature.find("geometry");
        if (it != feature.end() && it->is_object())
            geometries.push_back(*it);
    }
    auto extent = extent_of_geometries(geometries);
    if (!extent)
        return {0.0, 0.0, 1.0, 1.0};
    return *extent;
}

int nearest_interior_ring(const Json& geometry, const MapPoint& point) {
    const Json coords = geometry.value("coordinates", Json::array());
    if (!coords.is_array() || coords.size() < 2)
        return -1;
    int best_index = -1;
    double best = std::numeric_limits<double>::infinity();
    for (size_t index = 1; index < coords.size(); ++index) {
        const Json& ring = coords[index];
        if (!ring.is_array() || ring.empty())
            continue;
        const size_t edges = ring.size() - 1;
        const auto first = as_point(ring[0]);
        const auto last = as_point(ring[ring.size() - 1]);
        const bool unclosed =
            first.has_value() && last.has_value() && *first != *last;
        const size_t total_edges =
            edges + ((unclosed && ring.size() >= 3) ? 1 : 0);
        for (size_t i = 0; i < total_edges; ++i) {
            const auto a = as_point(ring[i]);
            const auto b = as_point(ring[(i + 1) % ring.size()]);
            if (!a || !b)
                continue;
            const double d = distance_to_segment(point, *a, *b);
            if (d < best) {
                best = d;
                best_index = static_cast<int>(index);
            }
        }
    }
    return best_index;
}

int nearest_part(const Json& geometry, const MapPoint& point) {
    const std::string gtype = geometry.value("type", Json("")).get<std::string>();
    if (gtype.rfind("Multi", 0) != 0)
        return -1;
    const Json parts = geometry.value("coordinates", Json::array());
    if (!parts.is_array())
        return -1;
    int best_index = -1;
    double best = std::numeric_limits<double>::infinity();
    for (size_t index = 0; index < parts.size(); ++index) {
        const Json& part = parts[index];
        if (gtype == "MultiPoint") {
            if (auto p = as_point(part)) {
                const double d = point_distance(point, *p);
                if (d < best) {
                    best = d;
                    best_index = static_cast<int>(index);
                }
            }
            continue;
        }
        if (gtype == "MultiPolygon") {
            Json sub = {{"type", "Polygon"}, {"coordinates", part}};
            if (point_in_polygon_scalar(point, sub))
                return static_cast<int>(index);
        }
        const Json& ring = (gtype == "MultiPolygon" && part.is_array() &&
                            !part.empty())
                               ? part[0]
                               : part;
        if (!ring.is_array())
            continue;
        for (const auto& vertex_value : ring) {
            if (auto vertex = as_point(vertex_value)) {
                const double d = point_distance(point, *vertex);
                if (d < best) {
                    best = d;
                    best_index = static_cast<int>(index);
                }
            }
        }
    }
    return best_index;
}

Json plain_geometry(const Json& result) {
    if (result.is_object() && result.contains("type") &&
        result.contains("coordinates")) {
        return Json{{"type", result["type"]},
                    {"coordinates", result["coordinates"]}};
    }
    return result;
}

bool crs_parseable(const std::string& crs_in,
                   const CrsValidator& validator) {
    std::string crs = crs_in;
    const auto slash = crs.find('/');
    if (slash != std::string::npos)
        crs = crs.substr(0, slash);
    // strip
    const auto first = crs.find_first_not_of(" \t\r\n");
    const auto last = crs.find_last_not_of(" \t\r\n");
    const std::string text =
        first == std::string::npos ? "" : crs.substr(first, last - first + 1);
    if (text.empty())
        return false;
    if (!validator)
        return true;
    return validator(text);
}

std::vector<MapPoint> iter_feature_coords(const std::vector<Json>& features) {
    std::vector<MapPoint> out;
    for (const auto& feature : features) {
        if (!feature.is_object())
            continue;
        const auto git = feature.find("geometry");
        if (git == feature.end() || !git->is_object())
            continue;
        const auto cit = git->find("coordinates");
        if (cit == git->end())
            continue;
        walk_leaf_points(*cit, out);
    }
    return out;
}

}  // namespace pwb::ui_composite
