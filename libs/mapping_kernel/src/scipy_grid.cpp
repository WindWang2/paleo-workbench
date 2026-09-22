// pwb::mapping — SciPy-griddata-equivalent interpolation; see
// scipy_grid.hpp for the contract. Ports
// geoviz_plots/interpolation/scipy_grid.py plus the scipy internals it
// reaches (qhull Delaunay walk, LinearNDInterpolator,
// CloughTocher2DInterpolator including _estimate_gradients_2d_global,
// NearestNDInterpolator, Rbf) — translated verbatim where practical.

#include <pwb/mapping/scipy_grid.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

namespace pwb::mapping {

std::pair<std::vector<double>, std::vector<double>> interpolation_grid_axes(
    const std::vector<double>& xs, const std::vector<double>& ys,
    int grid_n) {
    const int n = std::max(2, grid_n);
    auto axis = [&](const std::vector<double>& v) {
        auto [lo, hi] = std::minmax_element(v.begin(), v.end());
        const double pad = 0.05 * (*hi - *lo > 0.0 ? *hi - *lo : 1.0);
        // np.linspace: i*delta + start, with the last element forced to
        // exactly `stop`.
        const double start = *lo - pad;
        const double stop = *hi + pad;
        const double step = (stop - start) / (n - 1);
        std::vector<double> ax(static_cast<std::size_t>(n));
        for (int i = 0; i < n; ++i) ax[i] = start + step * i;
        ax[ax.size() - 1] = stop;
        return ax;
    };
    return {axis(xs), axis(ys)};
}

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
// scipy _qhull.pyx containment tolerance: eps = 100 * DBL_EPSILON.
constexpr double kEps = 100.0 * std::numeric_limits<double>::epsilon();

// Internal failure matching the oracle's caught set (QhullError /
// LinAlgError) — only these trigger the nearest fallback.
struct ScipyEngineError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// ~np.isnan per axis — inf propagates, mirroring the oracle.
struct FilteredSamples {
    std::vector<double> x, y, z;
};

FilteredSamples filter_nan_samples(const std::vector<double>& xs,
                                   const std::vector<double>& ys,
                                   const std::vector<double>& zs) {
    FilteredSamples out;
    const std::size_t n =
        std::min(xs.size(), std::min(ys.size(), zs.size()));
    for (std::size_t i = 0; i < n; ++i) {
        if (!std::isnan(xs[i]) && !std::isnan(ys[i]) && !std::isnan(zs[i])) {
            out.x.push_back(xs[i]);
            out.y.push_back(ys[i]);
            out.z.push_back(zs[i]);
        }
    }
    return out;
}

// ---------------------------------------------------------------------
// Delaunay triangulation (Bowyer-Watson). Not bit-identical to Qhull for
// co-circular or coincident inputs — the oracle's own result is
// tie-dependent there — but identical on generic sets up to simplex
// ordering. Triangles are stored CCW; nbrs[k] is the triangle across the
// edge opposite vertex k (qhull convention); transforms use the qhull
// layout [T00 T01 T10 T11 v2x v2y] with T = [v0-v2 | v1-v2]^{-1}.
// ---------------------------------------------------------------------
struct Delaunay {
    std::vector<double> x, y;              // unique point coords
    std::vector<int> orig;                 // unique index -> sample index
    std::vector<std::array<int, 3>> tris;  // CCW vertex ids
    std::vector<std::array<int, 3>> nbrs;  // opposite-vertex neighbours
    std::vector<std::array<double, 6>> transforms;
    double minx = 0.0, maxx = 0.0, miny = 0.0, maxy = 0.0;
};

double in_circle(double ax, double ay, double bx, double by, double cx,
                 double cy, double dx, double dy) {
    const double axd = ax - dx, ayd = ay - dy;
    const double bxd = bx - dx, byd = by - dy;
    const double cxd = cx - dx, cyd = cy - dy;
    const double alift = axd * axd + ayd * ayd;
    const double blift = bxd * bxd + byd * byd;
    const double clift = cxd * cxd + cyd * cyd;
    return alift * (bxd * cyd - cxd * byd)
           - blift * (axd * cyd - cxd * ayd)
           + clift * (axd * byd - bxd * ayd);
}

double orient2d(double ax, double ay, double bx, double by, double cx,
                double cy) {
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
}

std::uint64_t edge_key(int a, int b) {
    const std::uint32_t lo = static_cast<std::uint32_t>(std::min(a, b));
    const std::uint32_t hi = static_cast<std::uint32_t>(std::max(a, b));
    return (static_cast<std::uint64_t>(lo) << 32) | hi;
}

Delaunay delaunay(const std::vector<double>& xs,
                  const std::vector<double>& ys) {
    Delaunay d;
    // Exact-duplicate collapse, first occurrence wins (qhull joggles
    // duplicates; collapsing keeps the solve finite — documented
    // divergence).
    std::unordered_map<std::uint64_t, int> seen;
    seen.reserve(xs.size());
    for (std::size_t i = 0; i < xs.size(); ++i) {
        std::uint64_t ua, ub;
        const double a = xs[i], b = ys[i];
        std::memcpy(&ua, &a, 8);
        std::memcpy(&ub, &b, 8);
        const std::uint64_t key =
            ua * 0x9E3779B97F4A7C15ull
            ^ (ub + 0xBF58476D1CE4E5B9ull + (ua << 6) + (ua >> 2));
        if (seen.emplace(key, static_cast<int>(d.x.size())).second) {
            d.x.push_back(a);
            d.y.push_back(b);
            d.orig.push_back(static_cast<int>(i));
        }
    }
    const int n = static_cast<int>(d.x.size());
    if (n < 3) {
        throw ScipyEngineError("not enough points for triangulation");
    }
    d.minx = d.maxx = d.x[0];
    d.miny = d.maxy = d.y[0];
    for (int i = 1; i < n; ++i) {
        d.minx = std::min(d.minx, d.x[i]);
        d.maxx = std::max(d.maxx, d.x[i]);
        d.miny = std::min(d.miny, d.y[i]);
        d.maxy = std::max(d.maxy, d.y[i]);
    }
    const double midx = 0.5 * (d.minx + d.maxx);
    const double midy = 0.5 * (d.miny + d.maxy);
    const double dmax = std::max(d.maxx - d.minx, d.maxy - d.miny);
    if (!(dmax > 0.0) || !std::isfinite(dmax)) {
        throw ScipyEngineError("degenerate point set");
    }
    // Supertriangle comfortably enclosing the set (ids n..n+2).
    const double sx[3] = {midx - 20.0 * dmax, midx, midx + 20.0 * dmax};
    const double sy[3] = {midy - dmax, midy + 20.0 * dmax, midy - dmax};

    struct WorkTri {
        int a, b, c;
    };
    std::vector<WorkTri> work{{n, n + 1, n + 2}};
    auto px = [&](int i) { return i < n ? d.x[i] : sx[i - n]; };
    auto py = [&](int i) { return i < n ? d.y[i] : sy[i - n]; };

    for (int p = 0; p < n; ++p) {
        std::unordered_map<std::uint64_t, std::pair<int, int>> edge_use;
        std::vector<WorkTri> kept;
        kept.reserve(work.size());
        bool any_bad = false;
        for (const WorkTri& t : work) {
            const double det =
                in_circle(px(t.a), py(t.a), px(t.b), py(t.b), px(t.c),
                          py(t.c), d.x[p], d.y[p]);
            if (det > 0.0) {
                any_bad = true;
                const int e[3][2] = {{t.a, t.b}, {t.b, t.c}, {t.c, t.a}};
                for (const auto& ep : e) {
                    auto& slot = edge_use[edge_key(ep[0], ep[1])];
                    slot.first += 1;
                    if (slot.first == 1) slot.second = ep[0];
                }
            } else {
                kept.push_back(t);
            }
        }
        if (!any_bad) {
            // Co-circular boundary hit or numerical miss: split the
            // containing triangle so the sample is never dropped
            // (Delaunay up to degeneracy).
            bool done = false;
            for (std::size_t ti = 0; ti < kept.size() && !done; ++ti) {
                const WorkTri& t = kept[ti];
                if (orient2d(px(t.a), py(t.a), px(t.b), py(t.b), d.x[p],
                             d.y[p])
                        >= 0.0
                    && orient2d(px(t.b), py(t.b), px(t.c), py(t.c),
                                d.x[p], d.y[p])
                           >= 0.0
                    && orient2d(px(t.c), py(t.c), px(t.a), py(t.a),
                                d.x[p], d.y[p])
                           >= 0.0) {
                    kept.erase(kept.begin() + static_cast<long>(ti));
                    auto push_ccw = [&](int a, int b) {
                        if (orient2d(px(a), py(a), px(b), py(b), d.x[p],
                                     d.y[p])
                            > 0.0) {
                            kept.push_back({a, b, p});
                        } else {
                            kept.push_back({b, a, p});
                        }
                    };
                    push_ccw(t.a, t.b);
                    push_ccw(t.b, t.c);
                    push_ccw(t.c, t.a);
                    done = true;
                }
            }
            work.swap(kept);
            continue;
        }
        std::vector<WorkTri> next = std::move(kept);
        for (const auto& [key, use] : edge_use) {
            if (use.first != 1) continue;
            const int a = static_cast<int>(key >> 32);
            const int b = static_cast<int>(key & 0xFFFFFFFFu);
            if (orient2d(px(a), py(a), px(b), py(b), d.x[p], d.y[p])
                > 0.0) {
                next.push_back({a, b, p});
            } else {
                next.push_back({b, a, p});
            }
        }
        work.swap(next);
    }

    for (const WorkTri& t : work) {
        if (t.a >= n || t.b >= n || t.c >= n) continue;
        if (!(orient2d(d.x[t.a], d.y[t.a], d.x[t.b], d.y[t.b], d.x[t.c],
                       d.y[t.c])
              > 0.0)) {
            continue;  // drop zero-area facet
        }
        d.tris.push_back({t.a, t.b, t.c});
    }
    if (d.tris.empty()) {
        // Collinear/degenerate input — QhullError equivalent.
        throw ScipyEngineError("triangulation failed (degenerate input)");
    }

    // Neighbour table via shared edges.
    std::unordered_map<std::uint64_t, std::pair<int, int>> edge_owner;
    d.nbrs.assign(d.tris.size(), {-1, -1, -1});
    for (std::size_t t = 0; t < d.tris.size(); ++t) {
        const auto& tri = d.tris[t];
        for (int k = 0; k < 3; ++k) {
            const std::uint64_t key =
                edge_key(tri[(k + 1) % 3], tri[(k + 2) % 3]);
            auto [it, inserted] = edge_owner.emplace(
                key, std::pair<int, int>{static_cast<int>(t), k});
            if (!inserted) {
                const auto [ot, ok] = it->second;
                d.nbrs[t][k] = ot;
                d.nbrs[ot][ok] = static_cast<int>(t);
            }
        }
    }

    d.transforms.resize(d.tris.size());
    for (std::size_t t = 0; t < d.tris.size(); ++t) {
        const auto& tri = d.tris[t];
        const double m00 = d.x[tri[0]] - d.x[tri[2]];
        const double m01 = d.x[tri[1]] - d.x[tri[2]];
        const double m10 = d.y[tri[0]] - d.y[tri[2]];
        const double m11 = d.y[tri[1]] - d.y[tri[2]];
        const double det = m00 * m11 - m01 * m10;
        auto& tr = d.transforms[t];
        tr[0] = m11 / det;
        tr[1] = -m01 / det;
        tr[2] = -m10 / det;
        tr[3] = m00 / det;
        tr[4] = d.x[tri[2]];
        tr[5] = d.y[tri[2]];
    }
    return d;
}

// _barycentric_coordinates: c[k] = T_k . (p - v2), c[2] = 1 - c0 - c1.
void barycentric(const std::array<double, 6>& tr, double px, double py,
                 double c[3]) {
    c[0] = tr[0] * (px - tr[4]) + tr[1] * (py - tr[5]);
    c[1] = tr[2] * (px - tr[4]) + tr[3] * (py - tr[5]);
    c[2] = 1.0 - c[0] - c[1];
}

// _find_simplex: bbox precheck + directed walk (hop on the first
// negative barycentric coordinate, qhull semantics) + brute-force
// fallback. `start` is updated like qhull's start parameter.
int find_simplex(const Delaunay& d, double px, double py, int& start) {
    if (px < d.minx - kEps || px > d.maxx + kEps || py < d.miny - kEps
        || py > d.maxy + kEps) {
        return -1;
    }
    const int nsimplex = static_cast<int>(d.tris.size());
    int isimplex = (start >= 0 && start < nsimplex) ? start : 0;
    double c[3] = {0.0, 0.0, 0.0};
    const int max_cycle = 1 + nsimplex / 4;
    for (int cycle = 0; cycle < max_cycle; ++cycle) {
        if (isimplex == -1) break;
        const auto& tr = d.transforms[isimplex];
        int inside = 1;
        for (int k = 0; k < 3; ++k) {
            if (k < 2) {
                c[k] = tr[2 * k] * (px - tr[4])
                       + tr[2 * k + 1] * (py - tr[5]);
            } else {
                c[2] = 1.0 - c[0] - c[1];
            }
            if (c[k] < -kEps) {
                const int m = d.nbrs[isimplex][k];
                if (m == -1) {
                    start = isimplex;
                    return -1;  // outside the convex hull
                }
                isimplex = m;
                inside = -1;
                break;
            }
            if (!(c[k] <= 1.0 + kEps)) {
                inside = 0;  // degenerate coordinate -> brute force
            }
        }
        if (inside == -1) continue;
        if (inside == 1) {
            start = isimplex;
            return isimplex;
        }
        break;  // inside == 0 -> brute force
    }
    // _find_simplex_bruteforce (valid-transform path only — this
    // triangulation never emits degenerate transforms).
    for (int t = 0; t < nsimplex; ++t) {
        barycentric(d.transforms[t], px, py, c);
        bool inside = true;
        for (int k = 0; k < 3; ++k) {
            if (!(-kEps <= c[k] && c[k] <= 1.0 + kEps)) {
                inside = false;
                break;
            }
        }
        if (inside) {
            start = t;
            return t;
        }
    }
    start = -1;  // qhull leaves start at the failed result
    return -1;
}

// ---------------------------------------------------------------------
// Convex hull: Andrew monotone chain, CCW, extreme vertices only
// (collinear boundary points excluded, like qhull's hull.vertices).
// Containment: nonzero winding number (matplotlib rule) + inclusive
// boundary.
// ---------------------------------------------------------------------
std::vector<int> convex_hull_vertices(const std::vector<double>& x,
                                      const std::vector<double>& y) {
    const std::size_t n = x.size();
    std::vector<int> idx(n);
    std::iota(idx.begin(), idx.end(), 0);
    std::sort(idx.begin(), idx.end(), [&](int a, int b) {
        return x[a] < x[b] || (x[a] == x[b] && y[a] < y[b]);
    });
    std::vector<int> h(2 * n);
    std::size_t k = 0;
    auto cross = [&](int o, int a, int b) {
        return (x[a] - x[o]) * (y[b] - y[o])
               - (y[a] - y[o]) * (x[b] - x[o]);
    };
    for (std::size_t i = 0; i < n; ++i) {
        while (k >= 2 && cross(h[k - 2], h[k - 1], idx[i]) <= 0.0) --k;
        h[k++] = idx[i];
    }
    const std::size_t lower = k;
    for (std::size_t i = n; i-- > 0;) {
        while (k > lower && cross(h[k - 2], h[k - 1], idx[i]) <= 0.0)
            --k;
        h[k++] = idx[i];
    }
    h.resize(k > 0 ? k - 1 : 0);
    return h;
}

double is_left(double ax, double ay, double bx, double by, double px,
               double py) {
    return (bx - ax) * (py - ay) - (px - ax) * (by - ay);
}

bool point_in_hull(const std::vector<int>& hull,
                   const std::vector<double>& x,
                   const std::vector<double>& y, double px, double py) {
    const std::size_t m = hull.size();
    if (m < 3) return true;  // no polygon -> no masking
    int wn = 0;
    for (std::size_t i = 0; i < m; ++i) {
        const int a = hull[i];
        const int b = hull[(i + 1) % m];
        const double ax = x[a], ay = y[a], bx = x[b], by = y[b];
        const double l = is_left(ax, ay, bx, by, px, py);
        if (l == 0.0 && px >= std::min(ax, bx) && px <= std::max(ax, bx)
            && py >= std::min(ay, by) && py <= std::max(ay, by)) {
            return true;  // boundary-inclusive
        }
        if (ay <= py) {
            if (by > py && l > 0.0) ++wn;
        } else {
            if (by <= py && l < 0.0) --wn;
        }
    }
    return wn != 0;
}

// ---------------------------------------------------------------------
// Backends
// ---------------------------------------------------------------------
std::vector<double> nearest_grid(const std::vector<double>& x,
                                 const std::vector<double>& y,
                                 const std::vector<double>& z,
                                 const std::vector<double>& gx,
                                 const std::vector<double>& gy) {
    const std::size_t n = x.size();
    std::vector<double> out(gx.size() * gy.size(), kNaN);
    for (std::size_t i = 0; i < gy.size(); ++i) {
        for (std::size_t j = 0; j < gx.size(); ++j) {
            std::size_t best = 0;
            double best_d = std::numeric_limits<double>::infinity();
            for (std::size_t s = 0; s < n; ++s) {
                const double dx = gx[j] - x[s];
                const double dy = gy[i] - y[s];
                const double d2 = dx * dx + dy * dy;
                if (d2 < best_d) {
                    best_d = d2;
                    best = s;
                }
            }
            out[i * gx.size() + j] = z[best];
        }
    }
    return out;
}

std::vector<double> linear_grid(const Delaunay& d,
                                const std::vector<double>& z,
                                const std::vector<double>& gx,
                                const std::vector<double>& gy) {
    std::vector<double> out(gx.size() * gy.size(), kNaN);
    int start = 0;
    double c[3];
    for (std::size_t i = 0; i < gy.size(); ++i) {
        for (std::size_t j = 0; j < gx.size(); ++j) {
            const int t = find_simplex(d, gx[j], gy[i], start);
            if (t < 0) continue;
            barycentric(d.transforms[t], gx[j], gy[i], c);
            const auto& tri = d.tris[t];
            double v = 0.0;
            for (int k = 0; k < 3; ++k) v += c[k] * z[d.orig[tri[k]]];
            out[i * gx.size() + j] = v;
        }
    }
    return out;
}

// _estimate_gradients_2d_global: global least-squares curvature
// minimization, Gauss-Seidel sweeps (maxiter=400, tol=1e-6). Sequential
// accumulation order preserved; vertex-neighbour order follows triangle
// discovery order (qhull setlist order may differ — ~ulp effect).
std::vector<std::array<double, 2>> estimate_gradients(
    const Delaunay& d, const std::vector<double>& z) {
    const std::size_t n = d.x.size();
    std::vector<std::vector<int>> vnn(n);
    for (const auto& t : d.tris) {
        for (int k = 0; k < 3; ++k) {
            const int v = t[k];
            const int a = t[(k + 1) % 3], b = t[(k + 2) % 3];
            auto& list = vnn[v];
            if (std::find(list.begin(), list.end(), a) == list.end())
                list.push_back(a);
            if (std::find(list.begin(), list.end(), b) == list.end())
                list.push_back(b);
        }
    }
    std::vector<std::array<double, 2>> yv(n, {0.0, 0.0});
    constexpr double tol = 1e-6;
    for (int iter = 0; iter < 400; ++iter) {
        double err = 0.0;
        for (std::size_t i = 0; i < n; ++i) {
            double Q00 = 0.0, Q01 = 0.0, Q11 = 0.0;
            double s0 = 0.0, s1 = 0.0;
            for (const int j : vnn[i]) {
                const double ex = d.x[j] - d.x[i];
                const double ey = d.y[j] - d.y[i];
                const double L = std::hypot(ex, ey);
                const double L3 = L * L * L;
                const double f1 = z[d.orig[i]];
                const double f2 = z[d.orig[j]];
                const double df2 = -(ex * yv[j][0] + ey * yv[j][1]);
                Q00 += 4.0 * ex * ex / L3;
                Q01 += 4.0 * ex * ey / L3;
                Q11 += 4.0 * ey * ey / L3;
                s0 += (6.0 * (f1 - f2) - 2.0 * df2) * ex / L3;
                s1 += (6.0 * (f1 - f2) - 2.0 * df2) * ey / L3;
            }
            const double det = Q00 * Q11 - Q01 * Q01;
            // D3: a collinear neighbourhood makes det ~0 — dividing spreads
            // ±inf/NaN over every triangle touching the vertex (scipy raises
            // LinAlgError here and upstream falls back to nearest); keep the
            // previous estimate for the degenerate vertex instead.
            if (!std::isfinite(det) || std::fabs(det) < 1e-18) {
                continue;
            }
            const double r0 = (Q11 * s0 - Q01 * s1) / det;
            const double r1 = (-Q01 * s0 + Q00 * s1) / det;
            if (!std::isfinite(r0) || !std::isfinite(r1)) {
                continue;
            }
            double change = std::max(std::fabs(yv[i][0] + r0),
                                     std::fabs(yv[i][1] + r1));
            yv[i][0] = -r0;
            yv[i][1] = -r1;
            change /= std::max(1.0,
                               std::max(std::fabs(r0), std::fabs(r1)));
            if (change > err) err = change;
        }
        if (err < tol) break;
    }
    return yv;
}

// Per-triangle Clough-Tocher geometry: edges e12/e23/e31 plus g[k]
// (affine-invariant C1 shape parameters derived from each neighbour's
// centroid barycentric coordinates; -0.5 on hull edges).
struct CtGeom {
    double e12x, e12y, e23x, e23y, e31x, e31y;
    double g[3];
};

std::vector<CtGeom> ct_geometry(const Delaunay& d) {
    std::vector<CtGeom> out(d.tris.size());
    for (std::size_t t = 0; t < d.tris.size(); ++t) {
        const auto& tri = d.tris[t];
        CtGeom& g = out[t];
        g.e12x = d.x[tri[1]] - d.x[tri[0]];
        g.e12y = d.y[tri[1]] - d.y[tri[0]];
        g.e23x = d.x[tri[2]] - d.x[tri[1]];
        g.e23y = d.y[tri[2]] - d.y[tri[1]];
        g.e31x = d.x[tri[0]] - d.x[tri[2]];
        g.e31y = d.y[tri[0]] - d.y[tri[2]];
        for (int k = 0; k < 3; ++k) {
            const int itri = d.nbrs[t][k];
            if (itri == -1) {
                g.g[k] = -0.5;
                continue;
            }
            const auto& nt = d.tris[itri];
            const double cx =
                (d.x[nt[0]] + d.x[nt[1]] + d.x[nt[2]]) / 3.0;
            const double cy =
                (d.y[nt[0]] + d.y[nt[1]] + d.y[nt[2]]) / 3.0;
            double c[3];
            barycentric(d.transforms[t], cx, cy, c);
            if (k == 0) {
                g.g[k] = (2.0 * c[2] + c[1] - 1.0)
                         / (2.0 - 3.0 * c[2] - 3.0 * c[1]);
            } else if (k == 1) {
                g.g[k] = (2.0 * c[0] + c[2] - 1.0)
                         / (2.0 - 3.0 * c[0] - 3.0 * c[2]);
            } else {
                g.g[k] = (2.0 * c[1] + c[0] - 1.0)
                         / (2.0 - 3.0 * c[1] - 3.0 * c[0]);
            }
        }
    }
    return out;
}

// _clough_tocher_2d_single — verbatim port including the extended
// barycentric evaluation (minval shift).
double ct_eval_single(const CtGeom& g, const double f[3],
                      const double df[3][2], const double b[3]) {
    const double df12 = +(df[0][0] * g.e12x + df[0][1] * g.e12y);
    const double df21 = -(df[1][0] * g.e12x + df[1][1] * g.e12y);
    const double df23 = +(df[1][0] * g.e23x + df[1][1] * g.e23y);
    const double df32 = -(df[2][0] * g.e23x + df[2][1] * g.e23y);
    const double df31 = +(df[2][0] * g.e31x + df[2][1] * g.e31y);
    const double df13 = -(df[0][0] * g.e31x + df[0][1] * g.e31y);

    const double c3000 = f[0];
    const double c2100 = (df12 + 3.0 * c3000) / 3.0;
    const double c2010 = (df13 + 3.0 * c3000) / 3.0;
    const double c0300 = f[1];
    const double c1200 = (df21 + 3.0 * c0300) / 3.0;
    const double c0210 = (df23 + 3.0 * c0300) / 3.0;
    const double c0030 = f[2];
    const double c1020 = (df31 + 3.0 * c0030) / 3.0;
    const double c0120 = (df32 + 3.0 * c0030) / 3.0;

    const double c2001 = (c2100 + c2010 + c3000) / 3.0;
    const double c0201 = (c1200 + c0300 + c0210) / 3.0;
    const double c0021 = (c1020 + c0120 + c0030) / 3.0;

    const double c0111 =
        (g.g[0] * (-c0300 + 3.0 * c0210 - 3.0 * c0120 + c0030)
         + (-c0300 + 2.0 * c0210 - c0120 + c0021 + c0201))
        / 2.0;
    const double c1011 =
        (g.g[1] * (-c0030 + 3.0 * c1020 - 3.0 * c2010 + c3000)
         + (-c0030 + 2.0 * c1020 - c2010 + c2001 + c0021))
        / 2.0;
    const double c1101 =
        (g.g[2] * (-c3000 + 3.0 * c2100 - 3.0 * c1200 + c0300)
         + (-c3000 + 2.0 * c2100 - c1200 + c2001 + c0201))
        / 2.0;

    const double c1002 = (c1101 + c1011 + c2001) / 3.0;
    const double c0102 = (c1101 + c0111 + c0201) / 3.0;
    const double c0012 = (c1011 + c0111 + c0021) / 3.0;
    const double c0003 = (c1002 + c0102 + c0012) / 3.0;

    const double minval = std::min(b[0], std::min(b[1], b[2]));
    const double b1 = b[0] - minval;
    const double b2 = b[1] - minval;
    const double b3 = b[2] - minval;
    const double b4 = 3.0 * minval;

    return b1 * b1 * b1 * c3000 + 3 * b1 * b1 * b2 * c2100
           + 3 * b1 * b1 * b3 * c2010 + 3 * b1 * b1 * b4 * c2001
           + 3 * b1 * b2 * b2 * c1200 + 6 * b1 * b2 * b4 * c1101
           + 3 * b1 * b3 * b3 * c1020 + 6 * b1 * b3 * b4 * c1011
           + 3 * b1 * b4 * b4 * c1002 + b2 * b2 * b2 * c0300
           + 3 * b2 * b2 * b3 * c0210 + 3 * b2 * b2 * b4 * c0201
           + 3 * b2 * b3 * b3 * c0120 + 6 * b2 * b3 * b4 * c0111
           + 3 * b2 * b4 * b4 * c0102 + b3 * b3 * b3 * c0030
           + 3 * b3 * b3 * b4 * c0021 + 3 * b3 * b4 * b4 * c0012
           + b4 * b4 * b4 * c0003;
}

std::vector<double> cubic_grid(const Delaunay& d,
                               const std::vector<double>& z,
                               const std::vector<double>& gx,
                               const std::vector<double>& gy) {
    const auto grad = estimate_gradients(d, z);
    const auto geom = ct_geometry(d);
    std::vector<double> out(gx.size() * gy.size(), kNaN);
    int start = 0;
    double c[3];
    for (std::size_t i = 0; i < gy.size(); ++i) {
        for (std::size_t j = 0; j < gx.size(); ++j) {
            const int t = find_simplex(d, gx[j], gy[i], start);
            if (t < 0) continue;
            barycentric(d.transforms[t], gx[j], gy[i], c);
            const auto& tri = d.tris[t];
            double f[3], df[3][2];
            for (int k = 0; k < 3; ++k) {
                f[k] = z[d.orig[tri[k]]];
                df[k][0] = grad[tri[k]][0];
                df[k][1] = grad[tri[k]][1];
            }
            out[i * gx.size() + j] = ct_eval_single(geom[t], f, df, c);
        }
    }
    return out;
}

// Gaussian elimination with partial pivoting; false on a singular pivot
// (LinAlgError equivalent).
bool solve_dense(std::vector<std::vector<double>>& a,
                 std::vector<double>& b) {
    const std::size_t n = b.size();
    for (std::size_t col = 0; col < n; ++col) {
        std::size_t piv = col;
        for (std::size_t r = col + 1; r < n; ++r) {
            if (std::fabs(a[r][col]) > std::fabs(a[piv][col])) piv = r;
        }
        if (!(std::fabs(a[piv][col]) > 0.0) || !std::isfinite(a[piv][col])) {
            return false;
        }
        if (piv != col) {
            std::swap(a[piv], a[col]);
            std::swap(b[piv], b[col]);
        }
        for (std::size_t r = col + 1; r < n; ++r) {
            const double f = a[r][col] / a[col][col];
            if (f == 0.0) continue;
            for (std::size_t k = col; k < n; ++k) {
                a[r][k] -= f * a[col][k];
            }
            b[r] -= f * b[col];
        }
    }
    for (std::size_t i = n; i-- > 0;) {
        double s = b[i];
        for (std::size_t k = i + 1; k < n; ++k) s -= a[i][k] * b[k];
        if (!(std::fabs(a[i][i]) > 0.0)) return false;
        b[i] = s / a[i][i];
    }
    return true;
}

// Rbf(function="multiquadric", smooth=0): epsilon from the nonzero
// bounding-box extents, dense solve, phi = sqrt((r/eps)^2 + 1).
std::vector<double> rbf_grid(const std::vector<double>& x,
                             const std::vector<double>& y,
                             const std::vector<double>& z,
                             const std::vector<double>& gx,
                             const std::vector<double>& gy) {
    const std::size_t n = x.size();
    const auto [xlo, xhi] = std::minmax_element(x.begin(), x.end());
    const auto [ylo, yhi] = std::minmax_element(y.begin(), y.end());
    std::vector<double> edges;
    if (*xhi - *xlo != 0.0) edges.push_back(*xhi - *xlo);
    if (*yhi - *ylo != 0.0) edges.push_back(*yhi - *ylo);
    if (edges.empty()) {
        // np.power(..., 1.0/edges.size) with edges.size == 0 -> the
        // oracle's ZeroDivisionError, which escapes the fallback handler.
        throw std::runtime_error("float division by zero");
    }
    double prod = 1.0;
    for (const double e : edges) prod *= e;
    const double epsilon =
        std::pow(prod / static_cast<double>(n),
                 1.0 / static_cast<double>(edges.size()));

    std::vector<std::vector<double>> a(n, std::vector<double>(n));
    std::vector<double> rhs(z.begin(), z.end());
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = i; j < n; ++j) {
            const double dx = x[i] - x[j];
            const double dy = y[i] - y[j];
            const double r = std::sqrt(dx * dx + dy * dy) / epsilon;
            const double v = std::sqrt(r * r + 1.0);
            a[i][j] = v;
            a[j][i] = v;
        }
    }
    if (!solve_dense(a, rhs)) {
        throw ScipyEngineError("singular RBF system");
    }
    const std::vector<double>& nodes = rhs;
    std::vector<double> out(gx.size() * gy.size(), kNaN);
    for (std::size_t i = 0; i < gy.size(); ++i) {
        for (std::size_t j = 0; j < gx.size(); ++j) {
            double v = 0.0;
            for (std::size_t s = 0; s < n; ++s) {
                const double dx = gx[j] - x[s];
                const double dy = gy[i] - y[s];
                const double r = std::sqrt(dx * dx + dy * dy) / epsilon;
                v += std::sqrt(r * r + 1.0) * nodes[s];
            }
            out[i * gx.size() + j] = v;
        }
    }
    return out;
}

}  // namespace

