#include <pwb/mapping/polygonization.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <utility>

namespace pwb::mapping {
namespace {

// math.isclose(a, b, rel_tol=1e-9, abs_tol=abs_tol)
bool is_close_abs(double a, double b, double abs_tol) {
    return std::fabs(a - b)
        <= std::max(1e-9 * std::max(std::fabs(a), std::fabs(b)), abs_tol);
}

Point pt_key(const Point& p) {
    return {std::round(p[0] * 1e6) / 1e6, std::round(p[1] * 1e6) / 1e6};
}

// Insertion-ordered key map: Python dict semantics. Walk order is NOT the
// std::map iteration order — callers iterate insertion `order` or look up
// by key and then walk the neighbor list in append order.
struct OrderedKeys {
    std::vector<Point> order;
    std::map<Point, std::size_t> index;
    std::size_t slot(const Point& key) {
        const auto it = index.find(key);
        if (it != index.end()) return it->second;
        const std::size_t slot_id = order.size();
        order.push_back(key);
        index.emplace(key, slot_id);
        return slot_id;
    }
};

struct Neighbor {
    Point pt;
    std::size_t edge_id;
};

struct BBox {
    double xmin = 0.0;
    double ymin = 0.0;
    double xmax = 0.0;
    double ymax = 0.0;
};

BBox ring_bbox(const Ring& ring) {
    BBox b{
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
    };
    for (const Point& p : ring) {
        b.xmin = std::min(b.xmin, p[0]);
        b.ymin = std::min(b.ymin, p[1]);
        b.xmax = std::max(b.xmax, p[0]);
        b.ymax = std::max(b.ymax, p[1]);
    }
    return b;
}

// Even-odd ray-cast; same predicate as geometry_planar._ray_crosses /
// _hole_vertex_votes (XOR parity, horizontal edges do not straddle).
bool point_in_ring(double x, double y, const Ring& ring) {
    const std::size_t count = ring.size();
    bool crosses = false;
    for (std::size_t index = 0; index < count; ++index) {
        const double x1 = ring[index][0];
        const double y1 = ring[index][1];
        const double x2 = ring[(index + 1) % count][0];
        const double y2 = ring[(index + 1) % count][1];
        if (y1 == y2) continue;
        if ((y1 > y) != (y2 > y)) {
            const double t = (y - y1) / (y2 - y1);
            if (x < x1 + t * (x2 - x1)) crosses = !crosses;
        }
    }
    return crosses;
}

int hole_vertex_votes(const Ring& hole_open, const Ring& exterior) {
    int votes = 0;
    for (const Point& p : hole_open) {
        if (point_in_ring(p[0], p[1], exterior)) ++votes;
    }
    return votes;
}

void assign_holes_to_exteriors(std::vector<Polygon>& groups,
                               const std::vector<Ring>& holes,
                               PolygonizeQc& qc) {
    std::vector<BBox> ext_bbox;
    ext_bbox.reserve(groups.size());
    for (const Polygon& g : groups) ext_bbox.push_back(ring_bbox(g.exterior));

    for (const Ring& hole : holes) {
        if (hole.size() < 2) continue;
        const Ring hopen(hole.begin(), hole.end() - 1);
        const BBox hb = ring_bbox(hopen);
        int best_idx = -1;
        int best_votes = 0;
        for (std::size_t g_idx = 0; g_idx < groups.size(); ++g_idx) {
            const BBox& e = ext_bbox[g_idx];
            if (hb.xmax < e.xmin || hb.xmin > e.xmax || hb.ymax < e.ymin
                || hb.ymin > e.ymax) {
                continue;
            }
            const int votes = hole_vertex_votes(hopen, groups[g_idx].exterior);
            if (votes > best_votes) {
                best_votes = votes;
                best_idx = static_cast<int>(g_idx);
            }
        }
        if (best_idx >= 0 && best_votes > 0) {
            groups[static_cast<std::size_t>(best_idx)].holes.push_back(hole);
        } else {
            Ring promoted(hole.rbegin(), hole.rend());
            ext_bbox.push_back(ring_bbox(promoted));
            groups.push_back(Polygon{std::move(promoted), {}});
            qc.holes_promoted_to_exterior += 1;
        }
    }
}

std::array<double, 4> axis_extent(const Grid& grid) {
    // FactorGridResult.extent: (min(x), min(y), max(x), max(y)).
    if (grid.grid_x.empty() || grid.grid_y.empty()) {
        return {0.0, 0.0, 0.0, 0.0};
    }
    const auto xh = std::minmax_element(grid.grid_x.begin(), grid.grid_x.end());
    const auto yh = std::minmax_element(grid.grid_y.begin(), grid.grid_y.end());
    return {*xh.first, *yh.first, *xh.second, *yh.second};
}

double numpy_median(std::vector<double> values) {
    if (values.empty()) return 0.0;
    std::sort(values.begin(), values.end());
    const std::size_t n = values.size();
    if (n % 2 == 1) return values[n / 2];
    return 0.5 * (values[n / 2 - 1] + values[n / 2]);
}

Grid grid_from_factor(const FactorGrid& g) {
    Grid out;
    out.grid_x = g.grid_x;
    out.grid_y = g.grid_y;
    out.w = g.grid_x.size();
    out.h = g.grid_y.size();
    out.grid_z.resize(out.w * out.h, std::numeric_limits<double>::quiet_NaN());
    const std::size_t n = std::min(out.grid_z.size(), g.grid_z.size());
    for (std::size_t i = 0; i < n; ++i) {
        out.grid_z[i] = static_cast<double>(g.grid_z[i]);
    }
    return out;
}

}  // namespace

double signed_area(const Ring& ring) {
    const std::size_t n = ring.size();
    if (n < 3) return 0.0;
    double area2 = 0.0;
    for (std::size_t i = 0; i + 1 < n; ++i) {
        area2 += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
    }
    return 0.5 * area2;
}

double shoelace_area(const Ring& ring) {
    return std::fabs(signed_area(ring));
}

Point ring_centroid(const Ring& ring) {
    const std::size_t n = ring.size();
    if (n == 0) return {0.0, 0.0};
    double area2 = 0.0;
    double cx = 0.0;
    double cy = 0.0;
    for (std::size_t i = 0; i + 1 < n; ++i) {
        const double cross =
            ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
        area2 += cross;
        cx += (ring[i][0] + ring[i + 1][0]) * cross;
        cy += (ring[i][1] + ring[i + 1][1]) * cross;
    }
    if (is_close_abs(area2, 0.0, 1e-12)) {
        return {ring[0][0], ring[0][1]};
    }
    return {cx / (3.0 * area2), cy / (3.0 * area2)};
}

Ring simplify_collinear_ring(const Ring& ring) {
    if (ring.size() <= 4) return ring;
    const Ring pts(ring.begin(), ring.end() - 1);
    const std::size_t n = pts.size();
    Ring keep;
    keep.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        const Point& p_prev = pts[(i + n - 1) % n];
        const Point& p_curr = pts[i];
        const Point& p_next = pts[(i + 1) % n];
        const double dx1 = p_curr[0] - p_prev[0];
        const double dy1 = p_curr[1] - p_prev[1];
        const double dx2 = p_next[0] - p_curr[0];
        const double dy2 = p_next[1] - p_curr[1];
        const bool is_collinear =
            (is_close_abs(dy1, 0.0, 1e-9) && is_close_abs(dy2, 0.0, 1e-9)
             && dx1 * dx2 > 0.0)
            || (is_close_abs(dx1, 0.0, 1e-9) && is_close_abs(dx2, 0.0, 1e-9)
                && dy1 * dy2 > 0.0);
        if (!is_collinear) keep.push_back(p_curr);
    }
    if (keep.size() >= 3) {
        keep.push_back(keep.front());
        return keep;
    }
    return ring;
}

