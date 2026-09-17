#include <pwb/geomodel/builders.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace pwb::geomodel {

namespace {

// mapping.geometry_planar._ring_crossings_vectorized for one ring: even-odd
// ray crossings, y1==y2 edges skipped, strict x < x1 + t*(x2-x1), XOR.
bool ring_crossings_strict(double x, double y,
                           const std::vector<std::array<double, 2>>& ring) {
    bool crossings = false;
    const std::size_t count = ring.size();
    for (std::size_t index = 0; index < count; ++index) {
        const double x1 = ring[index][0];
        const double y1 = ring[index][1];
        const auto& nxt = ring[(index + 1) % count];
        const double x2 = nxt[0];
        const double y2 = nxt[1];
        if (y1 == y2) {
            continue;
        }
        const bool straddles = (y1 > y) != (y2 > y);
        if (!straddles) {
            continue;
        }
        const double t = (y - y1) / (y2 - y1);
        if (x < x1 + t * (x2 - x1)) {
            crossings = !crossings;
        }
    }
    return crossings;
}

std::vector<std::array<std::int64_t, 3>> orient_faces_outward_impl(
    const std::vector<Vec3>& verts,
    std::vector<std::array<std::int64_t, 3>> faces) {
    if (faces.empty() || verts.empty()) {
        return faces;
    }
    Vec3 shell_centroid{0.0, 0.0, 0.0};
    for (const auto& v : verts) {
        shell_centroid[0] += v[0];
        shell_centroid[1] += v[1];
        shell_centroid[2] += v[2];
    }
    const double n = static_cast<double>(verts.size());
    shell_centroid[0] /= n;
    shell_centroid[1] /= n;
    shell_centroid[2] /= n;
    for (auto& f : faces) {
        const Vec3& p0 = verts[static_cast<std::size_t>(f[0])];
        const Vec3& p1 = verts[static_cast<std::size_t>(f[1])];
        const Vec3& p2 = verts[static_cast<std::size_t>(f[2])];
        const Vec3 centroid{(p0[0] + p1[0] + p2[0]) / 3.0,
                            (p0[1] + p1[1] + p2[1]) / 3.0,
                            (p0[2] + p1[2] + p2[2]) / 3.0};
        const Vec3 e1{p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]};
        const Vec3 e2{p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]};
        const Vec3 normal{e1[1] * e2[2] - e1[2] * e2[1],
                          e1[2] * e2[0] - e1[0] * e2[2],
                          e1[0] * e2[1] - e1[1] * e2[0]};
        const Vec3 outward{centroid[0] - shell_centroid[0],
                           centroid[1] - shell_centroid[1],
                           centroid[2] - shell_centroid[2]};
        const double dot = normal[0] * outward[0] + normal[1] * outward[1] +
                           normal[2] * outward[2];
        if (dot < 0) {
            std::swap(f[1], f[2]);
        }
    }
    return faces;
}

}  // namespace

namespace {

bool shell_is_closed(const std::vector<Vec3>& verts,
                     const std::vector<std::array<std::int64_t, 3>>& faces);

double z_sign(const std::string& vertical_domain) {
    // TVDSS = KB - TVD: deeper is more negative — crossing checks must
    // respect this or healthy pairs get flagged as crossed.
    return vertical_domain == "tvdss" ? -1.0 : 1.0;
}

}  // namespace


