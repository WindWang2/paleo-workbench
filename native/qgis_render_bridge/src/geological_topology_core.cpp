// geological_topology_core.cpp — planar-subdivision polygonizer (geotopo).
//
// Pipeline (RFC §2): uniform-grid noding (exact pairwise intersection with
// collinear end-point injection) → tolerance-grid node interning → undirected
// edge dedup (shared tracts collapse to one edge with merged parents) →
// iterative dangling pruning → half-edge leftmost-turn face tracing.
// Every container is a flat std::vector; no per-edge heap allocation, which
// is the premise of the 5,000-segment ≤30 ms budget (RFC §2.6).

#include "geological_topology_core.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace pwb::geotopo {
namespace {

constexpr uint32_t kRemovedEdge = UINT32_MAX;

// geotopo Ticket 3 共用的环工具：坐标 flat [x0,y0,...]。

std::vector<std::pair<double, double>> open_ring(const std::vector<double>& xy) {
    std::vector<std::pair<double, double>> ring;
    const std::size_t n = xy.size() / 2;
    ring.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        ring.emplace_back(xy[2 * i], xy[2 * i + 1]);
    }
    if (ring.size() >= 2) {
        const auto& first = ring.front();
        const auto& last = ring.back();
        if (first.first == last.first && first.second == last.second) {
            ring.pop_back();  // 已闭合：规范为开链
        }
    }
    return ring;
}

double chain_length(const std::vector<std::pair<double, double>>& chain) {
    double total = 0.0;
    for (std::size_t i = 0; i + 1 < chain.size(); ++i) {
        total += std::hypot(chain[i + 1].first - chain[i].first,
                            chain[i + 1].second - chain[i].second);
    }
    return total;
}

// 线段真相交检测（容差版）：共享端点的相邻段不算。
bool segments_properly_cross(double ax, double ay, double bx, double by,
                             double cx, double cy, double dx, double dy,
                             double eps) {
    const double d1x = bx - ax, d1y = by - ay;
    const double d2x = dx - cx, d2y = dy - cy;
    const double denom = d1x * d2y - d1y * d2x;
    const double len1 = std::hypot(d1x, d1y);
    const double len2 = std::hypot(d2x, d2y);
    if (len1 <= eps || len2 <= eps) return false;
    if (std::fabs(denom) <= eps * len1 * len2) return false;  // 平行/共线
    const double t = ((cx - ax) * d2y - (cy - ay) * d2x) / denom;
    const double u = ((cx - ax) * d1y - (cy - ay) * d1x) / denom;
    return t > eps / len1 && t < 1.0 - eps / len1
        && u > eps / len2 && u < 1.0 - eps / len2;
}

