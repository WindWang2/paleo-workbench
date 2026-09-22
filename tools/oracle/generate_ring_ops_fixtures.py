#!/usr/bin/env python3
"""Oracle fixture generator for the C++ ring_ops kernel (conv-04 slice).

Imports the REAL product code —
    paleo_workbench.mapping.topology.repair_invalid_geometry
    paleo_workbench.mapping.geometry_operations.clip_polygon_to_ring
    paleo_workbench.mapping.geometry_operations.clip_polyline_to_ring
(no monkeypatching: shapely 2.1.2 runs its genuine make_valid / overlay paths)
— and freezes canonicalized outputs so the shapely-free C++ subset in
libs/mapping_kernel (ring_ops.cpp) can be verified case-exactly.

Every case is classified by INPUT SHAPE ONLY (self-intersection counting,
touch/collinear detection — the same predicates the C++ kernel implements):
  * portable=true  → the C++ kernel must reproduce the frozen output;
  * portable=false → shapely-only territory (GEOS make_valid / robust
    overlay); the C++ test skips these explicitly and prints the reason.
Classification never inspects the C++ output. Regenerate with:

    /home/kevin/projects/paleo_project/main/.venv/bin/python \\
        tools/oracle/generate_ring_ops_fixtures.py

Comparison contract (mirrored in ring_ops_test.cpp): rings are
rotation-normalized (lexicographically smallest vertex first), direction is
forced (exterior CCW / holes CW) only when every ring has non-zero area —
degenerate rings keep input order and direction; the |area|-largest ring is
the exterior; polylines are direction-normalized (reverse when first > last,
then rotate); coordinates are stored round(v, 9) and compared at 1e-9.
Fixture coordinates are integers or exact halves so degeneracy decisions are
exact in float64.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.mapping.geometry_operations import (  # noqa: E402
    clip_polygon_to_ring,
    clip_polyline_to_ring,
)
from paleo_workbench.mapping.topology import (  # noqa: E402
    repair_invalid_geometry,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)


# ---------------------------------------------------------------------------
# Input-shape classifier (mirrors ring_ops.cpp predicates; integer-exact)


def seg_x(p1, p2, q1, q2):
    """'none' | ('proper', t, u) | 'touch' | 'collinear'."""
    rx, ry = p2[0] - p1[0], p2[1] - p1[1]
    sx, sy = q2[0] - q1[0], q2[1] - q1[1]
    denom = rx * sy - ry * sx
    qpx, qpy = q1[0] - p1[0], q1[1] - p1[1]
    qp_x_s = qpx * sy - qpy * sx
    if denom == 0.0:
        if qp_x_s != 0.0:
            return ("none", 0.0, 0.0)
        if abs(rx) >= abs(ry):
            t2, t3 = (q1[0] - p1[0]) / rx, (q2[0] - p1[0]) / rx
        else:
            t2, t3 = (q1[1] - p1[1]) / ry, (q2[1] - p1[1]) / ry
        lo, hi = min(t2, t3), max(t2, t3)
        if hi < 0.0 or lo > 1.0:
            return ("none", 0.0, 0.0)
        return ("collinear", 0.0, 0.0)
    t = qp_x_s / denom
    u = (qpx * ry - qpy * rx) / denom
    if 0.0 < t < 1.0 and 0.0 < u < 1.0:
        return ("proper", t, u)
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return ("touch", t, u)
    return ("none", 0.0, 0.0)


def strip_closed(ring):
    ring = [list(p) for p in ring]
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring


def signed_area(open_ring):
    total = 0.0
    for i in range(len(open_ring) - 1):
        total += open_ring[i][0] * open_ring[i + 1][1]
        total -= open_ring[i + 1][0] * open_ring[i][1]
    return 0.5 * total


def ring_status(open_ring):
    """degenerate / touching / n_proper — same rules as ring_ops.cpp."""
    n = len(open_ring)
    if n < 3:
        return {"degenerate": True, "touching": False, "n_proper": 0}
    for i in range(n):
        if open_ring[i] == open_ring[(i + 1) % n]:
            return {"degenerate": True, "touching": False, "n_proper": 0}
    for i in range(n):
        a, b, c = open_ring[i], open_ring[(i + 1) % n], open_ring[(i + 2) % n]
        turn = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        dot = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
        if turn == 0.0 and dot < 0.0:
            return {"degenerate": True, "touching": False, "n_proper": 0}
    n_proper = 0
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            kind, _t, _u = seg_x(open_ring[i], open_ring[(i + 1) % n],
                                 open_ring[j], open_ring[(j + 1) % n])
            if kind == "proper":
                n_proper += 1
            elif kind in ("touch", "collinear"):
                return {"degenerate": False, "touching": True, "n_proper": 0}
    # Net signed area cancels across self-crossing lobes (a bowtie sums to
    # ~0), so the zero-area test only means "degenerate" on a simple ring.
    # Unclosed rings close implicitly (shapely semantics) before the test.
    if n_proper == 0 and abs(signed_area(open_ring + [open_ring[0]])) <= 1e-12:
        return {"degenerate": True, "touching": False, "n_proper": 0}
    return {"degenerate": False, "touching": False, "n_proper": n_proper}


def pip_ring(x, y, open_ring):
    crosses = False
    count = len(open_ring)
    for i in range(count):
        x1, y1 = open_ring[i]
        x2, y2 = open_ring[(i + 1) % count]
        if y1 == y2:
            continue
        if (y1 > y) != (y2 > y):
            t = (y - y1) / (y2 - y1)
            if x < x1 + t * (x2 - x1):
                crosses = not crosses
    return crosses


def pip_part(x, y, part):
    if not part or len(part[0]) < 3:
        return False
    if not pip_ring(x, y, part[0]):
        return False
    return not any(pip_ring(x, y, hole) for hole in part[1:])


def part_valid(part):
    """True iff the part is inside the shapely-free validity contract."""
    if not part:
        return False
    for ring in part:
        st = ring_status(ring)
        if st["degenerate"] or st["touching"] or st["n_proper"] != 0:
            return False
    for h in range(1, len(part)):
        if not pip_ring(part[h][0][0], part[h][0][1], part[0]):
            return False
        for k in range(h + 1, len(part)):
            if pip_ring(part[h][0][0], part[h][0][1], part[k]):
                return False
            if pip_ring(part[k][0][0], part[k][0][1], part[h]):
                return False
    for a in range(len(part)):
        for b in range(a + 1, len(part)):
            for i in range(len(part[a])):
                for j in range(len(part[b])):
                    kind, _t, _u = seg_x(part[a][i], part[a][(i + 1) % len(part[a])],
                                         part[b][j], part[b][(j + 1) % len(part[b])])
                    if kind != "none":
                        return False
    return True


def closure_pass(coords):
    """Exact topology.repair_invalid_geometry closure pass (Polygon only)."""
    fixed = []
    for ring in coords:
        if isinstance(ring, (list, tuple)) and len(ring) >= 3:
            r = [list(pt) for pt in ring]
            if r[0] != r[-1]:
                r.append(list(r[0]))
            fixed.append(r)
        else:
            fixed.append(ring)
    return fixed


# ---------------------------------------------------------------------------
# Canonicalization (mirrored in ring_ops_test.cpp)


def canon_ring(ring):
    pts = strip_closed(ring)
    if len(pts) < 3:
        return pts
    k = min(range(len(pts)), key=lambda i: (pts[i][0], pts[i][1]))
    return pts[k:] + pts[:k]


def canon_ring_dir(ring, want_ccw):
    pts = canon_ring(ring)
    sign = signed_area(pts) if len(pts) >= 3 else 0.0
    if (want_ccw and sign < 0.0) or (not want_ccw and sign > 0.0):
        pts = list(reversed(pts))
        # Re-rotate: after a reversal the lexicographically smallest vertex
        # sits at the end, so rotate again to keep the canonical rotation.
        if len(pts) >= 3:
            k = min(range(len(pts)), key=lambda i: (pts[i][0], pts[i][1]))
            pts = pts[k:] + pts[:k]
    return pts


def canon_polygon(rings):
    rings = [canon_ring(r) for r in rings]
    if not rings:
        return []
    areas = [abs(signed_area(r)) if len(r) >= 3 else 0.0 for r in rings]
    if all(a > 1e-12 for a in areas):
        ext_i = max(range(len(rings)), key=lambda i: areas[i])
        exterior = canon_ring_dir(rings[ext_i], True)
        holes = sorted(
            canon_ring_dir(r, False) for i, r in enumerate(rings) if i != ext_i
        )
        return [exterior] + holes
    return rings  # degenerate ring present: keep order and direction


def net_area(poly):
    if not poly:
        return 0.0
    total = abs(signed_area(poly[0])) if len(poly[0]) >= 3 else 0.0
    for hole in poly[1:]:
        total -= abs(signed_area(hole)) if len(hole) >= 3 else 0.0
    return total


def canon_result(parts):
    polys = [canon_polygon(p) for p in parts]
    polys = [p for p in polys if p]
    polys.sort(key=lambda p: (round(net_area(p), 6), [c for r in p for c in r]))
    return polys


def canon_piece(pts):
    pts = strip_closed(pts)
    if len(pts) >= 2 and (pts[0][0], pts[0][1]) > (pts[-1][0], pts[-1][1]):
        pts = list(reversed(pts))
    if len(pts) >= 3:
        k = min(range(len(pts)), key=lambda i: (pts[i][0], pts[i][1]))
        pts = pts[k:] + pts[:k]
    return pts


def canon_pieces(pieces):
    return sorted(canon_piece(p) for p in pieces)


def r9(points):
    if points is None:
        return None
    if points and isinstance(points[0], (int, float)):
        return [round(float(points[0]), 9), round(float(points[1]), 9)]
    return [r9(p) for p in points]


# ---------------------------------------------------------------------------
# Classification per op (input shape only)


def classify_repair(is_multi, raw_parts):
    """'portable' | reason-string, mirroring repair_bounded's contract."""
    if not raw_parts or (len(raw_parts) == 1 and not raw_parts[0]):
        return "portable"
    parts = [closure_pass(p) if not is_multi
             else [strip_closed(r) for r in p]
             for p in raw_parts]
    for rings in parts:
        for ring in rings:
            if len(ring) < 3:
                return "portable"  # ValueError → identity fallback
            # Only a ring that STAYS at 3 coordinates after shapely's
            # implicit closing (closed zero-area ring) hits make_valid→line;
            # an unclosed 3-coordinate ring closes to a legal triangle.
            if len(ring) == 3 and ring[0] == ring[-1]:
                return "degenerate zero-area ring: shapely make_valid makes a line"
    if all(part_valid([strip_closed(r) for r in rings]) for rings in parts):
        if not is_multi:
            return "portable"
        # Overlapping MultiPolygon parts are invalid; make_valid unions them
        # (GEOS territory).  Disjoint parts stay on the orient path.
        for a in range(len(parts)):
            for b in range(a + 1, len(parts)):
                va, vb = parts[a][0][0], parts[b][0][0]
                if pip_part(va[0], va[1], parts[b]) or pip_part(vb[0], vb[1], parts[a]):
                    return "MultiPolygon parts overlap: make_valid unions them"
                for ra in parts[a]:
                    for rb in parts[b]:
                        for i in range(len(ra)):
                            for j in range(len(rb)):
                                kind, _t, _u = seg_x(
                                    ra[i], ra[(i + 1) % len(ra)],
                                    rb[j], rb[(j + 1) % len(rb)])
                                if kind != "none":
                                    return ("MultiPolygon parts touch or "
                                            "cross: make_valid territory")
        return "portable"
    if not is_multi and len(parts) == 1 and len(parts[0]) == 1:
        st = ring_status(strip_closed(parts[0][0]))
        if not st["degenerate"] and not st["touching"] and st["n_proper"] == 1:
            return "portable"
    return "invalid geometry outside the shapely-free bounded contract"


