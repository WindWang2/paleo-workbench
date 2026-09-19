// qc.cpp — C++ port of paleo_workbench/workflow/qc.py (CONV-33, route A1).
//
// Parity anchors (line numbers refer to the frozen Python source):
//   make_issue                L27   field assembly + centroid locate chain
//   _geometry_centroid        L60   three-level fallback (facade area
//                                   centroid -> vertex-mean locate point for
//                                   degenerate/self-intersecting rings ->
//                                   no locate point for malformed input)
//   _vertex_mean_locate_point L77
//   _facies_ring              L104
//   _ring_to_polygon_geometry L122
//   _count_contour_lines      L129
//   _collect_issues           L142  six BASIC rules, Chinese messages verbatim
//   spatial_issues            L278
//   issue_layer_geojson       L289
//   _status_from_issues       L329
//   run_basic_qc              L338  stable-id upsert + active-run binding +
//                                   QcProvenanceSink best-effort (H3/H14)
//   active_quality_reports    L462  (coordinator pre-seeded; parity verified
//                                   against qc.py L462-472 — fall-through on
//                                   dangling active id, by_map first-seen key
//                                   order with last-report-wins value)
//   run_map_qc                L475  BASIC+EXTENDED merge, coverage honest
//
// Geometry sourcing decision: no C++ counterpart existed in libs/ for the two
// Python predicates qc.py leans on (ui_review's qc_issue_rows.cpp only mirrors
// spatial_issues truthiness; the mapping kernel's polygonization is not a
// header-exported dependency of workflow_runtime). Both are ported here as
// file-local helpers with the minimal pure semantics of their Python
// authorities — no loosening:
//   * validate_ring  <- geo-viz-engine/packages/geoviz_plots/
//     geoviz_plots/map_edit/api.py `_validate_ring_python` +
//     `_segments_properly_intersect` (qc.py L200-201 only consumes the
//     presence of code == "self_intersection").
//   * centroid facade <- paleo_workbench/mapping/geometry_operations.py
//     `centroid` (Point -> itself; lines -> vertex mean; polygons/multipolygons
//     -> shoelace area centroid with hole moment subtraction, degenerate
//     surfaces fail closed), backed by mapping/geological_pipeline/
//     polygonization.py `calculate_signed_area` / `ring_area_centroid`.
#include "pwb/workflow_runtime/qc.hpp"

#include "pwb/workflow_runtime/map_qa_rules.hpp"
#include "python_compat.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <functional>
#include <iterator>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_runtime {
namespace {

using domain::Json;

// ------------------------------------------------------- json micro-helpers

// Python dict.get(key) — missing key OR null value both read as None here.
const Json* member(const Json& obj, const char* key) {
    if (!obj.is_object()) {
        return nullptr;
    }
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) {
        return nullptr;
    }
    return &*it;
}

const Json* array_member(const Json& obj, const char* key) {
    const Json* value = member(obj, key);
    if (value == nullptr || !value->is_array()) {
        return nullptr;
    }
    return value;
}

// Python str(obj.get(key) or fallback) — first truthy value wins.
std::string truthy_str(const Json& obj, const char* key,
                       const std::string& fallback = {}) {
    const Json* value = member(obj, key);
    if (value != nullptr && pycompat::truthy(*value)) {
        return pycompat::str_scalar(*value);
    }
    return fallback;
}

// Python str() of a str-typed model field ("" when the Json view lost it).
std::string str_field(const Json& obj, const char* key) {
    const Json* value = member(obj, key);
    if (value != nullptr && value->is_string()) {
        return value->get<std::string>();
    }
    return {};
}

// Python float(v) on a json-loaded value: numbers (and, like
// isinstance(True, int), booleans) pass; strings parse only when fully
// numeric. Returns false where Python would raise TypeError/ValueError.
bool parse_float_like(const Json& value, double& out) {
    if (value.is_number()) {
        out = value.get<double>();
        return true;
    }
    if (value.is_boolean()) {
        out = value.get<bool>() ? 1.0 : 0.0;
        return true;
    }
    if (value.is_string()) {
        const std::string& text = value.get_ref<const std::string&>();
        char* end = nullptr;
        const double parsed = std::strtod(text.c_str(), &end);
        if (end != nullptr && end != text.c_str() &&
            *end == '\0' &&
            text.find_first_of(" \t\n\r\f\v") == std::string::npos) {
            out = parsed;
            return true;
        }
        return false;
    }
    return false;
}

bool is_numeric(const Json& value) {
    return value.is_number() || value.is_boolean();
}

double as_double(const Json& value) {
    if (value.is_boolean()) {
        return value.get<bool>() ? 1.0 : 0.0;
    }
    return value.get<double>();
}

std::string strip_ws(const std::string& value) {
    const char* ws = " \t\n\r\f\v";
    const std::size_t begin = value.find_first_not_of(ws);
    if (begin == std::string::npos) {
        return {};
    }
    const std::size_t end = value.find_last_not_of(ws);
    return value.substr(begin, end - begin + 1);
}

// Python f"{value:.2f}" lives in map_qa_rules.cpp (extent/confidence
// messages); qc.py itself formats no floats.