// 环自交（重复顶点捏合 或 非相邻段真相交）。
bool ring_self_crosses(const std::vector<std::pair<double, double>>& ring,
                       double eps) {
    const std::size_t n = ring.size();
    if (n < 4) return false;  // 三角形不可能自交
    {
        // 顶点捏合：同一位置出现两次（曲线回折触碰自身）即环非法。
        std::vector<std::size_t> order(n);
        for (std::size_t i = 0; i < n; ++i) order[i] = i;
        std::sort(order.begin(), order.end(), [&](std::size_t l, std::size_t r) {
            if (ring[l].first != ring[r].first) return ring[l].first < ring[r].first;
            if (ring[l].second != ring[r].second) return ring[l].second < ring[r].second;
            return l < r;
        });
        for (std::size_t k = 1; k < n; ++k) {
            const auto& p = ring[order[k - 1]];
            const auto& q = ring[order[k]];
            if (std::fabs(p.first - q.first) <= eps
                && std::fabs(p.second - q.second) <= eps) {
                return true;
            }
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        const auto& a1 = ring[i];
        const auto& a2 = ring[(i + 1) % n];
        for (std::size_t j = i + 2; j < n; ++j) {
            if (i == 0 && j == n - 1) continue;  // 首尾相邻
            const auto& b1 = ring[j];
            const auto& b2 = ring[(j + 1) % n];
            if (segments_properly_cross(a1.first, a1.second, a2.first, a2.second,
                                        b1.first, b1.second, b2.first, b2.second,
                                        eps)) {
                return true;
            }
        }
    }
    return false;
}

bool rings_cross_each_other(const std::vector<std::pair<double, double>>& ra,
                            const std::vector<std::pair<double, double>>& rb,
                            double eps) {
    const std::size_t n = ra.size();
    const std::size_t m = rb.size();
    for (std::size_t i = 0; i < n; ++i) {
        const auto& a1 = ra[i];
        const auto& a2 = ra[(i + 1) % n];
        for (std::size_t j = 0; j < m; ++j) {
            const auto& b1 = rb[j];
            const auto& b2 = rb[(j + 1) % m];
            if (segments_properly_cross(a1.first, a1.second, a2.first, a2.second,
                                        b1.first, b1.second, b2.first, b2.second,
                                        eps)) {
                return true;
            }
        }
    }
    return false;
}

struct Segment {
    double ax, ay, bx, by;
    uint32_t line = 0;
};

inline double cross_z(double ax, double ay, double bx, double by) {
    return ax * by - ay * bx;
}

inline double dot_xy(double ax, double ay, double bx, double by) {
    return ax * bx + ay * by;
}

// ---------------------------------------------------------------------------
// Node interning: tolerance grid with 3×3 neighbourhood merge (RFC §2.2).
// One-pass merge (no transitive closure) by contract — see 00-decisions D1.

class NodeTable {
  public:
    explicit NodeTable(double tolerance) : tolerance_(tolerance) {}

    uint32_t intern(double x, double y) {
        const long ix = static_cast<long>(std::llround(x / tolerance_));
        const long iy = static_cast<long>(std::llround(y / tolerance_));
        for (long dy = -1; dy <= 1; ++dy) {
            for (long dx = -1; dx <= 1; ++dx) {
                const auto it = buckets_.find(cell_key(ix + dx, iy + dy));
                if (it == buckets_.end()) {
                    continue;
                }
                for (const uint32_t id : it->second) {
                    if (std::fabs(coords_[2 * id] - x) <= tolerance_ &&
                        std::fabs(coords_[2 * id + 1] - y) <= tolerance_) {
                        return id;
                    }
                }
            }
        }
        const uint32_t id = static_cast<uint32_t>(coords_.size() / 2);
        coords_.push_back(x);
        coords_.push_back(y);
        buckets_[cell_key(ix, iy)].push_back(id);
        return id;
    }

    double x(uint32_t id) const { return coords_[2 * id]; }
    double y(uint32_t id) const { return coords_[2 * id + 1]; }
    std::size_t size() const { return coords_.size() / 2; }

  private:
    static int64_t cell_key(long ix, long iy) {
        return (static_cast<int64_t>(ix) << 32) ^ static_cast<int32_t>(iy);
    }

    double tolerance_;
    std::unordered_map<int64_t, std::vector<uint32_t>> buckets_;
    std::vector<double> coords_;
};

// ---------------------------------------------------------------------------
// Noding: uniform grid over segment bboxes; bucket pairs are intersected once.

void node_segments(const std::vector<Segment>& segments,
                   double tolerance,
                   std::vector<std::vector<double>>& splits) {
    splits.assign(segments.size(), {});
    if (segments.size() < 2) {
        return;
    }
    double xmin = std::numeric_limits<double>::max();
    double ymin = std::numeric_limits<double>::max();
    double xmax = std::numeric_limits<double>::lowest();
    double ymax = std::numeric_limits<double>::lowest();
    for (const Segment& s : segments) {
        xmin = std::min(xmin, std::min(s.ax, s.bx));
        ymin = std::min(ymin, std::min(s.ay, s.by));
        xmax = std::max(xmax, std::max(s.ax, s.bx));
        ymax = std::max(ymax, std::max(s.ay, s.by));
    }
    const double span = std::max(xmax - xmin, ymax - ymin);
    if (!(span > 0.0) || !std::isfinite(span)) {
        return;  // degenerate extent: no interior intersections possible
    }
    const double cell = span / std::sqrt(static_cast<double>(segments.size()));
    const long grid_nx = std::max<long>(
        1, static_cast<long>(std::ceil((xmax - xmin) / cell)));
    const long grid_ny = std::max<long>(
        1, static_cast<long>(std::ceil((ymax - ymin) / cell)));

    std::unordered_map<int64_t, std::vector<uint32_t>> buckets;
    buckets.reserve(segments.size() * 2);
    for (uint32_t i = 0; i < segments.size(); ++i) {
        const Segment& s = segments[i];
        const long ix0 = std::clamp<long>(
            static_cast<long>(std::floor((std::min(s.ax, s.bx) - xmin) / cell)), 0, grid_nx - 1);
        const long ix1 = std::clamp<long>(
            static_cast<long>(std::floor((std::max(s.ax, s.bx) - xmin) / cell)), 0, grid_nx - 1);
        const long iy0 = std::clamp<long>(
            static_cast<long>(std::floor((std::min(s.ay, s.by) - ymin) / cell)), 0, grid_ny - 1);
        const long iy1 = std::clamp<long>(
            static_cast<long>(std::floor((std::max(s.ay, s.by) - ymin) / cell)), 0, grid_ny - 1);
        for (long iy = iy0; iy <= iy1; ++iy) {
            for (long ix = ix0; ix <= ix1; ++ix) {
                buckets[(static_cast<int64_t>(ix) << 32) ^ static_cast<int32_t>(iy)]
                    .push_back(i);
            }
        }
    }

    std::unordered_set<uint64_t> seen_pairs;
    seen_pairs.reserve(segments.size() * 4);
    for (const auto& entry : buckets) {
        const std::vector<uint32_t>& members = entry.second;
        for (std::size_t a = 0; a < members.size(); ++a) {
            for (std::size_t b = a + 1; b < members.size(); ++b) {
                const uint32_t i = std::min(members[a], members[b]);
                const uint32_t j = std::max(members[a], members[b]);
                if (!seen_pairs.insert((static_cast<uint64_t>(i) << 32) | j).second) {
                    continue;
                }
                const Segment& si = segments[i];
                const Segment& sj = segments[j];
                const double d1x = si.bx - si.ax, d1y = si.by - si.ay;
                const double d2x = sj.bx - sj.ax, d2y = sj.by - sj.ay;
                const double len1 = std::hypot(d1x, d1y);
                const double len2 = std::hypot(d2x, d2y);
                if (len1 <= 0.0 || len2 <= 0.0) {
                    continue;
                }
                const double eps_t1 = tolerance / len1;
                const double eps_t2 = tolerance / len2;
                const double denom = cross_z(d1x, d1y, d2x, d2y);
                if (std::fabs(denom) <= tolerance * len1 * len2) {
                    // Parallel: only collinear overlaps inject endpoints.
                    const double acx = sj.ax - si.ax, acy = sj.ay - si.ay;
                    if (std::fabs(cross_z(acx, acy, d1x, d1y)) > tolerance * len1) {
                        continue;
                    }
                    const double len1_sq = len1 * len1;
                    const double len2_sq = len2 * len2;
                    // sj's endpoints on si's parameter axis.
                    for (const double t : {dot_xy(acx, acy, d1x, d1y) / len1_sq,
                                           dot_xy(sj.bx - si.ax, sj.by - si.ay, d1x, d1y) / len1_sq}) {
                        if (t > eps_t1 && t < 1.0 - eps_t1) {
                            splits[i].push_back(t);
                        }
                    }
                    // si's endpoints on sj's parameter axis.
                    for (const double u : {dot_xy(-acx, -acy, d2x, d2y) / len2_sq,
                                           dot_xy(si.bx - sj.ax, si.by - sj.ay, d2x, d2y) / len2_sq}) {
                        if (u > eps_t2 && u < 1.0 - eps_t2) {
                            splits[j].push_back(u);
                        }
                    }
                    continue;
                }
                const double t = cross_z(sj.ax - si.ax, sj.ay - si.ay, d2x, d2y) / denom;
                const double u = cross_z(sj.ax - si.ax, sj.ay - si.ay, d1x, d1y) / denom;
                // Per-segment split: a T-junction (endpoint of one on the
                // interior of the other) must still split the host segment;
                // a shared endpoint splits neither.
                const bool t_on_segment = t >= -eps_t1 && t <= 1.0 + eps_t1;
                const bool u_on_segment = u >= -eps_t2 && u <= 1.0 + eps_t2;
                if (t_on_segment && u_on_segment) {
                    if (t > eps_t1 && t < 1.0 - eps_t1) {
                        splits[i].push_back(t);
                    }
                    if (u > eps_t2 && u < 1.0 - eps_t2) {
                        splits[j].push_back(u);
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// DCEL primitives.

struct UndirectedEdge {
    uint32_t a, b;  // a < b
    std::vector<uint32_t> lines;
};

struct HalfEdge {
    uint32_t origin;
    uint32_t twin;
};

double shoelace_area(const std::vector<std::pair<double, double>>& ring) {
    double sum = 0.0;
    for (std::size_t i = 0; i < ring.size(); ++i) {
        const auto& p = ring[i];
        const auto& q = ring[(i + 1) % ring.size()];
        sum += p.first * q.second - q.first * p.second;
    }
    return sum / 2.0;
}

// Iteratively removes edges touching a degree-1 node (dead-end tips, until a
// fixpoint).  Removed edges are flagged with a == kRemovedEdge, then dropped.
std::size_t prune_dangling(std::vector<UndirectedEdge>& edges,
                           std::vector<uint32_t>& degree) {
    std::size_t dropped = 0;
    bool changed = true;
    while (changed) {
        changed = false;
        for (UndirectedEdge& edge : edges) {
            if (edge.a == kRemovedEdge) {
                continue;
            }
            if (degree[edge.a] <= 1 || degree[edge.b] <= 1) {
                --degree[edge.a];
                --degree[edge.b];
                edge.a = kRemovedEdge;
                ++dropped;
                changed = true;
            }
        }
    }
    std::vector<UndirectedEdge> kept;
    kept.reserve(edges.size());
    for (UndirectedEdge& edge : edges) {
        if (edge.a != kRemovedEdge) {
            kept.push_back(std::move(edge));
        }
    }
    edges = std::move(kept);
    return dropped;
}

}  // namespace

PolygonizeResult polygonize_control_lines(
    const std::vector<ControlLineInput>& lines,
    const PolygonizeOptions& options) {
    const auto started = std::chrono::steady_clock::now();
    PolygonizeResult result;
    const auto finish = [&result, started]() -> PolygonizeResult {
        result.elapsed_ms = std::chrono::duration<double, std::milli>(
                                std::chrono::steady_clock::now() - started)
                                .count();
        return result;
    };

    if (!(options.tolerance > 0.0) || !std::isfinite(options.tolerance)) {
        result.error = ErrorCode::InvalidTolerance;
        result.message = "tolerance must be positive";
        return finish();
    }
    std::vector<Segment> segments;
    for (std::size_t li = 0; li < lines.size(); ++li) {
        const ControlLineInput& line = lines[li];
        if (line.xy.size() < 4 || line.xy.size() % 2 != 0) {
            result.error = ErrorCode::InvalidInput;
            result.message = "line '" + line.id + "' needs >= 2 2D vertices";
            return finish();
        }
        for (std::size_t k = 0; k + 1 < line.xy.size() / 2; ++k) {
            Segment seg{line.xy[2 * k], line.xy[2 * k + 1],
                        line.xy[2 * k + 2], line.xy[2 * k + 3],
                        static_cast<uint32_t>(li)};
            if (!std::isfinite(seg.ax) || !std::isfinite(seg.ay) ||
                !std::isfinite(seg.bx) || !std::isfinite(seg.by)) {
                result.error = ErrorCode::InvalidInput;
                result.message = "line '" + line.id + "' has a non-finite vertex";
                return finish();
            }
            segments.push_back(seg);
        }
    }

    // 1) Noding: exact pairwise intersection on grid-bucketed candidates.
    std::vector<std::vector<double>> splits;
    node_segments(segments, options.tolerance, splits);

    // 2) Sub-segment materialization with tolerance node interning.
    NodeTable nodes(options.tolerance);
    std::vector<UndirectedEdge> edges;
    edges.reserve(segments.size() * 2);
    for (std::size_t i = 0; i < segments.size(); ++i) {
        const Segment& seg = segments[i];
        std::vector<double>& params = splits[i];
        std::sort(params.begin(), params.end());
        params.erase(std::unique(params.begin(), params.end()), params.end());
        uint32_t prev = nodes.intern(seg.ax, seg.ay);
        for (const double t : params) {
            const uint32_t next = nodes.intern(
                seg.ax + t * (seg.bx - seg.ax), seg.ay + t * (seg.by - seg.ay));
            if (next != prev) {
                edges.push_back({std::min(prev, next), std::max(prev, next), {seg.line}});
                prev = next;
            }
        }
        const uint32_t last = nodes.intern(seg.bx, seg.by);
        if (last != prev) {
            edges.push_back({std::min(prev, last), std::max(prev, last), {seg.line}});
        }
    }

    // 3) Deduplicate undirected edges (collinear shared tracts merge parents).
    std::sort(edges.begin(), edges.end(), [](const UndirectedEdge& l, const UndirectedEdge& r) {
        if (l.a != r.a) return l.a < r.a;
        return l.b < r.b;
    });
    std::vector<UndirectedEdge> unique_edges;
    unique_edges.reserve(edges.size());
    for (UndirectedEdge& edge : edges) {
        if (!unique_edges.empty() && unique_edges.back().a == edge.a &&
            unique_edges.back().b == edge.b) {
            for (const uint32_t line : edge.lines) {
                if (std::find(unique_edges.back().lines.begin(),
                              unique_edges.back().lines.end(),
                              line) == unique_edges.back().lines.end()) {
                    unique_edges.back().lines.push_back(line);
                }
            }
        } else {
            unique_edges.push_back(std::move(edge));
        }
    }
    result.node_count = nodes.size();

    // 4) Dangling pruning (dead-end tips cannot bound faces).
    std::vector<uint32_t> degree(nodes.size(), 0);
    for (const UndirectedEdge& edge : unique_edges) {
        ++degree[edge.a];
        ++degree[edge.b];
    }
    result.dropped_dangles = prune_dangling(unique_edges, degree);
    result.edge_count = unique_edges.size();
    if (unique_edges.empty()) {
        return finish();
    }

    // 5) Half-edges with per-node CCW angle order.
    std::vector<HalfEdge> half_edges(unique_edges.size() * 2);
    for (std::size_t e = 0; e < unique_edges.size(); ++e) {
        half_edges[2 * e] = {unique_edges[e].a, static_cast<uint32_t>(2 * e + 1)};
        half_edges[2 * e + 1] = {unique_edges[e].b, static_cast<uint32_t>(2 * e)};
    }
    std::vector<std::vector<uint32_t>> outgoing(nodes.size());
    for (uint32_t h = 0; h < half_edges.size(); ++h) {
        outgoing[half_edges[h].origin].push_back(h);
    }
    std::vector<uint32_t> position(half_edges.size(), 0);
    for (uint32_t v = 0; v < static_cast<uint32_t>(outgoing.size()); ++v) {
        std::sort(outgoing[v].begin(), outgoing[v].end(),
                  [&](uint32_t lhs, uint32_t rhs) {
                      const double la = std::atan2(
                          nodes.y(half_edges[half_edges[lhs].twin].origin) - nodes.y(v),
                          nodes.x(half_edges[half_edges[lhs].twin].origin) - nodes.x(v));
                      const double ra = std::atan2(
                          nodes.y(half_edges[half_edges[rhs].twin].origin) - nodes.y(v),
                          nodes.x(half_edges[half_edges[rhs].twin].origin) - nodes.x(v));
                      if (la != ra) return la < ra;
                      return lhs < rhs;
                  });
        for (std::size_t k = 0; k < outgoing[v].size(); ++k) {
            position[outgoing[v][k]] = static_cast<uint32_t>(k);
        }
    }

    // 6) Leftmost-turn face tracing: successor(he) = CCW predecessor of
    // twin(he) among the destination node's outgoing edges.  Rings with a
    // positive signed area are bounded faces; non-positive rings are the
    // unbounded face (or hole rings — see 04-known-limitations §5).
    std::vector<char> visited(half_edges.size(), 0);
    for (uint32_t start = 0; start < half_edges.size(); ++start) {
        if (visited[start]) {
            continue;
        }
        std::vector<uint32_t> ring_he;
        std::vector<std::pair<double, double>> ring;
        uint32_t he = start;
        do {
            visited[he] = 1;
            ring_he.push_back(he);
            const HalfEdge& h = half_edges[he];
            ring.emplace_back(nodes.x(h.origin), nodes.y(h.origin));
            const uint32_t twin = h.twin;
            const uint32_t v = half_edges[twin].origin;  // destination of he
            const std::vector<uint32_t>& out = outgoing[v];
            const uint32_t pos = position[twin];
            he = out[(pos + out.size() - 1) % out.size()];
            if (ring_he.size() > half_edges.size()) {
                break;  // defensive: cannot happen on a deduplicated graph
            }
        } while (he != start);
        const double signed_area = shoelace_area(ring);
        if (signed_area <= 0.0 || ring_he.size() > half_edges.size()) {
            continue;
        }
        PolygonFace face;
        face.area = signed_area;
        double cx = 0.0, cy = 0.0;
        for (const auto& p : ring) {
            face.exterior_xy.push_back(p.first);
            face.exterior_xy.push_back(p.second);
            cx += p.first;
            cy += p.second;
        }
        face.exterior_xy.push_back(ring.front().first);
        face.exterior_xy.push_back(ring.front().second);
        face.centroid_x = cx / static_cast<double>(ring.size());
        face.centroid_y = cy / static_cast<double>(ring.size());
        std::vector<uint32_t> parents;
        for (const uint32_t h : ring_he) {
            for (const uint32_t line : unique_edges[h / 2].lines) {
                if (std::find(parents.begin(), parents.end(), line) == parents.end()) {
                    parents.push_back(line);
                }
            }
        }
        for (const uint32_t line : parents) {
            face.source_lines.push_back(lines[line].id);
        }
        if (face.area < options.min_ring_area) {
            continue;
        }
        if (options.has_clip) {
            bool inside = true;
            for (std::size_t k = 0; k + 1 < face.exterior_xy.size(); k += 2) {
                const double x = face.exterior_xy[k];
                const double y = face.exterior_xy[k + 1];
                if (x < options.clip_xmin || x > options.clip_xmax ||
                    y < options.clip_ymin || y > options.clip_ymax) {
                    inside = false;
                    break;
                }
            }
            if (!inside) {
                continue;
            }
        }
        result.faces.push_back(std::move(face));
    }
    return finish();
}

std::string polygonize_result_to_json(const PolygonizeResult& result) {
    auto escape = [](const std::string& value) {
        std::string out;
        out.reserve(value.size() + 8);
        for (const char c : value) {
            switch (c) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (static_cast<unsigned char>(c) < 0x20) {
                        char buf[8];
                        std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                        out += buf;
                    } else {
                        out += c;
                    }
            }
        }
        return out;
    };
    char buf[64];
    std::string json = "{\"status\":\"";
    if (result.error == ErrorCode::Ok) {
        json += "ok\",\"dropped_dangles\":";
        std::snprintf(buf, sizeof(buf), "%zu", result.dropped_dangles);
        json += buf;
        json += ",\"node_count\":";
        std::snprintf(buf, sizeof(buf), "%zu", result.node_count);
        json += buf;
        json += ",\"edge_count\":";
        std::snprintf(buf, sizeof(buf), "%zu", result.edge_count);
        json += buf;
        json += ",\"elapsed_ms\":";
        std::snprintf(buf, sizeof(buf), "%.3f", result.elapsed_ms);
        json += buf;
        json += ",\"polygons\":[";
        for (std::size_t i = 0; i < result.faces.size(); ++i) {
            const PolygonFace& face = result.faces[i];
            if (i) json += ",";
            json += "{\"geometry\":{\"type\":\"Polygon\",\"coordinates\":[[";
            for (std::size_t k = 0; k + 1 < face.exterior_xy.size(); k += 2) {
                if (k) json += ",";
                std::snprintf(buf, sizeof(buf), "[%.17g,%.17g]",
                              face.exterior_xy[k], face.exterior_xy[k + 1]);
                json += buf;
            }
            json += "]]},\"area\":";
            std::snprintf(buf, sizeof(buf), "%.17g", face.area);
            json += buf;
            json += ",\"centroid\":[";
            std::snprintf(buf, sizeof(buf), "%.17g,%.17g", face.centroid_x, face.centroid_y);
            json += buf;
            json += "],\"source_lines\":[";
            for (std::size_t s = 0; s < face.source_lines.size(); ++s) {
                if (s) json += ",";
                json += "\"" + escape(face.source_lines[s]) + "\"";
            }
            json += "],\"ring_closed\":true}";
        }
        json += "]}";
    } else {
        json += "error\",\"code\":\"";
        json += error_code_string(result.error);
        json += "\",\"message\":\"" + escape(result.message) + "\"}";
    }
    return json;
}

SharedArcsResult find_shared_arcs(const std::vector<double>& ring_a_xy,
                                  const std::vector<double>& ring_b_xy,
                                  double tolerance) {
    SharedArcsResult result;
    if (!(tolerance > 0.0) || !std::isfinite(tolerance)) {
        result.error = ErrorCode::InvalidTolerance;
        result.message = "tolerance must be positive";
        return result;
    }
    const auto ring_a = open_ring(ring_a_xy);
    const auto ring_b = open_ring(ring_b_xy);
    if (ring_a.size() < 3 || ring_b.size() < 3) {
        result.error = ErrorCode::InvalidInput;
        result.message = "rings need at least 3 distinct vertices";
        return result;
    }
    NodeTable nodes(tolerance);
    const std::size_t n = ring_a.size();
    const std::size_t m = ring_b.size();
    std::vector<uint32_t> seq_a(n), seq_b(m);
    std::unordered_map<uint32_t, std::vector<std::size_t>> pos_b;
    for (std::size_t i = 0; i < n; ++i) {
        seq_a[i] = nodes.intern(ring_a[i].first, ring_a[i].second);
    }
    for (std::size_t j = 0; j < m; ++j) {
        seq_b[j] = nodes.intern(ring_b[j].first, ring_b[j].second);
        pos_b[seq_b[j]].push_back(j);
    }

    auto id_a = [&](std::size_t i) { return seq_a[(i + 4 * n) % n]; };
    auto id_b = [&](std::size_t j) { return seq_b[(j + 4 * m) % m]; };

    std::vector<char> claimed(n, 0);
    std::vector<std::pair<std::size_t, std::size_t>> recorded;
    for (std::size_t i = 0; i < n; ++i) {
        if (claimed[i]) continue;
        const auto it = pos_b.find(seq_a[i]);
        if (it == pos_b.end() || it->second.empty()) continue;
        for (const std::size_t j0 : it->second) {
            for (const int dir : {1, -1}) {
                // 从 (i, j0) 沿 dir 双向扩到极大匹配链。
                std::size_t bi = i, bj = j0;
                for (std::size_t guard = 0; guard < n; ++guard) {
                    const std::size_t pi = (bi + n - 1) % n;
                    const std::size_t pj = (bj + m - dir + m) % m;
                    if (id_a(pi) != id_b(pj)) break;
                    if ((pi + 1) % n == i) break;  // 绕满整环
                    bi = pi;
                    bj = pj;
                }
                std::size_t ei = bi, ej = bj;
                for (std::size_t guard = 0; guard < n; ++guard) {
                    const std::size_t ni = (ei + 1) % n;
                    const std::size_t nj = (ej + dir + m) % m;
                    if (id_a(ni) != id_b(nj)) break;
                    if (ni == bi) break;  // 绕满整环
                    ei = ni;
                    ej = nj;
                }
                if (ei == bi) continue;  // 单点角触：不是弧
                const auto key = std::make_pair(bi, ei);
                if (std::find(recorded.begin(), recorded.end(), key) != recorded.end()) {
                    continue;
                }
                recorded.push_back(key);
                SharedArc arc;
                for (std::size_t k = bi; ; k = (k + 1) % n) {
                    arc.arc_xy.push_back(ring_a[k].first);
                    arc.arc_xy.push_back(ring_a[k].second);
                    if (k == ei) break;
                }
                arc.length = chain_length([&] {
                    std::vector<std::pair<double, double>> chain;
                    for (std::size_t k = 0; k + 1 < arc.arc_xy.size(); k += 2) {
                        chain.emplace_back(arc.arc_xy[k], arc.arc_xy[k + 1]);
                    }
                    return chain;
                }());
                arc.start_x = arc.arc_xy[0];
                arc.start_y = arc.arc_xy[1];
                arc.end_x = arc.arc_xy[arc.arc_xy.size() - 2];
                arc.end_y = arc.arc_xy[arc.arc_xy.size() - 1];
                for (std::size_t k = bi; ; k = (k + 1) % n) {
                    claimed[k] = 1;
                    if (k == ei) break;
                }
                result.arcs.push_back(std::move(arc));
                break;  // 本 j0 已出链，方向不再重复
            }
            if (claimed[i]) break;
        }
    }
    return result;
}

ReshapePairResult reshape_shared_arc(const std::vector<double>& ring_a_xy,
                                     const std::vector<double>& ring_b_xy,
                                     const std::vector<double>& arc_xy,
                                     const std::vector<double>& curve_xy,
                                     double tolerance) {
    ReshapePairResult result;
    const auto fail = [&result](ErrorCode code, const std::string& message) {
        result.error = code;
        result.message = message;
        return result;
    };
    if (!(tolerance > 0.0) || !std::isfinite(tolerance)) {
        return fail(ErrorCode::InvalidTolerance, "tolerance must be positive");
    }
    const auto ring_a = open_ring(ring_a_xy);
    const auto ring_b = open_ring(ring_b_xy);
    const auto arc = open_ring(arc_xy);
    std::vector<std::pair<double, double>> curve;
    for (std::size_t k = 0; k + 1 < curve_xy.size(); k += 2) {
        curve.emplace_back(curve_xy[k], curve_xy[k + 1]);
    }
    if (ring_a.size() < 3 || ring_b.size() < 3 || arc.size() < 2 || curve.size() < 2) {
        return fail(ErrorCode::InvalidInput, "rings/arc/curve need more vertices");
    }

    const double area_before = std::fabs(shoelace_area(ring_a))
                             + std::fabs(shoelace_area(ring_b));

    NodeTable nodes(tolerance);
    // 弧节点链（去容差内重复）。
    std::vector<uint32_t> arc_ids;
    for (const auto& point : arc) {
        const uint32_t id = nodes.intern(point.first, point.second);
        if (arc_ids.empty() || arc_ids.back() != id) arc_ids.push_back(id);
    }
    if (arc_ids.size() < 2) {
        return fail(ErrorCode::ArcNotFound, "arc degenerates under tolerance");
    }
    const std::size_t arc_len = arc_ids.size();

    // 在环内定位弧（返回旋转到弧首的环 + 匹配方向）。
    const auto locate = [&](const std::vector<std::pair<double, double>>& ring,
                            std::vector<std::pair<double, double>>& rotated,
                            int& orientation) -> bool {
        const std::size_t count = ring.size();
        std::vector<uint32_t> seq(count);
        for (std::size_t i = 0; i < count; ++i) {
            seq[i] = nodes.intern(ring[i].first, ring[i].second);
        }
        for (std::size_t i = 0; i < count; ++i) {
            for (const int dir : {1, -1}) {
                bool all = true;
                for (std::size_t k = 0; k < arc_len; ++k) {
                    const uint32_t want = dir == 1 ? arc_ids[k]
                                                   : arc_ids[arc_len - 1 - k];
                    if (seq[(i + k) % count] != want) {
                        all = false;
                        break;
                    }
                }
                if (!all) continue;
                // 校验弧两端确实是环上的"可替换段"（弧长 < 环长）。
                if (arc_len >= count) continue;
                rotated.clear();
                rotated.reserve(count);
                for (std::size_t k = 0; k < count; ++k) {
                    rotated.push_back(ring[(i + k) % count]);
                }
                orientation = dir;
                return true;
            }
        }
        return false;
    };

    std::vector<std::pair<double, double>> rotated_a, rotated_b;
    int orient_a = 0, orient_b = 0;
    if (!locate(ring_a, rotated_a, orient_a) || !locate(ring_b, rotated_b, orient_b)) {
        return fail(ErrorCode::ArcNotFound,
                    "shared arc not found within tolerance");
    }

    const auto build_ring = [&](const std::vector<std::pair<double, double>>& rotated,
                                int orientation)
        -> std::vector<std::pair<double, double>> {
        std::vector<std::pair<double, double>> fresh;
        fresh.reserve(rotated.size() + curve.size());
        // 新环 = curve（弧方向一致的次序）+ 环上弧后继段（arc_len .. end）。
        if (orientation == 1) {
            fresh.insert(fresh.end(), curve.begin(), curve.end());
        } else {
            fresh.insert(fresh.end(), curve.rbegin(), curve.rend());
        }
        for (std::size_t k = arc_len; k < rotated.size(); ++k) {
            fresh.push_back(rotated[k]);
        }
        return fresh;
    };
    const auto new_a = build_ring(rotated_a, orient_a);
    const auto new_b = build_ring(rotated_b, orient_b);

    if (ring_self_crosses(new_a, tolerance) || ring_self_crosses(new_b, tolerance)) {
        return fail(ErrorCode::RingInvalid, "reshaped ring invalid: self-intersection");
    }
    if (rings_cross_each_other(new_a, new_b, tolerance)) {
        return fail(ErrorCode::OverlapFailed, "reshaped rings overlap each other");
    }
    const double area_after = std::fabs(shoelace_area(new_a))
                            + std::fabs(shoelace_area(new_b));
    result.area_before = area_before;
    result.area_after = area_after;
    result.area_residual = std::fabs(area_after - area_before);
    if (result.area_residual > tolerance * std::max(1.0, chain_length(curve))) {
        return fail(ErrorCode::ConservationFailed,
                    "area conservation failed (residual="
                        + std::to_string(result.area_residual) + ")");
    }

    const auto emit = [](std::vector<std::pair<double, double>> ring,
                         std::vector<double>& out) {
        if (shoelace_area(ring) < 0.0) {
            std::reverse(ring.begin(), ring.end());  // OGC CCW 外环
        }
        out.clear();
        for (const auto& point : ring) {
            out.push_back(point.first);
            out.push_back(point.second);
        }
        out.push_back(ring.front().first);
        out.push_back(ring.front().second);
    };
    emit(new_a, result.polygon_a_xy);
    emit(new_b, result.polygon_b_xy);
    return result;
}

std::string shared_arcs_result_to_json(const SharedArcsResult& result) {
    char buf[64];
    std::string json = "{\"status\":\"";
    if (result.error != ErrorCode::Ok) {
        json += "error\",\"code\":\"";
        json += error_code_string(result.error);
        json += "\",\"message\":\"" + result.message + "\"}";
        return json;
    }
    json += "ok\",\"arcs\":[";
    for (std::size_t i = 0; i < result.arcs.size(); ++i) {
        if (i) json += ",";
        const SharedArc& arc = result.arcs[i];
        json += "{\"arc\":[";
        for (std::size_t k = 0; k + 1 < arc.arc_xy.size(); k += 2) {
            if (k) json += ",";
            std::snprintf(buf, sizeof(buf), "[%.17g,%.17g]",
                          arc.arc_xy[k], arc.arc_xy[k + 1]);
            json += buf;
        }
        json += "],\"length\":";
        std::snprintf(buf, sizeof(buf), "%.17g", arc.length);
        json += buf;
        json += ",\"start\":[";
        std::snprintf(buf, sizeof(buf), "%.17g,%.17g", arc.start_x, arc.start_y);
        json += buf;
        json += "],\"end\":[";
        std::snprintf(buf, sizeof(buf), "%.17g,%.17g", arc.end_x, arc.end_y);
        json += buf;
        json += "]}";
    }
    json += "]}";
    return json;
}

std::string reshape_pair_result_to_json(const ReshapePairResult& result) {
    char buf[64];
    auto ring_json = [](const std::vector<double>& xy) {
        std::string out = "[[";
        char inner[64];
        for (std::size_t k = 0; k + 1 < xy.size(); k += 2) {
            if (k) out += ",";
            std::snprintf(inner, sizeof(inner), "[%.17g,%.17g]", xy[k], xy[k + 1]);
            out += inner;
        }
        out += "]]";
        return out;
    };
    if (result.error != ErrorCode::Ok) {
        std::string json = "{\"status\":\"error\",\"code\":\"";
        json += error_code_string(result.error);
        json += "\",\"message\":\"" + result.message + "\"}";
        return json;
    }
    std::string json = "{\"status\":\"ok\",\"polygon_a\":{\"type\":\"Polygon\",\"coordinates\":";
    json += ring_json(result.polygon_a_xy);
    json += "},\"polygon_b\":{\"type\":\"Polygon\",\"coordinates\":";
    json += ring_json(result.polygon_b_xy);
    json += "},\"area_before\":";
    std::snprintf(buf, sizeof(buf), "%.17g", result.area_before);
    json += buf;
    json += ",\"area_after\":";
    std::snprintf(buf, sizeof(buf), "%.17g", result.area_after);
    json += buf;
    json += ",\"area_residual\":";
    std::snprintf(buf, sizeof(buf), "%.17g", result.area_residual);
    json += buf;
    json += "}";
    return json;
}

}  // namespace pwb::geotopo