def boundaries_compatible(a_rings, b_ring):
    """No touch / collinear overlap between the two boundaries."""
    for ring in a_rings:
        for i in range(len(ring)):
            for k in range(len(b_ring)):
                kind, _t, _u = seg_x(ring[i], ring[(i + 1) % len(ring)],
                                     b_ring[k], b_ring[(k + 1) % len(b_ring)])
                if kind in ("touch", "collinear"):
                    return False
    return True


def classify_clip_polygon(is_multi, raw_parts, raw_ring):
    ring_open = strip_closed(raw_ring)
    rst = ring_status(ring_open)
    if rst["degenerate"]:
        return "clip ring degenerate"
    if rst["touching"] or rst["n_proper"] != 0:
        return "clip ring not simple: shapely make_valid territory"
    parts = [[strip_closed(r) for r in p] for p in raw_parts]
    if not raw_parts or (len(raw_parts) == 1 and not raw_parts[0]):
        return "portable"
    if not all(part_valid(p) for p in parts):
        return "subject polygon invalid outside the bounded contract"
    if is_multi:
        for a in range(len(parts)):
            for b in range(a + 1, len(parts)):
                va, vb = parts[a][0][0], parts[b][0][0]
                if pip_part(va[0], va[1], parts[b]):
                    return "MultiPolygon parts overlap"
                if pip_part(vb[0], vb[1], parts[a]):
                    return "MultiPolygon parts overlap"
                for ra in parts[a]:
                    for rb in parts[b]:
                        for i in range(len(ra)):
                            for j in range(len(rb)):
                                kind, _t, _u = seg_x(ra[i], ra[(i + 1) % len(ra)],
                                                     rb[j], rb[(j + 1) % len(rb)])
                                if kind != "none":
                                    return "MultiPolygon parts touch or cross"
    for rings in parts:
        if not boundaries_compatible(rings, ring_open):
            return "vertex-on-edge or collinear contact between boundaries"
    return "portable"