// ------------------------------------------- centroid facade (V8 M4 port) --
//
// geometry_operations.centroid: Point -> itself; LineString/MultiLineString
// -> vertex mean; Polygon/MultiPolygon -> shoelace area centroid with hole
// moment subtraction; anything else -> ValueError. The error channel mirrors
// the exception classes qc._geometry_centroid distinguishes: ValueError falls
// back to the vertex-mean locate point, TypeError/IndexError/KeyError mean
// "no locate point".

struct Pt {
    double x = 0.0;
    double y = 0.0;
};

enum class CentroidErr { kNone, kValue, kType };

// polygonization.calculate_signed_area (L31): 0.5 * sum over consecutive
// pairs; rings shorter than 3 vertices are area 0.
double signed_area(const std::vector<Pt>& ring) {
    const std::size_t n = ring.size();
    if (n < 3) {
        return 0.0;
    }
    double area2 = 0.0;
    for (std::size_t i = 0; i + 1 < n; ++i) {
        area2 += ring[i].x * ring[i + 1].y - ring[i + 1].x * ring[i].y;
    }
    return 0.5 * area2;
}

// polygonization.ring_area_centroid (L42): area centroid via the shoelace
// cross-moment; degenerate rings fall back to their first vertex.
Pt ring_area_centroid(const std::vector<Pt>& ring) {
    const std::size_t n = ring.size();
    if (n == 0) {
        return {0.0, 0.0};
    }
    double area2 = 0.0;
    double cx = 0.0;
    double cy = 0.0;
    for (std::size_t i = 0; i + 1 < n; ++i) {
        const double cross =
            ring[i].x * ring[i + 1].y - ring[i + 1].x * ring[i].y;
        area2 += cross;
        cx += (ring[i].x + ring[i + 1].x) * cross;
        cy += (ring[i].y + ring[i + 1].y) * cross;
    }
    // math.isclose(area2, 0.0, abs_tol=1e-12) with the default rel_tol.
    const double tolerance =
        std::max(1e-9 * std::max(std::fabs(area2), 0.0), 1e-12);
    if (std::fabs(area2) <= tolerance) {
        return {ring[0].x, ring[0].y};
    }
    return {cx / (3.0 * area2), cy / (3.0 * area2)};
}

bool centroid_facade(const Json& geometry, double& out_x, double& out_y,
                     CentroidErr& err) {
    err = CentroidErr::kNone;
    if (!geometry.is_object()) {
        err = CentroidErr::kType;
        return false;
    }
    const std::string geom_type = truthy_str(geometry, "type");
    const Json* coords = member(geometry, "coordinates");

    if (geom_type == "Point") {
        if (coords == nullptr || !coords->is_array()) {
            err = CentroidErr::kType;  // coords[0] on None -> TypeError
            return false;
        }
        double x = 0.0;
        double y = 0.0;
        if (coords->size() >= 2 && parse_float_like((*coords)[0], x) &&
            parse_float_like((*coords)[1], y)) {
            out_x = x;
            out_y = y;
            return true;
        }
        // IndexError/float()-ValueError: both end without a locate point for
        // Points (the vertex-mean fallback refuses the Point type).
        err = CentroidErr::kValue;
        return false;
    }

    if (geom_type == "LineString" || geom_type == "MultiLineString") {
        std::vector<const Json*> parts;
        if (geom_type == "LineString") {
            parts.push_back(coords);
        } else {
            if (coords == nullptr || !coords->is_array()) {
                err = CentroidErr::kType;  // list(None) -> TypeError
                return false;
            }
            for (const Json& part : *coords) {
                parts.push_back(&part);
            }
        }
        std::vector<Pt> vertices;
        for (const Json* part : parts) {
            if (part == nullptr || !part->is_array()) {
                continue;  // `for p in part or ()`
            }
            for (const Json& p : *part) {
                if (!p.is_array() || p.size() < 2) {
                    continue;
                }
                double x = 0.0;
                double y = 0.0;
                if (!parse_float_like(p[0], x) || !parse_float_like(p[1], y)) {
                    err = CentroidErr::kValue;  // float(str) -> ValueError
                    return false;
                }
                vertices.push_back({x, y});
            }
        }
        if (vertices.empty()) {
            err = CentroidErr::kValue;  // "centroid needs a non-empty
                                        // geometry"
            return false;
        }
        double sx = 0.0;
        double sy = 0.0;
        for (const Pt& v : vertices) {
            sx += v.x;
            sy += v.y;
        }
        out_x = sx / static_cast<double>(vertices.size());
        out_y = sy / static_cast<double>(vertices.size());
        return true;
    }

    if (geom_type == "Polygon" || geom_type == "MultiPolygon") {
        std::vector<const Json*> polys;
        if (geom_type == "Polygon") {
            polys.push_back(coords);
        } else {
            if (coords == nullptr || !coords->is_array()) {
                err = CentroidErr::kType;  // list(None) -> TypeError
                return false;
            }
            for (const Json& poly : *coords) {
                polys.push_back(&poly);
            }
        }
        double area_total = 0.0;
        double moment_x = 0.0;
        double moment_y = 0.0;
        for (const Json* rings : polys) {
            if (rings != nullptr && !rings->is_array()) {
                err = CentroidErr::kType;  // list(number) -> TypeError
                return false;
            }
            if (rings == nullptr || rings->empty()) {
                continue;
            }
            const Json& exterior_json = rings->front();
            if (!exterior_json.is_array()) {
                err = CentroidErr::kType;  // iterating a scalar -> TypeError
                return false;
            }
            std::vector<Pt> exterior;
            for (const Json& p : exterior_json) {
                if (!p.is_array() || p.size() < 2) {
                    continue;
                }
                double x = 0.0;
                double y = 0.0;
                if (!parse_float_like(p[0], x) || !parse_float_like(p[1], y)) {
                    // str * float inside the shoelace kernel -> TypeError.
                    err = CentroidErr::kType;
                    return false;
                }
                exterior.push_back({x, y});
            }
            if (exterior.empty()) {
                continue;
            }
            const double ext_area = std::fabs(signed_area(exterior));
            const Pt ext_c = ring_area_centroid(exterior);
            double part_area = ext_area;
            double part_moment_x = ext_c.x * ext_area;
            double part_moment_y = ext_c.y * ext_area;
            for (std::size_t h = 1; h < rings->size(); ++h) {
                const Json& hole_json = (*rings)[h];
                if (!hole_json.is_array()) {
                    err = CentroidErr::kType;
                    return false;
                }
                std::vector<Pt> hole;
                for (const Json& p : hole_json) {
                    if (!p.is_array() || p.size() < 2) {
                        continue;
                    }
                    double x = 0.0;
                    double y = 0.0;
                    if (!parse_float_like(p[0], x) ||
                        !parse_float_like(p[1], y)) {
                        err = CentroidErr::kType;
                        return false;
                    }
                    hole.push_back({x, y});
                }
                if (hole.empty()) {
                    continue;
                }
                const double hole_area = std::fabs(signed_area(hole));
                const Pt hole_c = ring_area_centroid(hole);
                part_area -= hole_area;
                part_moment_x -= hole_c.x * hole_area;
                part_moment_y -= hole_c.y * hole_area;
            }
            if (part_area > 0.0) {
                area_total += part_area;
                moment_x += part_moment_x;
                moment_y += part_moment_y;
            }
        }
        if (area_total <= 0.0) {
            err = CentroidErr::kValue;  // "centroid needs a non-degenerate
                                        // polygon"
            return false;
        }
        out_x = moment_x / area_total;
        out_y = moment_y / area_total;
        return true;
    }

    err = CentroidErr::kValue;  // unsupported geometry type
    return false;
}

