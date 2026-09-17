#include <pwb/mapping/contouring.hpp>

#include <algorithm>
#include <cstdint>
#include <map>
#include <unordered_map>

namespace pwb::mapping {
namespace {

double z_at(const Grid& grid, std::size_t i, std::size_t j) {
    return grid.grid_z[i * grid.w + j];
}

// Insertion-ordered key map: Python dict semantics (iteration order ==
// first-insertion order).
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

Point pt_key(const Point& p) {
    return {std::round(p[0] * 1e6) / 1e6, std::round(p[1] * 1e6) / 1e6};
}

struct Neighbor {
    Point key;
    Point pt;
    std::size_t edge_id;
};

std::vector<Polyline> stitch_segments(
    const std::vector<std::pair<Point, Point>>& segments, double simplify_tol,
    int smooth_iterations) {
    if (segments.empty()) return {};

    OrderedKeys keys;
    std::vector<std::vector<Neighbor>> adjacency;
    std::vector<bool> edges_used(segments.size(), false);

    for (std::size_t edge_id = 0; edge_id < segments.size(); ++edge_id) {
        const Point pA = segments[edge_id].first;
        const Point pB = segments[edge_id].second;
        const Point kA = pt_key(pA);
        const Point kB = pt_key(pB);
        if (kA == kB) continue;
        const std::size_t sa = keys.slot(kA);
        const std::size_t sb = keys.slot(kB);
        adjacency.resize(keys.order.size());
        adjacency[sa].push_back({kB, pB, edge_id});
        adjacency.resize(keys.order.size());
        adjacency[sb].push_back({kA, pA, edge_id});
    }

    std::vector<Polyline> polylines;

    // 1. Start from open endpoints (degree 1), in key insertion order.
    for (std::size_t start = 0; start < keys.order.size(); ++start) {
        int unused = 0;
        std::optional<std::size_t> first_edge;
        for (const Neighbor& n : adjacency[start]) {
            if (!edges_used[n.edge_id]) {
                ++unused;
                if (!first_edge.has_value()) first_edge = n.edge_id;
            }
        }
        if (unused != 1 || !first_edge.has_value()) continue;
        Polyline chain;
        Point curr_k = keys.order[start];
        const auto& first = segments[*first_edge];
        const Point first_pt = pt_key(first.first) == curr_k
            ? first.first
            : first.second;
        chain.push_back(first_pt);
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
            edges_used[chosen->edge_id] = true;
            chain.push_back(chosen->pt);
            curr_k = chosen->key;
        }
        if (chain.size() >= 2) polylines.push_back(std::move(chain));
    }

    // 2. Remaining edges form loops.
    for (std::size_t edge_id = 0; edge_id < segments.size(); ++edge_id) {
        if (edges_used[edge_id]) continue;
        const Point pA = segments[edge_id].first;
        const Point pB = segments[edge_id].second;
        const Point kA = pt_key(pA);
        const Point kB = pt_key(pB);
        if (kA == kB) continue;
        Polyline chain{pA, pB};
        edges_used[edge_id] = true;
        Point curr_k = kB;
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
            edges_used[chosen->edge_id] = true;
            chain.push_back(chosen->pt);
            curr_k = chosen->key;
            if (curr_k == kA) break;
        }
        if (chain.size() >= 2) polylines.push_back(std::move(chain));
    }

    std::vector<Polyline> processed;
    for (Polyline poly : polylines) {
        if (poly.size() < 2) continue;
        if (simplify_tol > 0.0) {
            poly = douglas_peucker(poly, simplify_tol);
        }
        if (smooth_iterations > 0 && poly.size() >= 3) {
            poly = chaikin_smooth(poly, smooth_iterations);
        }
        if (poly.size() >= 2) processed.push_back(std::move(poly));
    }
    return processed;
}

}  // namespace

double round_to(double value, int digits) {
    const double scale = std::pow(10.0, digits);
    return std::nearbyint(value * scale) / scale;   // half-to-even
}

bool is_close(double a, double b) {
    return std::fabs(a - b)
        <= 1e-9 * std::max(std::fabs(a), std::fabs(b));
}

