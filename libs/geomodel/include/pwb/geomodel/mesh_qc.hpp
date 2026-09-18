#pragma once

// pwb::geomodel — numeric mesh QC cores, a faithful C++ port of the
// geometry helpers in paleo_workbench/viz/geomodel/qc.py (G13, CONV-12).
// Frozen against tools/oracle/generate_geomodel_volume_fixtures.py:
//   * _tri_degenerate_fraction: shortest edge <= 1e-12 * max(longest, 1e-12);
//   * _edge_manifold_stats: undirected edge key lo*(max_hi+1)+hi,
//     boundary = count==1, nonmanifold = count>2;
//   * _connected_components: scipy csgraph semantics — components over the
//     WHOLE vertex array (isolated vertices count), union-find here; the
//     Python no-scipy fallback only differs for isolated vertices.
// The severity ladder / issue codes / export gate stay Python-side (business
// layer, ledger 12-decisions D4).
// Qt-free, Python-free, numpy-free.

#include <cstddef>
#include <cstdint>
#include <vector>

#include <pwb/geomodel/volume.hpp>  // Vec3

namespace pwb::geomodel {

double tri_degenerate_fraction(
    const std::vector<Vec3>& verts,
    const std::vector<std::array<std::int64_t, 3>>& faces);

struct EdgeManifoldStats {
    std::int64_t boundary = 0;
    std::int64_t nonmanifold = 0;
};

EdgeManifoldStats edge_manifold_stats(
    const std::vector<std::array<std::int64_t, 3>>& faces);

// Components over all vertices (scipy parity); faces may reference a
// subset. Empty faces -> 0.
int connected_components(std::size_t vertex_count,
                         const std::vector<std::array<std::int64_t, 3>>& faces);

}  // namespace pwb::geomodel
