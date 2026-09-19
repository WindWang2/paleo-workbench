#include "pwb/ui_data_core/map_edit_geometry.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <random>
#include <set>
#include <stdexcept>
#include <unordered_map>

namespace pwb::ui_data_core {
namespace {

double orient(const MapPoint& p, const MapPoint& q, const MapPoint& r) {
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
}

bool on_segment(const MapPoint& p, const MapPoint& q, const MapPoint& r) {
    return std::min(p[0], r[0]) - 1e-12 <= q[0] &&
           q[0] <= std::max(p[0], r[0]) + 1e-12 &&
           std::min(p[1], r[1]) - 1e-12 <= q[1] &&
           q[1] <= std::max(p[1], r[1]) + 1e-12;
}

bool point_in(const MapPoint& p, const MapPoint& a, const MapPoint& b) {
    return p == a || p == b;
}

domain::Json intersection_issue(int i0, int i1, int j0, int j1) {
    domain::Json issue = domain::Json::object();
    issue["code"] = "self_intersection";
    issue["message"] = "Edges " + std::to_string(i0) + "-" +
                       std::to_string(i1) + " and " + std::to_string(j0) +
                       "-" + std::to_string(j1) + " intersect";
    issue["edges"] = domain::Json::array(
        {domain::Json::array({i0, i1}), domain::Json::array({j0, j1})});
    return issue;
}

}  // namespace

// ---------------------------------------------------------------------------
// Coercion
// ---------------------------------------------------------------------------

std::optional<double> json_float(const domain::Json& value) {
    if (value.is_number()) {
        return value.get<double>();
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? 1.0 : 0.0;
    }
    if (value.is_string()) {
        // float(str): surrounding whitespace allowed; the whole payload
        // must parse ("nan"/"inf" spellings accepted like Python).
        const std::string text = value.get<std::string>();
        const auto first = text.find_first_not_of(" \t\n\r\v\f");
        if (first == std::string::npos) {
            return std::nullopt;
        }
        try {
            std::size_t used = 0;
            const double parsed = std::stod(text.substr(first), &used);
            const std::string rest = text.substr(first + used);
            if (rest.find_first_not_of(" \t\n\r\v\f") != std::string::npos) {
                return std::nullopt;
            }
            return parsed;
        } catch (...) {
            return std::nullopt;
        }
    }
    return std::nullopt;
}

bool json_is_point(const domain::Json& value) {
    return value.is_array() && value.size() >= 2 && !value[0].is_array() &&
           !value[1].is_array();
}

MapRing ring_to_pts(const domain::Json& ring) {
    MapRing out;
    if (!ring.is_array()) {
        return out;
    }
    for (const auto& p : ring) {
        if (!p.is_array() || p.size() < 2) {
            continue;
        }
        const auto x = json_float(p[0]);
        const auto y = json_float(p[1]);
        if (!x.has_value() || !y.has_value()) {
            continue;
        }
        out.push_back({*x, *y});
    }
    return out;
}

MapRing coerce_ring(const domain::Json& value) {
    MapRing ring;
    if (!value.is_array()) {
        return ring;
    }
    for (const auto& point : value) {
        if (!json_is_point(point)) {
            return {};
        }
        const auto x = json_float(point[0]);
        const auto y = json_float(point[1]);
        // _is_point admitted the shape; a non-floatable member raises
        // TypeError/ValueError in Python — propagate as invalid_argument.
        if (!x.has_value() || !y.has_value()) {
            throw std::invalid_argument(
                "coerce_ring: non-numeric point member");
        }
        ring.push_back({*x, *y});
    }
    if (!ring.empty() && ring.front() != ring.back()) {
        ring.push_back(ring.front());
    }
    return ring;
}

MapRing json_ring(const domain::Json& ring) {
    return ring_to_pts(ring);
}

domain::Json ring_to_json(const MapRing& ring) {
    domain::Json out = domain::Json::array();
    for (const auto& p : ring) {
        out.push_back(domain::Json::array({p[0], p[1]}));
    }
    return out;
}

domain::Json polygon_to_json(const MapPolygon& polygon) {
    domain::Json out = domain::Json::array();
    for (const auto& ring : polygon) {
        out.push_back(ring_to_json(ring));
    }
    return out;
}

domain::Json multipolygon_to_json(const MapMultiPolygon& polygons) {
    domain::Json out = domain::Json::array();
    for (const auto& polygon : polygons) {
        out.push_back(polygon_to_json(polygon));
    }
    return out;
}

// ---------------------------------------------------------------------------
// snap_point
// ---------------------------------------------------------------------------

MapPoint snap_point(const std::vector<MapPoint>& candidates, double x,
                    double y, double tol) {
    const double px = x;
    const double py = y;
    if (candidates.empty()) {
        return {px, py};
    }
    const double tol_f = std::max(0.0, tol);
    double best_d2 = tol_f * tol_f;
    bool have_best = false;
    MapPoint best{px, py};
    for (const auto& c : candidates) {
        const double dx = c[0] - px;
        const double dy = c[1] - py;
        const double d2 = dx * dx + dy * dy;
        if (d2 <= best_d2) {
            best_d2 = d2;
            best = c;
            have_best = true;
        }
    }
    return have_best ? best : MapPoint{px, py};
}

// ---------------------------------------------------------------------------
// Ring validation
// ---------------------------------------------------------------------------

bool segments_properly_intersect(const MapPoint& a1, const MapPoint& a2,
                                 const MapPoint& b1, const MapPoint& b2) {
    const double o1 = orient(a1, a2, b1);
    const double o2 = orient(a1, a2, b2);
    const double o3 = orient(b1, b2, a1);
    const double o4 = orient(b1, b2, a2);

    if (o1 * o2 < 0.0 && o3 * o4 < 0.0) {
        return true;
    }

    constexpr double eps = 1e-12;
    if (std::abs(o1) <= eps && on_segment(a1, b1, a2) &&
        !point_in(b1, a1, a2)) {
        return true;
    }
    if (std::abs(o2) <= eps && on_segment(a1, b2, a2) &&
        !point_in(b2, a1, a2)) {
        return true;
    }
    if (std::abs(o3) <= eps && on_segment(b1, a1, b2) &&
        !point_in(a1, b1, b2)) {
        return true;
    }
    if (std::abs(o4) <= eps && on_segment(b1, a2, b2) &&
        !point_in(a2, b1, b2)) {
        return true;
    }
    return false;
}

std::optional<ParsedRing> ring_points_and_edges(const MapRing& ring) {
    // Python validates list inputs of len >= 4; callers pre-coerce to
    // MapRing so every entry is a point already.
    if (ring.size() < 4) {
        return std::nullopt;
    }
    ParsedRing parsed;
    parsed.points = ring;
    parsed.closed = ring.front() == ring.back();
    parsed.n = parsed.closed ? static_cast<int>(ring.size()) - 1
                             : static_cast<int>(ring.size());
    if (parsed.n < 3) {
        return std::nullopt;
    }
    for (int i = 0; i < parsed.n - 1; ++i) {
        parsed.edges.emplace_back(i, i + 1);
    }
    if (parsed.closed) {
        parsed.edges.emplace_back(parsed.n - 1, 0);
    }
    return parsed;
}

domain::Json validate_ring(const MapRing& ring) {
    domain::Json issues = domain::Json::array();
    const auto parsed = ring_points_and_edges(ring);
    if (!parsed.has_value()) {
        return issues;
    }
    const auto& [pts, closed, n, edges] = *parsed;
    for (std::size_t ei = 0; ei < edges.size(); ++ei) {
        const auto [i0, i1] = edges[ei];
        for (std::size_t ej = ei + 1; ej < edges.size(); ++ej) {
            const auto [j0, j1] = edges[ej];
            if (i0 == j0 || i0 == j1 || i1 == j0 || i1 == j1) {
                continue;  // adjacent edges share a vertex
            }
            if (segments_properly_intersect(pts[i0], pts[i1], pts[j0],
                                            pts[j1])) {
                issues.push_back(intersection_issue(i0, i1, j0, j1));
                return issues;  // one is enough for V1 warnings
            }
        }
    }
    return issues;
}

domain::Json validate_ring_local(
    const MapRing& ring, const std::vector<long long>& moved_vertex_indices) {
    domain::Json issues = domain::Json::array();
    const auto parsed = ring_points_and_edges(ring);
    if (!parsed.has_value()) {
        return issues;
    }
    const auto& [pts, closed, n, edges] = *parsed;
    const long long ring_len = static_cast<long long>(pts.size());

    std::set<int> changed_edges;
    for (const long long raw_idx : moved_vertex_indices) {
        if (raw_idx < 0 || raw_idx >= ring_len) {
            continue;
        }
        long long v = raw_idx;
        if (closed && v == ring_len - 1) {
            v = 0;  // closing duplicate is vertex 0
        }
        if (v < 0 || v >= n) {
            continue;
        }
        for (std::size_t e = 0; e < edges.size(); ++e) {
            if (edges[e].first == v || edges[e].second == v) {
                changed_edges.insert(static_cast<int>(e));
            }
        }
    }

    for (const int ei : changed_edges) {
        const auto [i0, i1] = edges[ei];
        for (std::size_t ej = 0; ej < edges.size(); ++ej) {
            if (static_cast<int>(ej) == ei) {
                continue;
            }
            const auto [j0, j1] = edges[ej];
            if (i0 == j0 || i0 == j1 || i1 == j0 || i1 == j1) {
                continue;
            }
            if (segments_properly_intersect(pts[i0], pts[i1], pts[j0],
                                            pts[j1])) {
                issues.push_back(intersection_issue(i0, i1, j0, j1));
                return issues;
            }
        }
    }
    return issues;
}

// ---------------------------------------------------------------------------
// validate_adjacency
// ---------------------------------------------------------------------------

domain::Json validate_adjacency(const std::vector<MapRing>& rings,
                                double gap_tol) {
    domain::Json issues = domain::Json::array();
    if (rings.size() < 2) {
        return issues;
    }
    struct Prepared {
        std::vector<MapPoint> pts;
        double min_x, min_y, max_x, max_y;
    };
    std::vector<Prepared> prepared;
    for (const auto& ring : rings) {
        if (ring.size() < 2) {
            continue;
        }
        Prepared prep;
        prep.pts = ring;
        double min_x = ring[0][0], max_x = ring[0][0];
        double min_y = ring[0][1], max_y = ring[0][1];
        for (const auto& p : ring) {
            min_x = std::min(min_x, p[0]);
            max_x = std::max(max_x, p[0]);
            min_y = std::min(min_y, p[1]);
            max_y = std::max(max_y, p[1]);
        }
        prep.min_x = min_x;
        prep.min_y = min_y;
        prep.max_x = max_x;
        prep.max_y = max_y;
        prepared.push_back(std::move(prep));
    }

    const double tol = std::max(0.0, gap_tol);
    // x-interval sweep over tol-expanded bboxes (identical candidate set to
    // the O(n²) scan; y-overlap re-checked below).
    std::set<std::pair<int, int>> candidate_pairs;
    std::vector<int> order(prepared.size());
    for (std::size_t i = 0; i < order.size(); ++i) {
        order[i] = static_cast<int>(i);
    }
    std::sort(order.begin(), order.end(), [&](int a, int b) {
        return prepared[a].min_x < prepared[b].min_x;
    });
    std::vector<int> active;
    for (const int i : order) {
        const double min_x = prepared[i].min_x;
        active.erase(std::remove_if(active.begin(), active.end(),
                                    [&](int j) {
                                        return prepared[j].max_x + tol < min_x;
                                    }),
                     active.end());
        for (const int j : active) {
            if (!(prepared[i].max_y + tol < prepared[j].min_y ||
                  prepared[j].max_y + tol < prepared[i].min_y)) {
                candidate_pairs.insert(
                    j < i ? std::pair{j, i} : std::pair{i, j});
            }
        }
        active.push_back(i);
    }

    for (const auto& [i, j] : candidate_pairs) {
        const auto& pts_i = prepared[i].pts;
        const auto& pts_j = prepared[j].pts;
        const auto& bb_i = prepared[i];
        const auto& bb_j = prepared[j];
        bool connected = false;
        for (const auto& a : pts_i) {
            for (const auto& b : pts_j) {
                const double dx = a[0] - b[0];
                const double dy = a[1] - b[1];
                if (dx * dx + dy * dy <= tol * tol) {
                    connected = true;
                    break;
                }
            }
            if (connected) {
                break;
            }
        }
        const bool core_overlap =
            !(bb_i.max_x < bb_j.min_x || bb_j.max_x < bb_i.min_x ||
              bb_i.max_y < bb_j.min_y || bb_j.max_y < bb_i.min_y);
        if (core_overlap && !connected) {
            domain::Json issue = domain::Json::object();
            issue["code"] = "adjacency_overlap";
            issue["message"] = "Rings " + std::to_string(i) + " and " +
                               std::to_string(j) +
                               " may overlap without shared nodes";
            issue["pair"] = domain::Json::array({i, j});
            issues.push_back(std::move(issue));
        } else if (!core_overlap && !connected) {
            domain::Json issue = domain::Json::object();
            issue["code"] = "adjacency_gap";
            issue["message"] = "Rings " + std::to_string(i) + " and " +
                               std::to_string(j) +
                               " are near but not connected";
            issue["pair"] = domain::Json::array({i, j});
            issues.push_back(std::move(issue));
        }
    }
    return issues;
}

// ---------------------------------------------------------------------------
// snap_shared_nodes / rebuild_topology
// ---------------------------------------------------------------------------

std::vector<std::pair<int, int>> near_vertex_pairs(
    const std::vector<MapPoint>& coords, double tol) {
    std::vector<std::pair<int, int>> pairs;
    const int n = static_cast<int>(coords.size());
    if (n < 2) {
        return pairs;
    }
    const double tol2 = tol * tol;
    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            const double dx = coords[i][0] - coords[j][0];
            const double dy = coords[i][1] - coords[j][1];
            if (dx * dx + dy * dy <= tol2) {
                pairs.emplace_back(i, j);
            }
        }
    }
    return pairs;
}

