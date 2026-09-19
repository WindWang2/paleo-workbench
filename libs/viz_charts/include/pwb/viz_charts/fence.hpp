// Cross-well fence mesh and inter-well seismic slice — port of
// geoviz_plots/fence/fence_generator.py (verbatim numpy semantics).
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace pwb::viz_charts {

struct FenceWell {
    std::string name;
    double x = 0.0;
    double y = 0.0;
    double depth = 0.0;
};

struct FenceMesh {
    std::vector<float> vertices;  // 3 floats per vertex (x, y, z)
    std::vector<std::int32_t> faces;  // 3 indices per triangle
    std::vector<float> face_colors;  // 4 floats per face (RGBA)
};

// Triangulated quad-strip curtain between consecutive wells; z runs from 0
// down to -depth per side; face color = [0.1, 0.4+0.5*(1-r), 0.7+0.3*r, 0.75]
// with r = |z_top| / max(max_d, 1.0). Fewer than 2 wells → empty mesh.
FenceMesh generate_fence_mesh(const std::vector<FenceWell>& wells,
                              int nz_samples = 20);

// 2D amplitude section along the piecewise well trajectory (nearest-cell
// sampling, first sample of later segments dropped to avoid duplicates).
// `seismic` is row-major (ni, nx, nz); fewer than 2 wells or wrong rank →
// empty (Python returns a (0, 0) array).
std::vector<float> extract_seismic_slice(const std::vector<float>& seismic,
                                         int ni, int nx, int nz,
                                         const std::vector<FenceWell>& wells,
                                         int n_samples_per_segment = 50);

}  // namespace pwb::viz_charts
