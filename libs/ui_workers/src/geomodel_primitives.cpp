#include "pwb/ui_workers/geomodel_primitives.hpp"

#include <cmath>

#include <pwb/ui_workers/worker_common.hpp>  // np_linspace

// Faithful port of geoviz_plots/geomodel/primitives.py — including the
// numpy dtype staging: endpoints/axis live in float32 (np.array(f32)),
// but np.cross(axis_f32, seed_list) promotes the basis to FLOAT64 (the
// Python seed list is float64), offsets stay float64, and _finish casts
// the vertex list back to float32. Mirroring the staging keeps oracle
// diffs at the last-bit level.

namespace pwb::ui_workers {

namespace {

constexpr double kPi = 3.14159265358979323846;

using Vec3f = std::array<float, 3>;

Vec3f subf(const Vec3f& a, const Vec3f& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}
Vec3d crossd(const Vec3d& a, const Vec3d& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]};
}
Vec3f divf(const Vec3f& a, float s) {
    // numpy a / s — per-element float32 division (NOT reciprocal*mul —
    // they differ in the last bit).
    return {a[0] / s, a[1] / s, a[2] / s};
}
Vec3d divd(const Vec3d& a, double s) {
    return {a[0] / s, a[1] / s, a[2] / s};
}
float normf(const Vec3f& a) {
    return std::sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
}
double normd(const Vec3d& a) {
    return std::sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
}
Vec3f to_f32(const Vec3d& v) {
    return {static_cast<float>(v[0]), static_cast<float>(v[1]),
            static_cast<float>(v[2])};
}
Vec3d to_f64(const Vec3f& v) {
    return {static_cast<double>(v[0]), static_cast<double>(v[1]),
            static_cast<double>(v[2])};
}

// _orthonormal_basis — the float32 axis is crossed with a float64 Python
// seed list, so the whole basis pipeline runs in float64 (numpy
// promotion), then back out for the f32-vertex add.
std::pair<Vec3d, Vec3d> orthonormal_basis(const Vec3f& axis_f) {
    const Vec3d axis = to_f64(axis_f);
    const Vec3d seed = std::fabs(axis[0]) < 0.9 ? Vec3d{1.0, 0.0, 0.0}
                                                : Vec3d{0.0, 1.0, 0.0};
    const Vec3d o1raw = crossd(axis, seed);
    const Vec3d o1 = divd(o1raw, normd(o1raw));
    return {o1, crossd(axis, o1)};
}

GeomPrimitive finish(const std::vector<Vec3d>& vertices,
                     const std::vector<std::array<std::int32_t, 3>>& faces,
                     const Color4& color) {
    GeomPrimitive out;
    out.vertices.reserve(vertices.size());
    for (const auto& v : vertices) {
        out.vertices.push_back({static_cast<float>(v[0]),
                                static_cast<float>(v[1]),
                                static_cast<float>(v[2])});
    }
    out.faces = faces;
    out.face_colors.assign(faces.size(), {static_cast<float>(color[0]),
                                          static_cast<float>(color[1]),
                                          static_cast<float>(color[2]),
                                          static_cast<float>(color[3])});
    return out;
}

}  // namespace

GeomPrimitive generate_cylinder_geometry(const Vec3d& p1_in,
                                         const Vec3d& p2_in, double radius,
                                         const Color4& color,
                                         int resolution) {
    // np.array(p, dtype=np.float32) on the endpoints first.
    const Vec3f p1 = to_f32(p1_in);
    const Vec3f p2 = to_f32(p2_in);
    const Vec3f axis = subf(p2, p1);
    const float length = normf(axis);
    if (length == 0.0f) return {};
    const auto [o1, o2] = orthonormal_basis(divf(axis, length));

    std::vector<Vec3d> vertices;
    vertices.reserve(static_cast<std::size_t>(resolution) * 2 + 2);
    for (int i = 0; i < resolution; ++i) {
        const double theta = 2.0 * kPi * i / resolution;
        const double c = std::cos(theta) * radius;
        const double s = std::sin(theta) * radius;
        for (const Vec3f& p : {p1, p2}) {
            // p + (c*o1 + s*o2) — numpy evaluates the offset sum first;
            // keep the association so the f32 cast lands on the same bits.
            vertices.push_back(
                {static_cast<double>(p[0]) + (c * o1[0] + s * o2[0]),
                 static_cast<double>(p[1]) + (c * o1[1] + s * o2[1]),
                 static_cast<double>(p[2]) + (c * o1[2] + s * o2[2])});
        }
    }
    vertices.push_back({p1[0], p1[1], p1[2]});
    vertices.push_back({p2[0], p2[1], p2[2]});
    const auto idx_p1 = static_cast<std::int32_t>(vertices.size() - 2);
    const auto idx_p2 = static_cast<std::int32_t>(vertices.size() - 1);

    std::vector<std::array<std::int32_t, 3>> faces;
    faces.reserve(static_cast<std::size_t>(resolution) * 4);
    for (int i = 0; i < resolution; ++i) {
        const int next_i = (i + 1) % resolution;
        faces.push_back({2 * i, 2 * next_i, 2 * i + 1});
        faces.push_back({2 * next_i, 2 * next_i + 1, 2 * i + 1});
        faces.push_back({idx_p1, 2 * next_i, 2 * i});
        faces.push_back({idx_p2, 2 * i + 1, 2 * next_i + 1});
    }
    return finish(vertices, faces, color);
}

