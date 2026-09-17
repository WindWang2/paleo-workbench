// mapping_kernel.ring_ops — bounded ring clip & repair vs frozen Python
// oracle (tools/oracle/generate_ring_ops_fixtures.py).  Portable cases must
// reproduce the real Python product output (repair_invalid_geometry /
// clip_polygon_to_ring / clip_polyline_to_ring, shapely 2.1.2) under the
// canonical comparison contract; shapely-only cases are skipped explicitly
// with their reason printed, and the skip count must match the fixture.

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/ring_ops.hpp>

using pwb::domain::Json;
using pwb::mapping::Point;
using pwb::mapping::Polygon;
using pwb::mapping::Polyline;
using pwb::mapping::Ring;
using pwb::mapping::RingClipInput;
using pwb::mapping::RingOpsResult;
using pwb::mapping::PolylineClipResult;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

constexpr double kCoordTol = 1e-9;

// --- canonicalization (mirrors the generator; see the fixture "note") -----

Ring strip_closed(const Ring& ring) {
    Ring out = ring;
    if (out.size() >= 2 && out.front() == out.back()) out.pop_back();
    return out;
}

double signed_area_open(const Ring& pts) {
    double total = 0.0;
    for (std::size_t i = 0; i + 1 < pts.size(); ++i) {
        total += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1];
    }
    return 0.5 * total;
}

bool point_less(const Point& a, const Point& b) {
    return a[0] != b[0] ? a[0] < b[0] : a[1] < b[1];
}

Ring canon_ring(const Ring& ring) {
    Ring pts = strip_closed(ring);
    if (pts.size() < 3) return pts;
    const auto min_at = std::min_element(pts.begin(), pts.end(), point_less);
    std::rotate(pts.begin(), min_at, pts.end());
    return pts;
}

Ring canon_ring_dir(const Ring& ring, bool want_ccw) {
    Ring pts = canon_ring(ring);
    const double sign = pts.size() >= 3 ? signed_area_open(pts) : 0.0;
    if ((want_ccw && sign < 0.0) || (!want_ccw && sign > 0.0)) {
        std::reverse(pts.begin(), pts.end());
        // Re-rotate: after a reversal the lexicographically smallest vertex
        // sits at the end, so rotate again to keep the canonical rotation.
        if (pts.size() >= 3) {
            const auto min_at =
                std::min_element(pts.begin(), pts.end(), point_less);
            std::rotate(pts.begin(), min_at, pts.end());
        }
    }
    return pts;
}

bool ring_less(const Ring& a, const Ring& b) {
    return std::lexicographical_compare(
        a.begin(), a.end(), b.begin(), b.end(),
        [](const Point& p, const Point& q) { return point_less(p, q); });
}

std::vector<Ring> canon_polygon(const std::vector<Ring>& rings) {
    std::vector<Ring> canon;
    canon.reserve(rings.size());
    for (const Ring& ring : rings) canon.push_back(canon_ring(ring));
    bool all_nonzero = !canon.empty();
    for (const Ring& r : canon) {
        const double area = r.size() >= 3 ? std::fabs(signed_area_open(r)) : 0.0;
        if (area <= 1e-12) all_nonzero = false;
    }
    if (!all_nonzero) return canon;  // degenerate ring: keep order/direction
    std::size_t ext_i = 0;
    double best = -1.0;
    for (std::size_t i = 0; i < canon.size(); ++i) {
        const double area = std::fabs(signed_area_open(canon[i]));
        if (area > best) {
            best = area;
            ext_i = i;
        }
    }
    std::vector<Ring> out;
    out.push_back(canon_ring_dir(canon[ext_i], true));
    std::vector<Ring> holes;
    for (std::size_t i = 0; i < canon.size(); ++i) {
        if (i != ext_i) holes.push_back(canon_ring_dir(canon[i], false));
    }
    std::sort(holes.begin(), holes.end(), ring_less);
    for (Ring& hole : holes) out.push_back(std::move(hole));
    return out;
}

double net_area(const std::vector<Ring>& poly) {
    if (poly.empty()) return 0.0;
    double total = poly[0].size() >= 3 ? std::fabs(signed_area_open(poly[0])) : 0.0;
    for (std::size_t h = 1; h < poly.size(); ++h) {
        total -= poly[h].size() >= 3 ? std::fabs(signed_area_open(poly[h])) : 0.0;
    }
    return total;
}