std::vector<double> default_class_thresholds(double vmin, double vmax) {
    if (is_close(vmin, vmax)) return {vmin};
    const double span = vmax - vmin;
    return {vmin + span * 0.333, vmin + span * 0.666};
}

std::vector<double> unique_sorted_thresholds(
    const std::vector<double>& thresholds) {
    std::vector<double> out = thresholds;
    std::sort(out.begin(), out.end());
    out.erase(std::unique(out.begin(), out.end()), out.end());
    return out;
}

std::vector<std::int16_t> classify_grid(const Grid& grid,
                                        const std::vector<double>& thresholds,
                                        int n_classes) {
    const std::size_t w = grid.w ? grid.w : grid.grid_x.size();
    const std::size_t h = grid.h ? grid.h : grid.grid_y.size();
    std::vector<std::int16_t> out(h * w, 0);
    const int cap = std::max(0, n_classes - 1);
    const std::size_t n = std::min(out.size(), grid.grid_z.size());
    for (std::size_t idx = 0; idx < thresholds.size(); ++idx) {
        const double th = thresholds[idx];
        const auto cls = static_cast<std::int16_t>(
            std::min(static_cast<int>(idx) + 1, cap));
        for (std::size_t at = 0; at < n; ++at) {
            if (grid.grid_z[at] >= th) out[at] = cls;
        }
    }
    return out;
}