std::vector<double> nice_contour_levels(double vmin, double vmax,
                                        int target_count) {
    if (!std::isfinite(vmin) || !std::isfinite(vmax) || is_close(vmin, vmax)) {
        return {};
    }
    const double span = vmax - vmin;
    const double raw_step = span / std::max(2, target_count);
    const double exp = std::floor(std::log10(raw_step));
    const double frac = raw_step / std::pow(10.0, exp);

    double step;
    if (frac < 1.5) {
        step = 1.0 * std::pow(10.0, exp);
    } else if (frac < 3.5) {
        step = 2.0 * std::pow(10.0, exp);
    } else if (frac < 7.5) {
        step = 5.0 * std::pow(10.0, exp);
    } else {
        step = 10.0 * std::pow(10.0, exp);
    }

    const double start = std::ceil(vmin / step) * step;
    std::vector<double> levels;
    for (double curr = start; curr <= vmax; curr += step) {
        if (curr >= vmin) levels.push_back(round_to(curr, 8));
    }
    return levels;
}

std::vector<double> quantile_contour_levels(
    const Grid& grid, const std::vector<double>& quantiles) {
    std::vector<double> finite;
    finite.reserve(grid.grid_z.size());
    for (const double v : grid.grid_z) {
        if (std::isfinite(v)) finite.push_back(v);
    }
    if (finite.size() < 2) return {};
    std::sort(finite.begin(), finite.end());
    std::vector<double> levels;
    for (double q : quantiles) {
        const double p = (q <= 1.0 ? q * 100.0 : q);
        // np.nanpercentile 'linear': rank on the sorted sample.
        const double rank = (p / 100.0) * static_cast<double>(finite.size() - 1);
        const std::size_t lo = static_cast<std::size_t>(std::floor(rank));
        const std::size_t hi = static_cast<std::size_t>(std::ceil(rank));
        const double frac = rank - static_cast<double>(lo);
        const double value =
            finite[lo] + frac * (finite[std::min(hi, finite.size() - 1)]
                                 - finite[lo]);
        levels.push_back(round_to(value, 6));
    }
    std::sort(levels.begin(), levels.end());
    levels.erase(std::unique(levels.begin(), levels.end()), levels.end());
    return levels;
}

double polyline_length(const Polyline& points) {
    double total = 0.0;
    for (std::size_t i = 0; i + 1 < points.size(); ++i) {
        total += std::hypot(points[i + 1][0] - points[i][0],
                            points[i + 1][1] - points[i][1]);
    }
    return total;
}

Polyline douglas_peucker(const Polyline& points, double tolerance) {
    if (points.size() <= 2 || tolerance <= 0.0) return points;
    const double x0 = points.front()[0];
    const double y0 = points.front()[1];
    const double x1 = points.back()[0];
    const double y1 = points.back()[1];
    const double dx = x1 - x0;
    const double dy = y1 - y0;
    const double line_len = std::hypot(dx, dy);

    double max_dist = -1.0;
    std::size_t index = 0;
    bool have_index = false;
    for (std::size_t i = 1; i + 1 < points.size(); ++i) {
        const double px = points[i][0];
        const double py = points[i][1];
        const double d = line_len < 1e-12
            ? std::hypot(px - x0, py - y0)
            : std::fabs(dy * px - dx * py + x1 * y0 - y1 * x0) / line_len;
        if (d > max_dist) {
            max_dist = d;
            index = i;
            have_index = true;
        }
    }
    if (max_dist > tolerance && have_index) {
        const Polyline left_input(points.begin(),
                                   points.begin() + static_cast<long>(index) + 1);
        const Polyline right_input(points.begin() + static_cast<long>(index),
                                   points.end());
        const Polyline left = douglas_peucker(left_input, tolerance);
        const Polyline right = douglas_peucker(right_input, tolerance);
        Polyline out = left;
        out.pop_back();
        out.insert(out.end(), right.begin(), right.end());
        return out;
    }
    return Polyline{points.front(), points.back()};
}