// qc._vertex_mean_locate_point (L77): mean of every numeric vertex in the
// coordinates tree; Point and malformed coordinates have no fallback point.
bool vertex_mean_locate_point(const Json& geometry, double& out_x,
                              double& out_y) {
    if (!geometry.is_object()) {
        return false;
    }
    if (truthy_str(geometry, "type") == "Point") {
        return false;
    }
    const auto coords_it = geometry.find("coordinates");
    if (coords_it == geometry.end() || !coords_it->is_array()) {
        return false;
    }
    std::vector<Pt> vertices;
    std::function<void(const Json&)> iter_points = [&](const Json& node) {
        if (!node.is_array()) {
            return;
        }
        if (node.size() >= 2 && is_numeric(node[0]) && is_numeric(node[1])) {
            vertices.push_back({as_double(node[0]), as_double(node[1])});
            return;
        }
        for (const Json& child : node) {
            iter_points(child);
        }
    };
    iter_points(*coords_it);
    if (vertices.empty()) {
        return false;
    }
    double sx = 0.0;
    double sy = 0.0;
    for (const Pt& v : vertices) {
        sx += v.x;
        sy += v.y;
    }
    out_x = sx / static_cast<double>(vertices.size());
    out_y = sy / static_cast<double>(vertices.size());
    return true;
}

// qc._geometry_centroid (L60): facade -> ValueError fallback -> None.
bool geometry_centroid(const Json& geometry, double& out_x, double& out_y) {
    double x = 0.0;
    double y = 0.0;
    CentroidErr err = CentroidErr::kNone;
    if (centroid_facade(geometry, x, y, err)) {
        out_x = x;
        out_y = y;
        return true;
    }
    if (err == CentroidErr::kValue) {
        return vertex_mean_locate_point(geometry, out_x, out_y);
    }
    return false;
}

// ---------------------------------------- validate_ring port (geoviz V1) --
//
// Only the self_intersection presence is consumed downstream. Ports
// api.py `_segments_properly_intersect` + `_ring_points_and_edges` +
// `_validate_ring_python` (first issue short-circuits).

double orient(const Pt& p, const Pt& q, const Pt& r) {
    return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
}

bool point_on_segment(const Pt& p, const Pt& q, const Pt& r) {
    return std::min(p.x, r.x) - 1e-12 <= q.x &&
           q.x <= std::max(p.x, r.x) + 1e-12 &&
           std::min(p.y, r.y) - 1e-12 <= q.y &&
           q.y <= std::max(p.y, r.y) + 1e-12;
}

bool same_point(const Pt& a, const Pt& b) {
    return a.x == b.x && a.y == b.y;
}