std::vector<double> flatten(const std::vector<Ring>& poly) {
    std::vector<double> out;
    for (const Ring& ring : poly) {
        for (const Point& p : ring) {
            out.push_back(p[0]);
            out.push_back(p[1]);
        }
    }
    return out;
}

std::vector<std::vector<Ring>> canon_result(
    std::vector<std::vector<Ring>> parts) {
    std::vector<std::vector<Ring>> polys;
    for (std::vector<Ring>& p : parts) {
        std::vector<Ring> canon = canon_polygon(p);
        if (!canon.empty()) polys.push_back(std::move(canon));
    }
    std::sort(polys.begin(), polys.end(),
              [](const std::vector<Ring>& a, const std::vector<Ring>& b) {
                  const double na = std::round(net_area(a) * 1e6) / 1e6;
                  const double nb = std::round(net_area(b) * 1e6) / 1e6;
                  if (na != nb) return na < nb;
                  return flatten(a) < flatten(b);
              });
    return polys;
}

Ring canon_piece(const Ring& pts) {
    Ring out = strip_closed(pts);
    if (out.size() >= 2 && point_less(out.back(), out.front())) {
        std::reverse(out.begin(), out.end());
    }
    if (out.size() >= 3) {
        const auto min_at = std::min_element(out.begin(), out.end(), point_less);
        std::rotate(out.begin(), min_at, out.end());
    }
    return out;
}

std::vector<Ring> canon_pieces(std::vector<Ring> pieces) {
    std::vector<Ring> out;
    for (Ring& piece : pieces) out.push_back(canon_piece(piece));
    std::sort(out.begin(), out.end(), ring_less);
    return out;
}

// --- comparisons -----------------------------------------------------------

bool coords_close(const Ring& a, const Ring& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (std::fabs(a[i][0] - b[i][0]) > kCoordTol
            || std::fabs(a[i][1] - b[i][1]) > kCoordTol) {
            return false;
        }
    }
    return true;
}

bool polys_close(const std::vector<Ring>& a, const std::vector<Ring>& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (!coords_close(a[i], b[i])) return false;
    }
    return true;
}

bool results_close(const std::vector<std::vector<Ring>>& a,
                   const std::vector<std::vector<Ring>>& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (!polys_close(a[i], b[i])) return false;
    }
    return true;
}

// --- fixture helpers -------------------------------------------------------

Ring json_ring(const Json& arr) {
    Ring out;
    for (const Json& p : arr) {
        out.push_back(Point{p[0].get<double>(), p[1].get<double>()});
    }
    return out;
}

std::vector<std::vector<Ring>> json_parts(const Json& arr) {
    std::vector<std::vector<Ring>> out;
    for (const Json& part : arr) {
        std::vector<Ring> rings;
        for (const Json& ring : part) rings.push_back(json_ring(ring));
        out.push_back(std::move(rings));
    }
    return out;
}

std::vector<std::vector<Ring>> parts_from(const RingOpsResult& result) {
    std::vector<std::vector<Ring>> out;
    for (const Polygon& poly : result.polygons) {
        std::vector<Ring> rings;
        rings.push_back(poly.exterior);
        for (const Ring& hole : poly.holes) rings.push_back(hole);
        out.push_back(std::move(rings));
    }
    return out;
}

}  // namespace

