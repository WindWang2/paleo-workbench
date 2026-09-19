#pragma once

// UI-04 — geoviz_plots.geomodel.primitives port (cylinder / tube / fault
// demo geometry). Pure math, oracle-frozen — deliberately NOT bound to
// pwb::geo3d_viz's tube generator (different output contract: this one
// returns float32 verts + int32 faces + per-face RGBA colors).
//
// Every function returns (vertices Nx3 float32, faces Mx3 int32,
// face_colors Mx4 float32) — the GLMeshItem-ready triple.

#include <array>
#include <cstdint>
#include <utility>
#include <vector>

namespace pwb::ui_workers {

struct GeomPrimitive {
    std::vector<std::array<float, 3>> vertices;
    std::vector<std::array<std::int32_t, 3>> faces;
    std::vector<std::array<float, 4>> face_colors;
};

using Vec3d = std::array<double, 3>;
using Color4 = std::array<double, 4>;

// generate_cylinder_geometry(p1, p2, radius, color, resolution=12):
// capped cylinder spanning p1->p2; empty when the points coincide.
GeomPrimitive generate_cylinder_geometry(const Vec3d& p1, const Vec3d& p2,
                                         double radius = 2.0,
                                         const Color4& color = {1, 0, 0, 1},
                                         int resolution = 12);

// generate_tube_geometry(path, radius, color, resolution=12): tube swept
// along a polyline with per-station central-difference tangents; empty for
// < 2 stations.
GeomPrimitive generate_tube_geometry(
    const std::vector<Vec3d>& path, double radius = 3.0,
    const Color4& color = {0.8, 0.8, 0.8, 1.0}, int resolution = 12);

// generate_fault_geometry(xlim, ylim, nx=40, ny=40, color): demo dome
// surface offset by a synthetic throw along Y = 0.5*X + 10.
GeomPrimitive generate_fault_geometry(
    const std::pair<double, double>& xlim = {-100, 100},
    const std::pair<double, double>& ylim = {-100, 100}, int nx = 40,
    int ny = 40, const Color4& color = {0.1, 0.6, 0.8, 0.8});

}  // namespace pwb::ui_workers