HorizonGrid build_horizon_from_grid(int rows, int cols, double origin_x,
                                    double origin_y, double spacing_y,
                                    double spacing_x,
                                    std::vector<double> z_row_major,
                                    const std::string& vertical_domain,
                                    const std::string& unit,
                                    const std::string& object_id) {
    // Python builder checks under the display name; the constructor check
    // under the object_id. Both texts preserved.
    if (rows <= 0 || cols <= 0) {
        throw std::invalid_argument(
            object_id + ": z_grid must be a non-empty 2-D array");
    }
    HorizonGrid grid;
    grid.rows = rows;
    grid.cols = cols;
    grid.origin_x = origin_x;
    grid.origin_y = origin_y;
    grid.spacing_y = spacing_y;
    grid.spacing_x = spacing_x;
    grid.vertical_domain = vertical_domain;
    grid.unit = unit;
    grid.object_id = object_id;
    grid.z = std::move(z_row_major);
    if (grid.z.size() != static_cast<std::size_t>(rows) * cols) {
        throw std::invalid_argument(object_id + ": z_grid must be a non-empty 2-D array");
    }
    for (const double v : grid.z) {
        // _require_finite_structured: NaN is the only allowed hole.
        if (!std::isfinite(v) && !std::isnan(v)) {
            throw std::invalid_argument(
                object_id +
                ".z_grid: contains +/-inf (NaN is the only allowed hole)");
        }
    }
    return grid;
}

std::pair<std::vector<std::array<double, 4>>, int> dedupe_stations(
    const std::vector<std::array<double, 4>>& stations, double tol) {
    for (const auto& row : stations) {
        for (const double v : row) {
            if (!std::isfinite(v)) {
                throw std::invalid_argument(
                    "stations contain non-finite values");
            }
        }
    }
    std::vector<const std::array<double, 4>*> order;
    order.reserve(stations.size());
    for (const auto& row : stations) {
        order.push_back(&row);
    }
    std::stable_sort(order.begin(), order.end(),
                     [](const auto* a, const auto* b) {
                         return (*a)[0] < (*b)[0];
                     });
    std::vector<std::array<double, 4>> kept;
    int dropped = 0;
    for (const auto* row : order) {
        if (!kept.empty() && std::fabs((*row)[0] - kept.back()[0]) <=
                                 tol * std::max(1.0, std::fabs(kept.back()[0]))) {
            ++dropped;
            continue;
        }
        kept.push_back(*row);
    }
    return {std::move(kept), dropped};
}

TriMesh triangulate_heightfield(const HorizonGrid& grid) {
    TriMesh out;
    const int nI = grid.rows;
    const int nX = grid.cols;
    // Valid nodes and their compacted indices (row-major like the Python
    // boolean-mask compaction).
    std::vector<std::int64_t> idx(static_cast<std::size_t>(nI) * nX, -1);
    std::size_t next = 0;
    for (int i = 0; i < nI; ++i) {
        for (int j = 0; j < nX; ++j) {
            if (std::isfinite(grid.at(i, j))) {
                idx[static_cast<std::size_t>(i) * nX + j] =
                    static_cast<std::int64_t>(next++);
            }
        }
    }
    out.verts.reserve(next);
    for (int i = 0; i < nI; ++i) {
        for (int j = 0; j < nX; ++j) {
            if (std::isfinite(grid.at(i, j))) {
                out.verts.push_back({grid.origin_x + j * grid.spacing_x,
                                     grid.origin_y + i * grid.spacing_y,
                                     grid.at(i, j)});
            }
        }
    }
    for (int i = 0; i + 1 < nI; ++i) {
        for (int j = 0; j + 1 < nX; ++j) {
            const std::int64_t a = idx[static_cast<std::size_t>(i) * nX + j];
            const std::int64_t b = idx[static_cast<std::size_t>(i) * nX + j + 1];
            const std::int64_t c =
                idx[static_cast<std::size_t>(i + 1) * nX + j + 1];
            const std::int64_t d = idx[static_cast<std::size_t>(i + 1) * nX + j];
            if (a < 0 || b < 0 || c < 0 || d < 0) {
                continue;  // quads touching a NaN hole are dropped whole
            }
            // Winding: (a, b, c) + (a, c, d) keeps outward-up orientation.
            out.faces.push_back({a, b, c});
            out.faces.push_back({a, c, d});
        }
    }
    return out;
}