GeomPrimitive generate_tube_geometry(const std::vector<Vec3d>& path_in,
                                     double radius, const Color4& color,
                                     int resolution) {
    if (path_in.size() < 2) return {};
    std::vector<Vec3f> path;
    path.reserve(path_in.size());
    for (const auto& p : path_in) path.push_back(to_f32(p));
    const std::size_t stations = path.size();

    std::vector<Vec3d> vertices;
    vertices.reserve(stations * static_cast<std::size_t>(resolution));
    for (std::size_t j = 0; j < stations; ++j) {
        Vec3f tangent;
        if (j == 0) {
            tangent = subf(path[1], path[0]);
        } else if (j == stations - 1) {
            tangent = subf(path[stations - 1], path[stations - 2]);
        } else {
            tangent = subf(path[j + 1], path[j - 1]);
        }
        const float tang_len = normf(tangent);
        const Vec3f unit = tang_len == 0.0f
                               ? Vec3f{0.0f, 0.0f, 1.0f}
                               : divf(tangent, tang_len);
        const auto [o1, o2] = orthonormal_basis(unit);
        const Vec3f& p = path[j];
        for (int i = 0; i < resolution; ++i) {
            const double theta = 2.0 * kPi * i / resolution;
            const double c = std::cos(theta) * radius;
            const double s = std::sin(theta) * radius;
            // p + (c*o1 + s*o2) — numpy evaluates the offset sum first;
            // keep the association so the f32 cast lands on the same bits.
            vertices.push_back(
                {static_cast<double>(p[0]) + (c * o1[0] + s * o2[0]),
                 static_cast<double>(p[1]) + (c * o1[1] + s * o2[1]),
                 static_cast<double>(p[2]) + (c * o1[2] + s * o2[2])});
        }
    }
    std::vector<std::array<std::int32_t, 3>> faces;
    faces.reserve((stations - 1) * static_cast<std::size_t>(resolution) * 2);
    for (std::size_t j = 0; j + 1 < stations; ++j) {
        const auto ring = static_cast<std::int32_t>(j * resolution);
        const auto next_ring =
            static_cast<std::int32_t>((j + 1) * resolution);
        for (int i = 0; i < resolution; ++i) {
            const int next_i = (i + 1) % resolution;
            faces.push_back({ring + i, ring + next_i, next_ring + i});
            faces.push_back(
                {ring + next_i, next_ring + next_i, next_ring + i});
        }
    }
    return finish(vertices, faces, color);
}

GeomPrimitive generate_fault_geometry(
    const std::pair<double, double>& xlim,
    const std::pair<double, double>& ylim, int nx, int ny,
    const Color4& color) {
    // np.linspace — shared port (inclusive endpoints, pinned hi).
    const auto xs = np_linspace(xlim.first, xlim.second,
                                static_cast<std::size_t>(nx));
    const auto ys = np_linspace(ylim.first, ylim.second,
                                static_cast<std::size_t>(ny));

    // meshgrid 'xy' (default): grid[r][c] = (xs[c], ys[r]), shape (ny,nx);
    // ravel row-major → vertex index r*nx + c. z math is float64.
    std::vector<Vec3d> vertices;
    vertices.reserve(static_cast<std::size_t>(nx) * ny);
    for (int r = 0; r < ny; ++r) {
        for (int c = 0; c < nx; ++c) {
            const double x = xs[static_cast<std::size_t>(c)];
            const double y = ys[static_cast<std::size_t>(r)];
            double z = 15.0 * std::sin(x / 50.0) * std::cos(y / 50.0);
            if (y > 0.5 * x + 10.0) z += 25.0;
            vertices.push_back({x, y, z});
        }
    }
    std::vector<std::array<std::int32_t, 3>> faces;
    faces.reserve(static_cast<std::size_t>(nx > 0 ? nx - 1 : 0) *
                  (ny > 0 ? ny - 1 : 0) * 2);
    for (int r = 0; r + 1 < ny; ++r) {
        for (int c = 0; c + 1 < nx; ++c) {
            const std::int32_t v0 = r * nx + c;
            const std::int32_t v1 = v0 + 1;
            const std::int32_t v2 = (r + 1) * nx + c;
            const std::int32_t v3 = v2 + 1;
            faces.push_back({v0, v1, v2});
            faces.push_back({v1, v3, v2});
        }
    }
    return finish(vertices, faces, color);
}

}  // namespace pwb::ui_workers
