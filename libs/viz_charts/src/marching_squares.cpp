#include <pwb/viz_charts/marching_squares.hpp>

#include <pwb/viz_charts/colormaps.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <deque>
#include <map>
#include <tuple>
#include <utility>
#include <vector>

namespace pwb::viz_charts {
namespace {

// A crossing point is keyed by the grid edge it lies on — exact identity
// for chaining (no float-tolerance hashing). kind 0 = horizontal grid edge
// (top of cell (i,j)), kind 1 = vertical grid edge (left of cell (i,j)),
// kind 2 = cell-center diagonal reaching `corner` (0=tl,1=tr,2=br,3=bl).
struct EdgeKey {
    int kind = 0;
    std::size_t i = 0;
    std::size_t j = 0;
    int corner = 0;
    bool operator<(const EdgeKey& o) const {
        return std::tie(kind, i, j, corner) < std::tie(o.kind, o.i, o.j, o.corner);
    }
    bool operator==(const EdgeKey& o) const {
        return kind == o.kind && i == o.i && j == o.j && corner == o.corner;
    }
};

struct Vertex {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

struct Segment {
    EdgeKey ka;
    EdgeKey kb;
    double ax = 0.0, ay = 0.0;
    double bx = 0.0, by = 0.0;
};

Vertex mix(const Vertex& a, const Vertex& b, double t) {
    return {a.x + t * (b.x - a.x), a.y + t * (b.y - a.y),
            a.z + t * (b.z - a.z)};
}

// Triangle (center, cA, cB) with the grid-edge key of each of its three
// sides. `corner` values follow the cell-local numbering 0=tl 1=tr 2=br
// 3=bl, -1 = the cell center. Sides shared between triangles of the same
// cell (the diagonals) and sides shared with neighbouring cells (grid
// edges) get identical keys, so crossing points computed from either side
// chain exactly.
struct TriKeys {
    Vertex v[3];
    EdgeKey k[3];
};

// Triangulation of one grid cell, contourpy's NaN semantics: a quad with a
// non-finite corner is contoured over the triangle of its three valid
// corners (the diagonal skips the NaN corner); quads with two or more
// non-finite corners contribute nothing (verified against contourpy serial
// — see docs/development/cpp-viz-e/scope-ledger.md).
std::vector<TriKeys> cell_triangles(const std::vector<double>& gx,
                                    const std::vector<double>& gy,
                                    const std::vector<double>& z,
                                    std::size_t cols, std::size_t i,
                                    std::size_t j) {
    const Vertex corners[4] = {
        {gx[j], gy[i], z[i * cols + j]},           // 0 = tl
        {gx[j + 1], gy[i], z[i * cols + j + 1]},   // 1 = tr
        {gx[j + 1], gy[i + 1], z[(i + 1) * cols + j + 1]},  // 2 = br
        {gx[j], gy[i + 1], z[(i + 1) * cols + j]}, // 3 = bl
    };
    bool fin[4];
    int nfin = 0;
    for (int c = 0; c < 4; ++c) {
        fin[c] = std::isfinite(corners[c].z);
        nfin += fin[c] ? 1 : 0;
    }
    // Grid-edge keys shared with neighbours.
    const EdgeKey top{0, i, j, 0};        // horizontal edge of row i
    const EdgeKey bottom{0, i + 1, j, 0}; // horizontal edge of row i+1
    const EdgeKey left{1, i, j, 0};       // vertical edge of col j
    const EdgeKey right{1, i, j + 1, 0};  // vertical edge of col j+1
    const auto grid_key = [&](int a, int b) -> EdgeKey {
        if ((a == 0 && b == 1) || (a == 1 && b == 0)) return top;
        if ((a == 1 && b == 2) || (a == 2 && b == 1)) return right;
        if ((a == 2 && b == 3) || (a == 3 && b == 2)) return bottom;
        return left;  // 3-0
    };
    std::vector<TriKeys> out;
    if (nfin == 4) {
        const Vertex ctr{(corners[0].x + corners[1].x) / 2.0,
                         (corners[0].y + corners[3].y) / 2.0,
                         (corners[0].z + corners[1].z + corners[2].z +
                          corners[3].z) /
                             4.0};
        // Bilinear-center subdivision: CCW triangles around the center;
        // saddle cells resolve through the center value automatically.
        const EdgeKey d_tl{2, i, j, 0}, d_tr{2, i, j, 1};
        const EdgeKey d_br{2, i, j, 2}, d_bl{2, i, j, 3};
        out.push_back({{ctr, corners[0], corners[1]}, {d_tl, top, d_tr}});
        out.push_back({{ctr, corners[1], corners[2]}, {d_tr, right, d_br}});
        out.push_back({{ctr, corners[2], corners[3]}, {d_br, bottom, d_bl}});
        out.push_back({{ctr, corners[3], corners[0]}, {d_bl, left, d_tl}});
    } else if (nfin == 3) {
        // Cyclic corner order (0,1,2,3) minus the invalid corner; the edge
        // spanning the invalid corner is a cell-local diagonal keyed by it.
        int order[3];
        int m = 0;
        for (int c = 0; c < 4; ++c) {
            if (fin[c]) {
                order[m++] = c;
            }
        }
        // order[] is in cyclic quad order; edges (order0,order1),
        // (order1,order2), (order2,order0). The pair with index distance 2
        // (mod 4) is the diagonal past the NaN corner.
        const auto diag_key = [&](int a, int b) {
            return EdgeKey{2, i, j, a};  // corner id disambiguates
        };
        const int pairs[3][2] = {{order[0], order[1]},
                                 {order[1], order[2]},
                                 {order[2], order[0]}};
        TriKeys t;
        for (int e = 0; e < 3; ++e) {
            const int a = pairs[e][0];
            const int b = pairs[e][1];
            const int dist = (a - b + 4) % 4;
            t.v[e] = corners[a];
            t.k[e] = (dist == 2) ? diag_key(a, b) : grid_key(a, b);
        }
        // v[] currently holds corner a of each edge; the triangle's
        // vertices are exactly those three corners (a-values already
        // distinct and cyclic).
        out.push_back(t);
    }
    return out;
}

// Per-triangle iso-chord: a linear field crosses the level on exactly 0 or
// 2 of the three sides (strict `>` classification, Python parity). Used for
// partially-masked cells (contourpy contours the triangle of valid corners
// — verified against the serial backend).
void emit_triangle(const TriKeys& t, double lv, std::vector<Segment>& out) {
    double px[2] = {0, 0}, py[2] = {0, 0};
    EdgeKey pk[2];
    int n = 0;
    for (int e = 0; e < 3 && n < 2; ++e) {
        const Vertex& u = t.v[e];
        const Vertex& v = t.v[(e + 1) % 3];
        if ((u.z > lv) != (v.z > lv)) {
            const double ratio = (lv - u.z) / (v.z - u.z);
            const Vertex p = mix(u, v, ratio);
            px[n] = p.x;
            py[n] = p.y;
            pk[n] = t.k[e];
            ++n;
        }
    }
    if (n == 2) {
        out.push_back({pk[0], pk[1], px[0], py[0], px[1], py[1]});
    }
}

// Quad-based iso-line extraction over a fully-valid cell — the same
// topology contourpy's serial backend produces: crossings live on the four
// cell edges only (computed bit-identically by both cells sharing an
// edge), saddle cells pair the chords around the corner pair the center
// mean isolates, and a corner sitting exactly on the level yields a chord
// endpoint at that corner.
struct QuadCrossing {
    bool present = false;
    double x = 0.0;
    double y = 0.0;
};

void emit_quad_lines(const Vertex corners[4], std::size_t i, std::size_t j,
                     const std::vector<double>& gx,
                     const std::vector<double>& gy, double lv,
                     std::vector<Segment>& out) {
    const bool bit[4] = {corners[0].z > lv, corners[1].z > lv,
                         corners[2].z > lv, corners[3].z > lv};
    QuadCrossing top, right, bottom, left;
    if (bit[0] != bit[1]) {
        const double t = (lv - corners[0].z) / (corners[1].z - corners[0].z);
        top = {true, gx[j] + t * (gx[j + 1] - gx[j]), gy[i]};
    }
    if (bit[1] != bit[2]) {
        const double t = (lv - corners[1].z) / (corners[2].z - corners[1].z);
        right = {true, gx[j + 1], gy[i] + t * (gy[i + 1] - gy[i])};
    }
    if (bit[3] != bit[2]) {
        const double t = (lv - corners[3].z) / (corners[2].z - corners[3].z);
        bottom = {true, gx[j] + t * (gx[j + 1] - gx[j]), gy[i + 1]};
    }
    if (bit[0] != bit[3]) {
        const double t = (lv - corners[0].z) / (corners[3].z - corners[0].z);
        left = {true, gx[j], gy[i] + t * (gy[i + 1] - gy[i])};
    }

    const EdgeKey k_top{0, i, j, 0};
    const EdgeKey k_bottom{0, i + 1, j, 0};
    const EdgeKey k_left{1, i, j, 0};
    const EdgeKey k_right{1, i, j + 1, 0};
    const auto emit = [&](const QuadCrossing& a, const EdgeKey& ka,
                          const QuadCrossing& b, const EdgeKey& kb) {
        out.push_back({ka, kb, a.x, a.y, b.x, b.y});
    };

    const int n_cross = static_cast<int>(top.present) +
                        static_cast<int>(right.present) +
                        static_cast<int>(bottom.present) +
                        static_cast<int>(left.present);
    if (n_cross == 2) {
        if (top.present && right.present) {
            emit(top, k_top, right, k_right);
        } else if (right.present && bottom.present) {
            emit(right, k_right, bottom, k_bottom);
        } else if (bottom.present && left.present) {
            emit(bottom, k_bottom, left, k_left);
        } else if (left.present && top.present) {
            emit(left, k_left, top, k_top);
        } else if (top.present && bottom.present) {
            emit(top, k_top, bottom, k_bottom);
        } else {
            emit(left, k_left, right, k_right);
        }
    } else if (n_cross == 4) {
        // Saddle: the center mean decides which diagonal corner pair the
        // surface connects; chords wrap the isolated pair.
        const double center =
            (corners[0].z + corners[1].z + corners[2].z + corners[3].z) / 4.0;
        const bool center_high = center > lv;
        for (int c = 0; c < 4; ++c) {
            if (bit[c] == center_high) {
                continue;  // connected pair — no chord around it
            }
            switch (c) {
                case 0: emit(top, k_top, left, k_left); break;
                case 1: emit(top, k_top, right, k_right); break;
                case 2: emit(right, k_right, bottom, k_bottom); break;
                case 3: emit(bottom, k_bottom, left, k_left); break;
            }
        }
    }
}

// Sutherland–Hodgman clip by one half-plane of the triangle's linear
// interpolant (keep_above=true keeps z >= lv; false keeps z < lv).
std::vector<Vertex> clip_halfplane(std::vector<Vertex> poly, double lv,
                                   bool keep_above) {
    std::vector<Vertex> out;
    const std::size_t n = poly.size();
    for (std::size_t e = 0; e < n; ++e) {
        const Vertex& cur = poly[e];
        const Vertex& nxt = poly[(e + 1) % n];
        const auto inside = [&](const Vertex& v) {
            return keep_above ? (v.z >= lv) : (v.z < lv);
        };
        const bool ic = inside(cur);
        const bool in = inside(nxt);
        if (ic) {
            out.push_back(cur);
        }
        if (ic != in) {
            const double ratio = (lv - cur.z) / (nxt.z - cur.z);
            out.push_back(mix(cur, nxt, ratio));
        }
    }
    return out;
}

// Join segments into polylines through shared edge keys. Each key carries
// at most two segments (one crossing point per grid edge per level), so
// the walk is deterministic; loops close by repeating the first point.
std::vector<Polyline> chain_segments(const std::vector<Segment>& segments) {
    std::map<EdgeKey, std::vector<std::pair<std::size_t, int>>> adj;
    for (std::size_t s = 0; s < segments.size(); ++s) {
        adj[segments[s].ka].push_back({s, 0});
        adj[segments[s].kb].push_back({s, 1});
    }
    std::vector<char> used(segments.size(), 0);
    std::vector<Polyline> lines;
    for (std::size_t s = 0; s < segments.size(); ++s) {
        if (used[s]) {
            continue;
        }
        used[s] = 1;
        std::deque<double> xs{segments[s].ax, segments[s].bx};
        std::deque<double> ys{segments[s].ay, segments[s].by};
        EdgeKey end_keys[2] = {segments[s].kb, segments[s].ka};
        for (int dir = 0; dir < 2; ++dir) {
            EdgeKey cur = end_keys[dir];
            while (true) {
                const auto it = adj.find(cur);
                if (it == adj.end()) {
                    break;
                }
                std::size_t next = static_cast<std::size_t>(-1);
                int slot = -1;
                for (const auto& [si, sl] : it->second) {
                    if (!used[si]) {
                        next = si;
                        slot = sl;
                        break;
                    }
                }
                if (next == static_cast<std::size_t>(-1)) {
                    break;
                }
                used[next] = 1;
                const Segment& ns = segments[next];
                const bool at_a = (slot == 0);
                const double nx = at_a ? ns.bx : ns.ax;
                const double ny = at_a ? ns.by : ns.ay;
                if (dir == 0) {
                    xs.push_back(nx);
                    ys.push_back(ny);
                } else {
                    xs.push_front(nx);
                    ys.push_front(ny);
                }
                cur = at_a ? ns.kb : ns.ka;
            }
        }
        Polyline line;
        line.xs.assign(xs.begin(), xs.end());
        line.ys.assign(ys.begin(), ys.end());
        lines.push_back(std::move(line));
    }
    return lines;
}

// f"{lo:g}-{hi:g}"
std::string level_label(double lo, double hi) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%g-%g", lo, hi);
    return buf;
}


}  // namespace

std::optional<std::vector<std::pair<double, std::vector<Polyline>>>>
extract_contour_lines(const std::vector<double>& grid_x,
                      const std::vector<double>& grid_y,
                      const std::vector<double>& grid_z,
                      const std::vector<double>& levels,
                      const CancelCheck& cancelled) {
    const auto check = [&]() { return cancelled && cancelled(); };
    if (check()) {
        return std::nullopt;
    }
    const std::size_t cols = grid_x.size();
    const std::size_t rows = grid_y.size();
    std::vector<std::pair<double, std::vector<Polyline>>> result;
    if (rows < 2 || cols < 2 || grid_z.size() != rows * cols) {
        return result;
    }
    result.reserve(levels.size());
    for (const double lv : levels) {
        if (check()) {
            return std::nullopt;
        }
        std::vector<Segment> segments;
        for (std::size_t i = 0; i + 1 < rows; ++i) {
            for (std::size_t j = 0; j + 1 < cols; ++j) {
                const Vertex corners[4] = {
                    {grid_x[j], grid_y[i], grid_z[i * cols + j]},
                    {grid_x[j + 1], grid_y[i], grid_z[i * cols + j + 1]},
                    {grid_x[j + 1], grid_y[i + 1],
                     grid_z[(i + 1) * cols + j + 1]},
                    {grid_x[j], grid_y[i + 1], grid_z[(i + 1) * cols + j]}};
                const int nfin =
                    static_cast<int>(std::isfinite(corners[0].z)) +
                    static_cast<int>(std::isfinite(corners[1].z)) +
                    static_cast<int>(std::isfinite(corners[2].z)) +
                    static_cast<int>(std::isfinite(corners[3].z));
                if (nfin == 4) {
                    emit_quad_lines(corners, i, j, grid_x, grid_y, lv,
                                    segments);
                } else if (nfin == 3) {
                    for (const TriKeys& t :
                         cell_triangles(grid_x, grid_y, grid_z, cols, i, j)) {
                        emit_triangle(t, lv, segments);
                    }
                }
            }
        }
        result.emplace_back(lv, chain_segments(std::move(segments)));
    }
    return result;
}

std::optional<std::vector<BandedFill>> extract_filled_contours(
    const std::vector<double>& grid_x, const std::vector<double>& grid_y,
    const std::vector<double>& grid_z, const std::vector<double>& levels,
    std::string_view palette, const CancelCheck& cancelled) {
    const auto check = [&]() { return cancelled && cancelled(); };
    if (check()) {
        return std::nullopt;
    }
    const std::size_t cols = grid_x.size();
    const std::size_t rows = grid_y.size();
    std::vector<BandedFill> bands;
    if (rows < 2 || cols < 2 || grid_z.size() != rows * cols || levels.empty()) {
        return bands;
    }
    std::vector<double> sorted_levels = levels;
    std::sort(sorted_levels.begin(), sorted_levels.end());
    const double vmin = sorted_levels.front();
    const double vmax = sorted_levels.back();

    for (std::size_t b = 0; b + 1 < sorted_levels.size(); ++b) {
        if (check()) {
            return std::nullopt;
        }
        const double lo = sorted_levels[b];
        const double hi = sorted_levels[b + 1];
        BandedFill band;
        band.level_min = lo;
        band.level_max = hi;
        for (std::size_t i = 0; i + 1 < rows; ++i) {
            for (std::size_t j = 0; j + 1 < cols; ++j) {
                for (const TriKeys& t :
                     cell_triangles(grid_x, grid_y, grid_z, cols, i, j)) {
                    // Band region inside the triangle = {z >= lo} ∩ {z < hi}
                    // under the linear interpolant; the bilinear center
                    // disambiguates saddles automatically. Per-triangle
                    // polygons tile the band (holes stay empty), which the
                    // painter fills in one OddEvenFill path.
                    std::vector<Vertex> poly(t.v, t.v + 3);
                    poly = clip_halfplane(std::move(poly), lo, true);
                    if (poly.size() < 3) {
                        continue;
                    }
                    poly = clip_halfplane(std::move(poly), hi, false);
                    if (poly.size() < 3) {
                        continue;
                    }
                    Polyline ring;
                    ring.xs.reserve(poly.size());
                    ring.ys.reserve(poly.size());
                    for (const Vertex& v : poly) {
                        ring.xs.push_back(v.x);
                        ring.ys.push_back(v.y);
                    }
                    band.rings.points.push_back(std::move(ring));
                    band.rings.offsets.push_back({0, poly.size()});
                }
            }
        }
        const double midpoint = (lo + hi) / 2.0;
        const Rgb color = sample_colormap(palette, midpoint, vmin, vmax);
        band.color_r = color.r;
        band.color_g = color.g;
        band.color_b = color.b;
        band.label = level_label(lo, hi);
        bands.push_back(std::move(band));
    }
    return bands;
}

}  // namespace pwb::viz_charts