TriMesh build_fault_curtain_from_trace(
    const std::string& name,
    const std::vector<std::array<double, 2>>& trace_xy, double z_top,
    double z_bottom) {
    const int n = static_cast<int>(trace_xy.size());
    if (n < 2) {
        throw std::invalid_argument(
            name + ": trace_xy must be (M, 2) with M >= 2");
    }
    for (const auto& p : trace_xy) {
        if (!std::isfinite(p[0]) || !std::isfinite(p[1])) {
            throw std::invalid_argument(name + ": trace_xy must be finite");
        }
    }
    if ((z_bottom - z_top) <= 0.0) {
        throw std::invalid_argument(
            name + ": z_bottom must be below z_top (depth-positive convention)");
    }
    TriMesh out;
    out.verts.resize(static_cast<std::size_t>(2) * n);
    for (int k = 0; k < n; ++k) {
        out.verts[static_cast<std::size_t>(k)] = {trace_xy[k][0], trace_xy[k][1],
                                                  z_top};
        out.verts[static_cast<std::size_t>(n) + k] = {
            trace_xy[k][0], trace_xy[k][1], z_bottom};
    }
    out.faces.resize(static_cast<std::size_t>(2) * (n - 1));
    for (int q = 0; q + 1 < n; ++q) {
        const std::int64_t a = q;
        const std::int64_t b = q + 1;
        const std::int64_t c = q + n + 1;
        const std::int64_t d = q + n;
        out.faces[static_cast<std::size_t>(2 * q)] = {a, b, c};
        out.faces[static_cast<std::size_t>(2 * q + 1)] = {a, c, d};
    }
    return out;
}

namespace {

// Shared kept-cell classification for shell + hex builders: returns the
// kept (i, j) cells in row-major order plus the crossed / non-finite-node
// counters.
struct CellClassification {
    std::vector<std::pair<int, int>> kept;
    std::int64_t crossed_count = 0;
    std::int64_t non_finite_nodes = 0;
};

CellClassification classify_cells(const HorizonGrid& top,
                                  const HorizonGrid& base,
                                  const std::vector<std::array<double, 2>>& bnd) {
    CellClassification cc;
    const int nI = top.rows;
    const int nX = top.cols;
    for (int i = 0; i < nI; ++i) {
        for (int j = 0; j < nX; ++j) {
            if (!std::isfinite(top.at(i, j)) || !std::isfinite(base.at(i, j))) {
                ++cc.non_finite_nodes;
            }
        }
    }
    const double zsign = z_sign(top.vertical_domain);
    struct Candidate {
        int i;
        int j;
        double centre_x;
        double centre_y;
        bool crossed;
    };
    std::vector<Candidate> candidate;
    for (int i = 0; i + 1 < nI; ++i) {
        for (int j = 0; j + 1 < nX; ++j) {
            const double t00 = top.at(i, j), t01 = top.at(i, j + 1);
            const double t10 = top.at(i + 1, j), t11 = top.at(i + 1, j + 1);
            const double b00 = base.at(i, j), b01 = base.at(i, j + 1);
            const double b10 = base.at(i + 1, j), b11 = base.at(i + 1, j + 1);
            const bool finite = std::isfinite(t00) && std::isfinite(t01) &&
                                std::isfinite(t10) && std::isfinite(t11) &&
                                std::isfinite(b00) && std::isfinite(b01) &&
                                std::isfinite(b10) && std::isfinite(b11);
            if (!finite) {
                continue;
            }
            // Cell centre = 0.25 * sum of the four node coordinates, in the
            // Python operand order ((i,j) + (i,j+1) + (i+1,j) + (i+1,j+1)).
            const double centre_x = 0.25 * ((top.origin_x + j * top.spacing_x) +
                                            (top.origin_x + (j + 1) * top.spacing_x) +
                                            (top.origin_x + j * top.spacing_x) +
                                            (top.origin_x + (j + 1) * top.spacing_x));
            const double centre_y = 0.25 * ((top.origin_y + i * top.spacing_y) +
                                            (top.origin_y + i * top.spacing_y) +
                                            (top.origin_y + (i + 1) * top.spacing_y) +
                                            (top.origin_y + (i + 1) * top.spacing_y));
            const bool is_crossed =
                ((b00 - t00) * zsign < 0) || ((b01 - t01) * zsign < 0) ||
                ((b10 - t10) * zsign < 0) || ((b11 - t11) * zsign < 0);
            candidate.push_back({i, j, centre_x, centre_y, is_crossed});
        }
    }
    cc.crossed_count = static_cast<std::int64_t>(
        std::count_if(candidate.begin(), candidate.end(),
                      [](const Candidate& c) { return c.crossed; }));
    for (const Candidate& c : candidate) {
        if (c.crossed) {
            continue;
        }
        if (ring_crossings_strict(c.centre_x, c.centre_y, bnd)) {
            cc.kept.emplace_back(c.i, c.j);
        }
    }
    return cc;
}

}  // namespace

