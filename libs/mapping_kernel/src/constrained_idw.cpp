// Constrained-IDW surface kernel — see constrained_idw.hpp for scope,
// provenance and the frozen-oracle contract.

#include <pwb/mapping/constrained_idw.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>
#include <stdexcept>
#include <utility>

namespace pwb::mapping::constrained_idw {
namespace {

using pwb::mapping::Point;

constexpr double kInf = std::numeric_limits<double>::infinity();
constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
constexpr double kPi = 3.14159265358979323846;

// numpy's pairwise summation tree (numpy/core/src/umath/loops.c.src) so
// np.sum over k-length reductions matches bit-for-bit.
double numpy_pairwise_sum(const double* a, std::size_t n) {
    if (n < 8) {
        double res = 0.0;
        for (std::size_t i = 0; i < n; ++i) res += a[i];
        return res;
    }
    if (n <= 128) {
        double r[8];
        for (std::size_t i = 0; i < 8; ++i) r[i] = a[i];
        std::size_t i = 8;
        for (; i < n - (n % 8); i += 8) {
            r[0] += a[i + 0];
            r[1] += a[i + 1];
            r[2] += a[i + 2];
            r[3] += a[i + 3];
            r[4] += a[i + 4];
            r[5] += a[i + 5];
            r[6] += a[i + 6];
            r[7] += a[i + 7];
        }
        double res = ((r[0] + r[1]) + (r[2] + r[3])) +
                     ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; ++i) res += a[i];
        return res;
    }
    std::size_t n2 = n / 2;
    n2 -= n2 % 8;
    return numpy_pairwise_sum(a, n2) + numpy_pairwise_sum(a + n2, n - n2);
}

double numpy_sum(const std::vector<double>& v) {
    return numpy_pairwise_sum(v.data(), v.size());
}

// np.median: sorted copy; even length -> mean of the two middle values.
double numpy_median(std::vector<double> v) {
    if (v.empty()) return kNaN;
    std::sort(v.begin(), v.end());
    const std::size_t n = v.size();
    if (n % 2 == 1) return v[n / 2];
    return (v[n / 2 - 1] + v[n / 2]) / 2.0;
}

double clamp01(double v) { return std::max(0.0, std::min(1.0, v)); }

// Python .strip().lower() for string enumerations (block_mode/extend_mode).
std::string lower_trim(std::string s) {
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.front()))) {
        s.erase(s.begin());
    }
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back()))) {
        s.pop_back();
    }
    for (char& c : s) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return s;
}

// Python round(): half-to-even; the int cast clamps to a safe range first
// (far-out-of-grid coordinates would be UB in C++, Python makes big ints).
int py_round_int(double v) {
    constexpr double kLo = -1.0e9, kHi = 1.0e9;
    return static_cast<int>(
        std::nearbyint(std::max(kLo, std::min(kHi, v))));
}

// np.linspace(start, stop, num): y_i = i * ((stop-start)/(num-1)) + start,
// last element forced to stop.
std::vector<double> linspace(double start, double stop, std::size_t num) {
    std::vector<double> out(num, start);
    if (num == 0) return out;
    if (num == 1) {
        out[0] = start;
        return out;
    }
    const double step = (stop - start) / static_cast<double>(num - 1);
    for (std::size_t i = 0; i < num; ++i) {
        out[i] = static_cast<double>(i) * step + start;
    }
    out[num - 1] = stop;
    return out;
}

std::size_t argmin_abs(const std::vector<double>& axis, double x) {
    std::size_t best = 0;
    double best_val = std::abs(axis[0] - x);
    for (std::size_t i = 1; i < axis.size(); ++i) {
        const double val = std::abs(axis[i] - x);
        if (val < best_val) {
            best_val = val;
            best = i;
        }
    }
    return best;
}

// --------------------------------------------------------------------------- //
// Geometry predicates (constrained_engine.py)
// --------------------------------------------------------------------------- //

struct Seg {
    double ax, ay, bx, by;
};

std::vector<Seg> barrier_segments(const std::vector<BarrierLine>& barriers) {
    std::vector<Seg> out;
    for (const auto& barrier : barriers) {
        for (std::size_t i = 0; i + 1 < barrier.points.size(); ++i) {
            out.push_back({barrier.points[i][0], barrier.points[i][1],
                           barrier.points[i + 1][0], barrier.points[i + 1][1]});
        }
    }
    return out;
}

double cross2(double ax, double ay, double bx, double by) {
    return ax * by - ay * bx;
}

// strict_segments_intersect(a, b, c, d, tol)
bool strict_segments_intersect(double ax, double ay, double bx, double by,
                               double cx, double cy, double dx, double dy,
                               double tol) {
    const double rx = bx - ax, ry = by - ay;
    const double sx = dx - cx, sy = dy - cy;
    const double denom = cross2(rx, ry, sx, sy);
    const double qpx = cx - ax, qpy = cy - ay;
    if (std::abs(denom) <= 1e-12) {
        if (std::abs(cross2(qpx, qpy, rx, ry)) > 1e-12) return false;
        const double rr = rx * rx + ry * ry;
        if (rr <= 1e-24) return false;
        const double t0 = ((cx - ax) * rx + (cy - ay) * ry) / rr;
        const double t1 = ((dx - ax) * rx + (dy - ay) * ry) / rr;
        const double lo = std::min(t0, t1);
        const double hi = std::max(t0, t1);
        return hi > tol && lo < 1.0 - tol;
    }
    const double t = cross2(qpx, qpy, sx, sy) / denom;
    const double u = cross2(qpx, qpy, rx, ry) / denom;
    return tol < t && t < 1.0 - tol && -tol <= u && u <= 1.0 + tol;
}

bool blocked_by_barrier(double ax, double ay, double bx, double by,
                        const std::vector<Seg>& segments, double tol) {
    for (const Seg& s : segments) {
        if (strict_segments_intersect(ax, ay, bx, by, s.ax, s.ay, s.bx, s.by,
                                      tol)) {
            return true;
        }
    }
    return false;
}

double point_to_segment_distance(double px, double py, double ax, double ay,
                                 double bx, double by) {
    const double dx = bx - ax, dy = by - ay;
    const double len2 = dx * dx + dy * dy;
    if (len2 < 1e-12) return std::hypot(px - ax, py - ay);
    const double t = std::max(
        0.0, std::min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2));
    return std::hypot(px - (ax + t * dx), py - (ay + t * dy));
}

// fast_grid.rasterize_polygon_mask — strict ray cast (cell centers exactly on
// the ring are NOT inside).
void rasterize_polygon_mask(const std::vector<double>& grid_x,
                            const std::vector<double>& grid_y,
                            const std::vector<Point>& ring,
                            std::vector<std::uint8_t>& out) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    if (ring.size() < 3) return;  // stays zero
    const std::size_t count = ring.size();
    for (std::size_t row = 0; row < rows; ++row) {
        const double py = grid_y[row];
        for (std::size_t col = 0; col < cols; ++col) {
            const double px = grid_x[col];
            bool inside = false;
            std::size_t j = count - 1;
            for (std::size_t i = 0; i < count; ++i) {
                const double xi = ring[i][0], yi = ring[i][1];
                const double xj = ring[j][0], yj = ring[j][1];
                const bool cond = (yi > py) != (yj > py);
                if (cond) {
                    const double denom = yj - yi;
                    const double safe = std::abs(denom) > 1e-30 ? denom : 1e-30;
                    const double x_intersect =
                        (xj - xi) * (py - yi) / safe + xi;
                    if (px < x_intersect) inside = !inside;
                }
                j = i;
            }
            if (inside) out[row * cols + col] = 1;
        }
    }
}

// fast_grid.build_boundary_union_mask (exterior minus holes, unioned).
void build_boundary_union_mask(const std::vector<double>& grid_x,
                               const std::vector<double>& grid_y,
                               const std::vector<BoundaryPolygon>& boundaries,
                               std::vector<std::uint8_t>& mask) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    mask.assign(rows * cols, 0);
    for (const auto& boundary : boundaries) {
        if (boundary.exterior.size() < 3) continue;
        std::vector<std::uint8_t> poly(rows * cols, 0);
        rasterize_polygon_mask(grid_x, grid_y, boundary.exterior, poly);
        for (const auto& hole : boundary.holes) {
            if (hole.size() < 3) continue;
            std::vector<std::uint8_t> hole_mask(rows * cols, 0);
            rasterize_polygon_mask(grid_x, grid_y, hole, hole_mask);
            for (std::size_t i = 0; i < poly.size(); ++i) {
                if (hole_mask[i]) poly[i] = 0;
            }
        }
        for (std::size_t i = 0; i < mask.size(); ++i) {
            if (poly[i]) mask[i] = 1;
        }
    }
}

// masks._convex_hull — monotone chain over lexicographically sorted unique
// points (strictly convex, CCW: cross <= 0 pops).
std::vector<Point> convex_hull(std::vector<Point> points) {
    std::sort(points.begin(), points.end(),
              [](const Point& a, const Point& b) {
                  return a[0] < b[0] || (a[0] == b[0] && a[1] < b[1]);
              });
    points.erase(
        std::unique(points.begin(), points.end(),
                    [](const Point& a, const Point& b) {
                        return a[0] == b[0] && a[1] == b[1];
                    }),
        points.end());
    if (points.size() <= 2) return points;
    auto half = [&](auto begin, auto end) {
        std::vector<Point> chain;
        for (auto it = begin; it != end; ++it) {
            while (chain.size() >= 2) {
                const Point& o = chain[chain.size() - 2];
                const Point& a = chain[chain.size() - 1];
                if ((a[0] - o[0]) * ((*it)[1] - o[1]) -
                        (a[1] - o[1]) * ((*it)[0] - o[0]) <=
                    0.0) {
                    chain.pop_back();
                } else {
                    break;
                }
            }
            chain.push_back(*it);
        }
        return chain;
    };
    std::vector<Point> lower = half(points.begin(), points.end());
    std::vector<Point> upper = half(points.rbegin(), points.rend());
    std::vector<Point> hull(lower.begin(), lower.end() - 1);
    hull.insert(hull.end(), upper.begin(), upper.end() - 1);
    return hull;
}

bool data_hull_exists(const std::vector<Well>& wells) {
    if (wells.size() < 3) return false;
    std::vector<Point> pts;
    pts.reserve(wells.size());
    for (const auto& w : wells) pts.push_back({w.x, w.y});
    return convex_hull(std::move(pts)).size() >= 3;
}

// masks.build_data_hull_mask chain: hull (+ radial offset) rasterized.
// Returns false only when no usable hull exists; a hull whose raster covers
// zero cell centers still returns true with an all-zero mask (Python masks
// the whole domain out in that case).
bool build_data_hull_mask(const std::vector<double>& grid_x,
                          const std::vector<double>& grid_y,
                          const std::vector<Well>& wells,
                          double buffer_meters,
                          std::vector<std::uint8_t>& out) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    if (wells.size() < 3) return false;
    std::vector<Point> pts;
    pts.reserve(wells.size());
    for (const auto& w : wells) pts.push_back({w.x, w.y});
    std::vector<Point> hull = convex_hull(std::move(pts));
    if (hull.size() < 3) return false;
    if (buffer_meters > 0.0) {
        double cx = 0.0, cy = 0.0;
        for (const Point& p : hull) {
            cx += p[0];
            cy += p[1];
        }
        cx /= static_cast<double>(hull.size());
        cy /= static_cast<double>(hull.size());
        for (Point& p : hull) {
            const double dx = p[0] - cx, dy = p[1] - cy;
            const double length = std::hypot(dx, dy);
            if (length <= 1e-12) continue;
            const double scale = (length + buffer_meters) / length;
            p[0] = cx + dx * scale;
            p[1] = cy + dy * scale;
        }
    }
    out.assign(rows * cols, 0);
    rasterize_polygon_mask(grid_x, grid_y, hull, out);
    return true;
}

// scipy.ndimage.distance_transform_edt, exact: for every True cell the
// distance to the nearest False cell. Felzenszwalb two-pass on integer
// squared distances (BIG = 1e15 sentinel stays exact under 2^53 and never
// wins once a background cell exists) -> IEEE sqrt is bit-identical to scipy.
// An input without any False cell yields infinity (scipy's value there is
// undefined; unreachable from the frozen pipeline).
void distance_transform_edt(const std::vector<std::uint8_t>& mask,
                            std::size_t rows, std::size_t cols,
                            std::vector<double>& out) {
    const std::size_t n = rows * cols;
    constexpr double kBig = 1e15;
    bool any_zero = false;
    for (std::size_t i = 0; i < n; ++i) {
        if (!mask[i]) any_zero = true;
    }
    if (!any_zero) {
        out.assign(n, kInf);
        return;
    }
    std::vector<double> f(n, 0.0);
    for (std::size_t i = 0; i < n; ++i) f[i] = mask[i] ? kBig : 0.0;
    auto pass1d = [&](auto get, auto set, std::size_t len) {
        std::vector<std::size_t> v(len, 0);
        std::vector<double> z(len + 1, 0.0);
        std::size_t k = 0;
        v[0] = 0;
        z[0] = -kBig;
        z[1] = kBig;
        for (std::size_t q = 1; q < len; ++q) {
            const double fq = get(q) + static_cast<double>(q) *
                                             static_cast<double>(q);
            const double fv = get(v[k]) + static_cast<double>(v[k]) *
                                              static_cast<double>(v[k]);
            double s = (fq - fv) / (2.0 * static_cast<double>(q) -
                                    2.0 * static_cast<double>(v[k]));
            while (s <= z[k]) {
                --k;
                const double fv2 = get(v[k]) + static_cast<double>(v[k]) *
                                                   static_cast<double>(v[k]);
                s = (fq - fv2) / (2.0 * static_cast<double>(q) -
                                  2.0 * static_cast<double>(v[k]));
            }
            ++k;
            v[k] = q;
            z[k] = s;
            z[k + 1] = kBig;
        }
        // Extract into a scratch buffer: writing in place would clobber the
        // input values still queried by later positions.
        std::vector<double> out(len, 0.0);
        k = 0;
        for (std::size_t q = 0; q < len; ++q) {
            while (z[k + 1] < static_cast<double>(q)) ++k;
            const std::size_t idx = v[k];
            const double dd =
                static_cast<double>(q) - static_cast<double>(idx);
            out[q] = dd * dd + get(idx);
        }
        for (std::size_t q = 0; q < len; ++q) set(q, out[q]);
    };
    for (std::size_t row = 0; row < rows; ++row) {
        const std::size_t base = row * cols;
        pass1d([&](std::size_t q) { return f[base + q]; },
               [&](std::size_t q, double val) { f[base + q] = val; }, cols);
    }
    for (std::size_t col = 0; col < cols; ++col) {
        pass1d([&](std::size_t q) { return f[q * cols + col]; },
               [&](std::size_t q, double val) { f[q * cols + col] = val; },
               rows);
    }
    out.resize(n);
    for (std::size_t i = 0; i < n; ++i) out[i] = std::sqrt(f[i]);
}

// masks.build_bfs_reach_mask — domain cells within reach of any seed (EDT).
void build_bfs_reach_mask(const std::vector<std::uint8_t>& seed_mask,
                          const std::vector<std::uint8_t>& domain_mask,
                          std::size_t rows, std::size_t cols,
                          double max_distance_cells,
                          std::vector<std::uint8_t>& out) {
    const std::size_t n = rows * cols;
    std::vector<std::uint8_t> seeds(n, 0);
    bool any_seed = false;
    for (std::size_t i = 0; i < n; ++i) {
        seeds[i] = (seed_mask[i] && domain_mask[i]) ? 1 : 0;
        any_seed = any_seed || seeds[i] != 0;
    }
    if (max_distance_cells <= 0.0 || !any_seed) {
        out = seeds;  // Python returns seeds & domain
        return;
    }
    out.assign(n, 0);
    // scipy: distance_transform_edt(~seeds) — non-seed cells measure the
    // distance to the nearest seed; seed cells sit at 0.
    std::vector<std::uint8_t> not_seeds(n);
    for (std::size_t i = 0; i < n; ++i) not_seeds[i] = seeds[i] ? 0 : 1;
    std::vector<double> dist;
    distance_transform_edt(not_seeds, rows, cols, dist);
    for (std::size_t i = 0; i < n; ++i) {
        if (domain_mask[i] && dist[i] <= max_distance_cells) out[i] = 1;
    }
}

// constrained_engine.build_barrier_blank_mask — stadium-distance corridor.
// Returns false when the mask is empty (Python returns None).
bool build_barrier_blank_mask(const std::vector<double>& grid_x,
                              const std::vector<double>& grid_y,
                              const std::vector<BarrierLine>& barriers,
                              double blank_distance,
                              const std::vector<std::uint8_t>* domain,
                              std::vector<std::uint8_t>& out) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    out.assign(rows * cols, 0);
    if (barriers.empty() || blank_distance <= 0.0) return false;
    const double radius = blank_distance;
    bool any = false;
    for (const auto& barrier : barriers) {
        const auto& pts = barrier.points;
        if (pts.size() < 2) continue;
        for (std::size_t row = 0; row < rows; ++row) {
            const double cy = grid_y[row];
            for (std::size_t col = 0; col < cols; ++col) {
                const double cx = grid_x[col];
                double best_d = kInf;
                for (std::size_t i = 0; i + 1 < pts.size(); ++i) {
                    const double ax = pts[i][0], ay = pts[i][1];
                    const double bx = pts[i + 1][0], by = pts[i + 1][1];
                    const double length = std::hypot(bx - ax, by - ay);
                    double d;
                    if (length <= 1e-12) {
                        d = std::hypot(cx - ax, cy - ay);
                    } else {
                        const double ux = (bx - ax) / length;
                        const double uy = (by - ay) / length;
                        const double along = (cx - ax) * ux + (cy - ay) * uy;
                        const double t =
                            std::max(0.0, std::min(1.0, along / length));
                        d = std::hypot(cx - (ax + t * (bx - ax)),
                                       cy - (ay + t * (by - ay)));
                    }
                    best_d = std::min(best_d, d);
                }
                bool hit = best_d <= radius + 1e-12;
                if (hit && domain != nullptr) hit = (*domain)[row * cols + col];
                if (hit) {
                    out[row * cols + col] = 1;
                    any = true;
                }
            }
        }
    }
    return any;
}

// constrained_engine.build_barrier_proximity_mask (dilation_cells=2).
void build_barrier_proximity_mask(const std::vector<double>& grid_x,
                                  const std::vector<double>& grid_y,
                                  const std::vector<BarrierLine>& barriers,
                                  std::vector<std::uint8_t>& out) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    out.assign(rows * cols, 0);
    if (barriers.empty()) return;
    const double x0 = grid_x[0], y0 = grid_y[0];
    const double dx = grid_x[1] - grid_x[0];
    const double dy = grid_y[1] - grid_y[0];
    constexpr int kDilation = 2;
    for (const auto& barrier : barriers) {
        for (std::size_t i = 0; i + 1 < barrier.points.size(); ++i) {
            const double p0x = barrier.points[i][0],
                         p0y = barrier.points[i][1];
            const double p1x = barrier.points[i + 1][0],
                         p1y = barrier.points[i + 1][1];
            const double length = std::hypot(p1x - p0x, p1y - p0y);
            const double sample_step = std::min(std::abs(dx), std::abs(dy)) * 0.5;
            const int samples =
                std::max(2, static_cast<int>(length /
                                             std::max(sample_step, 1e-9)) +
                                2);
            for (int s = 0; s < samples; ++s) {
                const double t = static_cast<double>(s) /
                                 static_cast<double>(samples - 1);
                const double px = p0x + t * (p1x - p0x);
                const double py = p0y + t * (p1y - p0y);
                const int col =
                    py_round_int((px - x0) / (dx != 0.0 ? dx : 1.0));
                const int row =
                    py_round_int((py - y0) / (dy != 0.0 ? dy : 1.0));
                const int r0 = std::max(0, row - kDilation);
                const int r1 = std::min(static_cast<int>(rows) - 1,
                                        row + kDilation);
                const int c0 = std::max(0, col - kDilation);
                const int c1 = std::min(static_cast<int>(cols) - 1,
                                        col + kDilation);
                for (int r = r0; r <= r1; ++r) {
                    for (int c = c0; c <= c1; ++c) {
                        out[static_cast<std::size_t>(r) * cols +
                            static_cast<std::size_t>(c)] = 1;
                    }
                }
            }
        }
    }
}