def classify_clip_polyline(raw_line, raw_ring):
    ring_open = strip_closed(raw_ring)
    rst = ring_status(ring_open)
    if rst["degenerate"]:
        return "clip ring degenerate"
    if rst["touching"] or rst["n_proper"] != 0:
        return "clip ring not simple: shapely make_valid territory"
    line = strip_closed(raw_line)
    if len(line) < 2:
        return "line needs >= 2 vertices: shapely raises before any clipping"
    for i in range(len(line) - 1):
        if line[i] == line[i + 1]:
            return "zero-length segment in the input line"
    # GEOS nodes a self-crossing line at the crossing (extra pieces); the
    # bounded overlay does not.
    segs = len(line) - 1
    for i in range(segs):
        for j in range(i + 2, segs):
            kind, _t, _u = seg_x(line[i], line[i + 1], line[j], line[j + 1])
            if kind in ("proper", "touch", "collinear"):
                return "self-intersecting line: GEOS noding territory"
    return ("portable" if boundaries_compatible([line], ring_open)
            else "line/ring touch or collinear contact")


# ---------------------------------------------------------------------------
# Case runner


def _poly(is_multi, parts):
    if is_multi:
        return {"type": "MultiPolygon", "coordinates": parts}
    return {"type": "Polygon", "coordinates": parts[0] if parts else []}