std::pair<std::vector<Polygon>, PolygonizeQc>
polygonize_class(const Grid& grid,
                 const std::vector<std::int16_t>& class_grid,
                 int target_class) {
    PolygonizeQc qc;
    const std::size_t w = grid.w ? grid.w : grid.grid_x.size();
    const std::size_t h = grid.h ? grid.h : grid.grid_y.size();
    if (w == 0 || h == 0 || class_grid.size() != h * w
        || grid.grid_z.size() < h * w) {
        return {{}, qc};
    }

    const auto extent = axis_extent(grid);
    const double xmin = extent[0];
    const double ymin = extent[1];
    const double xmax = extent[2];
    const double ymax = extent[3];
    const double dx = (xmax - xmin) / static_cast<double>(std::max<std::size_t>(1, w));
    const double dy = (ymax - ymin) / static_cast<double>(std::max<std::size_t>(1, h));

    auto in_mask = [&](std::size_t i, std::size_t j) {
        const std::size_t at = i * w + j;
        return class_grid[at] == static_cast<std::int16_t>(target_class)
               && std::isfinite(grid.grid_z[at]);
    };

    bool any = false;
    for (std::size_t at = 0; at < h * w; ++at) {
        if (class_grid[at] == static_cast<std::int16_t>(target_class)
            && std::isfinite(grid.grid_z[at])) {
            any = true;
            break;
        }
    }
    if (!any) return {{}, qc};

    std::vector<std::pair<Point, Point>> segments;
    for (std::size_t i = 0; i < h; ++i) {
        const double y0 = ymin + static_cast<double>(i) * dy;
        const double y1 = ymin + static_cast<double>(i + 1) * dy;
        for (std::size_t j = 0; j < w; ++j) {
            if (!in_mask(i, j)) continue;
            const double x0 = xmin + static_cast<double>(j) * dx;
            const double x1 = xmin + static_cast<double>(j + 1) * dx;
            if (i == 0 || !in_mask(i - 1, j)) {
                segments.push_back({{x0, y0}, {x1, y0}});
            }
            if (j + 1 == w || !in_mask(i, j + 1)) {
                segments.push_back({{x1, y0}, {x1, y1}});
            }
            if (i + 1 == h || !in_mask(i + 1, j)) {
                segments.push_back({{x1, y1}, {x0, y1}});
            }
            if (j == 0 || !in_mask(i, j - 1)) {
                segments.push_back({{x0, y1}, {x0, y0}});
            }
        }
    }
    if (segments.empty()) return {{}, qc};

    OrderedKeys keys;
    std::vector<std::vector<Neighbor>> adjacency;
    std::vector<char> edges_used(segments.size(), 0);

    for (std::size_t edge_id = 0; edge_id < segments.size(); ++edge_id) {
        const Point pA = segments[edge_id].first;
        const Point pB = segments[edge_id].second;
        const Point kA = pt_key(pA);
        const Point kB = pt_key(pB);
        if (kA == kB) continue;
        const std::size_t sa = keys.slot(kA);
        adjacency.resize(keys.order.size());
        adjacency[sa].push_back({pB, edge_id});
    }

    std::vector<Ring> loops;
    for (std::size_t edge_id = 0; edge_id < segments.size(); ++edge_id) {
        if (edges_used[edge_id]) continue;
        const Point pA = segments[edge_id].first;
        const Point pB = segments[edge_id].second;
        const Point kA = pt_key(pA);
        Ring chain{pA, pB};
        edges_used[edge_id] = 1;
        Point curr_k = pt_key(pB);
        while (true) {
            const auto it = keys.index.find(curr_k);
            if (it == keys.index.end()) break;
            const Neighbor* chosen = nullptr;
            for (const Neighbor& n : adjacency[it->second]) {
                if (!edges_used[n.edge_id]) {
                    chosen = &n;
                    break;
                }
            }
            if (chosen == nullptr) break;
            edges_used[chosen->edge_id] = 1;
            chain.push_back(chosen->pt);
            curr_k = pt_key(chosen->pt);
            if (curr_k == kA) break;
        }
        if (chain.size() >= 4
            && is_close_abs(chain.front()[0], chain.back()[0], 1e-5)
            && is_close_abs(chain.front()[1], chain.back()[1], 1e-5)) {
            Ring simplified = simplify_collinear_ring(chain);
            if (simplified.size() >= 4) loops.push_back(std::move(simplified));
        }
    }
    if (loops.empty()) return {{}, qc};

    std::vector<Ring> exteriors;
    std::vector<Ring> holes;
    for (Ring& loop : loops) {
        const double signed_a = signed_area(loop);
        if (is_close_abs(signed_a, 0.0, 1e-12)) continue;
        if (signed_a > 0.0) exteriors.push_back(std::move(loop));
        else holes.push_back(std::move(loop));
    }

    if (exteriors.empty()) {
        for (Ring& h_loop : holes) {
            exteriors.emplace_back(h_loop.rbegin(), h_loop.rend());
        }
        holes.clear();
    }

    std::stable_sort(exteriors.begin(), exteriors.end(),
                     [](const Ring& a, const Ring& b) {
                         return shoelace_area(a) < shoelace_area(b);
                     });

    std::vector<Polygon> groups;
    groups.reserve(exteriors.size());
    for (Ring& ext : exteriors) {
        groups.push_back(Polygon{std::move(ext), {}});
    }
    assign_holes_to_exteriors(groups, holes, qc);
    return {std::move(groups), qc};
}