// constrained_engine.build_region_labels — 4-adjacency flood fill with
// barrier line-of-sight blocking across neighbor centers (tol 1e-9).
void build_region_labels(const std::vector<double>& grid_x,
                         const std::vector<double>& grid_y,
                         const std::vector<std::uint8_t>& domain_mask,
                         const std::vector<BarrierLine>& barriers,
                         const std::vector<Seg>& barrier_segs,
                         const std::vector<std::uint8_t>& near_mask,
                         std::vector<std::int32_t>& labels) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    labels.assign(rows * cols, -1);
    bool any_domain = false;
    for (std::uint8_t v : domain_mask) any_domain = any_domain || v != 0;
    if (!any_domain) return;
    std::int32_t current = 0;
    for (std::size_t seed_row = 0; seed_row < rows; ++seed_row) {
        for (std::size_t seed_col = 0; seed_col < cols; ++seed_col) {
            const std::size_t seed_idx = seed_row * cols + seed_col;
            if (!domain_mask[seed_idx] || labels[seed_idx] >= 0) continue;
            labels[seed_idx] = current;
            std::deque<std::pair<std::size_t, std::size_t>> queue;
            queue.emplace_back(seed_row, seed_col);
            while (!queue.empty()) {
                const auto [row, col] = queue.front();
                queue.pop_front();
                const double cx = grid_x[col], cy = grid_y[row];
                static constexpr std::pair<int, int> kOffsets[4] = {
                    {1, 0}, {-1, 0}, {0, 1}, {0, -1}};
                for (const auto& [dr, dc] : kOffsets) {
                    const std::ptrdiff_t nr =
                        static_cast<std::ptrdiff_t>(row) + dr;
                    const std::ptrdiff_t nc =
                        static_cast<std::ptrdiff_t>(col) + dc;
                    if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows) ||
                        nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                        continue;
                    }
                    const std::size_t nidx =
                        static_cast<std::size_t>(nr) * cols +
                        static_cast<std::size_t>(nc);
                    if (!domain_mask[nidx] || labels[nidx] >= 0) continue;
                    if (!barriers.empty() &&
                        (near_mask[row * cols + col] ||
                         near_mask[nidx])) {
                        if (blocked_by_barrier(cx, cy, grid_x[nc], grid_y[nr],
                                               barrier_segs, 1e-9)) {
                            continue;
                        }
                    }
                    labels[nidx] = current;
                    queue.emplace_back(static_cast<std::size_t>(nr),
                                       static_cast<std::size_t>(nc));
                }
            }
            ++current;
        }
    }
}

// constrained_engine.assign_well_regions — nearest labelled cell within
// expanding rings 0..3, else -2 (participates in every region).
std::vector<std::int32_t> assign_well_regions(
    const std::vector<Well>& wells, const std::vector<double>& grid_x,
    const std::vector<double>& grid_y,
    const std::vector<std::int32_t>& region_labels) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    std::vector<std::int32_t> out(wells.size(), -2);
    if (region_labels.empty() || grid_x.size() < 2 || grid_y.size() < 2) {
        return out;
    }
    const double x0 = grid_x[0], y0 = grid_y[0];
    const double dx = grid_x[1] - grid_x[0];
    const double dy = grid_y[1] - grid_y[0];
    for (std::size_t index = 0; index < wells.size(); ++index) {
        const double wx = wells[index].x, wy = wells[index].y;
        const int col = py_round_int((wx - x0) / (dx != 0.0 ? dx : 1.0));
        const int row = py_round_int((wy - y0) / (dy != 0.0 ? dy : 1.0));
        std::int32_t found = -2;
        for (int radius = 0; radius < 4; ++radius) {
            std::int32_t best_label = -1;
            double best_dist = 0.0;
            bool have_best = false;
            const int r0 = std::max(0, row - radius);
            const int r1 = std::min(static_cast<int>(rows) - 1,
                                    row + radius);
            const int c0 = std::max(0, col - radius);
            const int c1 = std::min(static_cast<int>(cols) - 1,
                                    col + radius);
            if (r1 < r0 || c1 < c0) continue;
            for (int rr = r0; rr <= r1; ++rr) {
                for (int cc = c0; cc <= c1; ++cc) {
                    const std::int32_t label =
                        region_labels[static_cast<std::size_t>(rr) * cols +
                                      static_cast<std::size_t>(cc)];
                    if (label < 0) continue;
                    const double dxx = grid_x[static_cast<std::size_t>(cc)] - wx;
                    const double dyy = grid_y[static_cast<std::size_t>(rr)] - wy;
                    const double dist = dxx * dxx + dyy * dyy;
                    if (!have_best || dist < best_dist) {
                        best_dist = dist;
                        best_label = label;
                        have_best = true;
                    }
                }
            }
            if (have_best) {
                found = best_label;
                break;
            }
        }
        out[index] = found;
    }
    return out;
}

// constrained_engine.build_well_coverage_mask.
void build_well_coverage_mask(const std::vector<double>& grid_x,
                              const std::vector<double>& grid_y,
                              const std::vector<Well>& wells,
                              double coverage_radius,
                              std::vector<std::uint8_t>& out) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    out.assign(rows * cols, 0);
    if (wells.empty() || coverage_radius <= 0.0 || grid_x.empty() ||
        grid_y.empty()) {
        return;
    }
    const double radius_sq = coverage_radius * coverage_radius;
    for (const auto& well : wells) {
        for (std::size_t row = 0; row < rows; ++row) {
            const double dy = grid_y[row] - well.y;
            for (std::size_t col = 0; col < cols; ++col) {
                const double dx = grid_x[col] - well.x;
                if (dx * dx + dy * dy <= radius_sq) {
                    out[row * cols + col] = 1;
                }
            }
        }
    }
}

// --------------------------------------------------------------------------- //
// Direction corridor (direction_corridor.py)
// --------------------------------------------------------------------------- //

struct ResolvedDirection {
    std::string line_id;
    std::vector<Point> points;
    double ratio = 1.0;
    double influence_radius = 0.0;
    int priority = 1;
    double core_radius = 0.0;
    std::string zone_id;
    std::string extend_mode = "auto";
    double transition = 0.0;
};

double polyline_length_pts(const std::vector<Point>& pts) {
    double total = 0.0;
    for (std::size_t i = 1; i < pts.size(); ++i) {
        total += std::hypot(pts[i][0] - pts[i - 1][0],
                            pts[i][1] - pts[i - 1][1]);
    }
    return total;
}

// resolve_direction_params — auto radii + explicit-radius reconciliation.
std::vector<ResolvedDirection> resolve_direction_params(
    const std::vector<DirectionLine>& specs, double search_radius,
    double mean_well_spacing, double map_extent) {
    const double base_search = std::max(search_radius, 1.0);
    const double spacing =
        std::max({mean_well_spacing, base_search * 0.15, 1.0});
    const double map_e = std::max({map_extent, base_search, 1.0});
    std::vector<ResolvedDirection> out;
    for (const auto& spec : specs) {
        if (!spec.active || spec.points.size() < 2) continue;
        ResolvedDirection r;
        r.line_id = spec.line_id;
        r.points = spec.points;
        r.ratio = std::max(spec.ratio, 1.0);
        const double line_len =
            std::max({polyline_length_pts(spec.points), spacing, 1.0});
        double auto_core = std::max(
            {base_search * 0.65, line_len * 0.12, spacing * 1.05});
        auto_core = std::min({auto_core, map_e * 0.16, line_len * 0.20});
        double auto_influence = std::max({auto_core * 3.2, spacing * 3.2,
                                          base_search * 1.45, line_len * 0.30});
        auto_influence =
            std::min({auto_influence, map_e * 0.38, line_len * 0.48});
        const bool influence_explicit = spec.influence_radius > 0.0;
        const bool core_explicit = spec.core_radius > 0.0;
        r.influence_radius = influence_explicit ? spec.influence_radius
                                                : auto_influence;
        r.core_radius = core_explicit ? spec.core_radius : auto_core;
        if (influence_explicit && !core_explicit) {
            r.core_radius = std::min(auto_core,
                                     std::max(r.influence_radius * 0.55,
                                              r.influence_radius * 0.4));
        }
        if (r.core_radius > r.influence_radius) {
            if (influence_explicit && !core_explicit) {
                r.core_radius =
                    std::max(r.influence_radius * 0.5,
                             std::min(r.core_radius, r.influence_radius * 0.85));
            } else if (influence_explicit && core_explicit) {
                r.core_radius = std::min(r.core_radius,
                                         r.influence_radius * 0.95);
            } else {
                r.influence_radius = std::max(r.influence_radius,
                                              r.core_radius * 1.05);
            }
        }
        r.core_radius = std::max(std::min(r.core_radius,
                                          r.influence_radius * 0.99), 0.0);
        r.influence_radius = std::max(r.influence_radius,
                                      r.core_radius + 1e-6);
        r.transition = spec.transition;
        if (r.transition <= 0.0) {
            r.transition = std::max(r.influence_radius - r.core_radius,
                                    std::max(r.core_radius * 0.2, 1e-6));
        }
        std::string mode = spec.extend_mode;
        for (char& c : mode) c = static_cast<char>(std::tolower(
            static_cast<unsigned char>(c)));
        if (mode != "auto" && mode != "none" && mode != "tangent") {
            mode = "auto";
        }
        r.extend_mode = mode;
        r.priority = spec.priority > 0 ? spec.priority : 1;
        r.zone_id = spec.zone_id;
        out.push_back(std::move(r));
    }
    return out;
}

struct PolylineGeometry {
    std::string line_id;
    std::vector<Point> points;
    std::vector<double> cumlen;
    double total_length = 0.0;
    double ratio = 1.0;
    double core_radius = 0.0;
    double influence_radius = 0.0;
    int priority = 1;
    std::string zone_id;
    std::string extend_mode = "auto";
    double transition = 0.0;
    double s_start = 0.0;
    double s_end = 0.0;
    int index = 0;
};

std::pair<double, double> unit_or_x(double dx, double dy) {
    const double length = std::hypot(dx, dy);
    if (length <= 1e-15) return {1.0, 0.0};
    return {dx / length, dy / length};
}

// build_polyline_geometry — arc-length chain, optionally end-extended.
PolylineGeometry build_polyline_geometry(const ResolvedDirection& spec,
                                         int index, double extend_distance) {
    std::vector<Point> raw = spec.points;
    std::vector<Point> cleaned;
    cleaned.push_back(raw[0]);
    for (std::size_t i = 1; i < raw.size(); ++i) {
        if (std::hypot(raw[i][0] - cleaned.back()[0],
                       raw[i][1] - cleaned.back()[1]) > 1e-12) {
            cleaned.push_back(raw[i]);
        }
    }
    PolylineGeometry g;
    g.line_id = spec.line_id;
    g.ratio = spec.ratio;
    g.core_radius = spec.core_radius;
    g.influence_radius = spec.influence_radius;
    g.priority = spec.priority;
    g.zone_id = spec.zone_id;
    g.extend_mode = spec.extend_mode;
    g.transition = spec.transition;
    g.index = index;
    if (cleaned.size() < 2) {
        g.points = {cleaned[0], cleaned[0]};
        g.cumlen = {0.0, 0.0};
        g.total_length = 0.0;
        g.s_start = 0.0;
        g.s_end = 0.0;
        return g;
    }
    const double extend = std::max(extend_distance, 0.0);
    const bool extendable =
        (spec.extend_mode == "auto" || spec.extend_mode == "tangent") &&
        extend > 0.0;
    std::vector<Point> chain;
    double s_start = 0.0;
    if (extendable) {
        const auto [t0x, t0y] = unit_or_x(cleaned[1][0] - cleaned[0][0],
                                          cleaned[1][1] - cleaned[0][1]);
        const Point start_ext{cleaned[0][0] - t0x * extend,
                              cleaned[0][1] - t0y * extend};
        const auto [t1x, t1y] =
            unit_or_x(cleaned.back()[0] - cleaned[cleaned.size() - 2][0],
                      cleaned.back()[1] - cleaned[cleaned.size() - 2][1]);
        const Point end_ext{cleaned.back()[0] + t1x * extend,
                            cleaned.back()[1] + t1y * extend};
        chain.push_back(start_ext);
        chain.insert(chain.end(), cleaned.begin(), cleaned.end());
        chain.push_back(end_ext);
        s_start = extend;
    } else {
        chain = cleaned;
    }
    g.points = chain;
    g.cumlen.assign(chain.size(), 0.0);
    for (std::size_t i = 1; i < chain.size(); ++i) {
        g.cumlen[i] = g.cumlen[i - 1] +
                      std::hypot(chain[i][0] - chain[i - 1][0],
                                 chain[i][1] - chain[i - 1][1]);
    }
    g.total_length = g.cumlen.back();
    g.s_start = s_start;
    g.s_end = g.total_length - (extendable ? extend : 0.0);
    return g;
}

// project_point_to_polyline — nearest segment (strict < keeps first best).
void project_point_to_polyline(double px, double py,
                               const PolylineGeometry& geom, double& out_s,
                               double& out_n, double& out_tx, double& out_ty,
                               double& out_dist) {
    double best_dist = kInf;
    out_s = 0.0;
    out_n = 0.0;
    out_tx = 1.0;
    out_ty = 0.0;
    out_dist = kInf;
    for (std::size_t i = 0; i + 1 < geom.points.size(); ++i) {
        const double ax = geom.points[i][0], ay = geom.points[i][1];
        const double bx = geom.points[i + 1][0],
                     by = geom.points[i + 1][1];
        const double dx = bx - ax, dy = by - ay;
        const double length_sq = dx * dx + dy * dy;
        if (length_sq <= 1e-24) continue;
        const double t = std::max(
            0.0, std::min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq));
        const double cx = ax + t * dx, cy = ay + t * dy;
        const double dist = std::hypot(px - cx, py - cy);
        if (dist < best_dist) {
            best_dist = dist;
            const double length = std::sqrt(length_sq);
            const double tx = dx / length, ty = dy / length;
            out_n = (px - cx) * (-ty) + (py - cy) * tx;
            out_s = geom.cumlen[i] + t * length;
            out_tx = tx;
            out_ty = ty;
            out_dist = dist;
        }
    }
}

// influence_strength — perpendicular envelope, exponential annulus decay
// (the Python ``transition`` parameter is unused there too).
double influence_strength(double dist_to_line, double core_radius,
                          double influence_radius, double /*transition*/,
                          double exp_k = 3.0) {
    const double d = std::abs(dist_to_line);
    const double core = std::max(core_radius, 0.0);
    const double inf = std::max(influence_radius, core + 1e-9);
    if (d <= core) return 1.0;
    if (d >= inf) return 0.0;
    double t = (d - core) / std::max(inf - core, 1e-9);
    t = clamp01(t);
    const double k = std::max(exp_k, 0.5);
    const double e_k = std::exp(-k);
    const double g = (std::exp(-k * t) - e_k) / std::max(1.0 - e_k, 1e-12);
    return clamp01(g);
}

// along_track_envelope — full strength on [s_start, s_end], smoothstep tip.
double along_track_envelope(double s, double s_start, double s_end,
                            double tip_length, const std::string& extend_mode) {
    const double s0 = std::min(s_start, s_end);
    const double s1 = std::max(s_start, s_end);
    const double ss = s;
    if (s0 - 1e-9 <= ss && ss <= s1 + 1e-9) return 1.0;
    const std::string mode = lower_trim(extend_mode);
    if (mode == "none" || mode == "off" || mode == "0" || mode == "false") {
        return 0.0;
    }
    double tip = std::max(tip_length, 0.0);
    if (tip <= 1e-12) tip = std::max(0.1 * (s1 - s0), 1e-6);
    const double t = ss < s0 ? (s0 - ss) / tip : (ss - s1) / tip;
    if (t >= 1.0) return 0.0;
    const double tt = clamp01(t);
    return 1.0 - tt * tt * (3.0 - 2.0 * tt);
}

double combined_influence(double dist_to_line, double s,
                          const PolylineGeometry& geom,
                          double tip_length = 0.0) {
    const double g_perp = influence_strength(dist_to_line, geom.core_radius,
                                             geom.influence_radius,
                                             geom.transition);
    if (g_perp <= 1e-12) return 0.0;
    double tip = tip_length;
    if (tip <= 0.0) {
        tip = std::max({0.12 * std::max(geom.s_end - geom.s_start, 1.0),
                        geom.core_radius * 0.35, 1.0});
    }
    return g_perp * along_track_envelope(s, geom.s_start, geom.s_end, tip,
                                         geom.extend_mode);
}

// estimate_mean_well_spacing — nearest-neighbour mean over ALL wells.
// (Upstream subsamples 400 wells via numpy PCG64 for n>400; not portable,
// see header note D6.)
double estimate_mean_well_spacing(const std::vector<Well>& wells) {
    const std::size_t n = wells.size();
    if (n < 2) return 0.0;
    std::vector<double> nearest(n, kInf);
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = 0; j < n; ++j) {
            if (i == j) continue;
            const double d = std::hypot(wells[j].x - wells[i].x,
                                        wells[j].y - wells[i].y);
            nearest[i] = std::min(nearest[i], d);
        }
    }
    std::vector<double> finite;
    for (double v : nearest) {
        if (std::isfinite(v)) finite.push_back(v);
    }
    if (finite.empty()) return 0.0;
    return numpy_sum(finite) / static_cast<double>(finite.size());
}

// build_direction_geometries — resolve then end-extend.
std::vector<PolylineGeometry> build_direction_geometries(
    const std::vector<DirectionLine>& dirs, double search_radius,
    double mean_well_spacing, double map_extent) {
    const std::vector<ResolvedDirection> resolved =
        resolve_direction_params(dirs, search_radius, mean_well_spacing,
                                 map_extent);
    std::vector<PolylineGeometry> geoms;
    for (std::size_t i = 0; i < resolved.size(); ++i) {
        const ResolvedDirection& spec = resolved[i];
        const double a = std::max(spec.ratio, 1.0);
        const double r_base = std::max(search_radius, 1.0);
        double extend = 0.0;
        if (spec.extend_mode == "auto" || spec.extend_mode == "tangent") {
            extend = std::min({a * r_base, spec.influence_radius,
                               std::max(map_extent * 0.35, r_base)});
        }
        geoms.push_back(build_polyline_geometry(spec, static_cast<int>(i),
                                                extend));
    }
    return geoms;
}

struct DirectionCache {
    std::vector<std::int32_t> dir_index;  // -1 = none
    std::vector<double> s, n, tx, ty, g, ratio, stretch;
};