def run_repair(cid, is_multi, parts):
    geom = _poly(is_multi, parts)
    verdict = classify_repair(is_multi, parts)
    try:
        out = repair_invalid_geometry(json.loads(json.dumps(geom)))
        out_type = str(out.get("type"))
        if out_type == "Polygon":
            expected_parts = [out.get("coordinates") or []]
        elif out_type == "MultiPolygon":
            expected_parts = list(out.get("coordinates") or [])
        else:
            expected_parts = None  # identity fallback to a non-polygon type
        return {
            "id": cid, "op": "repair", "portable": verdict == "portable",
            "skip_reason": "" if verdict == "portable" else verdict,
            "python_outcome": "ok", "python_error": "",
            "input": {"is_multi": is_multi, "parts": parts},
            "expected": (None if expected_parts is None
                         else r9(canon_result(expected_parts))),
            "expected_type": out_type,
        }
    except Exception as exc:  # pragma: no cover - classifier avoids these
        return {
            "id": cid, "op": "repair", "portable": False,
            "skip_reason": f"python raised: {exc}",
            "python_outcome": "error", "python_error": str(exc),
            "input": {"is_multi": is_multi, "parts": parts},
            "expected": None, "expected_type": "",
        }


def run_clip_polygon(cid, is_multi, parts, ring):
    geom = _poly(is_multi, parts)
    verdict = classify_clip_polygon(is_multi, parts, ring)
    try:
        out = clip_polygon_to_ring(json.loads(json.dumps(geom)),
                                   json.loads(json.dumps(ring)))
        if out is None:
            expected = None
            outcome = "none"
        else:
            expected_parts = ([out["coordinates"]] if out["type"] == "Polygon"
                              else list(out["coordinates"]))
            expected = r9(canon_result(expected_parts))
            outcome = "ok"
        return {
            "id": cid, "op": "clip_polygon",
            "portable": verdict == "portable",
            "skip_reason": "" if verdict == "portable" else verdict,
            "python_outcome": outcome, "python_error": "",
            "input": {"is_multi": is_multi, "parts": parts, "ring": ring},
            "expected": expected, "expected_type": "" if out is None else out["type"],
        }
    except Exception as exc:
        return {
            "id": cid, "op": "clip_polygon", "portable": False,
            "skip_reason": f"python raised: {exc}",
            "python_outcome": "error", "python_error": str(exc),
            "input": {"is_multi": is_multi, "parts": parts, "ring": ring},
            "expected": None, "expected_type": "",
        }


