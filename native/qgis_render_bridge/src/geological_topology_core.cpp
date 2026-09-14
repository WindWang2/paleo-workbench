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

}  // namespace pwb::geotopo