// dual_angle_blend_tangent — 2theta vector blend of two controlling tangents.
void dual_angle_blend_tangent(double atx, double aty, double ag, double aratio,
                              double btx, double bty, double bg, double bratio,
                              double& otx, double& oty, double& oratio) {
    const double ang_a = std::atan2(aty, atx);
    const double ang_b = std::atan2(bty, btx);
    const double wa = std::max(ag, 1e-9);
    const double wb = std::max(bg, 1e-9);
    const double cx = wa * std::cos(2.0 * ang_a) + wb * std::cos(2.0 * ang_b);
    const double cy = wa * std::sin(2.0 * ang_a) + wb * std::sin(2.0 * ang_b);
    const double ang = 0.5 * std::atan2(cy, cx);
    otx = std::cos(ang);
    oty = std::sin(ang);
    oratio = ag >= bg ? aratio : bratio;
}

// build_grid_direction_cache — per-cell controlling direction (best + second,
// dual-angle blend at junctions).
DirectionCache build_grid_direction_cache(
    const std::vector<double>& grid_x, const std::vector<double>& grid_y,
    const std::vector<std::uint8_t>& domain_mask,
    const std::vector<PolylineGeometry>& geoms) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    const std::size_t n = rows * cols;
    DirectionCache cache;
    cache.dir_index.assign(n, -1);
    cache.s.assign(n, 0.0);
    cache.n.assign(n, 0.0);
    cache.tx.assign(n, 0.0);
    cache.ty.assign(n, 0.0);
    cache.g.assign(n, 0.0);
    cache.ratio.assign(n, 1.0);
    cache.stretch.assign(n, 1.0);
    if (geoms.empty()) return cache;

    const bool multi_dir = geoms.size() >= 2;
    std::vector<double> best_score(n, -1.0), second_score(n, -1.0);
    std::vector<std::int32_t> best_dir(n, -1), second_dir(n, -1);
    std::vector<double> best_s(n, 0.0), best_n(n, 0.0), best_tx(n, 0.0),
        best_ty(n, 0.0), best_g(n, 0.0), best_ratio(n, 1.0);
    std::vector<double> second_s(n, 0.0), second_n(n, 0.0), second_tx(n, 0.0),
        second_ty(n, 0.0), second_g(n, 0.0), second_ratio(n, 1.0);

    for (const auto& geom : geoms) {
        for (std::size_t row = 0; row < rows; ++row) {
            for (std::size_t col = 0; col < cols; ++col) {
                const std::size_t idx = row * cols + col;
                if (!domain_mask[idx]) continue;
                double s, nn, tx, ty, dist;
                project_point_to_polyline(grid_x[col], grid_y[row], geom, s,
                                          nn, tx, ty, dist);
                const double g = combined_influence(dist, s, geom);
                const bool valid = g > 1e-9;
                const double prio_boost =
                    1.0 / static_cast<double>(std::max(geom.priority, 1));
                const double score =
                    g * (1.0 + 0.15 * prio_boost) /
                    (1.0 + dist / std::max(geom.influence_radius, 1.0));
                const bool is_best = valid && score > best_score[idx];
                bool is_second = false;
                if (multi_dir) {
                    is_second =
                        valid && !is_best && score > second_score[idx];
                    if (is_best) {
                        second_score[idx] = best_score[idx];
                        second_dir[idx] = best_dir[idx];
                        second_s[idx] = best_s[idx];
                        second_n[idx] = best_n[idx];
                        second_tx[idx] = best_tx[idx];
                        second_ty[idx] = best_ty[idx];
                        second_g[idx] = best_g[idx];
                        second_ratio[idx] = best_ratio[idx];
                    }
                    if (is_second) {
                        second_score[idx] = score;
                        second_dir[idx] = geom.index;
                        second_s[idx] = s;
                        second_n[idx] = nn;
                        second_tx[idx] = tx;
                        second_ty[idx] = ty;
                        second_g[idx] = g;
                        second_ratio[idx] = geom.ratio;
                    }
                }
                if (is_best) {
                    best_score[idx] = score;
                    best_dir[idx] = geom.index;
                    best_s[idx] = s;
                    best_n[idx] = nn;
                    best_tx[idx] = tx;
                    best_ty[idx] = ty;
                    best_g[idx] = g;
                    best_ratio[idx] = geom.ratio;
                }
            }
        }
    }

    for (std::size_t idx = 0; idx < n; ++idx) {
        if (best_dir[idx] < 0) continue;
        cache.dir_index[idx] = best_dir[idx];
        cache.s[idx] = best_s[idx];
        cache.n[idx] = best_n[idx];
        cache.tx[idx] = best_tx[idx];
        cache.ty[idx] = best_ty[idx];
        cache.g[idx] = best_g[idx];
        cache.ratio[idx] = best_ratio[idx];
    }

    if (multi_dir) {
        for (std::size_t idx = 0; idx < n; ++idx) {
            const bool compete = best_dir[idx] >= 0 && second_dir[idx] >= 0 &&
                                 best_g[idx] > 0.15 && second_g[idx] > 0.15 &&
                                 std::abs(best_score[idx] - second_score[idx]) <=
                                     std::max(0.15 * best_score[idx], 1e-6);
            if (!compete) continue;
            const PolylineGeometry& ga = geoms[best_dir[idx]];
            const PolylineGeometry& gb = geoms[second_dir[idx]];
            if (!ga.zone_id.empty() && !gb.zone_id.empty() &&
                ga.zone_id != gb.zone_id) {
                continue;
            }
            double btx, bty, br;
            dual_angle_blend_tangent(best_tx[idx], best_ty[idx],
                                     best_g[idx], best_ratio[idx],
                                     second_tx[idx], second_ty[idx],
                                     second_g[idx], second_ratio[idx], btx,
                                     bty, br);
            cache.tx[idx] = btx;
            cache.ty[idx] = bty;
            cache.g[idx] = std::max(best_g[idx], second_g[idx] * 0.85);
            cache.ratio[idx] = br;
        }
    }

    for (std::size_t idx = 0; idx < n; ++idx) {
        cache.stretch[idx] = 1.0 + (cache.ratio[idx] - 1.0) * cache.g[idx];
    }
    return cache;
}

// build_legacy_direction_field — (tx, ty, max(stretch,1)) with zeroed cells.
void build_legacy_direction_field(const DirectionCache& cache,
                                  std::vector<double>& field) {
    const std::size_t n = cache.g.size();
    field.assign(n * 3, 0.0);
    for (std::size_t i = 0; i < n; ++i) {
        if (cache.g[i] <= 1e-9) {
            field[i * 3 + 0] = 0.0;
            field[i * 3 + 1] = 0.0;
            field[i * 3 + 2] = 1.0;
        } else {
            field[i * 3 + 0] = cache.tx[i];
            field[i * 3 + 1] = cache.ty[i];
            field[i * 3 + 2] = std::max(cache.stretch[i], 1.0);
        }
    }
}

struct WellCurve {
    std::vector<double> s, n, g, tx, ty;
    std::vector<std::uint8_t> valid;
    double ratio = 1.0;
    std::string zone_id;
    double line_length = 0.0;
};

// precompute_well_curve_coords — per-direction well projections.
std::vector<WellCurve> precompute_well_curve_coords(
    const std::vector<Well>& wells,
    const std::vector<PolylineGeometry>& geoms) {
    std::vector<WellCurve> out(geoms.size());
    for (std::size_t gi = 0; gi < geoms.size(); ++gi) {
        const PolylineGeometry& geom = geoms[gi];
        WellCurve& wc = out[gi];
        const std::size_t n = wells.size();
        wc.s.assign(n, 0.0);
        wc.n.assign(n, 0.0);
        wc.g.assign(n, 0.0);
        wc.tx.assign(n, 0.0);
        wc.ty.assign(n, 0.0);
        wc.valid.assign(n, 0);
        for (std::size_t i = 0; i < n; ++i) {
            double s, nn, tx, ty, dist;
            project_point_to_polyline(wells[i].x, wells[i].y, geom, s, nn, tx,
                                      ty, dist);
            const double gg = combined_influence(dist, s, geom);
            wc.s[i] = s;
            wc.n[i] = nn;
            wc.g[i] = gg;
            wc.tx[i] = tx;
            wc.ty[i] = ty;
            wc.valid[i] = gg > 1e-9 ? 1 : 0;
        }
        wc.ratio = geom.ratio;
        wc.zone_id = geom.zone_id;
        wc.line_length =
            std::max({geom.s_end - geom.s_start, geom.total_length, 0.0});
    }
    return out;
}

// _blend_effective_distance_vec semantics for one pair.
double blend_effective_distance(double euclidean, double curve_dist,
                                double g_pair) {
    double g = std::max(0.0, std::min(1.0, g_pair));
    if (g >= 0.25) g = std::min(1.0, 0.70 + 0.30 * g);
    const double de2 = euclidean * euclidean;
    const double dc2 = curve_dist * curve_dist;
    return std::sqrt(std::max((1.0 - g) * de2 + g * dc2, 0.0));
}

// pairs_effective_distance — (d_eff, g_pair) per well for one cell.
void pairs_effective_distance(const std::vector<double>& euclidean,
                              int cell_dir, double cell_s, double cell_n,
                              double cell_g, double cell_ratio,
                              const WellCurve* wc, std::size_t n_wells,
                              std::vector<double>& d_eff,
                              std::vector<double>& g_pair) {
    d_eff = euclidean;
    g_pair.assign(n_wells, 0.0);
    if (cell_dir < 0 || cell_g <= 1e-9 || wc == nullptr) return;
    for (std::size_t i = 0; i < n_wells; ++i) {
        const double g = wc->valid[i] ? std::min(cell_g, wc->g[i]) : 0.0;
        g_pair[i] = g;
        if (g <= 1e-9) {
            d_eff[i] = euclidean[i];
            g_pair[i] = 0.0;
            continue;
        }
        const double a = std::max({cell_ratio, wc->ratio, 1.0});
        const double ds = (cell_s - wc->s[i]) / a;
        const double dn = cell_n - wc->n[i];
        const double d_curve = std::sqrt(std::max(ds * ds + dn * dn, 0.0));
        d_eff[i] = blend_effective_distance(euclidean[i], d_curve, g);
    }
}

// _elliptical_search_accept_vec semantics for one well pair.
bool elliptical_search_accept(double s0, double n0, double s1, double n1,
                              double ratio, double base_radius, double g_pair,
                              double euclidean, double line_length) {
    const double r = std::max(base_radius, 1e-9);
    const double g = clamp01(g_pair);
    if (g <= 1e-9) return euclidean <= r;
    const double a = std::max(ratio, 1.0);
    double r_par = r * (1.0 + g * (a - 1.0) * 1.15);
    if (line_length > 0.0) {
        r_par = std::max(r_par, std::max(g * line_length * 1.20,
                                         line_length * 1.05 * g));
    }
    r_par = std::max(r_par, r * a * std::max(g, 0.85));
    const double ds = std::abs(s0 - s1);
    const double dn = std::abs(n0 - n1);
    if ((ds / std::max(r_par, 1e-9)) * (ds / std::max(r_par, 1e-9)) +
            (dn / std::max(r, 1e-9)) * (dn / std::max(r, 1e-9)) <=
        1.0) {
        return true;
    }
    return g < 0.35 && euclidean <= r;
}

// pairs_in_search_neighborhood — per-well acceptance for one cell.
void pairs_in_search_neighborhood(const std::vector<double>& euclidean,
                                  const std::vector<double>& d_eff,
                                  const std::vector<double>& g_pair,
                                  double cell_s, double cell_n,
                                  double cell_ratio, int cell_dir,
                                  const WellCurve* wc, double base_radius,
                                  bool use_extended_search,
                                  std::size_t n_wells,
                                  std::vector<std::uint8_t>& in_nbhd) {
    const double r = std::max(base_radius, 1e-9);
    in_nbhd.assign(n_wells, 0);
    for (std::size_t i = 0; i < n_wells; ++i) {
        const bool fallback = use_extended_search ? d_eff[i] <= r
                                                  : euclidean[i] <= r;
        bool accepted;
        if (cell_dir < 0) {
            accepted = fallback;
        } else if (wc == nullptr) {
            accepted = euclidean[i] <= r;
        } else if (!use_extended_search) {
            accepted = euclidean[i] <= r;
        } else {
            accepted = elliptical_search_accept(
                cell_s, cell_n, wc->s[i], wc->n[i],
                std::max({cell_ratio, wc->ratio, 1.0}), r, g_pair[i],
                euclidean[i], wc->line_length);
        }
        in_nbhd[i] = (g_pair[i] <= 1e-9 ? fallback : accepted) ? 1 : 0;
    }
}

// nearest_direction_context — legacy fixed-angle fallback.
std::optional<std::array<double, 3>> nearest_direction_context(
    double px, double py, const std::vector<ResolvedDirection>& directions,
    double plateau) {
    bool have_best = false;
    double best_rank = 0.0, best_priority = 0.0, best_env = 0.0;
    double out_x = 0.0, out_y = 0.0, out_ratio = 0.0;
    for (const auto& direction : directions) {
        const double radius = std::max(direction.influence_radius, 1e-9);
        const double ratio = std::max(direction.ratio, 1.0);
        for (std::size_t i = 0; i + 1 < direction.points.size(); ++i) {
            const double p0x = direction.points[i][0],
                         p0y = direction.points[i][1];
            const double p1x = direction.points[i + 1][0],
                         p1y = direction.points[i + 1][1];
            const double vx = p1x - p0x, vy = p1y - p0y;
            const double length = std::hypot(vx, vy);
            if (length < 1e-12) continue;
            const double ux = vx / length, uy = vy / length;
            const double dx = px - p0x, dy = py - p0y;
            const double along = dx * ux + dy * uy;
            const double perp = std::abs(dx * (-uy) + dy * ux);
            const double along_c = std::max(0.0, std::min(length, along));
            const double cx = p0x + along_c * ux, cy = p0y + along_c * uy;
            const double distance = std::hypot(px - cx, py - cy);
            if (perp > radius && distance > radius) continue;
            if (distance > radius * 1.25) continue;
            double along_env;
            if (along < 0.0) {
                along_env = std::max(
                    0.0, 1.0 + along / std::max({radius * 0.25, length * 0.15,
                                                 1e-9}));
            } else if (along <= length) {
                along_env = 1.0;
            } else {
                const double beyond = along - length;
                along_env = std::max(
                    0.0,
                    1.0 - beyond / std::max({radius, length * 0.5, 1e-9}));
            }
            const double dd = perp > 1e-12 ? perp : distance;
            const double plateau_c = std::min(std::max(plateau, 0.0), 0.999);
            double perp_env;
            if (radius <= 1e-12) {
                perp_env = 0.0;
            } else {
                const double ratio_d = dd / radius;
                if (ratio_d <= plateau_c) {
                    perp_env = 1.0;
                } else if (ratio_d >= 1.0) {
                    perp_env = 0.0;
                } else {
                    perp_env = (1.0 - ratio_d) / (1.0 - plateau_c);
                }
            }
            if (along_env <= 1e-6 || perp_env <= 1e-6) continue;
            const double env = along_env * perp_env;
            const double effective_ratio = 1.0 + (ratio - 1.0) * env;
            const double on_seg_bonus =
                (0.0 <= along && along <= length) ? 0.0 : 0.15 * radius;
            const double rank_dist = distance + on_seg_bonus;
            const double priority = static_cast<double>(direction.priority);
            bool better = false;
            if (!have_best) {
                better = true;
            } else if (rank_dist < best_rank - 1e-9) {
                better = true;
            } else if (std::abs(rank_dist - best_rank) <= 1e-9) {
                if (priority < best_priority) {
                    better = true;
                } else if (priority == best_priority && -env < best_env) {
                    better = true;
                }
            }
            if (better) {
                have_best = true;
                best_rank = rank_dist;
                best_priority = priority;
                best_env = -env;
                out_x = ux;
                out_y = uy;
                out_ratio = effective_ratio;
            }
        }
    }
    if (!have_best || out_ratio <= 1.0 + 1e-9) return std::nullopt;
    return std::array<double, 3>{out_x, out_y, out_ratio};
}

double direction_perpendicular_scale(double ratio, double strength) {
    return 1.0 + std::max(ratio - 1.0, 0.0) * std::max(strength, 0.0);
}

double anisotropic_distance(double ox, double oy, double tx, double ty,
                            double ux, double uy, double ratio,
                            double perpendicular_scale) {
    const double vx = tx - ox, vy = ty - oy;
    const double u = vx * ux + vy * uy;
    const double v = vx * (-uy) + vy * ux;
    const double cross = std::max(perpendicular_scale, 1.0);
    return std::sqrt((u / std::max(ratio, 1.0)) * (u / std::max(ratio, 1.0)) +
                     (v * cross) * (v * cross));
}

double direction_corridor_weight(double ox, double oy, double ux, double uy,
                                 double ratio, double base_radius,
                                 double strength) {
    const double stretch = std::max(ratio - 1.0, 0.0);
    if (stretch <= 0.0 || strength <= 0.0) return 1.0;
    const double cross = std::abs(ox * (-uy) + oy * ux);
    const double corridor_width = std::max(base_radius / std::max(ratio, 1.0),
                                           1e-9);
    const double taper = 1.0 / (1.0 + (cross / corridor_width) *
                                          (cross / corridor_width));
    return 1.0 + stretch * strength * taper;
}

// build_direction_field — legacy fixed-angle fallback field (3 channels).
bool build_direction_field(const std::vector<double>& grid_x,
                           const std::vector<double>& grid_y,
                           const std::vector<std::uint8_t>& domain_mask,
                           const std::vector<ResolvedDirection>& directions,
                           double plateau, std::vector<double>& field) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    field.assign(rows * cols * 3, 0.0);
    for (std::size_t i = 0; i < rows * cols; ++i) field[i * 3 + 2] = 1.0;
    if (directions.empty() || grid_x.size() < 2 || grid_y.size() < 2) {
        return false;
    }
    bool has_any = false;
    for (std::size_t row = 0; row < rows; ++row) {
        for (std::size_t col = 0; col < cols; ++col) {
            const std::size_t idx = row * cols + col;
            if (!domain_mask[idx]) continue;
            auto context = nearest_direction_context(
                grid_x[col], grid_y[row], directions, plateau);
            if (!context) continue;
            const auto [ux, uy, ratio_eff] = *context;
            if (ratio_eff <= 1.0 + 1e-9) continue;
            field[idx * 3 + 0] = ux;
            field[idx * 3 + 1] = uy;
            field[idx * 3 + 2] = ratio_eff;
            has_any = true;
        }
    }
    return has_any;
}

// --------------------------------------------------------------------------- //
// Interpolation kernels (constrained_engine.py)
// --------------------------------------------------------------------------- //

struct InterpOutcome {
    bool ok = false;          // false -> Python None (NaN cell)
    double value = kNaN;
    int blocked = 0;
    bool used_direction = false;
};