bool segments_properly_intersect(const Pt& a1, const Pt& a2, const Pt& b1,
                                 const Pt& b2) {
    const double o1 = orient(a1, a2, b1);
    const double o2 = orient(a1, a2, b2);
    const double o3 = orient(b1, b2, a1);
    const double o4 = orient(b1, b2, a2);
    if (o1 * o2 < 0.0 && o3 * o4 < 0.0) {
        return true;
    }
    const double eps = 1e-12;
    if (std::fabs(o1) <= eps && point_on_segment(a1, b1, a2) &&
        !same_point(b1, a1) && !same_point(b1, a2)) {
        return true;
    }
    if (std::fabs(o2) <= eps && point_on_segment(a1, b2, a2) &&
        !same_point(b2, a1) && !same_point(b2, a2)) {
        return true;
    }
    if (std::fabs(o3) <= eps && point_on_segment(b1, a1, b2) &&
        !same_point(a1, b1) && !same_point(a1, b2)) {
        return true;
    }
    if (std::fabs(o4) <= eps && point_on_segment(b1, a2, b2) &&
        !same_point(a2, b1) && !same_point(a2, b2)) {
        return true;
    }
    return false;
}

bool ring_has_self_intersection(const Json& ring) {
    if (!ring.is_array() || ring.size() < 4) {
        return false;
    }
    std::vector<Pt> pts;
    pts.reserve(ring.size());
    for (const Json& p : ring) {
        if (!p.is_array() || p.size() < 2) {
            return false;
        }
        double x = 0.0;
        double y = 0.0;
        if (!parse_float_like(p[0], x) || !parse_float_like(p[1], y)) {
            return false;
        }
        pts.push_back({x, y});
    }
    const bool closed = same_point(pts.front(), pts.back());
    const std::size_t n = closed ? pts.size() - 1 : pts.size();
    if (n < 3) {
        return false;
    }
    std::vector<std::pair<std::size_t, std::size_t>> edges;
    for (std::size_t i = 0; i + 1 < n; ++i) {
        edges.emplace_back(i, i + 1);
    }
    if (closed) {
        edges.emplace_back(n - 1, 0);
    }
    for (std::size_t ei = 0; ei < edges.size(); ++ei) {
        for (std::size_t ej = ei + 1; ej < edges.size(); ++ej) {
            const auto [i0, i1] = edges[ei];
            const auto [j0, j1] = edges[ej];
            if (i0 == j0 || i0 == j1 || i1 == j0 || i1 == j1) {
                continue;  // adjacent edges share a vertex
            }
            if (segments_properly_intersect(pts[i0], pts[i1], pts[j0],
                                            pts[j1])) {
                return true;  // one issue is enough for V1 warnings
            }
        }
    }
    return false;
}

// ------------------------------------------------------ facies ring utils

// qc._facies_ring (L104): ring list, polygon-coordinate exterior, or the
// exterior of poly["geometry"] as a Polygon; null when nothing ring-shaped.
const Json* facies_ring(const Json& poly) {
    if (!poly.is_object()) {
        return nullptr;
    }
    const auto coords_it = poly.find("coordinates");
    if (coords_it != poly.end() && coords_it->is_array() &&
        !coords_it->empty()) {
        const Json& first = coords_it->front();
        if (first.is_number() || first.is_boolean()) {
            return nullptr;  // bool is isinstance-of-int in Python
        }
        if (first.is_array() && !first.empty() && first.front().is_number()) {
            return &*coords_it;
        }
        if (first.is_array() && !first.empty() && first.front().is_array()) {
            return &first;
        }
    }
    const auto geom_it = poly.find("geometry");
    if (geom_it != poly.end() && geom_it->is_object()) {
        const auto type_it = geom_it->find("type");
        if (type_it != geom_it->end() && type_it->is_string() &&
            type_it->get<std::string>() == "Polygon") {
            const auto rings_it = geom_it->find("coordinates");
            if (rings_it != geom_it->end() && rings_it->is_array() &&
                !rings_it->empty() && rings_it->front().is_array()) {
                return &rings_it->front();
            }
        }
    }
    return nullptr;
}

// qc._ring_to_polygon_geometry (L122): float-normalised closed polygon
// geometry built from the raw ring (used as the issue locate payload).
Json ring_to_polygon_geometry(const Json& ring) {
    Json coords = Json::array();
    for (const Json& p : ring) {
        if (!p.is_array() || p.size() < 2) {
            continue;
        }
        double x = 0.0;
        double y = 0.0;
        if (!parse_float_like(p[0], x) || !parse_float_like(p[1], y)) {
            continue;  // unreachable past a validating ring; Python raises
        }
        Json point = Json::array();
        point.push_back(x);
        point.push_back(y);
        coords.push_back(std::move(point));
    }
    if (!coords.empty()) {
        const Json& first = coords.front();
        const Json& last = coords.back();
        if (first[0].get<double>() != last[0].get<double>() ||
            first[1].get<double>() != last[1].get<double>()) {
            coords.push_back(first);
        }
    }
    Json coordinates = Json::array();
    coordinates.push_back(std::move(coords));
    Json geometry = Json::object();
    geometry["type"] = "Polygon";
    geometry["coordinates"] = std::move(coordinates);
    return geometry;
}

