#pragma once

// pwb::mapping — bounded ring clip & closure/orientation repair kernel
// (full-conversion plan M6 follow-up slice, task cpp-conv-04).  A faithful,
// shapely-free subset of:
//   * paleo_workbench.mapping.topology.repair_invalid_geometry — the ring
//     closure dict pass, the signed-area orient pass on the valid path, and a
//     bounded single-proper-crossing self-intersection split (bowtie → two
//     lobes) that matches shapely 2.1.2 make_valid output for that class;
//   * paleo_workbench.mapping.geometry_operations.clip_polygon_to_ring /
//     clip_polyline_to_ring — boundary-arc overlay (split at transversal
//     crossings, even-odd side classification, degree-2 node stitching) for
//     simple non-degenerate inputs.
// Everything else — GEOS make_valid on arbitrary invalid geometry, robust
// overlay with vertex-on-edge / collinear-overlap degeneracies, invalid clip
// rings — returns status=unsupported with a documented reason; the frozen
// oracle (tools/oracle/generate_ring_ops_fixtures.py) classifies cases by
// INPUT shape and the C++ test skips non-portable cases explicitly.
// Canonical comparison contract (rotation-normalized rings, |area|-largest
// ring as exterior, exteriors CCW / holes CW, polylines direction-normalized,
// coordinate tolerance 1e-9) lives in the test, not in the kernel.
// Qt-free, Python-free, GEOS-free.

#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/polygonization.hpp>

#include <string>
#include <vector>

namespace pwb::mapping {

enum class RingOpsStatus {
    ok,           // computed within the bounded contract
    unsupported,  // input outside the contract; reason states the cause
};

struct RingOpsResult {
    RingOpsStatus status = RingOpsStatus::unsupported;
    std::string reason;             // C++ contract cause ("" when ok)
    std::string geom_type;          // "Polygon" | "MultiPolygon" | "" (= Python None)
    std::vector<Polygon> polygons;  // empty ⇔ Python returned None
};

struct PolylineClipResult {
    RingOpsStatus status = RingOpsStatus::unsupported;
    std::string reason;
    std::vector<Polyline> pieces;   // traversal order along the input line
};

// A polygon geometry as raw rings: one part = [exterior, holes...].
using PolygonPart = std::vector<Ring>;

// repair_invalid_geometry input: MultiPolygon flag mirrors the Python dict
// "type" (closure applies to Polygon only).
struct RepairInput {
    bool is_multi = false;
    std::vector<PolygonPart> parts;
};

// Bounded repair: closure (dict pass, incl. the <4-coordinate ValueError
// fallback identity), validity classification, orient (exterior CCW / holes
// CW, rings closed) on the valid path, single-crossing bowtie split on the
// one invalid class inside the contract, unsupported otherwise.
RingOpsResult repair_bounded(const RepairInput& input);

struct RingClipInput {
    bool subject_is_multi = false;
    std::vector<PolygonPart> subject;
    Ring clip_ring;  // user domain ring; duplicate closing vertex tolerated
};

// Bounded clip_polygon_to_ring: subject ∩ ring via boundary overlay.  Empty
// result ⇒ status ok with polygons empty (Python returns None).
RingOpsResult clip_polygon_to_ring_bounded(const RingClipInput& input);

// Bounded clip_polyline_to_ring: pieces of *line* inside *clip_ring*, in
// traversal order; empty pieces ⇔ Python returned [].
PolylineClipResult clip_polyline_to_ring_bounded(const Polyline& line,
                                                 const Ring& clip_ring);

}  // namespace pwb::mapping