// _interpolate_grid_point_euclidean — stable-sort top-k IDW selection.
InterpOutcome interpolate_euclidean_point(
    double px, double py, const std::vector<double>& wx,
    const std::vector<double>& wy, const std::vector<double>& wz,
    const std::vector<Seg>& barrier_segs, const Config& config,
    const std::vector<double>& density, const std::vector<double>& euclidean,
    const std::vector<std::int32_t>* well_labels, std::int32_t cell_label,
    const std::vector<std::uint8_t>* blocked_row) {
    InterpOutcome out;
    const std::size_t n = wx.size();
    std::vector<std::uint8_t> blocked(n, 0);
    if (well_labels != nullptr && cell_label >= 0) {
        for (std::size_t i = 0; i < n; ++i) {
            if ((*well_labels)[i] >= 0 && (*well_labels)[i] != cell_label) {
                blocked[i] = 1;
            }
        }
    }
    if (!barrier_segs.empty()) {
        if (blocked_row != nullptr) {
            for (std::size_t i = 0; i < n; ++i) {
                if ((*blocked_row)[i]) blocked[i] = 1;
            }
        } else {
            for (std::size_t i = 0; i < n; ++i) {
                if (blocked_by_barrier(px, py, wx[i], wy[i], barrier_segs,
                                       config.endpoint_tolerance)) {
                    blocked[i] = 1;
                }
            }
        }
    }
    out.blocked =
        static_cast<int>(std::count(blocked.begin(), blocked.end(), 1));

    const double base_radius = std::max(config.search_radius, 1e-9);
    const std::size_t n_scales =
        config.limit_interpolation_to_search_radius ? 1 : 4;
    static constexpr double kScales[4] = {1.0, 1.5, 2.25, 3.0};
    std::vector<std::uint8_t> candidate(n, 0);
    int required = std::max(1, config.min_points);
    for (std::size_t pass = 0; pass < n_scales; ++pass) {
        const double r_pass = base_radius * kScales[pass];
        for (std::size_t i = 0; i < n; ++i) {
            if (!blocked[i] && euclidean[i] <= r_pass) candidate[i] = 1;
        }
        required = std::max(1, config.min_points - static_cast<int>(pass));
        const int count =
            static_cast<int>(std::count(candidate.begin(), candidate.end(), 1));
        if (count >= required) break;
    }
    const int count =
        static_cast<int>(std::count(candidate.begin(), candidate.end(), 1));
    if (count < required) return out;

    std::vector<std::size_t> cand;
    for (std::size_t i = 0; i < n; ++i) {
        if (candidate[i]) cand.push_back(i);
    }
    std::stable_sort(cand.begin(), cand.end(),
                     [&](std::size_t a, std::size_t b) {
                         return euclidean[a] < euclidean[b];
                     });
    const std::size_t take =
        std::min<std::size_t>(std::max(1, config.max_points), cand.size());
    std::vector<double> dists(take), values(take), weights(take);
    for (std::size_t k = 0; k < take; ++k) {
        const std::size_t idx = cand[k];
        dists[k] = euclidean[idx];
        values[k] = wz[idx];
        const double decluster =
            density.empty() ? 1.0 : density[idx];
        weights[k] = decluster / std::pow(std::max(dists[k], 1e-9),
                                          config.power);
    }
    const double weight_sum = numpy_sum(weights);
    if (weight_sum <= 0) return out;
    std::vector<double> weighted(take);
    for (std::size_t k = 0; k < take; ++k) weighted[k] = weights[k] * values[k];
    out.ok = true;
    out.used_direction = false;
    out.value = numpy_sum(weighted) / weight_sum;
    return out;
}

// _interpolate_grid_point_curve — curve-corridor candidate selection.
InterpOutcome interpolate_curve_point(
    const std::vector<double>& wx, const std::vector<double>& wy,
    const std::vector<double>& wz, const std::vector<Seg>& barrier_segs,
    const Config& config, const std::vector<double>& density,
    const std::vector<double>& euclidean,
    const std::vector<double>& candidate_distances,
    const std::vector<double>& direction_weight_factors,
    const std::vector<double>& g_pair, const std::vector<std::int32_t>* well_labels,
    std::int32_t cell_label, int cell_dir_index, double cell_s, double cell_n,
    double cell_ratio, const WellCurve* wc,
    const std::vector<std::uint8_t>* blocked_row) {
    InterpOutcome out;
    out.used_direction = true;
    const std::size_t n = wx.size();
    std::vector<std::uint8_t> blocked(n, 0);
    if (well_labels != nullptr && cell_label >= 0) {
        for (std::size_t i = 0; i < n; ++i) {
            if ((*well_labels)[i] >= 0 && (*well_labels)[i] != cell_label) {
                blocked[i] = 1;
            }
        }
    }
    if (!barrier_segs.empty() && blocked_row != nullptr) {
        for (std::size_t i = 0; i < n; ++i) {
            if ((*blocked_row)[i]) blocked[i] = 1;
        }
    }
    out.blocked =
        static_cast<int>(std::count(blocked.begin(), blocked.end(), 1));

    const double base_radius = std::max(config.search_radius, 1e-9);
    const std::size_t n_scales =
        config.limit_interpolation_to_search_radius ? 1 : 4;
    static constexpr double kScales[4] = {1.0, 1.5, 2.25, 3.0};
    std::vector<std::uint8_t> candidate(n, 0);
    int required = std::max(1, config.min_points);
    std::vector<std::uint8_t> in_nbhd;
    for (std::size_t pass = 0; pass < n_scales; ++pass) {
        const double r_pass = base_radius * kScales[pass];
        pairs_in_search_neighborhood(
            euclidean, candidate_distances, g_pair, cell_s, cell_n, cell_ratio,
            cell_dir_index, wc, r_pass, config.use_extended_search, n, in_nbhd);
        for (std::size_t i = 0; i < n; ++i) {
            candidate[i] = (!blocked[i] && in_nbhd[i]) ? 1 : 0;
        }
        required = std::max(1, config.min_points - static_cast<int>(pass));
        const int count =
            static_cast<int>(std::count(candidate.begin(), candidate.end(), 1));
        if (count >= required) break;
    }
    // Exact hit within the accepted neighborhood (first candidate wins).
    for (std::size_t i = 0; i < n; ++i) {
        if (candidate[i] && candidate_distances[i] <= 1e-9) {
            out.ok = true;
            out.value = wz[i];
            return out;
        }
    }
    const int count =
        static_cast<int>(std::count(candidate.begin(), candidate.end(), 1));
    if (count < required) return out;

    std::vector<std::size_t> cand;
    for (std::size_t i = 0; i < n; ++i) {
        if (candidate[i]) cand.push_back(i);
    }
    std::stable_sort(cand.begin(), cand.end(),
                     [&](std::size_t a, std::size_t b) {
                         return candidate_distances[a] < candidate_distances[b];
                     });
    const std::size_t take =
        std::min<std::size_t>(std::max(1, config.max_points), cand.size());
    std::vector<double> dists(take), values(take), weights(take);
    for (std::size_t k = 0; k < take; ++k) {
        const std::size_t idx = cand[k];
        dists[k] = candidate_distances[idx];
        values[k] = wz[idx];
        const double decluster =
            (density.empty() ? 1.0 : density[idx]) * direction_weight_factors[idx];
        weights[k] = decluster / std::pow(std::max(dists[k], 1e-9),
                                          config.power);
    }
    const double weight_sum = numpy_sum(weights);
    if (weight_sum <= 0) return out;
    std::vector<double> weighted(take);
    for (std::size_t k = 0; k < take; ++k) weighted[k] = weights[k] * values[k];
    out.ok = true;
    out.value = numpy_sum(weighted) / weight_sum;
    return out;
}

// _interpolate_grid_point — full dispatcher (exact hit, curve, legacy,
// euclidean).
InterpOutcome interpolate_grid_point(
    double px, double py, const std::vector<double>& wx,
    const std::vector<double>& wy, const std::vector<double>& wz,
    const std::vector<Seg>& barrier_segs,
    const std::vector<ResolvedDirection>& directions, const Config& config,
    const std::vector<double>& density,
    const std::vector<std::int32_t>* well_labels, std::int32_t cell_label,
    int cell_dir_index, double cell_s, double cell_n, double cell_g,
    double cell_ratio, const std::vector<WellCurve>* well_curves,
    const std::vector<std::uint8_t>* blocked_row) {
    InterpOutcome out;
    const std::size_t n = wx.size();
    std::vector<double> euclidean(n);
    for (std::size_t i = 0; i < n; ++i) {
        const double dx = wx[i] - px, dy = wy[i] - py;
        euclidean[i] = std::sqrt(dx * dx + dy * dy);
    }
    for (std::size_t i = 0; i < n; ++i) {
        if (euclidean[i] <= 1e-9) {
            out.ok = true;
            out.value = wz[i];
            out.blocked = 0;
            return out;
        }
    }
    const WellCurve* wc =
        (well_curves != nullptr && cell_dir_index >= 0 &&
         static_cast<std::size_t>(cell_dir_index) < well_curves->size())
            ? &(*well_curves)[static_cast<std::size_t>(cell_dir_index)]
            : nullptr;
    const bool use_curve = config.use_curve_direction_distance &&
                           well_curves != nullptr && cell_dir_index >= 0 &&
                           cell_g > 1e-9 && wc != nullptr;
    if (use_curve) {
        std::vector<double> d_eff, g_pair;
        pairs_effective_distance(euclidean, cell_dir_index, cell_s, cell_n,
                                 cell_g, cell_ratio, wc, n, d_eff, g_pair);
        std::vector<double> dir_factors(n, 1.0);
        for (std::size_t i = 0; i < n; ++i) {
            if (g_pair[i] > 1e-9) {
                dir_factors[i] =
                    1.0 + config.direction_corridor_strength * 0.35 * g_pair[i];
            }
        }
        return interpolate_curve_point(
            wx, wy, wz, barrier_segs, config, density, euclidean, d_eff,
            dir_factors, g_pair, well_labels, cell_label, cell_dir_index,
            cell_s, cell_n, cell_ratio, wc, blocked_row);
    }
    auto direction = nearest_direction_context(
        px, py, directions, config.direction_taper_plateau);
    const bool used_direction = direction.has_value();
    if (!used_direction) {
        return interpolate_euclidean_point(
            px, py, wx, wy, wz, barrier_segs, config, density, euclidean,
            well_labels, cell_label, blocked_row);
    }
    // Legacy fixed-angle pass loop.
    const auto [unit_x, unit_y, ratio] = *direction;
    const double perp_scale = direction_perpendicular_scale(
        ratio, config.direction_perpendicular_strength);
    std::vector<double> candidate_distances(n);
    std::vector<double> direction_weight_factors(n);
    for (std::size_t i = 0; i < n; ++i) {
        candidate_distances[i] =
            anisotropic_distance(px, py, wx[i], wy[i], unit_x, unit_y, ratio,
                                 perp_scale);
        direction_weight_factors[i] = direction_corridor_weight(
            wx[i] - px, wy[i] - py, unit_x, unit_y, ratio,
            std::max(config.search_radius, 1e-9),
            config.direction_corridor_strength);
    }
    out.used_direction = true;
    std::vector<std::uint8_t> blocked_mark(n, 0);
    int blocked_count = 0;
    const double base_radius = std::max(config.search_radius, 1e-9);
    const std::size_t n_scales =
        config.limit_interpolation_to_search_radius ? 1 : 4;
    static constexpr double kScales[4] = {1.0, 1.5, 2.25, 3.0};
    std::vector<std::array<double, 3>> weighted_candidates;
    int required = std::max(1, config.min_points);
    for (std::size_t pass = 0; pass < n_scales; ++pass) {
        const double r_pass = base_radius * kScales[pass];
        weighted_candidates.clear();
        for (std::size_t i = 0; i < n; ++i) {
            if (well_labels != nullptr && cell_label >= 0) {
                const std::int32_t wl = (*well_labels)[i];
                if (wl >= 0 && wl != cell_label) {
                    if (!blocked_mark[i]) {
                        blocked_mark[i] = 1;
                        ++blocked_count;
                    }
                    continue;
                }
            }
            if (!barrier_segs.empty()) {
                bool blocked_flag;
                if (blocked_row != nullptr) {
                    blocked_flag = (*blocked_row)[i] != 0;
                } else {
                    blocked_flag = blocked_by_barrier(
                        px, py, wx[i], wy[i], barrier_segs,
                        config.endpoint_tolerance);
                }
                if (blocked_flag) {
                    if (!blocked_mark[i]) {
                        blocked_mark[i] = 1;
                        ++blocked_count;
                    }
                    continue;
                }
            }
            const double filter_d = config.use_extended_search
                                        ? candidate_distances[i]
                                        : euclidean[i];
            if (filter_d > r_pass) continue;
            const double dist = candidate_distances[i];
            if (dist <= 1e-9) {
                out.ok = true;
                out.value = wz[i];
                out.blocked = blocked_count;
                return out;
            }
            const double density_weight = density.empty() ? 1.0 : density[i];
            weighted_candidates.push_back(
                {dist, wz[i], density_weight * direction_weight_factors[i]});
        }
        required = std::max(1, config.min_points - static_cast<int>(pass));
        if (static_cast<int>(weighted_candidates.size()) >= required) break;
    }
    out.blocked = blocked_count;
    if (static_cast<int>(weighted_candidates.size()) < required) return out;
    std::stable_sort(weighted_candidates.begin(), weighted_candidates.end(),
                     [](const std::array<double, 3>& a,
                        const std::array<double, 3>& b) { return a[0] < b[0]; });
    const std::size_t take =
        std::min<std::size_t>(std::max(1, config.max_points),
                              weighted_candidates.size());
    std::vector<double> dists(take), values(take), weights(take);
    for (std::size_t k = 0; k < take; ++k) {
        dists[k] = weighted_candidates[k][0];
        values[k] = weighted_candidates[k][1];
        weights[k] = weighted_candidates[k][2] /
                     std::pow(std::max(dists[k], 1e-9), config.power);
    }
    const double weight_sum = numpy_sum(weights);
    if (weight_sum <= 0) return out;
    std::vector<double> weighted(take);
    for (std::size_t k = 0; k < take; ++k) weighted[k] = weights[k] * values[k];
    out.ok = true;
    out.value = numpy_sum(weighted) / weight_sum;
    return out;
}

// --------------------------------------------------------------------------- //
// No-barrier batch IDW (fast_grid.interpolate_idw_grid_batch / _idw_row_block)
// --------------------------------------------------------------------------- //