VolumeShell build_volume_shell(
    const HorizonGrid& top, const HorizonGrid& base,
    const std::vector<std::array<double, 2>>& boundary,
    const std::string& object_id) {
    if (top.vertical_domain != base.vertical_domain || top.unit != base.unit) {
        throw std::invalid_argument(
            object_id + ": top/base surfaces must share vertical domain and unit");
    }
    if (boundary.size() < 3) {
        throw std::invalid_argument(
            object_id + ": boundary must be (M, 2) with M >= 3");
    }
    for (const auto& p : boundary) {
        if (!std::isfinite(p[0]) || !std::isfinite(p[1])) {
            throw std::invalid_argument(object_id + ": boundary must be finite");
        }
    }
    if (top.rows != base.rows || top.cols != base.cols ||
        top.origin_x != base.origin_x || top.origin_y != base.origin_y ||
        top.spacing_y != base.spacing_y || top.spacing_x != base.spacing_x) {
        throw std::invalid_argument(
            object_id +
            ": top/base grids must share shape/origin/spacing for column "
            "construction (resample first)");
    }
    const int nI = top.rows;
    const int nX = top.cols;
    if (nI < 2 || nX < 2) {
        throw std::invalid_argument(
            object_id + ": grid needs at least a 2x2 node lattice");
    }

    const CellClassification cc = classify_cells(top, base, boundary);

    VolumeShell out;
    out.qc.column_count = static_cast<std::int64_t>(cc.kept.size());
    out.qc.dropped_crossed = cc.crossed_count;
    out.qc.dropped_nan_nodes = cc.non_finite_nodes;
    out.qc.negative_thickness_count = 0;
    out.qc.unit = top.unit;

    if (cc.kept.empty()) {
        out.qc.min_thickness = 0.0;
        out.qc.max_thickness = 0.0;
        out.qc.mean_thickness = 0.0;
        out.qc.closed = false;
        return out;
    }

    // Node mask: corners of kept cells, compacted row-major.
    std::vector<int> node_ids(static_cast<std::size_t>(nI) * nX, -1);
    for (const auto& [i, j] : cc.kept) {
        node_ids[static_cast<std::size_t>(i) * nX + j] = 0;
        node_ids[static_cast<std::size_t>(i) * nX + j + 1] = 0;
        node_ids[static_cast<std::size_t>(i + 1) * nX + j] = 0;
        node_ids[static_cast<std::size_t>(i + 1) * nX + j + 1] = 0;
    }
    std::int64_t next_id = 0;
    for (int i = 0; i < nI; ++i) {
        for (int j = 0; j < nX; ++j) {
            if (node_ids[static_cast<std::size_t>(i) * nX + j] == 0) {
                node_ids[static_cast<std::size_t>(i) * nX + j] = next_id++;
            }
        }
    }
    const std::int64_t n_shared = next_id;

    out.mesh.verts.resize(static_cast<std::size_t>(2) * n_shared);
    for (int i = 0; i < nI; ++i) {
        for (int j = 0; j < nX; ++j) {
            const std::int64_t id = node_ids[static_cast<std::size_t>(i) * nX + j];
            if (id < 0) {
                continue;
            }
            const double x = top.origin_x + j * top.spacing_x;
            const double y = top.origin_y + i * top.spacing_y;
            out.mesh.verts[static_cast<std::size_t>(id)] = {x, y, top.at(i, j)};
            out.mesh.verts[static_cast<std::size_t>(n_shared) + id] = {x, y,
                                                                       base.at(i, j)};
        }
    }

    const auto nid = [&](int i, int j, std::int64_t sheet_offset) -> std::int64_t {
        return node_ids[static_cast<std::size_t>(i) * nX + j] + sheet_offset;
    };
    std::vector<std::array<std::int64_t, 3>> faces;
    const std::int64_t off_base = n_shared;
    const auto kept_has = [&](int ni, int nj) {
        return std::binary_search(cc.kept.begin(), cc.kept.end(),
                                  std::make_pair(ni, nj));
    };
    for (const auto& [i, j] : cc.kept) {
        const std::int64_t t00 = nid(i, j, 0);
        const std::int64_t t01 = nid(i, j + 1, 0);
        const std::int64_t t10 = nid(i + 1, j, 0);
        const std::int64_t t11 = nid(i + 1, j + 1, 0);
        const std::int64_t b00 = nid(i, j, off_base);
        const std::int64_t b01 = nid(i, j + 1, off_base);
        const std::int64_t b10 = nid(i + 1, j, off_base);
        const std::int64_t b11 = nid(i + 1, j + 1, off_base);
        faces.push_back({t00, t01, t11});
        faces.push_back({t00, t11, t10});
        faces.push_back({b00, b11, b01});
        faces.push_back({b00, b10, b11});
        const double thickness = 0.25 * std::fabs(
            (top.at(i, j) - base.at(i, j)) +
            (top.at(i, j + 1) - base.at(i, j + 1)) +
            (top.at(i + 1, j) - base.at(i + 1, j)) +
            (top.at(i + 1, j + 1) - base.at(i + 1, j + 1)));
        out.thicknesses.push_back(thickness);

        const std::tuple<std::int64_t, std::int64_t, std::int64_t, std::int64_t, int, int>
            edges[] = {
                {t00, t01, b00, b01, i - 1, j},  // -i edge
                {t01, t11, b01, b11, i, j + 1},  // +j edge
                {t11, t10, b11, b10, i + 1, j},  // +i edge
                {t10, t00, b10, b00, i, j - 1},  // -j edge
            };
        for (const auto& [ta, tb, ba, bb, ni, nj] : edges) {
            if (kept_has(ni, nj)) {
                continue;
            }
            faces.push_back({ta, tb, bb});
            faces.push_back({ta, bb, ba});
        }
    }

    out.mesh.faces = orient_faces_outward_impl(out.mesh.verts, std::move(faces));

    out.qc.min_thickness = *std::min_element(out.thicknesses.begin(),
                                             out.thicknesses.end());
    out.qc.max_thickness = *std::max_element(out.thicknesses.begin(),
                                             out.thicknesses.end());
    double sum = 0.0;
    for (const double t : out.thicknesses) {
        sum += t;
    }
    out.qc.mean_thickness =
        sum / static_cast<double>(out.thicknesses.size());
    out.qc.closed = shell_is_closed(out.mesh.verts, out.mesh.faces);
    return out;
}