Polyline chaikin_smooth(const Polyline& points, int iterations) {
    if (points.size() < 3 || iterations <= 0) return points;
    Polyline curr = points;
    const bool is_closed =
        std::fabs(curr.front()[0] - curr.back()[0]) <= 1e-5
        && std::fabs(curr.front()[1] - curr.back()[1]) <= 1e-5;
    for (int iteration = 0; iteration < iterations; ++iteration) {
        Polyline smoothed;
        if (is_closed) {
            const std::size_t n = curr.size() - 1;
            for (std::size_t i = 0; i < n; ++i) {
                const Point& p0 = curr[i];
                const Point& p1 = curr[(i + 1) % n];
                smoothed.push_back({0.75 * p0[0] + 0.25 * p1[0],
                                    0.75 * p0[1] + 0.25 * p1[1]});
                smoothed.push_back({0.25 * p0[0] + 0.75 * p1[0],
                                    0.25 * p0[1] + 0.75 * p1[1]});
            }
            if (!smoothed.empty()) {
                smoothed.push_back(smoothed.front());
            }
        } else {
            smoothed.push_back(curr.front());
            for (std::size_t i = 0; i + 1 < curr.size(); ++i) {
                const Point& p0 = curr[i];
                const Point& p1 = curr[i + 1];
                smoothed.push_back({0.75 * p0[0] + 0.25 * p1[0],
                                    0.75 * p0[1] + 0.25 * p1[1]});
                smoothed.push_back({0.25 * p0[0] + 0.75 * p1[0],
                                    0.25 * p0[1] + 0.75 * p1[1]});
            }
            smoothed.push_back(curr.back());
        }
        curr = std::move(smoothed);
    }
    return curr;
}

std::vector<Polyline> marching_squares_contours(const Grid& grid, double level,
                                                double simplify_tol,
                                                int smooth_iterations) {
    if (grid.h < 2 || grid.w < 2) return {};
    std::vector<std::pair<Point, Point>> segments;
    for (std::size_t i = 0; i + 1 < grid.h; ++i) {
        const double y0 = grid.grid_y[i];
        const double y1 = grid.grid_y[i + 1];
        for (std::size_t j = 0; j + 1 < grid.w; ++j) {
            const double x0 = grid.grid_x[j];
            const double x1 = grid.grid_x[j + 1];
            const double z00 = z_at(grid, i, j);
            const double z10 = z_at(grid, i, j + 1);
            const double z11 = z_at(grid, i + 1, j + 1);
            const double z01 = z_at(grid, i + 1, j);

            if (!(std::isfinite(z00) && std::isfinite(z10)
                  && std::isfinite(z11) && std::isfinite(z01))) {
                continue;
            }
            const double min_z = std::min(std::min(z00, z10),
                                          std::min(z11, z01));
            const double max_z = std::max(std::max(z00, z10),
                                          std::max(z11, z01));
            if (level < min_z || level > max_z) continue;

            const int b0 = z00 >= level ? 1 : 0;
            const int b1 = z10 >= level ? 1 : 0;
            const int b2 = z11 >= level ? 1 : 0;
            const int b3 = z01 >= level ? 1 : 0;
            const int case_idx = b0 | (b1 << 1) | (b2 << 2) | (b3 << 3);
            if (case_idx == 0 || case_idx == 15) continue;

            const double t0 = !is_close(z10, z00)
                ? (level - z00) / (z10 - z00) : 0.5;
            const Point p0{x0 + t0 * (x1 - x0), y0};
            const double t1 = !is_close(z11, z10)
                ? (level - z10) / (z11 - z10) : 0.5;
            const Point p1{x1, y0 + t1 * (y1 - y0)};
            const double t2 = !is_close(z11, z01)
                ? (level - z01) / (z11 - z01) : 0.5;
            const Point p2{x0 + t2 * (x1 - x0), y1};
            const double t3 = !is_close(z01, z00)
                ? (level - z00) / (z01 - z00) : 0.5;
            const Point p3{x0, y0 + t3 * (y1 - y0)};

            const double v_center = (z00 + z10 + z11 + z01) / 4.0;

            switch (case_idx) {
                case 1: case 14: segments.push_back({p3, p0}); break;
                case 2: case 13: segments.push_back({p0, p1}); break;
                case 3: case 12: segments.push_back({p3, p1}); break;
                case 4: case 11: segments.push_back({p1, p2}); break;
                case 5:
                    if (v_center >= level) {
                        segments.push_back({p3, p2});
                        segments.push_back({p0, p1});
                    } else {
                        segments.push_back({p3, p0});
                        segments.push_back({p1, p2});
                    }
                    break;
                case 6: case 9: segments.push_back({p0, p2}); break;
                case 7: case 8: segments.push_back({p2, p3}); break;
                case 10:
                    if (v_center >= level) {
                        segments.push_back({p3, p0});
                        segments.push_back({p1, p2});
                    } else {
                        segments.push_back({p0, p1});
                        segments.push_back({p2, p3});
                    }
                    break;
                default: break;
            }
        }
    }
    if (segments.empty()) return {};
    return stitch_segments(segments, simplify_tol, smooth_iterations);
}

}  // namespace pwb::mapping