void interpolate_idw_grid_batch(const std::vector<double>& grid_x,
                                const std::vector<double>& grid_y,
                                const std::vector<Well>& wells,
                                const std::vector<std::uint8_t>& domain_mask,
                                const Config& config,
                                const std::vector<double>& density,
                                const std::vector<std::int32_t>* region_labels,
                                const std::vector<std::int32_t>* well_labels,
                                const std::vector<double>* direction_field,
                                std::vector<double>& grid_z) {
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    const std::size_t n = rows * cols;
    grid_z.assign(n, kNaN);
    const std::size_t n_wells = wells.size();
    if (n_wells == 0) return;
    std::vector<double> wx(n_wells), wy(n_wells), wz(n_wells);
    for (std::size_t i = 0; i < n_wells; ++i) {
        wx[i] = wells[i].x;
        wy[i] = wells[i].y;
        wz[i] = wells[i].value;
    }
    const double radius = std::max(config.search_radius, 1e-9);
    const std::size_t n_scales =
        config.limit_interpolation_to_search_radius ? 1 : 4;
    static constexpr double kScales[4] = {1.0, 1.5, 2.25, 3.0};
    const std::size_t k = std::min<std::size_t>(
        std::max(1, config.max_points), n_wells);

    for (std::size_t row = 0; row < rows; ++row) {
        for (std::size_t col = 0; col < cols; ++col) {
            const std::size_t idx = row * cols + col;
            if (!domain_mask[idx]) continue;
            const double px = grid_x[col], py = grid_y[row];
            std::vector<double> euclidean(n_wells);
            for (std::size_t i = 0; i < n_wells; ++i) {
                euclidean[i] = std::hypot(wx[i] - px, wy[i] - py);
            }
            // Exact well hit: first well within 1e-9 wins.
            bool has_exact = false;
            std::size_t exact_idx = 0;
            for (std::size_t i = 0; i < n_wells; ++i) {
                if (euclidean[i] <= 1e-9) {
                    has_exact = true;
                    exact_idx = i;
                    break;
                }
            }
            if (has_exact) {
                grid_z[idx] = wz[exact_idx];
                continue;
            }
            // Per-cell direction context (row of the legacy field).
            const double* field = nullptr;
            double f_ux = 0.0, f_uy = 0.0, f_ratio = 1.0;
            bool f_stretched = false;
            if (direction_field != nullptr) {
                field = &(*direction_field)[idx * 3];
                f_ux = field[0];
                f_uy = field[1];
                f_ratio = std::max(field[2], 1.0);
                f_stretched = field[2] > 1.0 + 1e-9;
            }
            const double perp_scale =
                1.0 + std::max(f_ratio - 1.0, 0.0) *
                          std::max(config.direction_perpendicular_strength,
                                   0.0);
            std::vector<double> dist(n_wells);
            std::vector<double> dir_w(n_wells, 1.0);
            for (std::size_t i = 0; i < n_wells; ++i) {
                const double rel_x = wx[i] - px, rel_y = wy[i] - py;
                double d = euclidean[i];
                if (field != nullptr && f_stretched) {
                    const double u = rel_x * f_ux + rel_y * f_uy;
                    const double v = rel_x * (-f_uy) + rel_y * f_ux;
                    d = std::sqrt((u / f_ratio) * (u / f_ratio) +
                                  (v * perp_scale) * (v * perp_scale));
                }
                dist[i] = d;
                if (field != nullptr && config.direction_corridor_strength > 0.0) {
                    const double cross =
                        std::abs(rel_x * (-f_uy) + rel_y * f_ux);
                    const double corridor_width =
                        std::max(radius / std::max(f_ratio, 1.0), 1e-9);
                    const double stretch = std::max(f_ratio - 1.0, 0.0);
                    const double taper =
                        1.0 / (1.0 + (cross / corridor_width) *
                                           (cross / corridor_width));
                    dir_w[i] =
                        (stretch <= 0.0) ? 1.0
                                         : 1.0 + stretch *
                                                     config.direction_corridor_strength *
                                                     taper;
                }
            }
            const double* filter_base =
                config.use_extended_search ? dist.data() : euclidean.data();
            double result = kNaN;
            for (std::size_t pass = 0; pass < n_scales; ++pass) {
                const double r_pass = radius * kScales[pass];
                // Candidate set + region gate.
                std::vector<std::size_t> cand;
                for (std::size_t i = 0; i < n_wells; ++i) {
                    if (filter_base[i] > r_pass) continue;
                    if (region_labels != nullptr && well_labels != nullptr) {
                        const std::int32_t cl = (*region_labels)[idx];
                        const std::int32_t wl = (*well_labels)[i];
                        const bool region_ok =
                            (wl < 0) || (cl < 0) || (cl == wl);
                        if (!region_ok) continue;
                    }
                    cand.push_back(i);
                }
                // Stable top-k by distance.
                std::stable_sort(cand.begin(), cand.end(),
                                 [&](std::size_t a, std::size_t b) {
                                     return dist[a] < dist[b];
                                 });
                if (cand.size() > k) cand.resize(k);
                const std::size_t count = cand.size();
                const std::size_t need = static_cast<std::size_t>(
                    std::max(1, config.min_points - static_cast<int>(pass)));
                if (count < need) continue;  // eligible only when count>=need
                std::vector<double> w(count), wz_sel(count);
                for (std::size_t j = 0; j < count; ++j) {
                    const std::size_t wi = cand[j];
                    const double decluster =
                        density.empty() ? 1.0 : density[wi];
                    w[j] = decluster * dir_w[wi] /
                           std::pow(std::max(dist[wi], 1e-9), config.power);
                    wz_sel[j] = wz[wi];
                }
                double wsum;
                {
                    // np.sum over k entries (invalid -> 0): pad with zeros.
                    std::vector<double> w_padded(k, 0.0);
                    for (std::size_t j = 0; j < count; ++j) w_padded[j] = w[j];
                    wsum = numpy_pairwise_sum(w_padded.data(), w_padded.size());
                }
                std::vector<double> wz_padded(k, 0.0);
                for (std::size_t j = 0; j < count; ++j) {
                    wz_padded[j] = w[j] * wz_sel[j];
                }
                const double num =
                    numpy_pairwise_sum(wz_padded.data(), wz_padded.size());
                if (wsum > 0.0) {
                    result = num / wsum;
                    break;
                }
            }
            grid_z[idx] = result;
        }
    }
    // Value clamp: finite cells only, min first then max.
    if (config.value_min.has_value()) {
        for (std::size_t i = 0; i < n; ++i) {
            if (std::isfinite(grid_z[i])) {
                grid_z[i] = std::max(*config.value_min, grid_z[i]);
            }
        }
    }
    if (config.value_max.has_value()) {
        for (std::size_t i = 0; i < n; ++i) {
            if (std::isfinite(grid_z[i])) {
                grid_z[i] = std::min(*config.value_max, grid_z[i]);
            }
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        if (!domain_mask[i]) grid_z[i] = kNaN;
    }
}

// --------------------------------------------------------------------------- //
// Along-track ridge blend (direction_corridor.blend_corridor_along_track)
// --------------------------------------------------------------------------- //

struct AlongProfile {
    std::vector<double> s;
    std::vector<double> z;
};

// build_along_track_well_profiles — corridor wells as (s, value) samples.
std::map<int, AlongProfile> build_along_track_well_profiles(
    const std::vector<Well>& wells,
    const std::vector<WellCurve>& well_curves,
    const std::vector<PolylineGeometry>& geoms, double min_g) {
    std::map<int, AlongProfile> profiles;
    for (const auto& geom : geoms) {
        if (geom.index < 0 ||
            static_cast<std::size_t>(geom.index) >= well_curves.size()) {
            continue;
        }
        const WellCurve& wc = well_curves[static_cast<std::size_t>(geom.index)];
        std::vector<double> ss, zz;
        for (std::size_t i = 0; i < wells.size(); ++i) {
            if (!wc.valid[i]) continue;
            if (wc.g[i] < min_g) continue;
            const double n_lim =
                std::max({std::min(geom.core_radius * 0.46,
                                   geom.influence_radius * 0.22),
                          geom.core_radius * 0.24, 1.0});
            if (std::abs(wc.n[i]) > n_lim) continue;
            const double val = wells[i].value;
            if (!std::isfinite(val)) continue;
            ss.push_back(wc.s[i]);
            zz.push_back(val);
        }
        if (ss.empty()) continue;
        // np.argsort (quicksort) — s ties are a measure-zero event (D7); a
        // stable sort preserves the ascending order otherwise.
        std::vector<std::size_t> order(ss.size());
        for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
        std::stable_sort(order.begin(), order.end(),
                         [&](std::size_t a, std::size_t b) {
                             return ss[a] < ss[b];
                         });
        std::vector<double> s_arr(order.size()), z_arr(order.size());
        for (std::size_t i = 0; i < order.size(); ++i) {
            s_arr[i] = ss[order[i]];
            z_arr[i] = zz[order[i]];
        }
        // Merge near-duplicate s buckets; median per bucket.
        std::vector<double> s_m, z_m;
        double bucket_s = s_arr[0];
        std::vector<double> bucket_z{z_arr[0]};
        const double merge_eps = std::max(geom.core_radius * 0.05, 1.0);
        for (std::size_t i = 1; i < s_arr.size(); ++i) {
            if (std::abs(s_arr[i] - bucket_s) <= merge_eps) {
                bucket_z.push_back(z_arr[i]);
            } else {
                s_m.push_back(bucket_s);
                z_m.push_back(numpy_median(bucket_z));
                bucket_s = s_arr[i];
                bucket_z = {z_arr[i]};
            }
        }
        s_m.push_back(bucket_s);
        z_m.push_back(numpy_median(bucket_z));
        // Hard rule: ridge always reaches the direction-line tips.
        const double s_tip0 = std::min(geom.s_start, geom.s_end);
        const double s_tip1 = std::max(geom.s_start, geom.s_end);
        AlongProfile prof;
        prof.s.push_back(s_tip0);
        prof.z.push_back(z_m.front());
        prof.s.insert(prof.s.end(), s_m.begin(), s_m.end());
        prof.z.insert(prof.z.end(), z_m.begin(), z_m.end());
        prof.s.push_back(s_tip1);
        prof.z.push_back(z_m.back());
        // _interp_profile_vectorized np.argsort's the station axis (wells can
        // project before the original chain start); keep the stored profile
        // sorted the same way. Stable: s ties are measure-zero (D7).
        std::vector<std::size_t> tip_order(prof.s.size());
        for (std::size_t i = 0; i < tip_order.size(); ++i) tip_order[i] = i;
        std::stable_sort(tip_order.begin(), tip_order.end(),
                         [&](std::size_t a, std::size_t b) {
                             return prof.s[a] < prof.s[b];
                         });
        AlongProfile sorted_prof;
        sorted_prof.s.reserve(tip_order.size());
        sorted_prof.z.reserve(tip_order.size());
        for (std::size_t i : tip_order) {
            sorted_prof.s.push_back(prof.s[i]);
            sorted_prof.z.push_back(prof.z[i]);
        }
        profiles[geom.index] = std::move(sorted_prof);
    }
    return profiles;
}

// _interp_profile_vectorized — np.interp with constant extrapolation.
double interp_profile(double s, const AlongProfile& prof) {
    const std::vector<double>& ps = prof.s;
    const std::vector<double>& pz = prof.z;
    if (ps.empty()) return kNaN;
    if (ps.size() == 1) return pz[0];
    if (s < ps[0]) return pz[0];
    if (s > ps.back()) return pz.back();
    for (std::size_t i = 0; i + 1 < ps.size(); ++i) {
        const double a = ps[i], b = ps[i + 1];
        if ((a - 1e-12 <= s && s <= b + 1e-12) ||
            (b - 1e-12 <= s && s <= a + 1e-12)) {
            if (std::abs(b - a) <= 1e-12) return pz[i];
            const double t = clamp01((s - a) / (b - a));
            return pz[i] * (1.0 - t) + pz[i + 1] * t;
        }
    }
    // Fallback nearest (np.argmin over |ps - s|, first minimum).
    std::size_t best = 0;
    double best_val = std::abs(ps[0] - s);
    for (std::size_t i = 1; i < ps.size(); ++i) {
        const double val = std::abs(ps[i] - s);
        if (val < best_val) {
            best_val = val;
            best = i;
        }
    }
    return pz[best];
}

// blend_corridor_along_track — exponential ridge mix along each profile.
void blend_corridor_along_track(std::vector<double>& grid_z,
                                const DirectionCache& cache,
                                const std::vector<PolylineGeometry>& geoms,
                                const std::map<int, AlongProfile>& profiles,
                                const std::vector<std::uint8_t>& domain_mask,
                                double blend_strength, double min_cell_g,
                                double exp_k, int& cells_applied) {
    cells_applied = 0;
    if (profiles.empty()) return;
    const std::size_t n = grid_z.size();
    const double strength = clamp01(blend_strength);
    const double k_exp = std::max(exp_k, 0.5);
    for (const auto& [di, profile] : profiles) {
        const PolylineGeometry* geom = nullptr;
        for (const auto& g : geoms) {
            if (g.index == di) geom = &g;
        }
        if (geom == nullptr) continue;
        const double s0 = std::min(geom->s_start, geom->s_end);
        const double s1 = std::max(geom->s_start, geom->s_end);
        const double tip = std::max({geom->core_radius * 0.65,
                                     geom->influence_radius * 0.20, 1.0});
        const double core = std::max(geom->core_radius, 1e-9);
        const double inf = std::max(geom->influence_radius, core + 1e-9);
        const std::string mode = lower_trim(geom->extend_mode);
        const bool mode_none = mode == "none" || mode == "off" ||
                               mode == "0" || mode == "false";
        std::vector<std::size_t> sel;
        for (std::size_t i = 0; i < n; ++i) {
            if (domain_mask[i] && cache.dir_index[i] == di &&
                cache.g[i] >= min_cell_g) {
                sel.push_back(i);
            }
        }
        if (sel.empty()) continue;
        // Snapshot of the current surface under this profile's cells.
        std::vector<double> base(sel.size());
        for (std::size_t j = 0; j < sel.size(); ++j) base[j] = grid_z[sel[j]];
        std::vector<double> new_vals = base;
        std::vector<std::uint8_t> applied(sel.size(), 0);
        for (std::size_t j = 0; j < sel.size(); ++j) {
            const std::size_t idx = sel[j];
            const double s_cell = cache.s[idx];
            const double n_cell = cache.n[idx];
            const double g_cell = cache.g[idx];
            // Along-track envelope with exponential tip fade.
            double g_along = 0.0;
            const bool inside = s0 - 1e-9 <= s_cell && s_cell <= s1 + 1e-9;
            if (inside) {
                g_along = 1.0;
            } else if (!mode_none) {
                const double t_raw =
                    s_cell < s0 ? (s0 - s_cell) / tip : (s_cell - s1) / tip;
                const double t = clamp01(t_raw);
                if (t_raw < 1.0) {
                    const double e_k = std::exp(-k_exp);
                    g_along = clamp01((std::exp(-k_exp * t) - e_k) /
                                      std::max(1.0 - e_k, 1e-12));
                }
            }
            // Perp envelope.
            const double n_abs = std::abs(n_cell);
            double g_perp = 1.0;
            if (n_abs >= inf) {
                g_perp = 0.0;
            } else if (n_abs > core) {
                const double t = clamp01((n_abs - core) / std::max(inf - core,
                                                                   1e-9));
                const double k_perp = std::max(k_exp * 0.65, 2.0);
                const double e_k = std::exp(-k_perp);
                g_perp = clamp01((std::exp(-k_perp * t) - e_k) /
                                 std::max(1.0 - e_k, 1e-12));
            }
            const double axis_w =
                std::max(0.0, 1.0 - (n_abs / (core * 1.65)) *
                                        (n_abs / (core * 1.65)));
            const bool use = g_along > 1e-9 && g_perp > 1e-9;
            if (!use) continue;
            const double v_along = interp_profile(s_cell, profile);
            double w_lin = clamp01(
                g_cell * g_along * (0.30 * axis_w + 0.70 * g_perp));
            const bool changed =
                std::abs(v_along - base[j]) > 1e-9 && std::isfinite(base[j]);
            if (changed) w_lin = clamp01(w_lin * 1.45 + 0.24);
            const double raw =
                1.0 - std::exp(-k_exp * strength * (1.05 + 2.8 * w_lin));
            const double raw_max =
                1.0 - std::exp(-k_exp * strength * (1.05 + 2.8));
            double alpha =
                std::min(std::max(raw / std::max(raw_max, 1e-12) * 0.995, 0.0),
                         0.995);
            const bool on_span =
                s0 - 1e-9 <= s_cell && s_cell <= s1 + 1e-9;
            const bool on_core = on_span && n_abs <= core;
            const bool on_corridor = on_span && g_perp >= 0.10;
            if (on_corridor) alpha = std::max(alpha, 0.78 * strength);
            if (on_core) alpha = std::max(alpha, 0.995 * strength);
            alpha = clamp01(alpha);
            if (alpha > 0.995) alpha = 0.995;
            const bool finite_base = std::isfinite(base[j]);
            const bool fill = !finite_base && g_perp > 0.08;
            const bool blend = finite_base && alpha > 1e-6;
            if (fill) {
                new_vals[j] = v_along;
                applied[j] = 1;
            } else if (blend) {
                new_vals[j] = (1.0 - alpha) * base[j] + alpha * v_along;
                applied[j] = 1;
            }
        }
        for (std::size_t j = 0; j < sel.size(); ++j) {
            if (applied[j]) {
                grid_z[sel[j]] = new_vals[j];
                ++cells_applied;
            }
        }
    }
}

// --------------------------------------------------------------------------- //
// Field ops: gap fill / smooth / boundary refine / well anchoring
// --------------------------------------------------------------------------- //

// _anisotropic_fill_multiplier.
double anisotropic_fill_multiplier(int dr, int dc, double tx, double ty,
                                   double stretch, double aspect) {
    if (stretch <= 1.0 + 1e-9) return 1.0;
    const double ox = static_cast<double>(dc);
    const double oy = static_cast<double>(dr) * aspect;
    const double norm = std::hypot(ox, oy);
    if (norm <= 1e-12) return 1.0;
    const double align =
        std::abs(ox * tx + oy * ty) / norm;
    return 1.0 + (stretch - 1.0) * align;
}

// fill_internal_gaps — 8-neighbour weighted hole filling inside one region.
void fill_internal_gaps(std::vector<double>& grid,
                        const std::vector<double>& grid_x,
                        const std::vector<double>& grid_y,
                        const std::vector<std::uint8_t>& domain_mask,
                        int iterations, const Config& config,
                        const std::vector<Seg>& barrier_segs,
                        const std::vector<std::uint8_t>* near_mask,
                        const std::vector<std::int32_t>* region_labels,
                        const std::vector<double>* direction_field,
                        int& filled_count) {
    filled_count = 0;
    if (grid.empty() || iterations <= 0) return;
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    std::vector<std::uint8_t> fillable(rows * cols, 0);
    bool any = false;
    for (std::size_t i = 0; i < grid.size(); ++i) {
        fillable[i] = (domain_mask[i] && !std::isfinite(grid[i])) ? 1 : 0;
        any = any || fillable[i] != 0;
    }
    if (!any) return;
    const double step_x =
        grid_x.size() > 1 ? std::abs(grid_x[1] - grid_x[0]) : 1.0;
    const double step_y =
        grid_y.size() > 1 ? std::abs(grid_y[1] - grid_y[0]) : step_x;
    const double aspect = step_x > 1e-12 ? step_y / step_x : 1.0;
    static constexpr int kOff[8][2] = {{-1, 0}, {1, 0},  {0, -1}, {0, 1},
                                       {-1, -1}, {-1, 1}, {1, -1}, {1, 1}};
    static constexpr double kOffW[8] = {2.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0};
    for (int pass = 0; pass < iterations; ++pass) {
        std::vector<double> next = grid;
        int changed = 0;
        const int min_neighbors = pass < iterations - 1 ? 2 : 1;
        for (std::size_t row = 0; row < rows; ++row) {
            for (std::size_t col = 0; col < cols; ++col) {
                const std::size_t idx = row * cols + col;
                if (!fillable[idx] || std::isfinite(grid[idx])) continue;
                const bool check_barrier =
                    !barrier_segs.empty() &&
                    (near_mask == nullptr || (*near_mask)[idx] != 0);
                const double* field_entry =
                    direction_field != nullptr ? &(*direction_field)[idx * 3]
                                               : nullptr;
                double weighted_sum = 0.0, weight_sum = 0.0;
                int neighbor_count = 0;
                for (int o = 0; o < 8; ++o) {
                    const std::ptrdiff_t nr =
                        static_cast<std::ptrdiff_t>(row) + kOff[o][0];
                    const std::ptrdiff_t nc =
                        static_cast<std::ptrdiff_t>(col) + kOff[o][1];
                    if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows) ||
                        nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                        continue;
                    }
                    const std::size_t nidx =
                        static_cast<std::size_t>(nr) * cols +
                        static_cast<std::size_t>(nc);
                    const double value = grid[nidx];
                    if (!std::isfinite(value)) continue;
                    if (region_labels != nullptr &&
                        (*region_labels)[nidx] != (*region_labels)[idx]) {
                        continue;
                    }
                    if (check_barrier) {
                        if (blocked_by_barrier(
                                grid_x[col], grid_y[row], grid_x[nc],
                                grid_y[nr], barrier_segs, 1e-9)) {
                            continue;
                        }
                    }
                    double eff = kOffW[o];
                    if (field_entry != nullptr) {
                        eff *= anisotropic_fill_multiplier(
                            kOff[o][0], kOff[o][1], field_entry[0],
                            field_entry[1], field_entry[2], aspect);
                    }
                    weighted_sum += value * eff;
                    weight_sum += eff;
                    ++neighbor_count;
                }
                if (neighbor_count >= min_neighbors && weight_sum > 0) {
                    double value = weighted_sum / weight_sum;
                    if (config.value_min.has_value()) {
                        value = std::max(*config.value_min, value);
                    }
                    if (config.value_max.has_value()) {
                        value = std::min(*config.value_max, value);
                    }
                    next[idx] = value;
                    ++changed;
                }
            }
        }
        grid = next;
        if (changed == 0) break;
    }
    int filled = 0;
    for (std::size_t i = 0; i < grid.size(); ++i) {
        if (fillable[i] && std::isfinite(grid[i])) ++filled;
    }
    for (std::size_t i = 0; i < grid.size(); ++i) {
        if (!domain_mask[i]) grid[i] = kNaN;
    }
    filled_count = filled;
}

// complete_gap_fill — BFS diffusion from valued boundary into NaN domain.
void complete_gap_fill(std::vector<double>& grid,
                       const std::vector<std::uint8_t>& domain_mask,
                       const std::vector<std::int32_t>* region_labels,
                       const Config& config,
                       const std::vector<double>* direction_field,
                       double cell_aspect,
                       const std::vector<Seg>& barrier_segs,
                       const std::vector<double>* x_coords,
                       const std::vector<double>* y_coords,
                       const std::vector<std::uint8_t>* near_mask,
                       const std::vector<std::uint8_t>* exclusion_mask,
                       int& filled_count) {
    filled_count = 0;
    if (grid.empty()) return;
    const std::size_t rows = y_coords ? y_coords->size() : 0;
    const std::size_t cols = x_coords ? x_coords->size() : 0;
    std::vector<std::uint8_t> domain = domain_mask;
    if (exclusion_mask != nullptr) {
        for (std::size_t i = 0; i < domain.size(); ++i) {
            if ((*exclusion_mask)[i]) domain[i] = 0;
        }
    }
    bool remaining = false;
    for (std::size_t i = 0; i < grid.size(); ++i) {
        if (domain[i] && !std::isfinite(grid[i])) remaining = true;
    }
    if (!remaining) return;
    const double aspect = cell_aspect > 1e-12 ? cell_aspect : 1.0;
    static constexpr int kOff[8][2] = {{-1, 0}, {1, 0},  {0, -1}, {0, 1},
                                       {-1, -1}, {-1, 1}, {1, -1}, {1, 1}};
    auto same_region = [&](std::size_t a, std::size_t b) {
        if (region_labels == nullptr) return true;
        return (*region_labels)[a] == (*region_labels)[b];
    };
    std::deque<std::pair<std::size_t, std::size_t>> queue;
    std::vector<std::uint8_t> queued(rows * cols, 0);
    for (std::size_t row = 0; row < rows; ++row) {
        for (std::size_t col = 0; col < cols; ++col) {
            const std::size_t idx = row * cols + col;
            if (!domain[idx] || std::isfinite(grid[idx])) continue;
            for (const auto& off : kOff) {
                const std::ptrdiff_t nr =
                    static_cast<std::ptrdiff_t>(row) + off[0];
                const std::ptrdiff_t nc =
                    static_cast<std::ptrdiff_t>(col) + off[1];
                if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows) ||
                    nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                    continue;
                }
                const std::size_t nidx =
                    static_cast<std::size_t>(nr) * cols +
                    static_cast<std::size_t>(nc);
                if (std::isfinite(grid[nidx]) && same_region(idx, nidx)) {
                    queue.emplace_back(row, col);
                    queued[idx] = 1;
                    break;
                }
            }
        }
    }
    const bool check_barrier = !barrier_segs.empty() && x_coords != nullptr &&
                               y_coords != nullptr;
    int filled = 0;
    while (!queue.empty()) {
        const auto [row, col] = queue.front();
        queue.pop_front();
        const std::size_t idx = row * cols + col;
        if (std::isfinite(grid[idx])) continue;
        const double* field_entry =
            direction_field != nullptr ? &(*direction_field)[idx * 3] : nullptr;
        const bool los_gate = check_barrier && (near_mask == nullptr ||
                                                (*near_mask)[idx] != 0);
        double weighted_sum = 0.0, weight_sum = 0.0;
        for (const auto& off : kOff) {
            const std::ptrdiff_t nr =
                static_cast<std::ptrdiff_t>(row) + off[0];
            const std::ptrdiff_t nc =
                static_cast<std::ptrdiff_t>(col) + off[1];
            if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows) ||
                nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                continue;
            }
            const std::size_t nidx =
                static_cast<std::size_t>(nr) * cols +
                static_cast<std::size_t>(nc);
            if (exclusion_mask != nullptr && (*exclusion_mask)[nidx]) continue;
            const double value = grid[nidx];
            if (!std::isfinite(value) || !same_region(idx, nidx)) continue;
            if (los_gate) {
                if (blocked_by_barrier((*x_coords)[col], (*y_coords)[row],
                                       (*x_coords)[nc], (*y_coords)[nr],
                                       barrier_segs, 1e-9)) {
                    continue;
                }
            }
            double weight = (off[0] == 0 || off[1] == 0) ? 2.0 : 1.0;
            if (field_entry != nullptr) {
                weight *= anisotropic_fill_multiplier(off[0], off[1],
                                                      field_entry[0],
                                                      field_entry[1],
                                                      field_entry[2], aspect);
            }
            weighted_sum += value * weight;
            weight_sum += weight;
        }
        if (weight_sum <= 0) continue;
        double value = weighted_sum / weight_sum;
        if (config.value_min.has_value()) {
            value = std::max(*config.value_min, value);
        }
        if (config.value_max.has_value()) {
            value = std::min(*config.value_max, value);
        }
        grid[idx] = value;
        ++filled;
        for (const auto& off : kOff) {
            const std::ptrdiff_t nr =
                static_cast<std::ptrdiff_t>(row) + off[0];
            const std::ptrdiff_t nc =
                static_cast<std::ptrdiff_t>(col) + off[1];
            if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows) ||
                nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                continue;
            }
            const std::size_t nidx =
                static_cast<std::size_t>(nr) * cols +
                static_cast<std::size_t>(nc);
            if (domain[nidx] && !queued[nidx] && !std::isfinite(grid[nidx]) &&
                same_region(idx, nidx)) {
                queue.emplace_back(static_cast<std::size_t>(nr),
                                   static_cast<std::size_t>(nc));
                queued[nidx] = 1;
            }
        }
    }
    filled_count = filled;
}