ScipyGridResult interpolate_scipy_grid(
    const std::vector<double>& xs, const std::vector<double>& ys,
    const std::vector<double>& zs, const std::vector<double>& grid_x,
    const std::vector<double>& grid_y, const std::string& method,
    bool mask_convex_hull) {
    const FilteredSamples s = filter_nan_samples(xs, ys, zs);
    ScipyGridResult result;
    const std::size_t cells = grid_x.size() * grid_y.size();
    if (s.z.size() < 3) {
        result.grid_z.assign(cells, kNaN);
        return result;
    }
    if (method != "linear" && method != "cubic" && method != "nearest"
        && method != "rbf") {
        throw std::invalid_argument("unsupported interpolation method '"
                                    + method + "'");
    }

    std::vector<double>& grid = result.grid_z;
    try {
        if (method == "rbf") {
            grid = rbf_grid(s.x, s.y, s.z, grid_x, grid_y);
        } else if (method == "nearest") {
            grid = nearest_grid(s.x, s.y, s.z, grid_x, grid_y);
        } else {
            const Delaunay d = delaunay(s.x, s.y);
            if (method == "linear") {
                grid = linear_grid(d, s.z, grid_x, grid_y);
            } else {
                grid = cubic_grid(d, s.z, grid_x, grid_y);
            }
        }
    } catch (const ScipyEngineError&) {
        result.fallback = "nearest";
        result.requested_method = method;
        try {
            grid = nearest_grid(s.x, s.y, s.z, grid_x, grid_y);
        } catch (...) {
            grid.assign(cells, kNaN);
        }
    }

    if (mask_convex_hull) {
        // ConvexHull failure (collinear sets) skips masking, matching
        // the oracle's except-QhullError pass.
        try {
            const std::vector<int> hull =
                convex_hull_vertices(s.x, s.y);
            if (hull.size() >= 3) {
                for (std::size_t i = 0; i < grid_y.size(); ++i) {
                    for (std::size_t j = 0; j < grid_x.size(); ++j) {
                        if (!point_in_hull(hull, s.x, s.y, grid_x[j],
                                           grid_y[i])) {
                            grid[i * grid_x.size() + j] = kNaN;
                        }
                    }
                }
            }
        } catch (...) {
            // mirror the oracle: masking is best-effort
        }
    }
    return result;
}

}  // namespace pwb::mapping