// qc._count_contour_lines (L129).
int count_contour_lines(const Json& document) {
    int n = 0;
    const Json* lines = array_member(document, "line_features");
    if (lines == nullptr) {
        return n;
    }
    for (const Json& feat : *lines) {
        if (!feat.is_object()) {
            continue;
        }
        const std::string role = truthy_str(feat, "role");
        std::string prop_role;
        const Json* props = member(feat, "properties");
        if (props != nullptr && props->is_object()) {
            const Json* r = member(*props, "role");
            if (r == nullptr || !pycompat::truthy(*r)) {
                r = member(*props, "constraint_role");
            }
            if (r != nullptr && pycompat::truthy(*r)) {
                prop_role = pycompat::str_scalar(*r);
            }
        }
        if (role == "contour" || prop_role == "contour") {
            ++n;
        }
    }
    return n;
}

// ------------------------------------------------- _collect_issues (L142) --

// Python float(row.x) / float(row.y) on the Json seam: the typed model can
// never lose x/y, a raw dict can — the defensive except (qc.py L260-261)
// degrades to a non-spatial issue.
bool parse_float_like_or(const Json& obj, const char* key, double& out) {
    const auto it = obj.find(key);
    if (it == obj.end()) {
        return false;
    }
    return parse_float_like(*it, out);
}

Json collect_issues(const Json& project, const Json& document) {
    Json issues = Json::array();
    const std::string document_id = str_field(document, "id");
    const std::string map_ref = "map:" + document_id;

    // 1) Target horizon (map-level, no geometry)
    const std::string horizon = strip_ws(truthy_str(document,
                                                    "linked_target_horizon"));
    if (horizon.empty()) {
        QcIssueFields fields;
        fields.feature_kind = "map";
        fields.feature_id = document_id;
        fields.ref = map_ref;
        issues.push_back(make_issue("target_horizon_present", "error",
                                    "古地理图未关联目标层位", fields));
    }

    // 2–3) Facies presence + per-polygon geometry
    const Json* facies = array_member(document, "facies_polygons");
    if (facies == nullptr || facies->empty()) {
        QcIssueFields fields;
        fields.feature_kind = "map";
        fields.feature_id = document_id;
        fields.ref = map_ref;
        issues.push_back(make_issue("facies_polygons_present", "warning",
                                    "古地理图尚无相带多边形", fields));
    } else {
        for (const Json& poly : *facies) {
            if (!poly.is_object()) {
                QcIssueFields fields;
                fields.feature_kind = "facies";
                fields.ref = map_ref;
                issues.push_back(make_issue("facies_geometry_valid", "error",
                                            "相带记录格式无效", fields));
                continue;
            }
            const std::string fid =
                truthy_str(poly, "id", truthy_str(poly, "name"));
            const Json* ring = facies_ring(poly);
            if (ring == nullptr || !ring->is_array() || ring->size() < 3) {
                QcIssueFields fields;
                if (!fid.empty()) {
                    fields.feature_id = fid;
                }
                fields.feature_kind = "facies";
                fields.ref =
                    !fid.empty() ? map_ref + "/facies/" + fid : map_ref;
                issues.push_back(
                    make_issue("facies_geometry_valid", "error",
                               "相带 " + (fid.empty() ? "?" : fid) +
                                   " 顶点不足或缺少坐标",
                               fields));
                continue;
            }
            if (ring_has_self_intersection(*ring)) {
                Json extra = Json::object();
                extra["code"] = "self_intersection";
                QcIssueFields fields;
                if (!fid.empty()) {
                    fields.feature_id = fid;
                }
                fields.feature_kind = "facies";
                fields.geometry = ring_to_polygon_geometry(*ring);
                fields.ref =
                    !fid.empty() ? map_ref + "/facies/" + fid : map_ref;
                fields.extra = std::move(extra);
                issues.push_back(
                    make_issue("facies_geometry_valid", "error",
                               "相带 " + (fid.empty() ? "?" : fid) + " 自相交",
                               fields));
            }
        }
    }

    // 4) Well overlays
    const Json* overlays = array_member(document, "well_overlays");
    if (overlays == nullptr || overlays->empty()) {
        QcIssueFields fields;
        fields.feature_kind = "map";
        fields.feature_id = document_id;
        fields.ref = map_ref;
        issues.push_back(make_issue("well_overlays_present", "warning",
                                    "图面无井位叠加，编图证据不足", fields));
    }

    // 5) Contour isolines
    if (count_contour_lines(document) == 0) {
        QcIssueFields fields;
        fields.feature_kind = "map";
        fields.feature_id = document_id;
        fields.ref = map_ref;
        issues.push_back(
            make_issue("contour_lines_present", "warning",
                       "尚无等值线（ContourDraft）线要素，建议从制备生成初稿",
                       fields));
    }

    // 6) WellTable QC: one spatial issue per flagged sample
    const Json* tables = array_member(project, "well_tables");
    if (tables != nullptr) {
        for (const Json& table : *tables) {
            if (!table.is_object()) {
                continue;
            }
            const std::string table_h =
                strip_ws(truthy_str(table, "target_horizon"));
            if (!horizon.empty() && !table_h.empty() && table_h != horizon) {
                continue;
            }
            const std::string table_id = str_field(table, "id");
            const Json* rows = array_member(table, "rows");
            if (rows == nullptr) {
                continue;
            }
            for (const Json& row : *rows) {
                if (!row.is_object()) {
                    continue;
                }
                std::string flag = "ok";
                const Json* flag_json = member(row, "qc_flag");
                if (flag_json != nullptr && flag_json->is_string()) {
                    flag = flag_json->get<std::string>();
                }
                if (flag == "ok" || flag.empty()) {
                    continue;
                }
                std::string wid = truthy_str(row, "well_id",
                                             truthy_str(row, "name"));
                std::optional<Json> geom;
                double x = 0.0;
                double y = 0.0;
                if (parse_float_like_or(row, "x", x) &&
                    parse_float_like_or(row, "y", y)) {
                    Json coordinates = Json::array();
                    coordinates.push_back(x);
                    coordinates.push_back(y);
                    Json point = Json::object();
                    point["type"] = "Point";
                    point["coordinates"] = std::move(coordinates);
                    geom = std::move(point);
                }
                const std::string display_name =
                    truthy_str(row, "name", wid);
                Json extra = Json::object();
                extra["qc_flag"] = flag;
                const auto z_it = row.find("qc_z_star");
                extra["qc_z_star"] =
                    z_it != row.end() ? *z_it : Json(nullptr);
                QcIssueFields fields;
                if (!wid.empty()) {
                    fields.feature_id = wid;
                }
                fields.feature_kind = "well";
                fields.geometry = std::move(geom);
                fields.ref = !wid.empty()
                                 ? "well_table:" + table_id + "/" + wid
                                 : "well_table:" + table_id;
                fields.extra = std::move(extra);
                issues.push_back(
                    make_issue("well_table_qc_clean", "warning",
                               "井点 " + display_name + " 质控=" + flag,
                               fields));
            }
        }
    }

    return issues;
}

