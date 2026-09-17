#include <pwb/geomodel/section.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>

namespace pwb::geomodel {

namespace {

double max_abs_component(const Vec3& v) {
    return std::max({std::fabs(v[0]), std::fabs(v[1]), std::fabs(v[2])});
}

Vec3 sub(const Vec3& a, const Vec3& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

}  // namespace

Plane::Plane(const Vec3& normal, double d_value) {
    const double norm = std::sqrt(normal[0] * normal[0] +
                                  normal[1] * normal[1] +
                                  normal[2] * normal[2]);
    if (norm < 1e-12) {
        throw std::invalid_argument("plane normal must be non-zero");
    }
    n = {normal[0] / norm, normal[1] / norm, normal[2] / norm};
    d = d_value / norm;
}

double Plane::signed_distance(const Vec3& point) const {
    return point[0] * n[0] + point[1] * n[1] + point[2] * n[2] - d;
}

std::array<double, 4> Plane::as_clip_equation(bool invert) const {
    const double s = invert ? 1.0 : -1.0;
    return {s * n[0], s * n[1], s * n[2], s * -d};
}

Plane axis_plane(const std::string& axis, double value) {
    if (axis == "x") {
        return Plane({1.0, 0.0, 0.0}, value);
    }
    if (axis == "y") {
        return Plane({0.0, 1.0, 0.0}, value);
    }
    if (axis == "z") {
        return Plane({0.0, 0.0, 1.0}, value);
    }
    throw std::invalid_argument("axis must be x/y/z, got '" + axis + "'");
}

Plane plane_from_normal_point(const Vec3& normal, const Vec3& point) {
    return Plane(normal, normal[0] * point[0] + normal[1] * point[1] +
                             normal[2] * point[2]);
}

std::vector<std::array<double, 4>> clip_planes_for_box(const Vec3& lo,
                                                       const Vec3& hi,
                                                       bool invert) {
    const std::array<Plane, 6> planes = {
        Plane({1, 0, 0}, hi[0]),   Plane({-1, 0, 0}, -lo[0]),
        Plane({0, 1, 0}, hi[1]),   Plane({0, -1, 0}, -lo[1]),
        Plane({0, 0, 1}, hi[2]),   Plane({0, 0, -1}, -lo[2]),
    };
    std::vector<std::array<double, 4>> out;
    out.reserve(planes.size());
    for (const auto& p : planes) {
        out.push_back(p.as_clip_equation(invert));
    }
    return out;
}

std::vector<Segment> intersect_plane_with_triangles(
    const Plane& plane, const std::vector<Vec3>& verts,
    const std::vector<std::array<std::int64_t, 3>>& faces) {
    std::vector<Segment> segs;
    if (faces.empty()) {
        return segs;
    }
    for (const auto& f : faces) {
        std::array<Vec3, 3> p = {verts[static_cast<std::size_t>(f[0])],
                                 verts[static_cast<std::size_t>(f[1])],
                                 verts[static_cast<std::size_t>(f[2])]};
        std::array<double, 3> d = {plane.signed_distance(p[0]),
                                   plane.signed_distance(p[1]),
                                   plane.signed_distance(p[2])};
        std::vector<int> plus;
        std::vector<int> minus;
        std::vector<int> zeros;
        for (int k = 0; k < 3; ++k) {
            if (d[k] > 0) {
                plus.push_back(k);
            } else if (d[k] < 0) {
                minus.push_back(k);
            } else {
                zeros.push_back(k);
            }
        }
        if (zeros.size() >= 2) {
            segs.push_back({p[static_cast<std::size_t>(zeros[0])],
                            p[static_cast<std::size_t>(zeros[1])]});
            continue;
        }
        std::vector<Vec3> edge_pts;
        if (zeros.size() == 1 && !plus.empty() && !minus.empty()) {
            edge_pts.push_back(p[static_cast<std::size_t>(zeros[0])]);
        }
        for (const int a : plus) {
            for (const int b : minus) {
                const double t = d[a] / (d[a] - d[b]);
                edge_pts.push_back({p[a][0] + t * (p[b][0] - p[a][0]),
                                    p[a][1] + t * (p[b][1] - p[a][1]),
                                    p[a][2] + t * (p[b][2] - p[a][2])});
            }
        }
        if (edge_pts.size() >= 2) {
            segs.push_back({edge_pts[0], edge_pts[1]});
        }
    }
    return segs;
}

std::vector<std::vector<Vec3>> chain_segments(
    const std::vector<Segment>& segments) {
    if (segments.empty()) {
        return {};
    }
    double scale = 0.0;
    for (const auto& s : segments) {
        scale = std::max(scale, max_abs_component(s[0]));
        scale = std::max(scale, max_abs_component(s[1]));
    }
    const double tol = std::max(1e-9, scale * 1e-9);

    std::vector<std::vector<Vec3>> remaining;
    remaining.reserve(segments.size());
    for (const auto& s : segments) {
        remaining.push_back({s[0], s[1]});
    }
    std::vector<std::vector<Vec3>> chains;
    while (!remaining.empty()) {
        std::vector<Vec3> chain = std::move(remaining.front());
        remaining.erase(remaining.begin());
        bool extended = true;
        while (extended) {
            extended = false;
            for (std::size_t k = 0; k < remaining.size(); ++k) {
                const auto& s = remaining[k];
                if (max_abs_component(sub(s[0], chain.back())) < tol) {
                    chain.push_back(s[1]);
                    remaining.erase(remaining.begin() +
                                    static_cast<std::ptrdiff_t>(k));
                    extended = true;
                    break;
                }
                if (max_abs_component(sub(s[1], chain.back())) < tol) {
                    chain.push_back(s[0]);
                    remaining.erase(remaining.begin() +
                                    static_cast<std::ptrdiff_t>(k));
                    extended = true;
                    break;
                }
                if (max_abs_component(sub(s[1], chain.front())) < tol) {
                    chain.insert(chain.begin(), s[0]);
                    remaining.erase(remaining.begin() +
                                    static_cast<std::ptrdiff_t>(k));
                    extended = true;
                    break;
                }
                if (max_abs_component(sub(s[0], chain.front())) < tol) {
                    chain.insert(chain.begin(), s[1]);
                    remaining.erase(remaining.begin() +
                                    static_cast<std::ptrdiff_t>(k));
                    extended = true;
                    break;
                }
            }
        }
        chains.push_back(std::move(chain));
    }
    return chains;
}

std::vector<std::vector<Vec3>> horizon_plane_intersection(const Plane& plane,
                                                          const HorizonGrid& grid) {
    const TriMesh mesh = triangulate_heightfield(grid);
    const std::vector<Segment> segs =
        intersect_plane_with_triangles(plane, mesh.verts, mesh.faces);
    return chain_segments(segs);
}

std::vector<std::vector<Vec3>> mesh_plane_intersection(
    const Plane& plane, const std::vector<Vec3>& verts,
    const std::vector<std::array<std::int64_t, 3>>& faces) {
    const std::vector<Segment> segs = intersect_plane_with_triangles(plane, verts, faces);
    return chain_segments(segs);
}

std::optional<Vec3> well_plane_crossing(const Plane& plane,
                                        const std::vector<Vec3>& stations) {
    if (stations.size() < 2) {
        return std::nullopt;
    }
    std::vector<double> dist(stations.size());
    for (std::size_t k = 0; k < stations.size(); ++k) {
        dist[k] = plane.signed_distance(stations[k]);
    }
    auto sign = [](double v) { return v > 0 ? 1 : (v < 0 ? -1 : 0); };
    for (std::size_t k = 0; k + 1 < stations.size(); ++k) {
        if (sign(dist[k]) == 0) {
            return stations[k];
        }
        if (sign(dist[k]) != sign(dist[k + 1]) && sign(dist[k + 1]) != 0) {
            const double t = dist[k] / (dist[k] - dist[k + 1]);
            return Vec3{stations[k][0] + t * (stations[k + 1][0] - stations[k][0]),
                        stations[k][1] + t * (stations[k + 1][1] - stations[k][1]),
                        stations[k][2] + t * (stations[k + 1][2] - stations[k][2])};
        }
    }
    return std::nullopt;
}

}  // namespace pwb::geomodel