def run_clip_polyline(cid, line, ring):
    verdict = classify_clip_polyline(line, ring)
    try:
        out = clip_polyline_to_ring(json.loads(json.dumps(line)),
                                    json.loads(json.dumps(ring)))
        return {
            "id": cid, "op": "clip_polyline",
            "portable": verdict == "portable",
            "skip_reason": "" if verdict == "portable" else verdict,
            "python_outcome": "ok", "python_error": "",
            "input": {"line": line, "ring": ring},
            "expected": r9(canon_pieces(out)),
        }
    except Exception as exc:
        return {
            "id": cid, "op": "clip_polyline",
            "portable": False,  # the classifier missed it: Python raised
            "skip_reason": f"python raised: {exc}",
            "python_outcome": "error", "python_error": str(exc),
            "input": {"line": line, "ring": ring},
            "expected": None,
        }


# ---------------------------------------------------------------------------
# Case corpus

SQ = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]
SQ_CW = [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]
DONUT = [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    [[3, 3], [3, 7], [7, 7], [7, 3], [3, 3]],
]
DONUT_HOLE_CCW = [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]],
]
UNCLOSED_CW = [[[0, 0], [0, 4], [4, 4], [4, 0]]]
BOWTIE = [[[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]]
BOWTIE_ASYM = [[[0, 0], [6, 3], [4, 0], [0, 4], [0, 0]]]
STAR = [[[0, 0], [10, 0], [2, 8], [5, -2], [8, 8], [0, 0]]]
RING_RECT_BIG = [[-5, -5], [15, -5], [15, 15], [-5, 15], [-5, -5]]
RING_RECT_IN = [[2, 3], [8, 3], [8, 9], [2, 9], [2, 3]]
RING_RECT_OVER = [[5, 5], [15, 5], [15, 15], [5, 15], [5, 5]]
# L ring: big rectangle minus the upper-right notch (x >= 4, y >= 4); edges
# kept clear of every square vertex so no touch degeneracy.
RING_L_SHAPE = [
    [-2, -2], [14, -2], [14, 4], [4, 4], [4, 14], [-2, 14], [-2, -2]
]
# C ring: rectangle minus the notch 2 <= x <= 8, y >= 2 (capped at y=2).
# A band subject across the two arms clips into two disjoint pieces.
RING_C_SHAPE = [
    [0, 0], [10, 0], [10, 10], [8, 10], [8, 2], [2, 2], [2, 10], [0, 10],
    [0, 0]
]
BAND_ACROSS_ARMS = [[-1, 4], [11, 4], [11, 7], [-1, 7], [-1, 4]]
RING_RIGHT_HALF = [[5, -2], [20, -2], [20, 12], [5, 12], [5, -2]]
RING_DIAMOND_TOUCH = [[5, -5], [15, 5], [5, 15], [-5, 5], [5, -5]]
RING_DIAGONAL = [[2, -1], [13, 6], [11, 13], [-1, 9], [2, -1]]


def build_cases():
    cases = []
    sq_part = [SQ]           # one part: [exterior]
    sq_cw_part = [SQ_CW]
    donut_part = [DONUT]
    donut_hole_ccw_part = [DONUT_HOLE_CCW]
    bowtie_part = [BOWTIE]

    # -- repair_invalid_geometry -------------------------------------------
    cases.append(run_repair("repair_polygon_valid_unchanged", False, sq_part))
    cases.append(run_repair("repair_polygon_cw_exterior", False, sq_cw_part))
    cases.append(run_repair("repair_polygon_hole_ccw", False, donut_hole_ccw_part))
    cases.append(run_repair("repair_polygon_hole_cw", False, donut_part))
    cases.append(run_repair("repair_polygon_unclosed_cw", False, [UNCLOSED_CW]))
    cases.append(run_repair("repair_polygon_unclosed_ccw", False,
                            [[[[0, 0], [4, 0], [4, 4], [0, 4]]]]))
    cases.append(run_repair("repair_polygon_empty_coords", False, []))
    cases.append(run_repair("repair_multipolygon_empty", True, []))
    cases.append(run_repair("repair_multipolygon_mixed_orientation", True,
                            [SQ_CW,
                             [[[20, 20], [23, 20], [23, 23], [20, 23],
                               [20, 20]]]]))
    cases.append(run_repair("repair_multipolygon_unclosed", True,
                            [[[[0, 0], [2, 0], [2, 2], [0, 2]]],
                             [[[5, 5], [7, 5], [7, 7], [5, 7]]]]))
    cases.append(run_repair("repair_multipolygon_unclosed_triangle", True,
                            [[[[0, 0], [2, 0], [2, 2], [0, 2]]],
                             [[[5, 5], [6, 5], [5, 6]]]]))
    cases.append(run_repair("repair_short_ring_identity_fallback", False,
                            [[[[0, 0], [1, 0], [1, 1], [0, 1]],
                              [[5, 5], [6, 6]]]]))
    cases.append(run_repair("repair_two_vertex_ring_identity", False,
                            [[[[0, 0], [1, 0], [1, 1]]]]))
    cases.append(run_repair("repair_multipolygon_short_ring_identity", True,
                            [[[[0, 0], [2, 0], [2, 2], [0, 2]]],
                             [[[5, 5], [6, 6]]]]))
    cases.append(run_repair("repair_degenerate_three_coord_ring", False,
                            [[[[0, 0], [1, 0], [0, 0]]]]))
    cases.append(run_repair("repair_bowtie_diagonal", False, bowtie_part))
    cases.append(run_repair("repair_bowtie_asymmetric", False,
                            [[[[0, 0], [6, 3], [4, 0], [0, 4], [0, 0]]]]))
    cases.append(run_repair("repair_star_multi_crossing", False, [STAR]))
    cases.append(run_repair("repair_multipolygon_overlap_optional", True,
                            [SQ,
                             [[[5, 5], [8, 5], [8, 8], [5, 8], [5, 5]]]]))
    cases.append(run_repair("repair_hole_outside_exterior", False,
                            [[[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                              [[6, 6], [6, 8], [8, 8], [8, 6], [6, 6]]]]))
    cases.append(run_repair("repair_spike_ring", False,
                            [[[[0, 0], [4, 0], [2, 0], [0, 4], [0, 0]]]]))

    # -- clip_polygon_to_ring ----------------------------------------------
    cases.append(run_clip_polygon("clip_rect_ring_inside", False, sq_part,
                                  RING_RECT_IN))
    cases.append(run_clip_polygon("clip_rect_ring_contains", False, sq_part,
                                  RING_RECT_BIG))
    cases.append(run_clip_polygon("clip_rect_ring_overlap", False, sq_part,
                                  RING_RECT_OVER))
    cases.append(run_clip_polygon("clip_l_concave_ring", False, sq_part,
                                  RING_L_SHAPE))
    cases.append(run_clip_polygon("clip_c_ring_splits_band", False,
                                  [[BAND_ACROSS_ARMS]], RING_C_SHAPE))
    cases.append(run_clip_polygon("clip_diagonal_quad_ring", False, sq_part,
                                  RING_DIAGONAL))
    cases.append(run_clip_polygon("clip_holed_subject_right_half", False,
                                  donut_part, RING_RIGHT_HALF))
    cases.append(run_clip_polygon("clip_ring_inside_hole_empty", False,
                                  donut_part,
                                  [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]))
    cases.append(run_clip_polygon("clip_multipolygon_subject", True,
                                  [SQ,
                                   [[[20, 20], [24, 20], [24, 24], [20, 24],
                                     [20, 20]]]],
                                  RING_RIGHT_HALF))
    cases.append(run_clip_polygon("clip_multipolygon_both_kept", True,
                                  [[[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]],
                                   [[[6, 0], [10, 0], [10, 4], [6, 4], [6, 0]]]],
                                  [[-1, -1], [11, -1], [11, 5], [-1, 5], [-1, -1]]))
    cases.append(run_clip_polygon("clip_disjoint_none", False, sq_part,
                                  [[30, 30], [40, 30], [40, 40], [30, 40],
                                   [30, 30]]))
    cases.append(run_clip_polygon("clip_cw_ring_same_result", False, sq_part,
                                  [[2, 3], [2, 9], [8, 9], [8, 3], [2, 3]]))
    cases.append(run_clip_polygon("clip_vertex_on_edge", False, sq_part,
                                  RING_DIAMOND_TOUCH))
    cases.append(run_clip_polygon("clip_collinear_overlap_optional", False,
                                  sq_part,
                                  [[0, 0], [10, 0], [10, 5], [0, 5], [0, 0]]))
    cases.append(run_clip_polygon("clip_ring_two_points_error", False,
                                  sq_part, [[0, 0], [5, 5]]))
    cases.append(run_clip_polygon("clip_selfintersecting_ring", False,
                                  sq_part, BOWTIE[0]))

    # -- clip_polyline_to_ring ---------------------------------------------
    ring_sq = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    cases.append(run_clip_polyline("line_crosses", [[-2, 5], [12, 5]], ring_sq))
    cases.append(run_clip_polyline("line_inside", [[1, 1], [9, 9]], ring_sq))
    cases.append(run_clip_polyline("line_outside", [[-2, -5], [12, -5]], ring_sq))
    cases.append(run_clip_polyline("line_two_pieces", [[-1, 5], [13, 5]],
                                   RING_C_SHAPE))
    cases.append(run_clip_polyline("line_bent_two_entries",
                                   [[-1, 2], [11, 2], [11, 8], [-1, 8]], ring_sq))
    cases.append(run_clip_polyline("line_closed_loop_inside",
                                   [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]],
                                   ring_sq))
    cases.append(run_clip_polyline("line_single_point", [[5, 5]], ring_sq))
    cases.append(run_clip_polyline("line_zero_length_optional",
                                   [[0, 0], [0, 0], [5, 5]], ring_sq))
    cases.append(run_clip_polyline("line_ring_two_points_error",
                                   [[1, 1], [9, 9]], [[0, 0], [5, 5]]))
    cases.append(run_clip_polyline("line_diagonal_two_crossings",
                                   [[-2, 0], [12, 10]], ring_sq))
    cases.append(run_clip_polyline("line_through_ring_vertex_optional",
                                   [[-1, -1], [11, 11]], ring_sq))
    cases.append(run_clip_polyline("line_selfintersecting_optional",
                                   [[1, 1], [9, 9], [9, 1], [1, 9]], ring_sq))
    cases.append(run_clip_polyline("line_collinear_with_edge",
                                   [[-2, 0], [12, 0]], ring_sq))
    cases.append(run_clip_polyline("line_grazes_corner",
                                   [[-2, 0], [10, 0], [10, 12]], ring_sq))

    return cases


def main() -> None:
    cases = build_cases()
    portable = sum(1 for c in cases if c["portable"])
    fixture = {
        "generator": "tools/oracle/generate_ring_ops_fixtures.py",
        "note": (
            "Expected values come from the real Python product code "
            "(repair_invalid_geometry / clip_polygon_to_ring / "
            "clip_polyline_to_ring with shapely 2.1.2). portable cases are "
            "frozen contracts for the C++ ring_ops kernel; non-portable "
            "cases are shapely-only territory and are skipped by the C++ "
            "test with their reason printed. Canonicalization: rings "
            "rotation-normalized to the lexicographically smallest vertex, "
            "|area|-largest ring is the exterior, exteriors CCW / holes CW "
            "(only when every ring has non-zero area), coordinates "
            "round(v, 9), comparison tolerance 1e-9."
        ),
        "counts": {
            "portable": portable,
            "shapely_optional": len(cases) - portable,
            "total": len(cases),
        },
        "cases": cases,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "ring_ops_oracle.json"
    path.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"wrote {path}")
    print(f"cases={len(cases)} portable={portable} "
          f"shapely_optional={len(cases) - portable}")
    for case in cases:
        if not case["portable"]:
            print(f"  skip {case['id']}: {case['skip_reason']}")
        elif case["python_outcome"] != "ok" and case["op"] != "clip_polyline":
            print(f"  note {case['id']}: outcome={case['python_outcome']} "
                  f"expected={case['expected']}")


if __name__ == "__main__":
    main()
