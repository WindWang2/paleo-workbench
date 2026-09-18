#pragma once

// pwb::geomodel — section / clip-plane intersection kernel, a faithful C++
// port of paleo_workbench/viz/geomodel/section.py (G8 geometry half,
// CONV-12). Frozen against tools/oracle/generate_geomodel_volume_fixtures.py:
//   * Plane n.p = d with construction-time normalization (|n| < 1e-12
//     rejects with the Python message) and d divided by |n|;
//   * GL clip equations keep n.p <= d by submitting (-n, -d) (invert
//     flips the half-space);
//   * triangle-plane segments: >= 2 on-plane vertices connect them
//     directly, otherwise the (+,-) vertex pairs interpolate in ascending
//     index order and only the first two edge points form the segment;
//   * greedy chaining uses the scale-aware tolerance
//     max(1e-9, max|coordinate| * 1e-9) with the Python four-direction
//     match order (tail/tail, head/tail, tail/head, head/head);
//   * well crossing follows np.sign: a zero vertex returns immediately.
// Qt-free, Python-free, numpy-free.

#include <array>
#include <optional>
#include <string>
#include <vector>

#include <pwb/geomodel/builders.hpp>  // HorizonGrid, TriMesh, Vec3

namespace pwb::geomodel {

struct Plane {
    Vec3 n{1.0, 0.0, 0.0};  // unit normal
    double d = 0.0;

    Plane(const Vec3& normal, double d_value);  // normalizes, throws < 1e-12

    double signed_distance(const Vec3& point) const;
    std::array<double, 4> as_clip_equation(bool invert = false) const;
};

// "x" / "y" / "z" constant plane; throws with the Python repr message.
Plane axis_plane(const std::string& axis, double value);

Plane plane_from_normal_point(const Vec3& normal, const Vec3& point);

// Six inward clip equations for the axis-aligned box (lo, hi).
std::vector<std::array<double, 4>> clip_planes_for_box(
    const Vec3& lo, const Vec3& hi, bool invert = false);

using Segment = std::array<Vec3, 2>;

// Intersection segments of a plane with a triangle soup (unsorted).
std::vector<Segment> intersect_plane_with_triangles(
    const Plane& plane, const std::vector<Vec3>& verts,
    const std::vector<std::array<std::int64_t, 3>>& faces);

// Greedy chaining of segments into polylines (section display order).
std::vector<std::vector<Vec3>> chain_segments(const std::vector<Segment>& segments);

// Section curve of a structured horizon (NaN holes split the curve).
std::vector<std::vector<Vec3>> horizon_plane_intersection(
    const Plane& plane, const HorizonGrid& grid);

std::vector<std::vector<Vec3>> mesh_plane_intersection(
    const Plane& plane, const std::vector<Vec3>& verts,
    const std::vector<std::array<std::int64_t, 3>>& faces);

// First crossing point of a well polyline with the plane, or nullopt.
std::optional<Vec3> well_plane_crossing(const Plane& plane,
                                        const std::vector<Vec3>& stations);

}  // namespace pwb::geomodel