// qc._status_from_issues (L329).
std::string status_from_issues(const Json& issues) {
    bool has_error = false;
    bool has_warning = false;
    if (issues.is_array()) {
        for (const Json& issue : issues) {
            if (!issue.is_object()) {
                continue;
            }
            std::string severity;
            const auto it = issue.find("severity");
            if (it != issue.end() && it->is_string()) {
                severity = it->get<std::string>();
            }
            std::transform(severity.begin(), severity.end(), severity.begin(),
                           [](unsigned char c) {
                               return static_cast<char>(
                                   std::tolower(static_cast<int>(c)));
                           });
            if (severity == "error" || severity == "critical") {
                has_error = true;
            }
            if (severity == "warning") {
                has_warning = true;
            }
        }
    }
    if (has_error) {
        return "error";
    }
    if (has_warning) {
        return "warning";
    }
    return "pass";
}

const Json* find_map_document(const Json& project,
                              const std::string& map_document_id) {
    const Json* docs = array_member(project, "paleomap_documents");
    if (docs == nullptr) {
        return nullptr;
    }
    for (const Json& doc : *docs) {
        if (!doc.is_object()) {
            continue;
        }
        const auto it = doc.find("id");
        if (it != doc.end() && it->is_string() &&
            it->get<std::string>() == map_document_id) {
            return &doc;
        }
    }
    return nullptr;
}

Json* find_quality_reports_array(domain::Json& project) {
    const auto it = project.find("quality_reports");
    if (it != project.end() && it->is_array()) {
        return &*it;
    }
    return nullptr;
}

}  // namespace

// ------------------------------------------------------------ make_issue --

domain::Json make_issue(std::string_view rule, std::string_view severity,
                        std::string_view message, const QcIssueFields& fields) {
    Json issue = Json::object();
    issue["rule"] = std::string(rule);
    issue["severity"] = std::string(severity);
    issue["message"] = std::string(message);
    if (fields.feature_id.has_value()) {
        issue["feature_id"] = *fields.feature_id;
    }
    if (fields.feature_kind.has_value()) {
        issue["feature_kind"] = *fields.feature_kind;
    }
    if (fields.ref.has_value()) {
        issue["ref"] = *fields.ref;
    }
    if (fields.geometry.has_value()) {
        issue["geometry"] = *fields.geometry;
        double x = 0.0;
        double y = 0.0;
        if (geometry_centroid(*fields.geometry, x, y)) {
            Json centroid = Json::array();
            centroid.push_back(x);
            centroid.push_back(y);
            issue["centroid"] = std::move(centroid);
        }
    }
    if (!fields.extra.is_null() && pycompat::truthy(fields.extra) &&
        fields.extra.is_object()) {
        for (auto it = fields.extra.begin(); it != fields.extra.end(); ++it) {
            issue[it.key()] = it.value();
        }
    }
    return issue;
}

// -------------------------------------------------------- spatialIssues ---

domain::Json spatial_issues(const domain::Json& issues) {
    Json out = Json::array();
    if (!issues.is_array()) {
        return out;
    }
    for (const Json& issue : issues) {
        if (!issue.is_object()) {
            continue;
        }
        const Json* geometry = member(issue, "geometry");
        const Json* centroid = member(issue, "centroid");
        const bool locatable =
            (geometry != nullptr && pycompat::truthy(*geometry)) ||
            (centroid != nullptr && pycompat::truthy(*centroid));
        if (locatable) {
            out.push_back(issue);
        }
    }
    return out;
}

// ---------------------------------------------------- issue_layer_geojson -