int main() {
    std::ifstream stream(PWB_RING_OPS_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    int ran_portable = 0;
    int skipped = 0;
    for (const Json& c : oracle["cases"]) {
        const std::string id = c["id"].get<std::string>();
        const std::string op = c["op"].get<std::string>();
        const bool portable = c["portable"].get<bool>();
        if (!portable) {
            ++skipped;
            std::printf("skip %s (%s): %s\n", id.c_str(), op.c_str(),
                        c["skip_reason"].get<std::string>().c_str());
            continue;
        }
        ++ran_portable;
        const Json& input = c["input"];
        const std::string outcome = c["python_outcome"].get<std::string>();

        if (op == "repair") {
            pwb::mapping::RepairInput in;
            in.is_multi = input["is_multi"].get<bool>();
            in.parts = json_parts(input["parts"]);
            const RingOpsResult got = pwb::mapping::repair_bounded(in);
            check(got.status == pwb::mapping::RingOpsStatus::ok,
                  id + " status");
            const std::string expected_type =
                c["expected_type"].get<std::string>();
            check(got.geom_type == expected_type,
                  id + " geom_type: " + got.geom_type + " vs " + expected_type);
            // orient(sign=1.0) direction contract, asserted on the RAW
            // output (canonicalization absorbs direction by design): on the
            // orient/bowtie paths every ring has >= 3 coordinates and
            // exteriors are CCW / holes CW.  The <3-coordinate identity
            // fallback preserves input direction — no promise there.
            bool all_rings_ge3 = !got.polygons.empty();
            for (const Polygon& poly : got.polygons) {
                if (poly.exterior.size() < 3) all_rings_ge3 = false;
                for (const Ring& hole : poly.holes) {
                    if (hole.size() < 3) all_rings_ge3 = false;
                }
            }
            if (all_rings_ge3) {
                for (const Polygon& poly : got.polygons) {
                    check(pwb::mapping::signed_area(poly.exterior) > 0.0,
                          id + " exterior CCW");
                    for (const Ring& hole : poly.holes) {
                        check(pwb::mapping::signed_area(hole) < 0.0,
                              id + " hole CW");
                    }
                }
            }
            std::vector<std::vector<Ring>> expected;
            for (const Json& poly : c["expected"]) {
                std::vector<Ring> rings;
                for (const Json& ring : poly) rings.push_back(json_ring(ring));
                expected.push_back(std::move(rings));
            }
            check(results_close(canon_result(parts_from(got)), expected),
                  id + " geometry (got polys="
                      + std::to_string(got.polygons.size()) + ", want "
                      + std::to_string(expected.size()) + ")");
        } else if (op == "clip_polygon") {
            RingClipInput in;
            in.subject_is_multi = input["is_multi"].get<bool>();
            in.subject = json_parts(input["parts"]);
            in.clip_ring = json_ring(input["ring"]);
            const RingOpsResult got =
                pwb::mapping::clip_polygon_to_ring_bounded(in);
            check(got.status == pwb::mapping::RingOpsStatus::ok,
                  id + " status");
            if (outcome == "none") {
                check(got.polygons.empty() && got.geom_type.empty(),
                      id + " expected empty (Python None)");
            } else {
                const std::string expected_type =
                    c["expected_type"].get<std::string>();
                check(got.geom_type == expected_type,
                      id + " geom_type: " + got.geom_type + " vs "
                          + expected_type);
                std::vector<std::vector<Ring>> expected;
                for (const Json& poly : c["expected"]) {
                    std::vector<Ring> rings;
                    for (const Json& ring : poly) {
                        rings.push_back(json_ring(ring));
                    }
                    expected.push_back(std::move(rings));
                }
                check(results_close(canon_result(parts_from(got)), expected),
                      id + " geometry");
            }
        } else if (op == "clip_polyline") {
            const Polyline line = json_ring(input["line"]);
            const Ring ring = json_ring(input["ring"]);
            const PolylineClipResult got =
                pwb::mapping::clip_polyline_to_ring_bounded(line, ring);
            check(got.status == pwb::mapping::RingOpsStatus::ok,
                  id + " status");
            std::vector<Ring> expected;
            for (const Json& piece : c["expected"]) {
                expected.push_back(json_ring(piece));
            }
            std::vector<Ring> got_pieces;
            for (const Polyline& piece : got.pieces) {
                got_pieces.push_back(piece);
            }
            check(polys_close(canon_pieces(std::move(got_pieces)),
                              canon_pieces(std::move(expected))),
                  id + " pieces");
        } else {
            check(false, id + " unknown op " + op);
        }
    }

    const Json& counts = oracle["counts"];
    check(ran_portable == counts["portable"].get<int>(),
          "portable count " + std::to_string(ran_portable));
    check(skipped == counts["shapely_optional"].get<int>(),
          "skip count " + std::to_string(skipped));
    std::printf("%s: %d failure(s) over %d portable + %d shapely-only cases\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, ran_portable,
                skipped);
    return g_failures == 0 ? 0 : 1;
}