bool point_in_ring_strict(double x, double y,
                          const std::vector<std::array<double, 2>>& ring) {
    return ring_crossings_strict(x, y, ring);
}

HexMesh build_columnar_hex_mesh(const HorizonGrid& top, const HorizonGrid& base,
                                const std::vector<std::array<double, 2>>& boundary,
                                int n_layers) {
    if (n_layers < 1) {
        throw std::invalid_argument("n_layers must be >= 1");
    }
    if (boundary.size() < 3) {
        throw std::invalid_argument("boundary must be (M, 2) with M >= 3");
    }
    for (const auto& p : boundary) {
        if (!std::isfinite(p[0]) || !std::isfinite(p[1])) {
            throw std::invalid_argument("boundary must be finite");
        }
    }
    if (top.vertical_domain != base.vertical_domain || top.unit != base.unit) {
        throw std::invalid_argument(
            "top/base surfaces must share vertical domain and unit");
    }
    if (top.rows != base.rows || top.cols != base.cols ||
        top.origin_x != base.origin_x || top.origin_y != base.origin_y ||
        top.spacing_y != base.spacing_y || top.spacing_x != base.spacing_x) {
        throw std::invalid_argument(
            "top/base grids must share shape/origin/spacing");
    }
    const int nI = top.rows;
    const int nX = top.cols;
    if (nI < 2 || nX < 2) {
        throw std::invalid_argument("grid needs at least a 2x2 node lattice");
    }

    const CellClassification cc = classify_cells(top, base, boundary);

    HexMesh out;
    out.info.n_cells = static_cast<std::int64_t>(cc.kept.size());
    out.info.n_layers = n_layers;
    out.info.n_hexes = out.info.n_cells * n_layers;
    out.info.skipped_crossed = cc.crossed_count;
    out.info.unit = top.unit;
    out.info.merge = "none";

    const std::size_t n_cells = cc.kept.size();
    out.nodes.resize(n_cells * static_cast<std::size_t>(n_layers + 1) * 4);
    out.hexes.resize(n_cells * static_cast<std::size_t>(n_layers));

    constexpr int corners_i[4] = {0, 1, 1, 0};
    constexpr int corners_j[4] = {0, 0, 1, 1};
    const double step = 1.0 / static_cast<double>(n_layers);

    for (std::size_t c = 0; c < n_cells; ++c) {
        const auto [i, j] = cc.kept[c];
        const std::size_t cell_node_base =
            c * static_cast<std::size_t>(n_layers + 1) * 4;
        for (int corner = 0; corner < 4; ++corner) {
            const int gi = i + corners_i[corner];
            const int gj = j + corners_j[corner];
            const double cx = top.origin_x + gj * top.spacing_x;
            const double cy = top.origin_y + gi * top.spacing_y;
            const double zt = top.at(gi, gj);
            const double zb = base.at(gi, gj);
            for (int layer = 0; layer <= n_layers; ++layer) {
                const double f = layer == n_layers
                                     ? 1.0
                                     : static_cast<double>(layer) * step;
                const std::size_t idx =
                    cell_node_base + static_cast<std::size_t>(layer) * 4 + corner;
                out.nodes[idx] = {cx, cy, zt + (zb - zt) * f};
            }
        }
        for (int layer = 0; layer < n_layers; ++layer) {
            const std::size_t lo =
                cell_node_base + static_cast<std::size_t>(layer) * 4;
            auto& hex = out.hexes[c * static_cast<std::size_t>(n_layers) + layer];
            for (int k = 0; k < 4; ++k) {
                hex[k] = static_cast<std::int64_t>(lo + k);
                hex[k + 4] = static_cast<std::int64_t>(lo + 4 + k);
            }
        }
    }
    return out;
}

namespace {

bool shell_is_closed(const std::vector<Vec3>&,
                     const std::vector<std::array<std::int64_t, 3>>& faces) {
    if (faces.empty()) {
        return false;
    }
    std::int64_t max_hi = 0;
    for (const auto& f : faces) {
        max_hi = std::max({max_hi, f[0], f[1], f[2]});
    }
    std::vector<std::int64_t> keys;
    keys.reserve(faces.size() * 3);
    for (const auto& f : faces) {
        const std::int64_t tri[3] = {f[0], f[1], f[2]};
        for (int e = 0; e < 3; ++e) {
            const std::int64_t a = tri[e];
            const std::int64_t b = tri[(e + 1) % 3];
            keys.push_back(std::min(a, b) * (max_hi + 1) + std::max(a, b));
        }
    }
    std::sort(keys.begin(), keys.end());
    bool all_two = true;
    for (std::size_t k = 0; k < keys.size();) {
        std::size_t run = 1;
        while (k + run < keys.size() && keys[k + run] == keys[k]) {
            ++run;
        }
        if (run != 2) {
            all_two = false;
            break;
        }
        k += run;
    }
    return all_two;
}

}  // namespace

}  // namespace pwb::geomodel