domain::Json issue_layer_geojson(
    const std::optional<project::QualityReport>& report,
    const std::optional<std::string>& map_document_id) {
    Json features = Json::array();
    Json collection = Json::object();
    collection["type"] = "FeatureCollection";
    collection["features"] = features;
    if (!report.has_value()) {
        return collection;
    }
    for (const Json& issue : spatial_issues(report->issues)) {
        const Json* geometry = member(issue, "geometry");
        if (geometry == nullptr || !geometry->is_object()) {
            continue;
        }
        Json props = Json::object();
        for (const char* key :
             {"rule", "severity", "message", "feature_id", "feature_kind",
              "ref"}) {
            const auto it = issue.find(key);
            props[key] = it != issue.end() ? *it : Json(nullptr);
        }
        props["map_document_id"] =
            (map_document_id.has_value() && !map_document_id->empty())
                ? Json(*map_document_id)
                : Json(report->linked_map_document_id);
        Json feature = Json::object();
        feature["type"] = "Feature";
        feature["geometry"] = *geometry;
        feature["properties"] = std::move(props);
        collection["features"].push_back(std::move(feature));
    }
    Json top = Json::object();
    top["report_id"] = report->id;
    top["linked_map_document_id"] = report->linked_map_document_id;
    top["status"] = report->status;
    collection["properties"] = std::move(top);
    return collection;
}

// ---------------------------------------------------------- run_basic_qc --

project::QualityReport run_basic_qc(domain::Json& project,
                                    const std::string& map_document_id,
                                    bool bind_active_run,
                                    const QcRunDeps& deps) {
    const Json* document = find_map_document(project, map_document_id);
    if (document == nullptr) {
        throw std::invalid_argument("unknown map document: " +
                                    map_document_id);
    }
    const std::string document_id = str_field(*document, "id");

    Json issues = collect_issues(project, *document);
    const std::string status = status_from_issues(issues);

    Json* reports = find_quality_reports_array(project);
    std::optional<std::size_t> existing_idx;
    std::string previous_id;
    if (reports != nullptr) {
        for (std::size_t index = 0; index < reports->size(); ++index) {
            const Json& entry = (*reports)[index];
            if (!entry.is_object()) {
                continue;
            }
            const auto linked = entry.find("linked_map_document_id");
            if (linked != entry.end() && linked->is_string() &&
                linked->get<std::string>() == map_document_id) {
                existing_idx = index;
                const auto id = entry.find("id");
                if (id != entry.end() && id->is_string() &&
                    !id->get<std::string>().empty()) {
                    previous_id = id->get<std::string>();
                }
                break;
            }
        }
    }

    project::QualityReport report;
    report.id = !previous_id.empty() ? previous_id
                                     : deps.clock.make_id("qc");
    report.linked_map_document_id = map_document_id;
    for (std::string_view rule : kBasicQcRules) {
        report.rules.emplace_back(rule);
    }
    report.issues = std::move(issues);
    report.status = status;
    report.generated_at = deps.clock.now_iso();
    // Provenance marker (H14): False until the registration below succeeds.
    report.provenance_registered = false;
    report.rule_status = Json::object();
    for (std::string_view rule : kBasicQcRules) {
        report.rule_status[std::string(rule)] =
            Json{{"evaluated", true}, {"reason", ""}};
    }
    report.coverage = Json{{"evaluated", static_cast<int>(std::size(
                                             kBasicQcRules))},
                           {"skipped", 0}};

    // Provenance seam (H3/H14): best-effort registration — the serialized
    // report still carries provenance_registered = false at this point
    // (Python dumps the temp file before flipping the flag). A null sink is
    // the get_catalog() -> None branch: registration never happens and the
    // report stays visibly unregistered.
    if (deps.provenance_sink != nullptr) {
        try {
            // Stable per-map domain key (#373 / C15): the linked prediction
            // task, falling back to the document id.
            std::string domain_task_id = truthy_str(
                *document, "linked_prediction_task_id", document_id);
            std::vector<std::string> source_task_ids{document_id};
            Json parameters = Json::object();
            parameters["map_document_id"] = map_document_id;
            parameters["qc_status"] = status;
            const std::optional<QcRunRegistration> registration =
                deps.provenance_sink->register_qc_run(
                    "QC " + str_field(*document, "name"), source_task_ids,
                    domain_task_id, parameters, report.to_dict());
            if (registration.has_value()) {
                report.provenance_registered = true;
            }
        } catch (...) {
            // Python's broad except: registration failure must never fail
            // the QC run itself (logged there; visible here via the false
            // provenance_registered flag).
        }
    }

    if (reports == nullptr) {
        project["quality_reports"] = Json::array();
        reports = &project.at("quality_reports");
    }
    if (existing_idx.has_value()) {
        (*reports)[*existing_idx] = report.to_dict();
    } else {
        reports->push_back(report.to_dict());
    }

    if (bind_active_run) {
        const auto runs_it = project.find("compilation_runs");
        if (runs_it != project.end() && runs_it->is_array() &&
            !runs_it->empty()) {
            Json& run = runs_it->back();
            run["active_quality_report_id"] = report.id;
            run["active_paleomap_document_id"] = map_document_id;
            run["updated_at"] = deps.clock.now_iso();
        }
    }

    return report;
}

