#pragma once

// pwb::geomodel — formation volume kernel, a faithful C++ port of
// paleo_workbench/viz/formation_volume.py (full-conversion plan M8 first
// slice, CONV-12). Frozen against the Python implementation via committed
// oracle fixtures (tools/oracle/generate_geomodel_volume_fixtures.py):
//   * watertight grid polyhedron: top sheet (up), bottom sheet (down),
//     four side-wall strips, V = |sum(p0 . (p1 x p2)) / 6| over all faces;
//   * grid_shape is mandatory in the caller's hands — the Python sqrt
//     inference was removed upstream (#846) and the (rows*cols != N) guard
//     keeps the same error text;
//   * accumulation in float64 exactly like the Python vstack-astype path.
// The "grid_shape is required" ValueError guards an optional parameter and
// is unrepresentable in the C++ signature (rows/cols are mandatory), so it
// has no ported counterpart (ledger 12-decisions D3).
// Qt-free, Python-free, numpy-free.

#include <array>
#include <cstddef>
#include <vector>

namespace pwb::geomodel {

using Vec3 = std::array<double, 3>;

// Closed polyhedron volume between two gridded horizon vertex arrays.
// Throws std::invalid_argument with the Python message when the vertex
// counts differ or rows*cols != top.size().
double closed_mesh_volume(const std::vector<Vec3>& top_vertices,
                          const std::vector<Vec3>& bot_vertices,
                          std::size_t rows, std::size_t cols);

}  // namespace pwb::geomodel