// smooth_valid_grid — 9-offset weighted average, barrier/region aware.
void smooth_valid_grid(std::vector<double>& grid,
                       const std::vector<double>& grid_x,
                       const std::vector<double>& grid_y,
                       const std::vector<Seg>& barrier_segs, int iterations,
                       const std::vector<std::uint8_t>* near_mask,
                       const std::vector<std::int32_t>* region_labels,
                       const std::vector<double>* direction_field,
                       double direction_strength) {
    if (iterations <= 0 || grid.empty()) return;
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    std::vector<std::uint8_t> valid(rows * cols, 0);
    for (std::size_t i = 0; i < grid.size(); ++i) {
        valid[i] = std::isfinite(grid[i]) ? 1 : 0;
    }
    bool any_valid = false;
    for (std::uint8_t v : valid) any_valid = any_valid || v != 0;
    if (!any_valid) return;
    const double step_x =
        grid_x.size() > 1 ? std::abs(grid_x[1] - grid_x[0]) : 1.0;
    const double step_y =
        grid_y.size() > 1 ? std::abs(grid_y[1] - grid_y[0]) : step_x;
    const double aspect = step_x > 1e-12 ? step_y / step_x : 1.0;
    direction_strength = std::max(0.0, direction_strength);
    static constexpr int kOff[9][2] = {{0, 0},  {-1, 0}, {1, 0},  {0, -1},
                                       {0, 1},  {-1, -1}, {-1, 1},
                                       {1, -1}, {1, 1}};
    static constexpr double kOffW[9] = {4.0, 2.0, 2.0, 2.0, 2.0,
                                        1.0, 1.0, 1.0, 1.0};
    for (int it = 0; it < iterations; ++it) {
        std::vector<double> next = grid;
        std::vector<double> ws(rows * cols, 0.0), ww(rows * cols, 0.0);
        for (int o = 0; o < 9; ++o) {
            const int dr = kOff[o][0], dc = kOff[o][1];
            const double weight = kOffW[o];
            for (std::size_t row = 0; row < rows; ++row) {
                const std::ptrdiff_t nr =
                    static_cast<std::ptrdiff_t>(row) + dr;
                if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows)) {
                    continue;
                }
                for (std::size_t col = 0; col < cols; ++col) {
                    const std::ptrdiff_t nc =
                        static_cast<std::ptrdiff_t>(col) + dc;
                    if (nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                        continue;
                    }
                    const std::size_t dst = row * cols + col;
                    const std::size_t src =
                        static_cast<std::size_t>(nr) * cols +
                        static_cast<std::size_t>(nc);
                    bool ok = valid[src] != 0;
                    double eff = weight;
                    if (dr != 0 || dc != 0) {
                        if (region_labels != nullptr &&
                            (*region_labels)[src] != (*region_labels)[dst]) {
                            ok = false;
                        }
                        if (ok && !barrier_segs.empty()) {
                            const bool near_gate =
                                near_mask == nullptr || (*near_mask)[dst] != 0;
                            if (near_gate &&
                                blocked_by_barrier(
                                    grid_x[col], grid_y[row], grid_x[nc],
                                    grid_y[nr], barrier_segs, 1e-9)) {
                                ok = false;
                            }
                        }
                        if (ok && direction_field != nullptr) {
                            const double* fe =
                                &(*direction_field)[dst * 3];
                            const double base = anisotropic_fill_multiplier(
                                dr, dc, fe[0], fe[1], fe[2], aspect);
                            if (base > 1.0) {
                                eff = weight *
                                      (1.0 + (base - 1.0) * direction_strength);
                            }
                        }
                    }
                    if (ok) {
                        ws[dst] += grid[src] * eff;
                        ww[dst] += eff;
                    }
                }
            }
        }
        for (std::size_t i = 0; i < grid.size(); ++i) {
            if (ww[i] > 0.0) next[i] = ws[i] / ww[i];
            if (!valid[i]) next[i] = kNaN;
        }
        grid = next;
    }
}

// refine_domain_boundary_transition — edge band blend (exact EDT).
void refine_domain_boundary_transition(
    std::vector<double>& grid, const std::vector<std::uint8_t>& domain_mask,
    const std::vector<double>& grid_x, const std::vector<double>& grid_y,
    const std::vector<Seg>& barrier_segs,
    const std::vector<std::uint8_t>* near_mask,
    const std::vector<std::int32_t>* region_labels, int feather_cells,
    int iterations) {
    if (iterations <= 0 || grid.empty()) return;
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    bool any_domain = false;
    for (std::uint8_t v : domain_mask) any_domain = any_domain || v != 0;
    if (!any_domain) return;
    std::vector<double> dist_to_edge;
    distance_transform_edt(domain_mask, rows, cols, dist_to_edge);
    const double feather = std::max(static_cast<double>(feather_cells), 1.0);
    std::vector<std::uint8_t> edge_band(rows * cols, 0);
    bool any_band = false;
    for (std::size_t i = 0; i < grid.size(); ++i) {
        edge_band[i] = (domain_mask[i] && dist_to_edge[i] > 0.0 &&
                        dist_to_edge[i] <= feather)
                           ? 1
                           : 0;
        any_band = any_band || edge_band[i] != 0;
    }
    if (!any_band) return;
    std::vector<std::uint8_t> valid(rows * cols, 0);
    for (std::size_t i = 0; i < grid.size(); ++i) {
        valid[i] = (std::isfinite(grid[i]) && domain_mask[i]) ? 1 : 0;
    }
    static constexpr int kOff[8][2] = {{-1, 0}, {1, 0},  {0, -1}, {0, 1},
                                       {-1, -1}, {-1, 1}, {1, -1}, {1, 1}};
    static constexpr double kOffW[8] = {2.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0};
    for (int it = 0; it < iterations; ++it) {
        std::vector<double> next = grid;
        for (std::size_t row = 0; row < rows; ++row) {
            for (std::size_t col = 0; col < cols; ++col) {
                const std::size_t idx = row * cols + col;
                if (!edge_band[idx] || !valid[idx]) continue;
                const bool check_barrier =
                    !barrier_segs.empty() &&
                    (near_mask == nullptr || (*near_mask)[idx] != 0);
                double weighted_sum = 0.0, weight_sum = 0.0;
                for (int o = 0; o < 8; ++o) {
                    const std::ptrdiff_t nr =
                        static_cast<std::ptrdiff_t>(row) + kOff[o][0];
                    const std::ptrdiff_t nc =
                        static_cast<std::ptrdiff_t>(col) + kOff[o][1];
                    if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows) ||
                        nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                        continue;
                    }
                    const std::size_t nidx =
                        static_cast<std::size_t>(nr) * cols +
                        static_cast<std::size_t>(nc);
                    if (!valid[nidx]) continue;
                    if (region_labels != nullptr &&
                        (*region_labels)[nidx] != (*region_labels)[idx]) {
                        continue;
                    }
                    if (check_barrier) {
                        if (blocked_by_barrier(
                                grid_x[col], grid_y[row], grid_x[nc],
                                grid_y[nr], barrier_segs, 1e-9)) {
                            continue;
                        }
                    }
                    const double edge_factor =
                        dist_to_edge[nidx] / feather;
                    const double eff_w =
                        kOffW[o] * std::max(edge_factor, 0.35);
                    weighted_sum += grid[nidx] * eff_w;
                    weight_sum += eff_w;
                }
                if (weight_sum > 0.0) {
                    const double interior = weighted_sum / weight_sum;
                    const double blend =
                        clamp01(dist_to_edge[idx] / feather);
                    next[idx] = interior * blend + grid[idx] * (1.0 - blend);
                }
            }
        }
        for (std::size_t i = 0; i < grid.size(); ++i) {
            if (!valid[i]) next[i] = kNaN;
        }
        grid = next;
    }
}

// apply_well_residual_anchoring — residual write-back at the wells (scalar
// reference semantics; upstream asserts vectorized parity within 1e-12 due to
// np.hypot vs math.hypot 1-ULP differences).
void apply_well_residual_anchoring(
    std::vector<double>& grid, const std::vector<double>& grid_x,
    const std::vector<double>& grid_y, const std::vector<Well>& wells,
    const std::vector<std::uint8_t>& domain_mask, const Config& config,
    const std::vector<std::int32_t>* region_labels,
    const std::vector<std::int32_t>* well_labels,
    const std::vector<double>* direction_field,
    std::map<std::string, double>& stats) {
    stats["well_anchor_count"] = 0.0;
    stats["well_anchor_residual_cells"] = 0.0;
    stats["well_anchor_max_residual"] = 0.0;
    stats["well_anchor_core_cells"] = 0.0;
    stats["well_anchor_smooth_cells"] = 0.0;
    stats["well_anchor_anisotropic"] = 0.0;
    stats["well_anchor_limited_count"] = 0.0;
    if (!config.well_anchor_enabled || grid.empty() || wells.empty()) return;
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    // Grid step (nanmedian of diff == the single diff for linspace axes).
    // _estimate_grid_step == max(|dx|, |dy|, 1e-9) on linspace axes.
    const double step = std::max(
        {grid_x.size() > 1 ? std::abs(grid_x[1] - grid_x[0]) : 1.0,
         grid_y.size() > 1 ? std::abs(grid_y[1] - grid_y[0]) : 1.0, 1e-9});
    bool has_dir = false;
    if (direction_field != nullptr) {
        for (std::size_t i = 0; i < rows * cols; ++i) {
            if ((*direction_field)[i * 3 + 2] > 1.0 + 1e-9) {
                has_dir = true;
                break;
            }
        }
    }
    const bool preserve_aniso = config.well_anchor_preserve_anisotropy || has_dir;
    if (has_dir) stats["well_anchor_anisotropic"] = 1.0;
    double anchor_radius = config.well_anchor_radius;
    if (anchor_radius <= 0.0) {
        anchor_radius = preserve_aniso ? std::max(step * 4.0, step * 2.5)
                                       : std::max(step * 10.0, step * 4.0);
    }
    const double core_radius =
        preserve_aniso
            ? std::max(step * 0.9, std::min(anchor_radius * 0.22, step * 1.6))
            : std::max(step * 1.5, std::min(anchor_radius * 0.32, step * 3.0));
    double max_stretch = 1.0;
    if (has_dir) {
        for (std::size_t i = 0; i < rows * cols; ++i) {
            max_stretch = std::max(max_stretch,
                                   (*direction_field)[i * 3 + 2]);
        }
    }
    const double search_bbox_radius =
        has_dir ? anchor_radius * std::max(max_stretch, 1.0) : anchor_radius;
    const int radius_cells = std::max(
        3, static_cast<int>(std::ceil(search_bbox_radius / step)) + 1);
    const double blend_radius =
        preserve_aniso ? std::max(anchor_radius * 0.55, step * 2.0)
                       : std::max(anchor_radius * 1.15, step * 4.0);
    const double sigma = preserve_aniso
                             ? std::max(anchor_radius * 0.28, step * 1.0)
                             : std::max(anchor_radius * 0.45, step * 1.5);
    const int blend_cells =
        std::max(radius_cells,
                 static_cast<int>(std::ceil(blend_radius *
                                            std::max(max_stretch, 1.0) / step)) +
                     1);
    double value_span = 0.0;
    if (config.value_min.has_value() && config.value_max.has_value()) {
        value_span = std::max(*config.value_max - *config.value_min, 0.0);
    } else {
        bool any_finite = false;
        double lo = kInf, hi = -kInf;
        for (const auto& well : wells) {
            if (std::isfinite(well.value)) {
                any_finite = true;
                lo = std::min(lo, well.value);
                hi = std::max(hi, well.value);
            }
        }
        if (any_finite) value_span = hi - lo;
    }
    const double residual_cap =
        value_span * std::max(0.0, config.well_anchor_max_residual_fraction);

    struct WellCenter {
        std::size_t row, col;
        double x, y, target, halo_target, ux, uy, ratio;
    };
    std::vector<WellCenter> well_centers;
    for (std::size_t well_index = 0; well_index < wells.size(); ++well_index) {
        const Well& well = wells[well_index];
        const std::size_t col = argmin_abs(grid_x, well.x);
        const std::size_t row = argmin_abs(grid_y, well.y);
        if (row >= rows || col >= cols) continue;
        if (!domain_mask[row * cols + col]) continue;
        if (region_labels != nullptr && well_labels != nullptr) {
            const std::int32_t wl = (*well_labels)[well_index];
            const std::int32_t cl = (*region_labels)[row * cols + col];
            if (wl >= 0 && cl >= 0 && wl != cl) continue;
        }
        const double center_value = grid[row * cols + col];
        double target_value = well.value;
        if (!std::isfinite(target_value)) continue;
        if (config.value_min.has_value()) {
            target_value = std::max(*config.value_min, target_value);
        }
        if (config.value_max.has_value()) {
            target_value = std::min(*config.value_max, target_value);
        }
        const double residual =
            std::isfinite(center_value) ? target_value - center_value : 0.0;
        stats["well_anchor_max_residual"] =
            std::max(stats["well_anchor_max_residual"], std::abs(residual));
        stats["well_anchor_count"] += 1.0;
        double halo_scale = 1.0;
        if (residual_cap > 1e-9 && std::abs(residual) > residual_cap) {
            halo_scale = residual_cap / std::abs(residual);
            stats["well_anchor_limited_count"] += 1.0;
        }
        const double halo_target = std::isfinite(center_value)
                                       ? center_value + residual * halo_scale
                                       : target_value;
        double ux = 1.0, uy = 0.0, ratio_eff = 1.0;
        if (has_dir && direction_field != nullptr) {
            ux = (*direction_field)[(row * cols + col) * 3 + 0];
            uy = (*direction_field)[(row * cols + col) * 3 + 1];
            ratio_eff = (*direction_field)[(row * cols + col) * 3 + 2];
            if (ratio_eff <= 1.0 + 1e-9 ||
                std::abs(ux) + std::abs(uy) <= 1e-12) {
                ux = 1.0;
                uy = 0.0;
                ratio_eff = 1.0;
            } else {
                const double nrm = std::hypot(ux, uy);
                ux /= nrm != 0.0 ? nrm : 1.0;
                uy /= nrm != 0.0 ? nrm : 1.0;
            }
        }
        well_centers.push_back({row, col, well.x, well.y, target_value,
                                halo_target, ux, uy, ratio_eff});
        // Stage 1: core + cos-taper halo.
        bool core_hit = false;
        int halo_cells = 0;
        for (int dr = -radius_cells; dr <= radius_cells; ++dr) {
            for (int dc = -radius_cells; dc <= radius_cells; ++dc) {
                const std::ptrdiff_t nr =
                    static_cast<std::ptrdiff_t>(row) + dr;
                const std::ptrdiff_t nc =
                    static_cast<std::ptrdiff_t>(col) + dc;
                if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows) ||
                    nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                    continue;
                }
                const std::size_t nidx =
                    static_cast<std::size_t>(nr) * cols +
                    static_cast<std::size_t>(nc);
                if (!domain_mask[nidx]) continue;
                if (region_labels != nullptr &&
                    (*region_labels)[nidx] != (*region_labels)[row * cols + col]) {
                    continue;
                }
                const double gx = grid_x[nc], gy = grid_y[nr];
                double dist;
                if (ratio_eff > 1.0 + 1e-9) {
                    dist = anisotropic_distance(
                        well.x, well.y, gx, gy, ux, uy, ratio_eff,
                        direction_perpendicular_scale(
                            ratio_eff,
                            config.direction_perpendicular_strength));
                } else {
                    dist = std::hypot(gx - well.x, gy - well.y);
                }
                if (dist > anchor_radius) continue;
                if (nr == static_cast<std::ptrdiff_t>(row) &&
                    nc == static_cast<std::ptrdiff_t>(col)) {
                    grid[nidx] = target_value;
                    core_hit = true;
                } else if (std::abs(residual) > 1e-9 &&
                           std::isfinite(grid[nidx])) {
                    ++halo_cells;
                    double t = std::max(0.0, dist - core_radius) /
                               std::max(anchor_radius - core_radius, 1e-9);
                    t = clamp01(t);
                    const double weight = 0.5 * (1.0 + std::cos(kPi * t));
                    double corrected = grid[nidx] + residual * halo_scale * weight;
                    if (config.value_min.has_value() &&
                        config.value_max.has_value() &&
                        *config.value_min <= target_value &&
                        target_value <= *config.value_max) {
                        corrected = std::max(*config.value_min,
                                             std::min(*config.value_max,
                                                      corrected));
                    }
                    grid[nidx] = corrected;
                }
            }
        }
        if (core_hit) stats["well_anchor_core_cells"] += 1.0;
        stats["well_anchor_residual_cells"] += static_cast<double>(halo_cells);
    }
    // Stage 2: blend pass (reads the pre-blend grid, writes a copy).
    if (!well_centers.empty() &&
        (!preserve_aniso || blend_radius >= step * 1.5)) {
        std::vector<double> blended = grid;
        const double two_sig2 = 2.0 * sigma * sigma;
        const double core_mix = preserve_aniso ? 0.70 : 0.85;
        const double outer_well = preserve_aniso ? 0.35 : 0.55;
        const double outer_keep = preserve_aniso ? 0.65 : 0.45;
        for (const auto& wc : well_centers) {
            int smooth_cells = 0;
            for (int dr = -blend_cells; dr <= blend_cells; ++dr) {
                for (int dc = -blend_cells; dc <= blend_cells; ++dc) {
                    const std::ptrdiff_t nr =
                        static_cast<std::ptrdiff_t>(wc.row) + dr;
                    const std::ptrdiff_t nc =
                        static_cast<std::ptrdiff_t>(wc.col) + dc;
                    if (nr < 0 || nr >= static_cast<std::ptrdiff_t>(rows) ||
                        nc < 0 || nc >= static_cast<std::ptrdiff_t>(cols)) {
                        continue;
                    }
                    const std::size_t nidx =
                        static_cast<std::size_t>(nr) * cols +
                        static_cast<std::size_t>(nc);
                    if (!domain_mask[nidx] || !std::isfinite(grid[nidx])) {
                        continue;
                    }
                    if (region_labels != nullptr &&
                        (*region_labels)[nidx] !=
                            (*region_labels)[wc.row * cols + wc.col]) {
                        continue;
                    }
                    const double gx = grid_x[nc], gy = grid_y[nr];
                    double dist;
                    if (wc.ratio > 1.0 + 1e-9) {
                        dist = anisotropic_distance(
                            wc.x, wc.y, gx, gy, wc.ux, wc.uy, wc.ratio,
                            direction_perpendicular_scale(
                                wc.ratio,
                                config.direction_perpendicular_strength));
                    } else {
                        dist = std::hypot(gx - wc.x, gy - wc.y);
                    }
                    if (dist > blend_radius) continue;
                    ++smooth_cells;
                    double new_v;
                    if (nr == static_cast<std::ptrdiff_t>(wc.row) &&
                        nc == static_cast<std::ptrdiff_t>(wc.col)) {
                        new_v = wc.target;
                    } else if (preserve_aniso) {
                        const double radial =
                            std::exp(-(dist * dist) /
                                     std::max(two_sig2, 1e-12));
                        if (dist <= core_radius) {
                            new_v = core_mix * wc.halo_target +
                                    (1.0 - core_mix) * grid[nidx];
                        } else {
                            new_v = radial * (outer_well * wc.halo_target +
                                              outer_keep * grid[nidx]) +
                                    (1.0 - radial) * grid[nidx];
                        }
                    } else {
                        // Python: sample_r = max(1, ceil(1.6*step/step)) == 2.
                        const int sample_r = 2;
                        double acc = 0.0, wsum = 0.0;
                        for (int sdr = -sample_r; sdr <= sample_r; ++sdr) {
                            for (int sdc = -sample_r; sdc <= sample_r; ++sdc) {
                                const std::ptrdiff_t sr =
                                    static_cast<std::ptrdiff_t>(nr) + sdr;
                                const std::ptrdiff_t sc =
                                    static_cast<std::ptrdiff_t>(nc) + sdc;
                                if (sr < 0 ||
                                    sr >= static_cast<std::ptrdiff_t>(rows) ||
                                    sc < 0 ||
                                    sc >= static_cast<std::ptrdiff_t>(cols)) {
                                    continue;
                                }
                                const std::size_t sidx =
                                    static_cast<std::size_t>(sr) * cols +
                                    static_cast<std::size_t>(sc);
                                if (!domain_mask[sidx] ||
                                    !std::isfinite(grid[sidx])) {
                                    continue;
                                }
                                if (region_labels != nullptr &&
                                    (*region_labels)[sidx] !=
                                        (*region_labels)[nidx]) {
                                    continue;
                                }
                                const double d2 =
                                    static_cast<double>(sdr * sdr + sdc * sdc) *
                                    (step * step);
                                const double sw =
                                    std::exp(-d2 /
                                             std::max(two_sig2 * 0.35, 1e-12));
                                acc += grid[sidx] * sw;
                                wsum += sw;
                            }
                        }
                        if (wsum <= 1e-12) continue;
                        const double local_mean = acc / wsum;
                        const double radial =
                            std::exp(-(dist * dist) /
                                     std::max(two_sig2, 1e-12));
                        if (dist <= core_radius) {
                            new_v = core_mix * wc.halo_target +
                                    (1.0 - core_mix) * local_mean;
                        } else {
                            new_v = radial * (outer_well * wc.halo_target +
                                              outer_keep * local_mean) +
                                    (1.0 - radial) * local_mean;
                        }
                    }
                    if (config.value_min.has_value() &&
                        config.value_max.has_value() &&
                        *config.value_min <= wc.target &&
                        wc.target <= *config.value_max) {
                        new_v = std::max(*config.value_min,
                                         std::min(*config.value_max, new_v));
                    }
                    blended[nidx] = new_v;
                }
            }
            if (smooth_cells > 0) {
                stats["well_anchor_smooth_cells"] +=
                    static_cast<double>(smooth_cells);
            }
        }
        grid = blended;
    }
}

