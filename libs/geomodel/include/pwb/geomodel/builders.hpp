#pragma once

// pwb::geomodel — pure-geometry domain builders, a faithful C++ port of
// paleo_workbench/viz/geomodel/builders.py (CONV-12). Frozen against
// tools/oracle/generate_geomodel_volume_fixtures.py:
//   * heightfield triangulation keeps NaN holes as holes — quads touching a
//     NaN node are dropped whole, vertex indexing compacted row-major;
//   * volume shells refuse crossed top/base columns (dropped and counted,
//     never silently reordered) in the domain's z sense
//     (_z_sign: tvdss is -1 because TVDSS = KB - TVD, deeper is negative);
//   * cell-centre boundary test is the STRICT even-odd ray crossing of
//     mapping.geometry_planar.points_in_polygon_vectorized (PNPOLY, y1==y2
//     edges skipped, x < x1 + t*(x2-x1), XOR) — NOT the inclusive variant
//     in libs/mapping_kernel (different on-edge semantics, both frozen);
//   * shells orient every triangle away from the shell centroid (star-shaped
//     assumption, ADR-09) and report an edge-manifold "closed" check;
//   * columnar hex meshes give every cell PRIVATE nodes (merge: none),
//     layer fractions are np.linspace(0, 1, n_layers + 1) including the
//     exact endpoint, and hex rows are filled layer-major
//     (hexes[layer::n_layers] on the Python side);
//   * DomainError text is preserved verbatim as std::invalid_argument.
// The well-trajectory dataclass constructors stay Python-side (no geometry
// consumer in this slice); dedupe_stations is ported as the import helper.
// Qt-free, Python-free, numpy-free.

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include <pwb/geomodel/volume.hpp>  // Vec3

namespace pwb::geomodel {

// ---------------------------------------------------------------------------
// structured horizon grid
// ---------------------------------------------------------------------------

struct HorizonGrid {
    int rows = 0;  // nI (y)
    int cols = 0;  // nX (x)
    double origin_x = 0.0;
    double origin_y = 0.0;
    double spacing_y = 1.0;  // dy (row step)
    double spacing_x = 1.0;  // dx (column step)
    std::string vertical_domain = "depth";  // depth | twt | tvdss
    std::string unit = "m";
    std::string object_id;  // "horizon:<slug>", only used in error text
    std::vector<double> z;  // row-major rows*cols; NaN = hole

    double& at(int i, int j) { return z[static_cast<std::size_t>(i) * cols + j]; }
    double at(int i, int j) const {
        return z[static_cast<std::size_t>(i) * cols + j];
    }
};

// Raises std::invalid_argument "z_grid must be a non-empty 2-D array" for
// empty grids (rows/cols <= 0) and the +/-inf rejection of
// _require_finite_structured ("NaN is the only allowed hole").
HorizonGrid build_horizon_from_grid(int rows, int cols, double origin_x,
                                    double origin_y, double spacing_y,
                                    double spacing_x,
                                    std::vector<double> z_row_major,
                                    const std::string& vertical_domain,
                                    const std::string& unit,
                                    const std::string& object_id);

// ---------------------------------------------------------------------------
// wells
// ---------------------------------------------------------------------------

// Sort by MD and drop duplicate / zero-length stations with the relative
// tolerance |dm| <= tol * max(1, |prev_md|). Returns (kept, dropped_count).
std::pair<std::vector<std::array<double, 4>>, int> dedupe_stations(
    const std::vector<std::array<double, 4>>& stations, double tol = 1e-9);

// ---------------------------------------------------------------------------
// heightfield triangulation
// ---------------------------------------------------------------------------

struct TriMesh {
    std::vector<Vec3> verts;
    std::vector<std::array<std::int64_t, 3>> faces;
};

TriMesh triangulate_heightfield(const HorizonGrid& grid);

// ---------------------------------------------------------------------------
// faults
// ---------------------------------------------------------------------------

TriMesh build_fault_curtain_from_trace(
    const std::string& name,
    const std::vector<std::array<double, 2>>& trace_xy, double z_top,
    double z_bottom);

// ---------------------------------------------------------------------------
// stratigraphic volume shell
// ---------------------------------------------------------------------------

struct ShellQc {
    std::int64_t column_count = 0;
    std::int64_t dropped_crossed = 0;
    std::int64_t dropped_nan_nodes = 0;
    std::int64_t negative_thickness_count = 0;
    double min_thickness = 0.0;
    double max_thickness = 0.0;
    double mean_thickness = 0.0;
    bool closed = false;
    std::string unit;
};

struct VolumeShell {
    TriMesh mesh;
    std::vector<double> thicknesses;  // per kept cell, sorted (i, j) order
    ShellQc qc;
};

VolumeShell build_volume_shell(
    const HorizonGrid& top, const HorizonGrid& base,
    const std::vector<std::array<double, 2>>& boundary,
    const std::string& object_id);

// Strict even-odd containment for ONE ring (the builders' single-ring
// polygon): PNPOLY crossings with y1==y2 edges skipped and a strict
// x < x1 + t*(x2-x1) test. Boundary behaviour is whatever the arithmetic
// yields — deliberately NOT the inclusive variant.
bool point_in_ring_strict(double x, double y,
                          const std::vector<std::array<double, 2>>& ring);

// ---------------------------------------------------------------------------
// computational hex mesh (FLAC3D / Abaqus export feedstock)
// ---------------------------------------------------------------------------

struct HexMeshInfo {
    std::int64_t n_cells = 0;
    std::int64_t n_layers = 0;
    std::int64_t n_hexes = 0;
    std::int64_t skipped_crossed = 0;
    std::string unit;
    std::string merge = "none";
};

struct HexMesh {
    std::vector<Vec3> nodes;
    std::vector<std::array<std::int64_t, 8>> hexes;
    HexMeshInfo info;
};

HexMesh build_columnar_hex_mesh(const HorizonGrid& top, const HorizonGrid& base,
                                const std::vector<std::array<double, 2>>& boundary,
                                int n_layers = 4);


}  // namespace pwb::geomodel
