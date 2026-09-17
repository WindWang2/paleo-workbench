#include <pwb/mapping/ring_ops.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <utility>

namespace pwb::mapping {
namespace {

bool same_point(const Point& a, const Point& b) {
    return a[0] == b[0] && a[1] == b[1];
}

// geometry_planar._ray_crosses predicate (even-odd; horizontal edges never
// straddle) — one ring, no holes.
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

// point_in_polygon_scalar semantics for one part: inside the exterior and
// not inside any of its holes.
bool point_in_part(const Point& p, const PolygonPart& part) {
    if (part.empty() || part[0].size() < 3) return false;
    if (!point_in_ring(p[0], p[1], part[0])) return false;
    for (std::size_t h = 1; h < part.size(); ++h) {
        if (point_in_ring(p[0], p[1], part[h])) return false;
    }
    return true;
}

Ring strip_closed(const Ring& ring) {
    Ring out = ring;
    if (out.size() >= 2 && same_point(out.front(), out.back())) out.pop_back();
    return out;
}

Ring closed_ring(const Ring& open) {
    Ring out = open;
    if (!out.empty() && !same_point(out.front(), out.back())) {
        out.push_back(out.front());
    }
    return out;
}

double turn_area(const Ring& open) {
    return signed_area(closed_ring(open));
}

enum class SegX { none, proper, touch, collinear_overlap };

// Classify the intersection of segments p1->p2 and q1->q2.  'proper' is a
// transversal crossing at strictly interior parameters of both segments;
// every on-segment endpoint contact is 'touch'.  Zero-length segments must
// be rejected by the caller (division by the dominant direction axis below).
SegX classify_seg(const Point& p1, const Point& p2, const Point& q1,
                  const Point& q2, double& t_out, double& u_out) {
    const double rx = p2[0] - p1[0];
    const double ry = p2[1] - p1[1];
    const double sx = q2[0] - q1[0];
    const double sy = q2[1] - q1[1];
    const double denom = rx * sy - ry * sx;
    const double qpx = q1[0] - p1[0];
    const double qpy = q1[1] - p1[1];
    const double qp_x_s = qpx * sy - qpy * sx;
    if (denom == 0.0) {
        if (qp_x_s != 0.0) return SegX::none;  // parallel, not collinear
        double t2, t3;
        if (std::fabs(rx) >= std::fabs(ry)) {
            t2 = (q1[0] - p1[0]) / rx;
            t3 = (q2[0] - p1[0]) / rx;
        } else {
            t2 = (q1[1] - p1[1]) / ry;
            t3 = (q2[1] - p1[1]) / ry;
        }
        const double lo = std::min(t2, t3);
        const double hi = std::max(t2, t3);
        if (hi < 0.0 || lo > 1.0) return SegX::none;
        return SegX::collinear_overlap;
    }
    const double t = qp_x_s / denom;
    const double u = (qpx * ry - qpy * rx) / denom;
    if (t > 0.0 && t < 1.0 && u > 0.0 && u < 1.0) {
        t_out = t;
        u_out = u;
        return SegX::proper;
    }
    if (t >= 0.0 && t <= 1.0 && u >= 0.0 && u <= 1.0) return SegX::touch;
    return SegX::none;
}

struct RingStatus {
    bool degenerate = false;  // <3 vertices, repeated vertex, spike, ~zero area
    bool touching = false;    // non-adjacent on-segment contact / collinear overlap
    int proper_crossings = 0;
    std::size_t cross_i = 0;  // the single crossing: edges (i, j), i < j,
    std::size_t cross_j = 0;  // crossing at parameter t of edge i
    double cross_t = 0.0;
    Point cross_pt{0.0, 0.0};
};

// Self-status of one open ring.  Adjacent same-direction collinear vertices
// stay simple (GEOS keeps them); a reversal spike and any non-adjacent
// contact do not.
RingStatus ring_status(const Ring& open) {
    RingStatus st;
    const std::size_t n = open.size();
    if (n < 3) {
        st.degenerate = true;
        return st;
    }
    for (std::size_t i = 0; i < n; ++i) {
        if (same_point(open[i], open[(i + 1) % n])) {
            st.degenerate = true;
            return st;
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        const Point& a = open[i];
        const Point& b = open[(i + 1) % n];
        const Point& c = open[(i + 2) % n];
        const double turn =
            (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
        const double dot =
            (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]);
        if (turn == 0.0 && dot < 0.0) {
            st.degenerate = true;  // spike: reverses along the same line
            return st;
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = i + 2; j < n; ++j) {
            if (i == 0 && j == n - 1) continue;  // adjacent through the wrap
            double t = 0.0;
            double u = 0.0;
            const SegX x =
                classify_seg(open[i], open[(i + 1) % n], open[j],
                             open[(j + 1) % n], t, u);
            if (x == SegX::proper) {
                st.proper_crossings += 1;
                st.cross_i = i;
                st.cross_j = j;
                st.cross_t = t;
                st.cross_pt = {
                    open[i][0] + t * (open[(i + 1) % n][0] - open[i][0]),
                    open[i][1] + t * (open[(i + 1) % n][1] - open[i][1])};
            } else if (x != SegX::none) {
                st.touching = true;
                return st;
            }
        }
    }
    // Net signed area cancels across self-crossing lobes (a bowtie sums to
    // ~0), so the zero-area test only means "degenerate" on a simple ring.
    if (st.proper_crossings == 0 && std::fabs(turn_area(open)) <= 1e-12) {
        st.degenerate = true;
        return st;
    }
    return st;
}

// Self-status of an OPEN polyline (no wrap adjacency): GEOS nodes a
// self-crossing line at the crossing, so self-intersecting lines must stay
// outside the clip contract.
RingStatus line_status(const Ring& open_line) {
    RingStatus st;
    const std::size_t segs = open_line.size() >= 2 ? open_line.size() - 1 : 0;
    for (std::size_t i = 0; i < segs; ++i) {
        for (std::size_t j = i + 2; j < segs; ++j) {
            double t = 0.0;
            double u = 0.0;
            const SegX x = classify_seg(open_line[i], open_line[i + 1],
                                        open_line[j], open_line[j + 1], t, u);
            if (x == SegX::proper) {
                st.proper_crossings += 1;
            } else if (x != SegX::none) {
                st.touching = true;
                return st;
            }
        }
    }
    return st;
}

// Bounded GeoJSON-polygon validity: every ring simple, holes strictly inside
// the exterior, distinct rings without any contact.  Sufficient for
// is_valid == True on the contract class.
bool part_valid(const PolygonPart& open_rings) {
    if (open_rings.empty()) return false;
    for (const Ring& ring : open_rings) {
        const RingStatus st = ring_status(ring);
        if (st.degenerate || st.touching || st.proper_crossings != 0) return false;
    }
    for (std::size_t h = 1; h < open_rings.size(); ++h) {
        if (!point_in_ring(open_rings[h][0][0], open_rings[h][0][1],
                           open_rings[0])) {
            return false;  // hole not strictly inside the exterior
        }
        for (std::size_t k = h + 1; k < open_rings.size(); ++k) {
            if (point_in_ring(open_rings[h][0][0], open_rings[h][0][1],
                              open_rings[k])
                || point_in_ring(open_rings[k][0][0], open_rings[k][0][1],
                                 open_rings[h])) {
                return false;  // nested or overlapping holes
            }
        }
    }
    for (std::size_t a = 0; a < open_rings.size(); ++a) {
        for (std::size_t b = a + 1; b < open_rings.size(); ++b) {
            const Ring& ra = open_rings[a];
            const Ring& rb = open_rings[b];
            for (std::size_t i = 0; i < ra.size(); ++i) {
                for (std::size_t j = 0; j < rb.size(); ++j) {
                    double t = 0.0;
                    double u = 0.0;
                    if (classify_seg(ra[i], ra[(i + 1) % ra.size()], rb[j],
                                     rb[(j + 1) % rb.size()], t, u)
                        != SegX::none) {
                        return false;
                    }
                }
            }
        }
    }
    return true;
}

// orient(sign=1.0): exterior CCW, holes CW; rings closed.
Polygon make_polygon(Ring exterior_open, std::vector<Ring> holes_open) {
    Polygon poly;
    poly.exterior = closed_ring(exterior_open);
    if (signed_area(poly.exterior) < 0.0) {
        poly.exterior = Ring(poly.exterior.rbegin(), poly.exterior.rend());
    }
    for (Ring& hole : holes_open) {
        Ring closed_hole = closed_ring(hole);
        if (signed_area(closed_hole) > 0.0) {
            closed_hole = Ring(closed_hole.rbegin(), closed_hole.rend());
        }
        poly.holes.push_back(std::move(closed_hole));
    }
    return poly;
}

Polygon orient_part(const PolygonPart& open_rings) {
    std::vector<Ring> holes(open_rings.begin() + 1, open_rings.end());
    return make_polygon(open_rings[0], std::move(holes));
}

// True when no ring of any part touches, crosses or contains any ring of
// another part (MultiPolygon validity inside the bounded contract).
bool parts_pairwise_disjoint(const std::vector<PolygonPart>& parts) {
    for (std::size_t a = 0; a < parts.size(); ++a) {
        for (std::size_t b = a + 1; b < parts.size(); ++b) {
            if (point_in_part(parts[a][0][0], parts[b])
                || point_in_part(parts[b][0][0], parts[a])) {
                return false;
            }
            for (const Ring& ra : parts[a]) {
                for (const Ring& rb : parts[b]) {
                    for (std::size_t i = 0; i < ra.size(); ++i) {
                        for (std::size_t j = 0; j < rb.size(); ++j) {
                            double t = 0.0;
                            double u = 0.0;
                            if (classify_seg(ra[i], ra[(i + 1) % ra.size()],
                                             rb[j], rb[(j + 1) % rb.size()],
                                             t, u) != SegX::none) {
                                return false;
                            }
                        }
                    }
                }
            }
        }
    }
    return true;
}

struct Crossing {
    std::size_t seg = 0;  // segment index on this boundary
    double t = 0.0;       // parameter on that segment
    int node = -1;        // shared crossing index (one per crossing event)
};

struct PairCrossings {
    std::vector<Crossing> a;  // on ring A
    std::vector<Crossing> b;  // on ring B
    std::string unsupported;  // non-empty on touch / collinear overlap
};

// Transversal crossings between two open rings; each event shares one node
// id across both boundaries.  Any touch or collinear overlap is outside the
// bounded contract.
PairCrossings ring_crossings(const Ring& a_open, const Ring& b_open,
                             int& node_counter) {
    PairCrossings out;
    const std::size_t na = a_open.size();
    const std::size_t nb = b_open.size();
    for (std::size_t i = 0; i < na; ++i) {
        std::vector<Crossing> on_seg;
        for (std::size_t k = 0; k < nb; ++k) {
            double t = 0.0;
            double u = 0.0;
            const SegX x = classify_seg(a_open[i], a_open[(i + 1) % na],
                                        b_open[k], b_open[(k + 1) % nb], t, u);
            if (x == SegX::touch) {
                out.unsupported =
                    "vertex-on-edge contact between the two boundaries";
                return out;
            }
            if (x == SegX::collinear_overlap) {
                out.unsupported = "collinear overlapping edges";
                return out;
            }
            if (x != SegX::proper) continue;
            Crossing ca;
            ca.seg = i;
            ca.t = t;
            ca.node = node_counter;
            on_seg.push_back(ca);
            Crossing cb;
            cb.seg = k;
            cb.t = u;
            cb.node = node_counter;
            out.b.push_back(cb);
            ++node_counter;
        }
        std::sort(on_seg.begin(), on_seg.end(),
                  [](const Crossing& l, const Crossing& r) { return l.t < r.t; });
        for (const Crossing& c : on_seg) out.a.push_back(c);
    }
    return out;
}

struct Arc {
    std::vector<Point> pts;  // includes both endpoint nodes
    int node_a = -1;         // crossing index at pts.front(); -1 = uncut ring
    int node_b = -1;         // crossing index at pts.back()
    bool from_subject = false;
    bool kept = false;
};

// Point at half the cumulative length — a representative strictly interior
// sample for the side classification (arcs never touch the other boundary).
Point arc_midpoint(const std::vector<Point>& pts) {
    double total = 0.0;
    for (std::size_t i = 0; i + 1 < pts.size(); ++i) {
        total += std::hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
    }
    double half = total / 2.0;
    for (std::size_t i = 0; i + 1 < pts.size(); ++i) {
        const double len =
            std::hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
        if (i + 2 == pts.size() || half <= len) {
            const double f = len == 0.0 ? 0.0 : half / len;
            return {pts[i][0] + f * (pts[i + 1][0] - pts[i][0]),
                    pts[i][1] + f * (pts[i + 1][1] - pts[i][1])};
        }
        half -= len;
    }
    return pts.front();
}

// Split one open boundary at its (seg, t)-sorted crossings.  With no
// crossings the whole boundary is one nodeless arc; with exactly one
// crossing the single arc loops back to the same node.
std::vector<Arc> split_boundary(const Ring& open,
                                std::vector<Crossing> crossings,
                                bool from_subject) {
    const std::size_t n = open.size();
    std::vector<Arc> arcs;
    std::sort(crossings.begin(), crossings.end(),
              [](const Crossing& l, const Crossing& r) {
                  return l.seg != r.seg ? l.seg < r.seg : l.t < r.t;
              });
    if (crossings.empty()) {
        Arc arc;
        arc.pts = open;
        arc.from_subject = from_subject;
        arcs.push_back(std::move(arc));
        return arcs;
    }
    const auto crossing_point = [&](const Crossing& c) {
        const Point& s = open[c.seg];
        const Point& e = open[(c.seg + 1) % n];
        return Point{s[0] + c.t * (e[0] - s[0]), s[1] + c.t * (e[1] - s[1])};
    };
    for (std::size_t c = 0; c < crossings.size(); ++c) {
        const Crossing& here = crossings[c];
        const Crossing& next = crossings[(c + 1) % crossings.size()];
        Arc arc;
        arc.node_a = here.node;
        arc.node_b = next.node;
        arc.from_subject = from_subject;
        arc.pts.push_back(crossing_point(here));
        // Number of whole segments the arc passes through, following the
        // boundary forward (the last arc wraps through the ring start).
        // pos = seg + t parametrizes the closed boundary; a wrap arc from
        // the last crossing back past position 0 increments by n.
        const double pos_a = static_cast<double>(here.seg) + here.t;
        double pos_b = static_cast<double>(next.seg) + next.t;
        if (pos_b <= pos_a) pos_b += static_cast<double>(n);
        const std::size_t steps =
            static_cast<std::size_t>(std::floor(pos_b))
            - static_cast<std::size_t>(std::floor(pos_a));
        for (std::size_t s = 0; s < steps; ++s) {
            arc.pts.push_back(open[(here.seg + 1 + s) % n]);
        }
        arc.pts.push_back(crossing_point(next));
        arcs.push_back(std::move(arc));
    }
    return arcs;
}

}  // namespace

RingOpsResult repair_bounded(const RepairInput& input) {
    RingOpsResult out;
    out.geom_type = input.is_multi ? "MultiPolygon" : "Polygon";

    // Empty geometry: shape() → valid empty → orient → mapping keeps type.
    if (input.parts.empty()
        || (input.parts.size() == 1 && input.parts[0].empty())) {
        out.status = RingOpsStatus::ok;
        return out;
    }

    // Python closure pass (Polygon only): rings with >= 3 vertices get a
    // duplicate first vertex appended when r[0] != r[-1]; others untouched.
    std::vector<PolygonPart> parts = input.parts;
    if (!input.is_multi) {
        PolygonPart fixed;
        fixed.reserve(parts[0].size());
        for (const Ring& ring : parts[0]) {
            if (ring.size() >= 3) {
                Ring r = ring;
                if (!same_point(r.front(), r.back())) r.push_back(r.front());
                fixed.push_back(std::move(r));
            } else {
                fixed.push_back(ring);
            }
        }
        parts[0] = std::move(fixed);
    }

    // Ring with fewer than 3 coordinates: LinearRing construction raises
    // inside shapely → except: pass → the geometry (closure-fixed for
    // Polygon) is returned unchanged.  A ring that stays at 3 coordinates
    // after shapely's implicit closing (i.e. a closed zero-area ring) is
    // constructed fine but make_valid decomposes it to a line (GEOS
    // territory → unsupported); an unclosed 3-coordinate ring closes to a
    // legal triangle and proceeds to the validity checks.
    for (const PolygonPart& rings : parts) {
        for (const Ring& ring : rings) {
            if (ring.size() < 3) {
                out.status = RingOpsStatus::ok;
                for (const PolygonPart& p : parts) {
                    Polygon poly;
                    if (!p.empty()) poly.exterior = p[0];
                    for (std::size_t h = 1; h < p.size(); ++h) {
                        poly.holes.push_back(p[h]);
                    }
                    out.polygons.push_back(std::move(poly));
                }
                return out;
            }
            if (ring.size() == 3 && same_point(ring.front(), ring.back())) {
                out.reason =
                    "degenerate zero-area ring — shapely make_valid territory";
                return out;
            }
        }
    }

    std::vector<PolygonPart> open_parts;
    open_parts.reserve(parts.size());
    bool all_valid = true;
    for (const PolygonPart& p : parts) {
        PolygonPart open_rings;
        open_rings.reserve(p.size());
        for (const Ring& ring : p) open_rings.push_back(strip_closed(ring));
        if (!part_valid(open_rings)) all_valid = false;
        open_parts.push_back(std::move(open_rings));
    }
    // Overlapping MultiPolygon parts are invalid GeoJSON; make_valid unions
    // them (GEOS territory) — outside the orient path's contract.
    if (all_valid && input.is_multi && !parts_pairwise_disjoint(open_parts)) {
        all_valid = false;
    }

    if (all_valid) {
        out.status = RingOpsStatus::ok;
        for (const PolygonPart& open_rings : open_parts) {
            out.polygons.push_back(orient_part(open_rings));
        }
        return out;
    }

    // Bounded invalid class: one Polygon, one ring, exactly one proper
    // self-crossing (a bowtie) — shapely 2.1.2 make_valid splits it into the
    // two lobes (verified against the frozen fixtures).
    if (!input.is_multi && open_parts.size() == 1 && open_parts[0].size() == 1) {
        const Ring& open = open_parts[0][0];
        const RingStatus st = ring_status(open);
        if (!st.degenerate && !st.touching && st.proper_crossings == 1) {
            const std::size_t n = open.size();
            const std::size_t i = st.cross_i;
            const std::size_t j = st.cross_j;
            Ring lobe_a{st.cross_pt};
            for (std::size_t k = i + 1; k <= j; ++k) lobe_a.push_back(open[k]);
            Ring lobe_b{st.cross_pt};
            for (std::size_t k = j + 1; k < n; ++k) lobe_b.push_back(open[k]);
            for (std::size_t k = 0; k <= i; ++k) lobe_b.push_back(open[k]);
            out.status = RingOpsStatus::ok;
            for (const Ring* lobe : {&lobe_a, &lobe_b}) {
                out.polygons.push_back(make_polygon(*lobe, {}));
            }
            out.geom_type = "MultiPolygon";
            return out;
        }
    }

    out.status = RingOpsStatus::unsupported;
    out.reason = "invalid geometry outside the shapely-free bounded contract";
    return out;
}

RingOpsResult clip_polygon_to_ring_bounded(const RingClipInput& input) {
    RingOpsResult out;
    out.geom_type = input.subject_is_multi ? "MultiPolygon" : "Polygon";

    if (input.subject.empty()
        || (input.subject.size() == 1 && input.subject[0].empty())) {
        out.status = RingOpsStatus::ok;  // empty subject ∩ ring → Python None
        out.geom_type = "";
        return out;
    }
    if (input.subject_is_multi) {
        for (const PolygonPart& p : input.subject) {
            if (p.empty()) {
                out.reason = "empty part inside a MultiPolygon subject";
                return out;
            }
        }
    }

    const Ring ring_open = strip_closed(input.clip_ring);
    const RingStatus rst = ring_status(ring_open);
    if (rst.degenerate) {
        out.reason =
            "clip ring degenerate (needs >= 3 distinct vertices, non-zero area)";
        return out;
    }
    if (rst.touching || rst.proper_crossings != 0) {
        // Python validates the ring through shapely make_valid first (GEOS).
        out.reason = "clip ring not simple — shapely make_valid territory";
        return out;
    }

    std::vector<PolygonPart> open_parts;
    for (const PolygonPart& p : input.subject) {
        PolygonPart open_rings;
        for (const Ring& ring : p) open_rings.push_back(strip_closed(ring));
        if (!part_valid(open_rings)) {
            out.reason = "subject polygon invalid outside the bounded contract";
            return out;
        }
        open_parts.push_back(std::move(open_rings));
    }
    if (input.subject_is_multi && !parts_pairwise_disjoint(open_parts)) {
        out.reason = "MultiPolygon parts are not pairwise disjoint";
        return out;
    }

    std::vector<Polygon> results;
    for (const PolygonPart& part : open_parts) {
        // Crossings between every part ring and the clip ring (shared nodes).
        std::vector<std::vector<Crossing>> sub_x_per_ring(part.size());
        std::vector<Crossing> ring_x;
        int node_counter = 0;
        bool ok = true;
        for (std::size_t r = 0; r < part.size(); ++r) {
            PairCrossings bc = ring_crossings(part[r], ring_open, node_counter);
            if (!bc.unsupported.empty()) {
                out.reason = bc.unsupported;
                ok = false;
                break;
            }
            sub_x_per_ring[r] = std::move(bc.a);
            for (Crossing& c : bc.b) ring_x.push_back(c);
        }
        if (!ok) return out;

        if (node_counter == 0) {
            // No crossings: nested or disjoint.
            if (point_in_ring(part[0][0][0], part[0][0][1], ring_open)) {
                results.push_back(orient_part(part));  // part inside the ring
            } else if (point_in_part(ring_open[0], part)) {
                results.push_back(make_polygon(ring_open, {}));  // ring inside
            }
            continue;
        }

        // Build and keep the boundary arcs of the intersection.
        std::vector<Arc> arcs;
        for (std::size_t r = 0; r < part.size(); ++r) {
            std::vector<Arc> part_arcs =
                split_boundary(part[r], sub_x_per_ring[r], true);
            for (Arc& arc : part_arcs) arcs.push_back(std::move(arc));
        }
        {
            std::vector<Arc> ring_arcs =
                split_boundary(ring_open, ring_x, false);
            for (Arc& arc : ring_arcs) arcs.push_back(std::move(arc));
        }
        for (Arc& arc : arcs) {
            const Point mid = arc_midpoint(arc.pts);
            arc.kept = arc.from_subject ? point_in_ring(mid[0], mid[1], ring_open)
                                        : point_in_part(mid, part);
        }

        // Stitch: every node has exactly one kept subject arc end and one
        // kept ring arc end (transversal crossing) → degree 2.
        struct ArcEnd {
            std::size_t arc = 0;
            bool at_a = false;
        };
        std::vector<std::vector<ArcEnd>> node_ends(
            static_cast<std::size_t>(node_counter));
        for (std::size_t a = 0; a < arcs.size(); ++a) {
            if (!arcs[a].kept) continue;
            if (arcs[a].node_a < 0) continue;  // uncut ring: standalone loop
            node_ends[static_cast<std::size_t>(arcs[a].node_a)].push_back({a, true});
            node_ends[static_cast<std::size_t>(arcs[a].node_b)].push_back({a, false});
        }
        bool stitch_ok = true;
        for (const auto& ends : node_ends) {
            if (ends.size() != 2) {
                out.reason = "stitching invariant violated (node degree != 2)";
                stitch_ok = false;
                break;
            }
        }
        if (!stitch_ok) return out;

        std::vector<char> arc_used(arcs.size(), 0);
        std::vector<Ring> loops;
        for (std::size_t first = 0; first < arcs.size(); ++first) {
            if (!arcs[first].kept || arc_used[first]) continue;
            if (arcs[first].node_a < 0) {
                loops.push_back(arcs[first].pts);  // uncut ring loop
                arc_used[first] = 1;
                continue;
            }
            Ring loop = arcs[first].pts;
            arc_used[first] = 1;
            std::size_t cur_arc = first;
            int node = arcs[first].node_b;
            const int start_node = arcs[first].node_a;
            std::size_t steps = 0;
            const std::size_t max_steps = arcs.size();
            while (node != start_node) {
                if (++steps > max_steps) {
                    out.reason = "stitching walk failed to close";
                    stitch_ok = false;
                    break;
                }
                const auto& ends = node_ends[static_cast<std::size_t>(node)];
                const ArcEnd& step =
                    (ends[0].arc == cur_arc) ? ends[1] : ends[0];
                const Arc& next_arc = arcs[step.arc];
                arc_used[step.arc] = 1;
                if (step.at_a) {
                    for (std::size_t k = 1; k < next_arc.pts.size(); ++k) {
                        loop.push_back(next_arc.pts[k]);
                    }
                } else {
                    for (std::size_t k = next_arc.pts.size() - 1; k-- > 0;) {
                        loop.push_back(next_arc.pts[k]);
                    }
                }
                node = step.at_a ? next_arc.node_b : next_arc.node_a;
                cur_arc = step.arc;
            }
            if (!stitch_ok) break;
            // The walk ends on the incoming arc's own copy of the start
            // node (the two crossing-point expressions agree to within an
            // ulp); drop it and close with the exact loop start.
            loop.pop_back();
            loops.push_back(std::move(loop));
        }
        if (!stitch_ok) return out;

        // Ring classification: depth <= 1 for simple ∩ simple.  A loop is a
        // hole iff some other loop contains it; each hole goes to its
        // smallest containing exterior.
        std::vector<std::size_t> ext_idx;
        std::vector<std::size_t> hole_idx;
        for (std::size_t l = 0; l < loops.size(); ++l) {
            bool contained = false;
            for (std::size_t m = 0; m < loops.size() && !contained; ++m) {
                if (m == l) continue;
                if (point_in_ring(loops[l][0][0], loops[l][0][1], loops[m])) {
                    contained = true;
                }
            }
            (contained ? hole_idx : ext_idx).push_back(l);
        }
        std::sort(ext_idx.begin(), ext_idx.end(), [&](std::size_t x, std::size_t y) {
            return std::fabs(turn_area(loops[x])) < std::fabs(turn_area(loops[y]));
        });
        std::vector<std::vector<Ring>> holes_of(ext_idx.size());
        for (const std::size_t h : hole_idx) {
            for (std::size_t e = 0; e < ext_idx.size(); ++e) {
                if (point_in_ring(loops[h][0][0], loops[h][0][1],
                                  loops[ext_idx[e]])) {
                    holes_of[e].push_back(loops[h]);
                    break;
                }
            }
        }
        for (std::size_t e = 0; e < ext_idx.size(); ++e) {
            results.push_back(make_polygon(loops[ext_idx[e]],
                                           std::move(holes_of[e])));
        }
    }

    out.status = RingOpsStatus::ok;
    if (results.size() == 1) out.geom_type = "Polygon";
    else if (results.size() > 1) out.geom_type = "MultiPolygon";
    else out.geom_type = "";
    out.polygons = std::move(results);
    return out;
}

PolylineClipResult clip_polyline_to_ring_bounded(const Polyline& line,
                                                 const Ring& clip_ring) {
    PolylineClipResult out;

    const Ring ring_open = strip_closed(clip_ring);
    const RingStatus rst = ring_status(ring_open);
    if (rst.degenerate) {
        out.reason =
            "clip ring degenerate (needs >= 3 distinct vertices, non-zero area)";
        return out;
    }
    if (rst.touching || rst.proper_crossings != 0) {
        out.reason = "clip ring not simple — shapely make_valid territory";
        return out;
    }
    if (line.size() < 2) {
        // Python LineString raises before any clipping happens.
        out.reason = "line needs >= 2 vertices (shapely raises ValueError)";
        return out;
    }
    for (std::size_t i = 0; i + 1 < line.size(); ++i) {
        if (same_point(line[i], line[i + 1])) {
            out.reason = "zero-length segment in the input line";
            return out;
        }
    }
    // GEOS nodes a self-crossing line at the crossing (extra pieces); the
    // bounded overlay does not — such lines stay shapely-only.
    if (line_status(line).proper_crossings != 0) {
        out.reason = "self-intersecting line — GEOS noding territory";
        return out;
    }

    // Crossings per line segment (strictly interior on both sides).
    struct LineCut {
        std::size_t seg = 0;
        double t = 0.0;
        Point pt{0.0, 0.0};
    };
    std::vector<LineCut> cuts;
    for (std::size_t i = 0; i + 1 < line.size(); ++i) {
        std::vector<LineCut> on_seg;
        for (std::size_t k = 0; k < ring_open.size(); ++k) {
            double t = 0.0;
            double u = 0.0;
            const SegX x = classify_seg(line[i], line[i + 1],
                                        ring_open[k],
                                        ring_open[(k + 1) % ring_open.size()],
                                        t, u);
            if (x == SegX::touch) {
                out.reason = "line endpoint or vertex on the clip ring edge";
                return out;
            }
            if (x == SegX::collinear_overlap) {
                out.reason = "line segment collinear with a clip ring edge";
                return out;
            }
            if (x != SegX::proper) continue;
            LineCut cut;
            cut.seg = i;
            cut.t = t;
            cut.pt = {line[i][0] + t * (line[i + 1][0] - line[i][0]),
                      line[i][1] + t * (line[i + 1][1] - line[i][1])};
            on_seg.push_back(cut);
        }
        std::sort(on_seg.begin(), on_seg.end(),
                  [](const LineCut& l, const LineCut& r) { return l.t < r.t; });
        for (const LineCut& c : on_seg) cuts.push_back(c);
    }

    // Split the line at the cuts, keeping traversal order: a piece ends at
    // every cut and the next one restarts there; whole segments between the
    // cuts contribute their vertices.
    std::vector<Polyline> pieces;
    Polyline current{line[0]};
    std::size_t cut_idx = 0;
    for (std::size_t i = 0; i + 1 < line.size(); ++i) {
        while (cut_idx < cuts.size() && cuts[cut_idx].seg == i) {
            current.push_back(cuts[cut_idx].pt);
            pieces.push_back(current);
            current = Polyline{cuts[cut_idx].pt};
            ++cut_idx;
        }
        current.push_back(line[i + 1]);
    }
    pieces.push_back(std::move(current));

    for (Polyline& piece : pieces) {
        if (piece.size() < 2) continue;
        const Point mid = arc_midpoint(piece);
        if (point_in_ring(mid[0], mid[1], ring_open)) {
            out.pieces.push_back(std::move(piece));
        }
    }
    out.status = RingOpsStatus::ok;
    return out;
}

}  // namespace pwb::mapping