// --------------------------------------------------------------------------- //
// Small resolvers (constrained_engine.py / masks.py)
// --------------------------------------------------------------------------- //

bool is_full_block_mode(const std::string& block_mode) {
    static const char* kNonBlocking[] = {"none", "off", "no_block", "soft",
                                         "partial", "0", "false"};
    const std::string mode = lower_trim(block_mode);
    for (const char* nb : kNonBlocking) {
        if (mode == nb) return false;
    }
    return true;
}

double resolve_interpolation_mask_radius(double mask_radius,
                                         double search_radius) {
    if (mask_radius > 0.0) return mask_radius;
    return std::max(search_radius, 1.0);
}

// resolve_barrier_buffer_distance → (distance, auto_applied).
std::pair<double, bool> resolve_barrier_buffer_distance(
    double requested_distance, double legacy_cell_buffer, double grid_step,
    double map_width, double map_height, double search_radius,
    bool has_barriers, bool auto_enabled) {
    if (requested_distance > 0.0) return {requested_distance, false};
    if (legacy_cell_buffer > 0.0) return {legacy_cell_buffer, false};
    if (!has_barriers || !auto_enabled) return {0.0, false};
    const double map_extent = std::max({map_width, map_height, grid_step});
    double adaptive = std::max({grid_step * 2.0, search_radius * 0.03,
                                map_extent * 0.012});
    adaptive = std::min({adaptive, map_extent * 0.04, 400.0});
    return {adaptive, true};
}

double estimate_hull_buffer_meters(double map_diagonal, double ratio = 0.02) {
    return std::max(map_diagonal * std::max(ratio, 0.0), 0.0);
}

double resolve_data_hull_buffer_meters(double requested_buffer,
                                       double search_radius,
                                       double map_diagonal,
                                       bool limit_to_well_coverage) {
    const double explicit_buffer = requested_buffer;
    if (explicit_buffer > 0.0) return explicit_buffer;
    if (!limit_to_well_coverage) return 0.0;
    const double radius = std::max(search_radius, 1.0);
    return std::min(std::max(radius * 0.15,
                             estimate_hull_buffer_meters(map_diagonal, 0.02)),
                    radius * 0.5);
}

double resolve_bfs_reach_cells(double search_radius, double grid_step,
                               std::size_t grid_resolution,
                               bool limit_to_well_coverage,
                               bool data_hull_active) {
    (void)search_radius;
    (void)grid_step;
    (void)data_hull_active;
    if (limit_to_well_coverage) {
        return std::min(4.0, std::max(2.0,
                                      static_cast<double>(grid_resolution) *
                                          0.02));
    }
    return static_cast<double>(std::max(
        static_cast<std::size_t>(static_cast<double>(grid_resolution) * 4.0),
        std::size_t{9999}));
}

double resolve_contour_support_dilation_cells(std::size_t grid_resolution,
                                              bool limit_to_well_coverage) {
    if (limit_to_well_coverage) {
        return std::min(3.0, std::max(2.0,
                                      static_cast<double>(grid_resolution) *
                                          0.015));
    }
    return std::min(6.0, std::max(3.0,
                                  static_cast<double>(grid_resolution) * 0.03));
}

double estimate_grid_step(const std::vector<double>& grid_x,
                          const std::vector<double>& grid_y) {
    // linspace axes have a constant diff; nanmedian == that diff.
    const double dx =
        grid_x.size() > 1 ? std::abs(grid_x[1] - grid_x[0]) : 1.0;
    const double dy =
        grid_y.size() > 1 ? std::abs(grid_y[1] - grid_y[0]) : dx;
    return std::max({dx, dy, 1e-9});
}

double grid_aspect(const std::vector<double>& grid_x,
                   const std::vector<double>& grid_y) {
    const double step_x =
        grid_x.size() > 1 ? std::abs(grid_x[1] - grid_x[0]) : 1.0;
    const double step_y =
        grid_y.size() > 1 ? std::abs(grid_y[1] - grid_y[0]) : step_x;
    return step_x > 1e-12 ? step_y / step_x : 1.0;
}

// extend_barriers_for_partition — tangential endpoint extension.
std::vector<BarrierLine> extend_barriers_for_partition(
    const std::vector<BarrierLine>& barriers, double extension_distance) {
    if (barriers.empty() || extension_distance <= 0) return barriers;
    std::vector<BarrierLine> extended;
    for (const auto& barrier : barriers) {
        std::vector<Point> points = barrier.points;
        if (points.size() < 2) {
            extended.push_back(barrier);
            continue;
        }
        const double sdx = points[0][0] - points[1][0];
        const double sdy = points[0][1] - points[1][1];
        const double slen = std::hypot(sdx, sdy);
        if (slen > 1e-12) {
            points[0] = {points[0][0] + sdx / slen * extension_distance,
                         points[0][1] + sdy / slen * extension_distance};
        }
        const std::size_t m = points.size();
        const double edx = points[m - 1][0] - points[m - 2][0];
        const double edy = points[m - 1][1] - points[m - 2][1];
        const double elen = std::hypot(edx, edy);
        if (elen > 1e-12) {
            points[m - 1] = {points[m - 1][0] + edx / elen * extension_distance,
                             points[m - 1][1] + edy / elen * extension_distance};
        }
        BarrierLine copy = barrier;
        copy.points = points;
        extended.push_back(copy);
    }
    return extended;
}

// compute_declustering_weights — down-weight dense clusters.
std::vector<double> compute_declustering_weights(
    const std::vector<Well>& wells, double radius, double strength) {
    const std::size_t n = wells.size();
    if (n == 0) return {};
    if (radius <= 0.0 || strength <= 0.0 || n <= 1) {
        return std::vector<double>(n, 1.0);
    }
    const double radius_sq = radius * radius;
    std::vector<double> weights(n);
    for (std::size_t i = 0; i < n; ++i) {
        double local_count = 0.0;
        for (std::size_t j = 0; j < n; ++j) {
            const double dx = wells[i].x - wells[j].x;
            const double dy = wells[i].y - wells[j].y;
            if (dx * dx + dy * dy <= radius_sq) local_count += 1.0;
        }
        local_count = std::max(local_count, 1.0);
        weights[i] = 1.0 / std::pow(local_count, strength);
    }
    const double mean_weight = numpy_sum(weights) / static_cast<double>(n);
    if (mean_weight > 0) {
        for (double& w : weights) w /= mean_weight;
    }
    return weights;
}

std::pair<int, int> summarize_point_density(const std::vector<Well>& wells,
                                            double radius) {
    if (wells.empty() || radius <= 0.0) return {0, 0};
    const double radius_sq = radius * radius;
    int isolated = 0, dense = 0;
    for (std::size_t i = 0; i < wells.size(); ++i) {
        int local_count = 0;
        for (std::size_t j = 0; j < wells.size(); ++j) {
            const double dx = wells[i].x - wells[j].x;
            const double dy = wells[i].y - wells[j].y;
            if (dx * dx + dy * dy <= radius_sq) ++local_count;
        }
        if (local_count <= 1) ++isolated;
        if (local_count >= 5) ++dense;
    }
    return {isolated, dense};
}

}  // namespace

// --------------------------------------------------------------------------- //
// generate_constrained_idw — surface path of the vendored engine
// --------------------------------------------------------------------------- //