// -------------------------------------------------- active_quality_reports -
// 协调者预置（轮2 种子，A1 路复核 parity）：qc.py L462-472。
// 活动 run 的 active_quality_report_id 指向者；无 run / 未绑定 / 指向不存在
// → 每图最新一份（by_map 去重，键序 = 首见序，Python dict 插入序 parity）。
std::vector<project::QualityReport> active_quality_reports(
    const domain::Json& project) {
    std::vector<project::QualityReport> out;
    const auto reports_it = project.find("quality_reports");
    const bool has_reports =
        reports_it != project.end() && reports_it->is_array();

    const auto runs_it = project.find("compilation_runs");
    if (runs_it != project.end() && runs_it->is_array() && !runs_it->empty()) {
        const domain::Json& run = runs_it->back();
        const auto active = run.find("active_quality_report_id");
        if (active != run.end() && active->is_string()) {
            const std::string active_id = active->get<std::string>();
            if (has_reports) {
                for (const domain::Json& item : *reports_it) {
                    if (!item.is_object()) {
                        continue;
                    }
                    const auto id = item.find("id");
                    if (id != item.end() && id->is_string() &&
                        id->get<std::string>() == active_id) {
                        out.push_back(project::QualityReport::from_dict(item));
                        return out;
                    }
                }
            }
            // 指向不存在（或报告段畸形）→ 与 Python 一致落 by_map 兜底。
        }
    }

    if (has_reports) {
        std::vector<std::string> order;
        std::map<std::string, const domain::Json*> by_map;
        for (const domain::Json& item : *reports_it) {
            if (!item.is_object()) {
                continue;
            }
            const auto linked = item.find("linked_map_document_id");
            if (linked == item.end() || !linked->is_string()) {
                continue;
            }
            const std::string key = linked->get<std::string>();
            if (by_map.find(key) == by_map.end()) {
                order.push_back(key);
            }
            by_map[key] = &item;
        }
        out.reserve(order.size());
        for (const std::string& key : order) {
            out.push_back(project::QualityReport::from_dict(*by_map[key]));
        }
    }
    return out;
}

// ------------------------------------------------------------ run_map_qc --

project::QualityReport run_map_qc(domain::Json& project,
                                  const std::string& map_document_id,
                                  bool bind_active_run,
                                  const MapQcInputs& inputs,
                                  const QcRunDeps& deps) {
    const Json* document = find_map_document(project, map_document_id);
    if (document == nullptr) {
        throw std::invalid_argument("unknown map document: " +
                                    map_document_id);
    }

    const project::QualityReport base =
        run_basic_qc(project, map_document_id, bind_active_run, deps);
    // `document` points into project["paleomap_documents"], which the basic
    // upsert never touches (it only writes quality_reports and the last
    // compilation run) — safe across the mutation.
    const Json extended =
        collect_extended_qc_issues(project, *document, inputs);

    Json merged = base.issues;
    if (extended.is_array()) {
        for (const Json& issue : extended) {
            merged.push_back(issue);
        }
    }
    const std::string status = status_from_issues(merged);

    Json rule_status = Json::object();
    for (std::string_view rule : kBasicQcRules) {
        rule_status[std::string(rule)] =
            Json{{"evaluated", true}, {"reason", ""}};
    }
    const Json extended_coverage = extended_rule_coverage(inputs);
    for (auto it = extended_coverage.begin(); it != extended_coverage.end();
         ++it) {
        rule_status[it.key()] = it.value();
    }
    int skipped = 0;
    for (auto it = rule_status.begin(); it != rule_status.end(); ++it) {
        const auto evaluated = it.value().find("evaluated");
        bool is_evaluated = true;
        if (evaluated != it.value().end() && evaluated->is_boolean()) {
            is_evaluated = evaluated->get<bool>();
        }
        if (!is_evaluated) {
            ++skipped;
        }
    }

    Json* reports = find_quality_reports_array(project);
    std::optional<std::size_t> document_index;
    std::string report_id = base.id;
    if (reports != nullptr) {
        for (std::size_t index = 0; index < reports->size(); ++index) {
            const Json& entry = (*reports)[index];
            if (!entry.is_object()) {
                continue;
            }
            const auto linked = entry.find("linked_map_document_id");
            if (linked != entry.end() && linked->is_string() &&
                linked->get<std::string>() == map_document_id) {
                document_index = index;
                const auto id = entry.find("id");
                if (id != entry.end() && id->is_string() &&
                    !id->get<std::string>().empty()) {
                    report_id = id->get<std::string>();
                }
                break;
            }
        }
    }

    project::QualityReport report;
    report.id = report_id;
    report.linked_map_document_id = map_document_id;
    for (std::string_view rule : kBasicQcRules) {
        report.rules.emplace_back(rule);
    }
    for (std::string_view rule : kExtendedQcRules) {
        report.rules.emplace_back(rule);
    }
    report.issues = std::move(merged);
    report.status = status;
    report.generated_at = deps.clock.now_iso();
    report.provenance_registered = base.provenance_registered;
    report.rule_status = std::move(rule_status);
    report.coverage =
        Json{{"evaluated", static_cast<int>(report.rule_status.size()) -
                               skipped},
             {"skipped", skipped}};

    if (reports == nullptr) {
        project["quality_reports"] = Json::array();
        reports = &project.at("quality_reports");
    }
    if (document_index.has_value()) {
        (*reports)[*document_index] = report.to_dict();
    } else {
        reports->push_back(report.to_dict());
    }

    return report;
}

}  // namespace pwb::workflow_runtime