std::vector<Polygon> filter_small_polygons(const std::vector<Polygon>& geoms,
                                           double min_area) {
    std::vector<Polygon> kept;
    kept.reserve(geoms.size());
    for (const Polygon& geom : geoms) {
        double area = shoelace_area(geom.exterior);
        for (const Ring& hole : geom.holes) area -= shoelace_area(hole);
        if (std::max(0.0, area) < min_area) continue;
        kept.push_back(geom);
    }
    return kept;
}

FactorPolygonizeResult polygonize_factor_grid(const Grid& grid,
                                              std::optional<double> level) {
    FactorPolygonizeResult out;
    double lvl = 0.0;
    if (level.has_value()) {
        lvl = *level;
    } else {
        std::vector<double> finite;
        finite.reserve(grid.grid_z.size());
        for (double z : grid.grid_z) {
            if (std::isfinite(z)) finite.push_back(z);
        }
        lvl = numpy_median(std::move(finite));
    }
    out.level = lvl;

    const std::size_t w = grid.w ? grid.w : grid.grid_x.size();
    const std::size_t h = grid.h ? grid.h : grid.grid_y.size();
    std::vector<std::int16_t> class_grid(h * w, 0);
    const std::size_t n = std::min(class_grid.size(), grid.grid_z.size());
    for (std::size_t at = 0; at < n; ++at) {
        if (grid.grid_z[at] >= lvl) class_grid[at] = 1;
    }
    auto traced = polygonize_class(grid, class_grid, 1);
    out.polygons = std::move(traced.first);
    out.qc = traced.second;
    return out;
}

FactorPolygonizeResult polygonize_factor_grid(const FactorGrid& grid,
                                              std::optional<double> level) {
    return polygonize_factor_grid(grid_from_factor(grid), level);
}

}  // namespace pwb::mapping