Result generate_constrained_idw(const std::vector<Well>& wells,
                                const std::vector<BoundaryPolygon>& boundaries,
                                const std::vector<BarrierLine>& barriers,
                                const std::vector<DirectionLine>& directions,
                                const Config& config) {
    if (wells.size() < 3) {
        throw std::invalid_argument(
            "有效井点不足，至少需要 3 个，当前 " +
            std::to_string(wells.size()) + " 个");
    }
    if (boundaries.empty()) {
        throw std::invalid_argument("当前图层模式需要至少 1 个边界面");
    }

    Result result;
    auto& diag = result.diagnostics;
    const int resolution =
        std::max(20, std::min(2000, config.grid_resolution));

    // _build_grid_axes
    std::vector<Point> axis_points;
    for (const auto& boundary : boundaries) {
        axis_points.insert(axis_points.end(), boundary.exterior.begin(),
                           boundary.exterior.end());
    }
    if (axis_points.empty()) {
        throw std::invalid_argument("边界面缺少有效顶点");
    }
    double xs_min = kInf, xs_max = -kInf, ys_min = kInf, ys_max = -kInf;
    for (const auto& p : axis_points) {
        xs_min = std::min(xs_min, p[0]);
        xs_max = std::max(xs_max, p[0]);
        ys_min = std::min(ys_min, p[1]);
        ys_max = std::max(ys_max, p[1]);
    }
    const double span = std::max({xs_max - xs_min, ys_max - ys_min, 1.0});
    const double margin = span * std::max(0.0, config.boundary_margin_ratio);
    result.grid_x = linspace(xs_min - margin, xs_max + margin,
                             static_cast<std::size_t>(resolution));
    result.grid_y = linspace(ys_min - margin, ys_max + margin,
                             static_cast<std::size_t>(resolution));
    const std::vector<double>& grid_x = result.grid_x;
    const std::vector<double>& grid_y = result.grid_y;
    const std::size_t rows = grid_y.size(), cols = grid_x.size();
    const std::size_t n_cells = rows * cols;
    result.grid_z.assign(n_cells, kNaN);

    // Active constraints.
    std::vector<BarrierLine> active_barriers;
    for (const auto& line : barriers) {
        if (line.active && is_full_block_mode(line.block_mode) &&
            line.points.size() >= 2) {
            active_barriers.push_back(line);
        }
    }
    std::vector<DirectionLine> active_directions;
    for (const auto& line : directions) {
        if (line.active && line.points.size() >= 2) {
            active_directions.push_back(line);
        }
    }
    diag["参与井点数"] = static_cast<double>(wells.size());
    int control_points = 0;
    for (const auto& well : wells) {
        if (well.is_control_point) ++control_points;
    }
    diag["控制点数"] = static_cast<double>(control_points);
    diag["control_point_count"] = static_cast<double>(control_points);
    diag["有效打断线数"] = static_cast<double>(active_barriers.size());
    diag["active_barrier_count"] = static_cast<double>(active_barriers.size());
    diag["有效方向线数"] = static_cast<double>(active_directions.size());
    diag["active_direction_count"] =
        static_cast<double>(active_directions.size());
    diag["有效网格点数"] = 0.0;
    diag["无效网格点数"] = 0.0;
    diag["显式插值区数"] = 0.0;
    diag["explicit_interpolation_area_count"] = 0.0;
    diag["插值区外网格点数"] = 0.0;
    diag["outside_interpolation_area_grid_points"] = 0.0;
    diag["生成等值线条数"] = 0.0;  // contour chain not ported (D2)
    diag["被打断线过滤的井点-网格关系数量"] = 0.0;
    diag["blocked_well_grid_relations"] = 0.0;
    diag["打断线屏蔽网格点数"] = 0.0;
    diag["barrier_buffer_masked_grid_points"] = 0.0;
    diag["分割区域数"] = 0.0;
    diag["region_count"] = 0.0;
    diag["使用方向距离的网格点数"] = 0.0;
    diag["direction_distance_grid_points"] = 0.0;
    diag["普通距离网格点数"] = 0.0;
    diag["plain_distance_grid_points"] = 0.0;
    diag["方向线覆盖百分比"] = 0.0;
    diag["direction_coverage_percent"] = 0.0;

    std::vector<double> density =
        compute_declustering_weights(wells, config.decluster_radius,
                                     config.decluster_strength);
    const auto [n_isolated, n_dense] =
        summarize_point_density(wells, config.decluster_radius);
    diag["孤立井点数"] = static_cast<double>(n_isolated);
    diag["密集井点数"] = static_cast<double>(n_dense);

    // ── Step 1: domain masks ──
    const double grid_step = estimate_grid_step(grid_x, grid_y);
    const double map_width = cols > 1 ? grid_x[cols - 1] - grid_x[0] : grid_step;
    const double map_height = rows > 1 ? grid_y[rows - 1] - grid_y[0] : grid_step;
    const double map_diagonal = std::hypot(map_width, map_height);
    const std::vector<BarrierLine> partition_barriers =
        config.barrier_extend_to_boundary
            ? extend_barriers_for_partition(active_barriers, map_diagonal)
            : active_barriers;
    const auto [buffer_distance, buffer_auto_applied] =
        resolve_barrier_buffer_distance(
            std::max(0.0, config.barrier_buffer_distance),
            std::max(0.0, config.barrier_blank_cells) * grid_step, grid_step,
            map_width, map_height, config.search_radius,
            !active_barriers.empty(), config.barrier_buffer_auto);
    const double blank_distance = buffer_distance;

    std::vector<std::uint8_t> boundary_mask;
    build_boundary_union_mask(grid_x, grid_y, boundaries, boundary_mask);
    std::vector<std::uint8_t> blank_mask;
    const bool has_blank = build_barrier_blank_mask(
        grid_x, grid_y, active_barriers, blank_distance, &boundary_mask,
        blank_mask);
    const double core_stop_distance = std::max(grid_step * 0.85, 1e-9);
    std::vector<std::uint8_t> contour_stop_mask;
    const bool has_stop = build_barrier_blank_mask(
        grid_x, grid_y, active_barriers, core_stop_distance, &boundary_mask,
        contour_stop_mask);
    // Python round(): half-to-even.
    diag["打断线缓冲距离"] =
        static_cast<double>(py_round_int(blank_distance));
    diag["barrier_buffer_distance"] = buffer_distance;
    diag["barrier_buffer_auto_applied"] = buffer_auto_applied ? 1.0 : 0.0;
    diag["barrier_surface_blank_distance"] = blank_distance;
    diag["barrier_buffer_applies_to_surface"] = 1.0;
    diag["barrier_contour_core_stop_distance"] = core_stop_distance;
    int stop_count = 0;
    if (has_stop) {
        for (std::uint8_t v : contour_stop_mask) stop_count += v;
    }
    diag["barrier_contour_stop_grid_points"] = static_cast<double>(stop_count);

    // Direction radii / coverage masks (the curve corridor resolves radii
    // itself; the legacy half-map auto radius is never applied upstream).
    // _resolve_direction_radii preserves influence sentinels (<=0) for the
    // curve-corridor path; the legacy fallback uses them as given.
    std::vector<ResolvedDirection> resolved_directions;
    for (const auto& line : active_directions) {
        ResolvedDirection r;
        r.line_id = line.line_id;
        r.points = line.points;
        r.ratio = std::max(line.ratio, 1.0);
        r.influence_radius = line.influence_radius;
        r.priority = line.priority > 0 ? line.priority : 1;
        r.core_radius = line.core_radius;
        r.zone_id = line.zone_id;
        r.extend_mode = line.extend_mode;
        r.transition = line.transition;
        resolved_directions.push_back(std::move(r));
    }
    const double effective_mask_radius = resolve_interpolation_mask_radius(
        config.interpolation_mask_radius, config.search_radius);
    const bool apply_well_coverage_mask =
        config.interpolation_mask_radius > 0.0 ||
        config.limit_interpolation_to_search_radius;
    diag["interpolation_mask_radius_effective"] =
        apply_well_coverage_mask ? effective_mask_radius : 0.0;
    diag["well_coverage_limited"] = apply_well_coverage_mask ? 1.0 : 0.0;
    diag["data_hull_limited"] = 0.0;
    diag["data_hull_buffer_meters"] = 0.0;
    std::vector<std::uint8_t> well_coverage_mask;
    if (apply_well_coverage_mask) {
        std::vector<Well> mask_source_wells;
        for (const auto& well : wells) {
            if (config.interpolation_mask_use_control_points ||
                !well.is_control_point) {
                mask_source_wells.push_back(well);
            }
        }
        if (mask_source_wells.empty()) mask_source_wells = wells;
        build_well_coverage_mask(grid_x, grid_y, mask_source_wells,
                                 effective_mask_radius, well_coverage_mask);
    }
    const bool limit_well_coverage = config.limit_interpolation_to_search_radius;
    const double hull_buffer = resolve_data_hull_buffer_meters(
        config.data_hull_buffer_meters, config.search_radius, map_diagonal,
        apply_well_coverage_mask);
    const bool hull_requested =
        hull_buffer > 0.0 || config.data_hull_buffer_meters > 0.0;
    std::vector<std::uint8_t> data_hull_mask;
    bool data_hull_present = false;
    bool data_hull_mask_any = false;
    if (hull_requested && !limit_well_coverage) {
        data_hull_mask_any = build_data_hull_mask(
            grid_x, grid_y, wells, hull_buffer, data_hull_mask);
        if (data_hull_mask_any) {
            for (std::uint8_t v : data_hull_mask) {
                if (v) {
                    data_hull_present = true;
                    break;
                }
            }
            // Python marks the hull path taken even when the raster is empty
            // (an empty raster then wipes the whole domain below).
            diag["data_hull_limited"] = 1.0;
            diag["data_hull_buffer_meters"] = hull_buffer;
        }
    } else if (hull_requested && data_hull_exists(wells)) {
        data_hull_present = true;
        diag["data_hull_limited"] = 1.0;
        diag["data_hull_buffer_meters"] = hull_buffer;
    }
    diag["data_hull_domain_skipped"] =
        (limit_well_coverage && diag["data_hull_limited"] != 0.0) ? 1.0 : 0.0;

    std::vector<std::uint8_t> domain_mask(n_cells, 0);
    for (std::size_t i = 0; i < n_cells; ++i) {
        std::uint8_t v = boundary_mask[i];
        if (has_blank && blank_mask[i]) v = 0;
        if (apply_well_coverage_mask && !well_coverage_mask[i]) v = 0;
        if (!limit_well_coverage && data_hull_mask_any && !data_hull_mask[i]) {
            v = 0;
        }
        domain_mask[i] = v;
    }
    const int valid_cells =
        static_cast<int>(std::count(domain_mask.begin(), domain_mask.end(), 1));
    const int outside_cells = std::max(
        static_cast<int>(n_cells) - valid_cells, 0);
    diag["插值区外网格点数"] = static_cast<double>(outside_cells);
    diag["outside_interpolation_area_grid_points"] =
        static_cast<double>(outside_cells);
    if (has_blank) {
        int blank_count = 0;
        for (std::size_t i = 0; i < n_cells; ++i) {
            if (blank_mask[i] && boundary_mask[i]) ++blank_count;
        }
        diag["打断线屏蔽网格点数"] = static_cast<double>(blank_count);
        diag["barrier_buffer_masked_grid_points"] =
            static_cast<double>(blank_count);
    }
    int boundary_count = 0;
    for (std::uint8_t v : boundary_mask) boundary_count += v;
    diag["无效网格点数"] =
        static_cast<double>(boundary_count - valid_cells);

    // ── Step 2: barrier regions ──
    std::vector<std::uint8_t> near_active_mask, near_partition_mask;
    build_barrier_proximity_mask(grid_x, grid_y, active_barriers,
                                 near_active_mask);
    build_barrier_proximity_mask(grid_x, grid_y, partition_barriers,
                                 near_partition_mask);
    std::vector<std::int32_t> region_labels;
    std::vector<std::int32_t> well_labels;
    bool has_region_labels = false;
    if (!active_barriers.empty()) {
        const std::vector<Seg> partition_segs =
            barrier_segments(partition_barriers);
        build_region_labels(grid_x, grid_y, domain_mask, partition_barriers,
                            partition_segs, near_partition_mask, region_labels);
        has_region_labels = true;
        std::int32_t max_label = -1;
        for (std::int32_t v : region_labels) max_label = std::max(max_label, v);
        const double region_count = max_label >= 0 ? max_label + 1.0 : 0.0;
        diag["分割区域数"] = region_count;
        diag["region_count"] = region_count;
        well_labels = assign_well_regions(wells, grid_x, grid_y, region_labels);
    } else {
        const double region_count = valid_cells > 0 ? 1.0 : 0.0;
        diag["分割区域数"] = region_count;
        diag["region_count"] = region_count;
    }

    // ── Step 3: constrained IDW trend surface ──
    const bool use_curve =
        config.use_curve_direction_distance && !resolved_directions.empty();
    std::vector<PolylineGeometry> direction_geoms;
    DirectionCache direction_cache;
    bool has_cache = false;
    std::vector<double> direction_field_for_idw;
    bool has_direction_field = false;
    std::vector<WellCurve> well_curve_coords;
    if (!resolved_directions.empty()) {
        const double mean_spacing = estimate_mean_well_spacing(wells);
        direction_geoms = build_direction_geometries(
            active_directions, config.search_radius, mean_spacing,
            std::max(map_width, map_height));
        if (!direction_geoms.empty()) {
            direction_cache = build_grid_direction_cache(grid_x, grid_y,
                                                         domain_mask,
                                                         direction_geoms);
            has_cache = true;
            build_legacy_direction_field(direction_cache,
                                         direction_field_for_idw);
            has_direction_field = true;
            well_curve_coords =
                precompute_well_curve_coords(wells, direction_geoms);
            diag["direction_curve_corridor"] = 1.0;
            diag["mean_well_spacing"] = mean_spacing;
            diag["direction_geom_count"] =
                static_cast<double>(direction_geoms.size());
        } else {
            diag["direction_curve_corridor"] = 0.0;
        }
    }
    if (!has_direction_field && config.anisotropic_fill &&
        !resolved_directions.empty()) {
        has_direction_field = build_direction_field(
            grid_x, grid_y, domain_mask, resolved_directions,
            config.direction_taper_plateau, direction_field_for_idw);
        diag["direction_curve_corridor"] = 0.0;
    }

    diag["vectorized_idw"] = 0.0;
    double& blocked_total = diag["blocked_well_grid_relations"];
    double& blocked_cn = diag["被打断线过滤的井点-网格关系数量"];
    double& plain_total = diag["普通距离网格点数"];
    double& plain_en = diag["plain_distance_grid_points"];
    double& dir_total = diag["使用方向距离的网格点数"];
    double& dir_en = diag["direction_distance_grid_points"];

    if (!active_barriers.empty()) {
        // Point path with hard line-of-sight (host fix #382).
        const std::vector<Seg> active_segs = barrier_segments(active_barriers);
        std::vector<double> wx(wells.size()), wy(wells.size()),
            wz(wells.size());
        for (std::size_t i = 0; i < wells.size(); ++i) {
            wx[i] = wells[i].x;
            wy[i] = wells[i].y;
            wz[i] = wells[i].value;
        }
        for (std::size_t row = 0; row < rows; ++row) {
            for (std::size_t col = 0; col < cols; ++col) {
                const std::size_t idx = row * cols + col;
                if (!domain_mask[idx]) continue;
                const std::int32_t cell_label =
                    has_region_labels ? region_labels[idx] : -2;
                int cell_dir = -1;
                double c_s = 0.0, c_n = 0.0, c_g = 0.0, c_ratio = 1.0;
                if (has_cache) {
                    cell_dir = direction_cache.dir_index[idx];
                    c_s = direction_cache.s[idx];
                    c_n = direction_cache.n[idx];
                    c_g = direction_cache.g[idx];
                    c_ratio = direction_cache.ratio[idx];
                }
                // Per-cell LOS block row (vectorized mask in Python; the
                // per-pair reference arithmetic is identical).
                std::vector<std::uint8_t> blocked_row(wells.size(), 0);
                if (!active_segs.empty()) {
                    for (std::size_t i = 0; i < wells.size(); ++i) {
                        if (blocked_by_barrier(grid_x[col], grid_y[row], wx[i],
                                               wy[i], active_segs,
                                               config.endpoint_tolerance)) {
                            blocked_row[i] = 1;
                        }
                    }
                }
                const InterpOutcome outcome = interpolate_grid_point(
                    grid_x[col], grid_y[row], wx, wy, wz, active_segs,
                    resolved_directions, config, density,
                    has_region_labels ? &well_labels : nullptr, cell_label,
                    cell_dir, c_s, c_n, c_g, c_ratio,
                    well_curve_coords.empty() ? nullptr : &well_curve_coords,
                    &blocked_row);
                blocked_total += static_cast<double>(outcome.blocked);
                blocked_cn += static_cast<double>(outcome.blocked);
                if (!outcome.ok || !std::isfinite(outcome.value)) continue;
                double value = outcome.value;
                if (config.value_min.has_value()) {
                    value = std::max(*config.value_min, value);
                }
                if (config.value_max.has_value()) {
                    value = std::min(*config.value_max, value);
                }
                result.grid_z[idx] = value;
                if (outcome.used_direction) {
                    dir_total += 1.0;
                    dir_en += 1.0;
                } else {
                    plain_total += 1.0;
                    plain_en += 1.0;
                }
            }
        }
    } else {
        diag["vectorized_idw"] = 1.0;
        interpolate_idw_grid_batch(
            grid_x, grid_y, wells, domain_mask, config, density,
            has_region_labels ? &region_labels : nullptr,
            has_region_labels ? &well_labels : nullptr,
            has_direction_field ? &direction_field_for_idw : nullptr,
            result.grid_z);
    }

    // Along-track red-oval stretch.
    double max_dir_ratio = 1.0;
    for (const auto& g : direction_geoms) {
        max_dir_ratio = std::max(max_dir_ratio, g.ratio);
    }
    const bool apply_along_track =
        has_cache && !direction_geoms.empty() && !well_curve_coords.empty() &&
        use_curve && max_dir_ratio >= 2.0 && config.use_extended_search &&
        config.along_track_blend_strength > 0.05;
    std::map<int, AlongProfile> along_profiles;
    if (apply_along_track) {
        along_profiles = build_along_track_well_profiles(
            wells, well_curve_coords, direction_geoms, 0.10);
        int along_cells = 0;
        blend_corridor_along_track(
            result.grid_z, direction_cache, direction_geoms, along_profiles,
            domain_mask, config.along_track_blend_strength,
            config.along_track_min_cell_g, config.along_track_exp_k,
            along_cells);
        diag["along_track_stretch"] = 1.0;
        diag["along_track_cells"] = static_cast<double>(along_cells);
        diag["along_track_profiles"] =
            static_cast<double>(along_profiles.size());
        if (config.value_min.has_value() || config.value_max.has_value()) {
            for (std::size_t i = 0; i < n_cells; ++i) {
                if (!std::isfinite(result.grid_z[i])) continue;
                if (config.value_min.has_value()) {
                    result.grid_z[i] =
                        std::max(*config.value_min, result.grid_z[i]);
                }
                if (config.value_max.has_value()) {
                    result.grid_z[i] =
                        std::min(*config.value_max, result.grid_z[i]);
                }
            }
        }
    } else {
        diag["along_track_stretch"] = 0.0;
    }

    {
        int finite_count = 0;
        for (std::size_t i = 0; i < n_cells; ++i) {
            if (domain_mask[i] && std::isfinite(result.grid_z[i])) {
                ++finite_count;
            }
        }
        diag["有效网格点数"] = static_cast<double>(finite_count);
        if (has_direction_field) {
            int direction_used = 0;
            for (std::size_t i = 0; i < n_cells; ++i) {
                if (domain_mask[i] && std::isfinite(result.grid_z[i]) &&
                    direction_field_for_idw[i * 3 + 2] > 1.0 + 1e-9) {
                    ++direction_used;
                }
            }
            dir_total = static_cast<double>(direction_used);
            dir_en = static_cast<double>(direction_used);
            plain_total = diag["有效网格点数"] - dir_total;
            plain_en = plain_total;
        }
        const double valid_grid_points = diag["有效网格点数"];
        const double direction_points = diag["使用方向距离的网格点数"];
        const double coverage =
            valid_grid_points > 0
                ? std::nearbyint(100.0 * direction_points / valid_grid_points)
                : 0.0;
        diag["方向线覆盖百分比"] = coverage;
        diag["direction_coverage_percent"] = coverage;
    }

    // ── Step 4: region-local gap fill + smoothing (no cross-barrier) ──
    const std::vector<Seg> smoothing_segs =
        config.smooth_across_barriers ? std::vector<Seg>()
                                      : barrier_segments(active_barriers);
    const std::vector<std::int32_t>* smoothing_labels =
        config.smooth_across_barriers ? nullptr
                                      : (has_region_labels ? &region_labels
                                                           : nullptr);
    const std::vector<std::uint8_t>* smoothing_near =
        !smoothing_segs.empty() ? &near_active_mask : nullptr;

    std::vector<double>* direction_field = nullptr;
    std::vector<double> fallback_direction_field;
    if (has_direction_field) {
        direction_field = &direction_field_for_idw;
    } else if (config.anisotropic_fill && !resolved_directions.empty()) {
        build_direction_field(grid_x, grid_y, domain_mask, resolved_directions,
                              config.direction_taper_plateau,
                              fallback_direction_field);
        direction_field = &fallback_direction_field;
    }

    int gap_iterations = std::max(0, config.gap_fill_iterations);
    const bool data_hull_active = data_hull_mask_any || data_hull_present;
    std::vector<std::uint8_t> idw_support(n_cells, 0);
    for (std::size_t i = 0; i < n_cells; ++i) {
        idw_support[i] =
            (domain_mask[i] && std::isfinite(result.grid_z[i])) ? 1 : 0;
    }
    const double bfs_reach_cells = resolve_bfs_reach_cells(
        config.search_radius, grid_step, cols, limit_well_coverage,
        data_hull_active);
    diag["bfs_reach_cells"] = bfs_reach_cells;
    std::vector<std::uint8_t> gap_fill_domain;
    build_bfs_reach_mask(idw_support, domain_mask, rows, cols, bfs_reach_cells,
                         gap_fill_domain);
    if (limit_well_coverage) {
        gap_iterations = std::min(gap_iterations, data_hull_active ? 3 : 0);
    }
    int filled_count = 0;
    fill_internal_gaps(result.grid_z, grid_x, grid_y, gap_fill_domain,
                       gap_iterations, config, smoothing_segs, smoothing_near,
                       smoothing_labels, direction_field, filled_count);
    diag["补值网格点数"] = static_cast<double>(filled_count);

    if (limit_well_coverage) {
        diag["扩展补值网格点数"] = 0.0;
        diag["bfs_gap_fill_skipped"] = 1.0;
    } else {
        int extended_count = 0;
        const std::vector<Seg> active_segs = barrier_segments(active_barriers);
        complete_gap_fill(result.grid_z, gap_fill_domain, smoothing_labels,
                          config, direction_field, grid_aspect(grid_x, grid_y),
                          active_segs, &grid_x, &grid_y, &near_active_mask,
                          &blank_mask, extended_count);
        diag["扩展补值网格点数"] = static_cast<double>(extended_count);
        diag["bfs_gap_fill_skipped"] = 0.0;
    }

    smooth_valid_grid(result.grid_z, grid_x, grid_y, smoothing_segs,
                      std::max(0, config.grid_smoothing_iterations),
                      smoothing_near, smoothing_labels, direction_field,
                      config.direction_smoothing_strength);

    std::vector<std::uint8_t> contour_support_mask;
    if (limit_well_coverage) {
        build_bfs_reach_mask(
            idw_support, domain_mask, rows, cols,
            resolve_contour_support_dilation_cells(cols, true),
            contour_support_mask);
    } else {
        contour_support_mask = domain_mask;
    }
    refine_domain_boundary_transition(result.grid_z, contour_support_mask,
                                      grid_x, grid_y, smoothing_segs,
                                      smoothing_near, smoothing_labels, 4, 2);
    std::map<std::string, double> anchor_stats;
    apply_well_residual_anchoring(
        result.grid_z, grid_x, grid_y, wells, contour_support_mask, config,
        has_region_labels ? &region_labels : nullptr,
        has_region_labels ? &well_labels : nullptr, direction_field,
        anchor_stats);
    for (const auto& [key, value] : anchor_stats) diag[key] = value;

    // Re-apply the ridge blend after residual anchoring.
    if (apply_along_track && !along_profiles.empty() && has_cache) {
        int along_cells_post = 0;
        blend_corridor_along_track(
            result.grid_z, direction_cache, direction_geoms, along_profiles,
            domain_mask, std::min(1.0, config.along_track_blend_strength),
            config.along_track_min_cell_g, config.along_track_exp_k,
            along_cells_post);
        diag["along_track_post_anchor_cells"] =
            static_cast<double>(along_cells_post);
        if (config.value_min.has_value() || config.value_max.has_value()) {
            for (std::size_t i = 0; i < n_cells; ++i) {
                if (!std::isfinite(result.grid_z[i])) continue;
                if (config.value_min.has_value()) {
                    result.grid_z[i] =
                        std::max(*config.value_min, result.grid_z[i]);
                }
                if (config.value_max.has_value()) {
                    result.grid_z[i] =
                        std::min(*config.value_max, result.grid_z[i]);
                }
            }
        }
    }

    // Display masking: support stays finite-only; domain outside support NaN.
    std::vector<std::uint8_t> display_support(n_cells, 0);
    for (std::size_t i = 0; i < n_cells; ++i) {
        display_support[i] =
            (contour_support_mask[i] && std::isfinite(result.grid_z[i])) ? 1
                                                                         : 0;
    }
    for (std::size_t i = 0; i < n_cells; ++i) {
        if (!domain_mask[i]) result.grid_z[i] = kNaN;
    }
    for (std::size_t i = 0; i < n_cells; ++i) {
        if (!display_support[i]) result.grid_z[i] = kNaN;
    }
    // Barrier corridor stays nodata on the display surface (#370).
    if (has_blank && !active_barriers.empty()) {
        int forced = 0;
        for (std::size_t i = 0; i < n_cells; ++i) {
            if (blank_mask[i] && boundary_mask[i]) {
                result.grid_z[i] = kNaN;
                ++forced;
            }
        }
        diag["barrier_buffer_forced_zero_cells"] = static_cast<double>(forced);
        diag["barrier_buffer_filled_cells"] = static_cast<double>(forced);
    } else {
        diag["barrier_buffer_forced_zero_cells"] = 0.0;
        diag["barrier_buffer_filled_cells"] = 0.0;
    }
    return result;
}

}  // namespace pwb::mapping::constrained_idw