std::vector<MapRing> snap_shared_nodes(const std::vector<MapRing>& rings,
                                       double tol) {
    if (rings.empty()) {
        return {};
    }
    const double tol_f = std::max(0.0, tol);
    // prepared = [_ring_to_pts(r) for r in rings] — rings are typed already.
    std::vector<std::pair<int, int>> refs;  // (ring_i, vertex_j)
    std::vector<MapPoint> coords;
    for (std::size_t ri = 0; ri < rings.size(); ++ri) {
        for (std::size_t vi = 0; vi < rings[ri].size(); ++vi) {
            refs.emplace_back(static_cast<int>(ri), static_cast<int>(vi));
            coords.push_back(rings[ri][vi]);
        }
    }
    const int n = static_cast<int>(coords.size());
    if (n == 0) {
        return rings;
    }
    std::vector<int> parent(n);
    for (int i = 0; i < n; ++i) {
        parent[i] = i;
    }
    const auto find = [&parent](int i) {
        while (parent[i] != i) {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        return i;
    };
    const double tol2 = tol_f * tol_f;
    for (const auto& [i, j] : near_vertex_pairs(coords, tol_f)) {
        const double dx = coords[i][0] - coords[j][0];
        const double dy = coords[i][1] - coords[j][1];
        if (dx * dx + dy * dy <= tol2) {
            const int ra = find(i);
            const int rb = find(j);
            if (ra != rb) {
                parent[rb] = ra;
            }
        }
    }
    std::unordered_map<int, std::vector<int>> clusters;
    for (int i = 0; i < n; ++i) {
        clusters[find(i)].push_back(i);
    }
    std::unordered_map<int, MapPoint> reps;
    for (const auto& [root, members] : clusters) {
        double sx = 0.0;
        double sy = 0.0;
        for (const int m : members) {
            sx += coords[m][0];
            sy += coords[m][1];
        }
        const double k = static_cast<double>(members.size());
        reps[root] = {sx / k, sy / k};
    }
    std::vector<MapRing> out = rings;
    for (int idx = 0; idx < n; ++idx) {
        const auto [ri, vi] = refs[idx];
        out[ri][vi] = reps[find(idx)];
    }
    return out;
}

TopologyRebuildReport rebuild_topology(const std::vector<MapRing>& rings,
                                       double snap_tol,
                                       std::optional<double> gap_tol) {
    TopologyRebuildReport report;
    report.rings = snap_shared_nodes(rings, snap_tol);
    report.changed = report.rings != rings;
    for (std::size_t i = 0; i < report.rings.size(); ++i) {
        domain::Json ring_issues = validate_ring(report.rings[i]);
        if (!ring_issues.empty()) {
            domain::Json entry = domain::Json::object();
            entry["index"] = static_cast<long long>(i);
            entry["issues"] = std::move(ring_issues);
            report.ring_issues.push_back(std::move(entry));
        }
    }
    const double adj_tol = gap_tol.has_value() ? *gap_tol : snap_tol;
    report.adjacency_issues = validate_adjacency(report.rings, adj_tol);
    return report;
}

// ---------------------------------------------------------------------------
// Shapely-bound seam wrappers
// ---------------------------------------------------------------------------

std::optional<MapRing> merge_rings(const MapRing& ring_a,
                                   const MapRing& ring_b,
                                   MapGeometryBackend* backend) {
    if (ring_a.size() < 3 || ring_b.size() < 3) {
        return std::nullopt;
    }
    if (backend == nullptr) {
        return std::nullopt;  // no shapely → Python returns None
    }
    try {
        return backend->merge_rings(ring_a, ring_b);
    } catch (...) {
        return std::nullopt;  // merge failure → None
    }
}

std::optional<std::vector<MapRing>> split_ring_by_line(
    const MapRing& ring, const MapRing& line, MapGeometryBackend* backend) {
    if (ring.size() < 3 || line.size() < 2) {
        return std::nullopt;
    }
    if (backend == nullptr) {
        return std::nullopt;
    }
    try {
        auto parts = backend->split_ring_by_line(ring, line);
        if (!parts.has_value() || parts->size() < 2) {
            return std::nullopt;
        }
        return parts;
    } catch (...) {
        return std::nullopt;
    }
}

domain::Json validate_polygon_geometry(std::string_view geometry_type,
                                       const domain::Json& coordinates,
                                       MapGeometryBackend* backend) {
    domain::Json issues = domain::Json::array();
    if (geometry_type != "Polygon" && geometry_type != "MultiPolygon") {
        domain::Json issue = domain::Json::object();
        issue["code"] = "unsupported_geometry";
        issue["message"] = "Expected Polygon or MultiPolygon";
        issues.push_back(std::move(issue));
        return issues;
    }
    if (backend == nullptr) {
        return issues;  // ImportError → []
    }
    try {
        return backend->shape_issues(geometry_type, coordinates);
    } catch (...) {
        return issues;
    }
}

// ---------------------------------------------------------------------------
// geometry_schema helpers
// ---------------------------------------------------------------------------

std::pair<std::string, MapMultiPolygon> canonical_facies_geometry(
    const domain::Json& raw) {
    const domain::Json empty_obj = domain::Json::object();
    const domain::Json empty_arr = domain::Json::array();

    // geometry = raw.get("geometry") if isinstance(dict) else {}
    const domain::Json* geometry = &empty_obj;
    if (raw.is_object()) {
        const auto it = raw.find("geometry");
        if (it != raw.end() && it->is_object()) {
            geometry = &*it;
        }
    }

    // geometry_type = str(raw.get("geometry_type") or geometry.get("type")
    //                     or "")
    const domain::Json* type_value = nullptr;
    if (raw.is_object()) {
        const auto it = raw.find("geometry_type");
        if (it != raw.end() && json_truthy(*it)) {
            type_value = &*it;
        }
    }
    if (type_value == nullptr) {
        const auto it = geometry->find("type");
        if (it != geometry->end() && json_truthy(*it)) {
            type_value = &*it;
        }
    }
    const std::string raw_geometry_type =
        type_value != nullptr ? json_str(*type_value) : "";

    // coordinates = geometry.get("coordinates") if geometry else
    //               raw.get("coordinates");  then ``coordinates or []``.
    const domain::Json* coordinates = &empty_arr;
    if (json_truthy(*geometry)) {
        const auto it = geometry->find("coordinates");
        if (it != geometry->end()) {
            coordinates = &*it;
        }
    } else if (raw.is_object()) {
        const auto it = raw.find("coordinates");
        if (it != raw.end()) {
            coordinates = &*it;
        }
    }
    if (!json_truthy(*coordinates)) {
        coordinates = &empty_arr;
    }

    std::string geometry_type = raw_geometry_type;
    if (geometry_type != "Polygon" && geometry_type != "MultiPolygon") {
        if (coordinates->is_array() && !coordinates->empty()) {
            const auto& first = (*coordinates)[0];
            if (json_is_point(first)) {
                geometry_type = "Polygon";
            } else if (first.is_array() && !first.empty() &&
                       json_is_point(first[0])) {
                geometry_type = "Polygon";
            } else {
                geometry_type = "MultiPolygon";
            }
        } else {
            geometry_type = "Polygon";
        }
    }

    std::vector<domain::Json> source_polygons;
    if (geometry_type == "Polygon") {
        if (coordinates->is_array() && !coordinates->empty() &&
            json_is_point((*coordinates)[0])) {
            // [[coordinates]] — one polygon, one ring of raw points.
            source_polygons.push_back(domain::Json::array({*coordinates}));
        } else {
            // [*coordinates] — one polygon whose entries coerce as rings.
            domain::Json polygon = domain::Json::array();
            if (coordinates->is_array()) {
                for (const auto& ring : *coordinates) {
                    polygon.push_back(ring);
                }
            }
            source_polygons.push_back(std::move(polygon));
        }
    } else if (coordinates->is_array()) {
        for (const auto& polygon : *coordinates) {
            source_polygons.push_back(polygon);
        }
    }

    MapMultiPolygon polygons;
    for (const auto& source_polygon : source_polygons) {
        if (!source_polygon.is_array()) {
            continue;
        }
        MapPolygon rings;
        for (const auto& source_ring : source_polygon) {
            MapRing ring = coerce_ring(source_ring);
            if (!ring.empty()) {
                rings.push_back(std::move(ring));
            }
        }
        if (!rings.empty()) {
            polygons.push_back(std::move(rings));
        }
    }
    return {geometry_type, std::move(polygons)};
}

domain::Json compact_facies_coordinates(std::string_view geometry_type,
                                        const MapMultiPolygon& polygons) {
    if (geometry_type == "Polygon") {
        static const MapPolygon empty_polygon;
        const MapPolygon& rings =
            polygons.empty() ? empty_polygon : polygons.front();
        if (rings.size() == 1) {
            return ring_to_json(rings.front());
        }
        return polygon_to_json(rings);
    }
    return multipolygon_to_json(polygons);
}

std::string new_feature_id(std::string_view prefix) {
    static std::mt19937_64 rng{std::random_device{}()};
    std::string hex;
    hex.reserve(12);
    static constexpr char digits[] = "0123456789abcdef";
    for (int i = 0; i < 12; ++i) {
        hex.push_back(digits[rng() & 0xfU]);
    }
    return std::string(prefix) + "_" + hex;
}

bool coordinate_status_is_flagged(std::string_view status) {
    return status != "ok";
}

}  // namespace pwb::ui_data_core
