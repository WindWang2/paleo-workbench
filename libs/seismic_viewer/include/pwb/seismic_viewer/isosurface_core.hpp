#pragma once

// VIZ-D isosurface core — marching-tetrahedra isosurface extraction, the
// exact algorithm of the frozen native oracle (native/seismic_3d_core
// marching_cubes_3d @ pybind "0.2.17a0", injected into geoviz via
// isosurface.set_isosurface_extractor by paleo_workbench.native_backend).
// Lifted into the seismic stack so C++ presenters consume it without the
// Python detour; geo3d_viz SceneObject {verts, faces, Mesh} can render the
// output directly (no generic mesh engine is reimplemented here).
//
// Semantics (frozen with the native oracle):
//   * 6 tetrahedra per cube around the body-diagonal corner0->corner7;
//     consistent face diagonals keep the mesh watertight;
//   * grid values equal to the isovalue are nudged by
//     eps = 1e-3 * (|iso| + 1) so cuts land strictly inside edges;
//   * cubes touching non-finite voxels are skipped (missing data => a hole,
//     never NaN vertices);
//   * every triangle emits 3 fresh vertices (no dedup, oracle behaviour);
//     normals are oriented away from the inside-centroid.

#include <cstdint>
#include <span>
#include <vector>

namespace pwb::seismic_viewer::isosurface {

struct IsosurfaceMesh {
    std::vector<float> verts;  // xyz triplets, 3 * n_triangles values
    std::vector<std::int32_t> faces; // vertex-index triplets (0..3n-1)
};

// `volume` is packed row-major (n_i, n_x, n_s). Returns an empty mesh for
// extents < 2 on any axis or when nothing crosses the isovalue.
[[nodiscard]] IsosurfaceMesh extract_isosurface(std::span<const float> volume,
                                                std::int64_t n_i, std::int64_t n_x,
                                                std::int64_t n_s, float isovalue);

} // namespace pwb::seismic_viewer::isosurface
