// map_edit_core — native geometry hot path for the paleo mapping editor.
// Bound via pybind11 as module ``map_edit_core`` (see paleo_workbench/mapping/CPP_EXTENSION.md).

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <cmath>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace {

constexpr double kEps = 1e-12;

double dist2(double ax, double ay, double bx, double by) {
    const double dx = ax - bx;
    const double dy = ay - by;
    return dx * dx + dy * dy;
}

double point_to_segment_dist2(
    double px,
    double py,
    double ax,
    double ay,
    double bx,
    double by
) {
    const double dx = bx - ax;
    const double dy = by - ay;
    if (dx == 0.0 && dy == 0.0) {
        return dist2(px, py, ax, ay);
    }
    double t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy);
    t = std::max(0.0, std::min(1.0, t));
    return dist2(px, py, ax + t * dx, ay + t * dy);
}

bool is_closed_ring(const py::list& ring) {
    const py::ssize_t n = py::len(ring);
    if (n < 2) {
        return false;
    }
    py::object a = ring[0];
    py::object b = ring[n - 1];
    if (!py::isinstance<py::sequence>(a) || !py::isinstance<py::sequence>(b)) {
        return false;
    }
    py::sequence sa = a.cast<py::sequence>();
    py::sequence sb = b.cast<py::sequence>();
    if (py::len(sa) < 2 || py::len(sb) < 2) {
        return false;
    }
    return sa[0].cast<double>() == sb[0].cast<double>()
        && sa[1].cast<double>() == sb[1].cast<double>();
}

bool point_in_ring(double px, double py, const py::list& ring) {
    py::ssize_t n = py::len(ring);
    if (n < 3) {
        return false;
    }
    // Drop closing duplicate for iteration.
    if (is_closed_ring(ring)) {
        n = n - 1;
        if (n < 3) {
            return false;
        }
    }
    bool inside = false;
    py::ssize_t j = n - 1;
    for (py::ssize_t i = 0; i < n; ++i) {
        py::sequence pi = ring[static_cast<size_t>(i)].cast<py::sequence>();
        py::sequence pj = ring[static_cast<size_t>(j)].cast<py::sequence>();
        const double xi = pi[0].cast<double>();
        const double yi = pi[1].cast<double>();
        const double xj = pj[0].cast<double>();
        const double yj = pj[1].cast<double>();
        // Standard ray-cast: the (yi > py) != (yj > py) guard already excludes
        // horizontal edges (yi == yj), so yj - yi is provably non-zero here and
        // no division guard is needed (the previous 1e-30 fallback was dead
        // code — cpp-core-review M16). Points exactly on an edge/vertex have
        // unspecified inside/outside, which is fine for hit-test use.
        if (((yi > py) != (yj > py))
            && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) {
            inside = !inside;
        }
        j = i;
    }
    return inside;
}

void set_xy(py::list& point, double x, double y) {
    // Mutate in place when possible.
    if (py::len(point) >= 2) {
        point[0] = x;
        point[1] = y;
    }
}

}  // namespace

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

std::optional<std::string> hit_test(
    const py::list& features,
    double x,
    double y,
    double tol
) {
    // Tolerance semantics (cpp-core-review I6, intentionally shared with the
    // Python fallback `_hit_test_python`): when tol <= 0 (the default),
    //   - points hit within a small radius (1e-9, squared -> tol2),
    //   - open-line vertices hit on near-exact match (1e-18, squared -> ~1e-9),
    //   - ring/line edges hit within max(tol^2, 1e-18).
    // These three thresholds differ by design (bare points need a usable pick
    // radius; open lines default to exact-vertex snaps). Both backends agree.
    const double px = x;
    const double py = y;
    const double point_tol = tol > 0.0 ? tol : 1e-9;
    const double tol2 = point_tol * point_tol;
    const double edge_tol2 = (tol > 0.0 ? tol : 0.0) * (tol > 0.0 ? tol : 0.0);

    for (const auto& item : features) {
        // Expect (id, coordinates) or sequence of length 2.
        py::sequence pair = item.cast<py::sequence>();
        if (py::len(pair) < 2) {
            continue;
        }
        std::string fid = py::str(pair[0]);
        py::object coords_obj = pair[1];
        if (!py::isinstance<py::list>(coords_obj) && !py::isinstance<py::sequence>(coords_obj)) {
            continue;
        }
        py::list coords = py::list(coords_obj);
        if (py::len(coords) == 0) {
            continue;
        }
        py::object first = coords[0];
        // Point: [x, y] — first element is a number
        if (py::isinstance<py::float_>(first) || py::isinstance<py::int_>(first)) {
            if (py::len(coords) >= 2) {
                try {
                    const double cx = coords[0].cast<double>();
                    const double cy = coords[1].cast<double>();
                    if (dist2(px, py, cx, cy) <= tol2) {
                        return fid;
                    }
                } catch (const py::error_already_set&) {
                    continue;  // M11: malformed coordinate -> skip feature
                }
            }
            continue;
        }
        // Ring / line: wrap the whole feature body so ANY malformed coordinate
        // (a string like "ab" reaching is_closed_ring, a non-numeric element,
        // etc.) skips the feature instead of propagating a hard cast/index
        // error. Matches the Python fallback's lenient isinstance filtering
        // (cpp-core-review M11).
        try {
            py::ssize_t n = py::len(coords);
            if (n < 2) {
                continue;
            }
            const bool closed = is_closed_ring(coords);
            if (closed && point_in_ring(px, py, coords)) {
                return fid;
            }
            if (edge_tol2 <= 0.0 && !closed) {
                for (py::ssize_t i = 0; i < n; ++i) {
                    py::sequence p = coords[static_cast<size_t>(i)].cast<py::sequence>();
                    if (dist2(px, py, p[0].cast<double>(), p[1].cast<double>()) <= 1e-18) {
                        return fid;
                    }
                }
                continue;
            }
            const py::ssize_t seg_count = n - 1;
            for (py::ssize_t i = 0; i < seg_count; ++i) {
                py::sequence a = coords[static_cast<size_t>(i)].cast<py::sequence>();
                py::sequence b = coords[static_cast<size_t>(i + 1)].cast<py::sequence>();
                const double d2 = point_to_segment_dist2(
                    px,
                    py,
                    a[0].cast<double>(),
                    a[1].cast<double>(),
                    b[0].cast<double>(),
                    b[1].cast<double>()
                );
                if (d2 <= std::max(edge_tol2, 1e-18)) {
                    return fid;
                }
            }
        } catch (const py::error_already_set&) {
            continue;  // M11: skip feature with malformed coordinates
        }
    }
    return std::nullopt;
}

std::pair<double, double> snap(
    const py::list& candidates,
    double x,
    double y,
    double tol
) {
    // Contract (cpp-core-review M12, shared with the Python fallback
    // `_snap_point_python`): returns the nearest candidate within tol. When no
    // candidate is within tol, the ORIGINAL (x, y) is returned unchanged — a
    // miss is indistinguishable from a perfect snap at distance 0. Callers
    // that need to distinguish a miss must check the distance themselves; the
    // public `snap_point` wrapper documents this.
    const double px = x;
    const double py = y;
    const double tol_f = std::max(0.0, tol);
    double best_d2 = tol_f * tol_f;
    double bx = px;
    double by = py;
    for (const auto& raw : candidates) {
        if (raw.is_none()) {
            continue;
        }
        py::sequence p = raw.cast<py::sequence>();
        if (py::len(p) < 2) {
            continue;
        }
        const double cx = p[0].cast<double>();
        const double cy = p[1].cast<double>();
        const double d2 = dist2(cx, cy, px, py);
        if (d2 <= best_d2) {
            best_d2 = d2;
            bx = cx;
            by = cy;
        }
    }
    return {bx, by};
}

std::pair<double, double> snap_indexed(
    const std::vector<double>& xs,
    const std::vector<double>& ys,
    double x,
    double y,
    double tol
) {
    // Compact-buffer twin of Python SnapCandidateIndex.snap (parity contract
    // shared with `_snap_point_python`): nearest candidate within tol wins;
    // ties resolve to the LAST candidate in buffer order (the scan keeps
    // updating on <=). A miss returns the ORIGINAL (x, y) unchanged. Buffers
    // arrive pre-filtered/coerced by the Python façade, so a linear scan over
    // cache-friendly double arrays is both exact and fast; the grid lives on
    // the Python fallback side.
    const double tol_f = std::max(0.0, tol);
    double best_d2 = tol_f * tol_f;
    double bx = x;
    double by = y;
    const size_t n = std::min(xs.size(), ys.size());
    for (size_t i = 0; i < n; ++i) {
        const double d2 = dist2(xs[i], ys[i], x, y);
        if (d2 <= best_d2) {
            best_d2 = d2;
            bx = xs[i];
            by = ys[i];
        }
    }
    return {bx, by};
}

void move_feature(py::list coordinates, double dx, double dy) {
    if (py::len(coordinates) == 0) {
        return;
    }
    py::object first = coordinates[0];
    if (py::isinstance<py::float_>(first) || py::isinstance<py::int_>(first)) {
        if (py::len(coordinates) >= 2) {
            coordinates[0] = coordinates[0].cast<double>() + dx;
            coordinates[1] = coordinates[1].cast<double>() + dy;
        }
        return;
    }
    for (py::ssize_t i = 0; i < py::len(coordinates); ++i) {
        py::object pt = coordinates[static_cast<size_t>(i)];
        if (py::isinstance<py::list>(pt)) {
            // list: mutate in place, preserve type.
            py::list point = py::cast<py::list>(pt);
            if (py::len(point) >= 2) {
                point[0] = point[0].cast<double>() + dx;
                point[1] = point[1].cast<double>() + dy;
            }
        } else if (py::isinstance<py::tuple>(pt)) {
            // tuple: immutable, so write back a NEW tuple of the same element
            // type rather than silently converting to list (cpp-core-review
            // M13 — the old py::list(pt) mutated the caller's element type).
            py::tuple point = py::cast<py::tuple>(pt);
            if (py::len(point) >= 2) {
                py::tuple moved = py::make_tuple(
                    point[0].cast<double>() + dx,
                    point[1].cast<double>() + dy
                );
                coordinates[static_cast<size_t>(i)] = moved;
            }
        }
        // Other sequence types: skip (match the Python fallback's isinstance filter).
    }
}

// Helper: write (x, y) to ring[i], preserving the element's Python type
// (list mutated in place; tuple replaced with a new tuple). cpp-core-review M13.
void write_vertex(py::list& ring, py::ssize_t i, double x, double y) {
    py::object pt = ring[i];
    if (py::isinstance<py::list>(pt)) {
        py::list point = py::cast<py::list>(pt);
        set_xy(point, x, y);
    } else if (py::isinstance<py::tuple>(pt)) {
        ring[i] = py::make_tuple(x, y);
    } else {
        ring[i] = py::make_tuple(x, y);  // fallback
    }
}

void set_vertex(py::list ring, int index, double x, double y) {
    const py::ssize_t n = py::len(ring);
    if (index < 0 || index >= n) {
        throw py::index_error("vertex index out of range");
    }
    const bool closed = is_closed_ring(ring);
    write_vertex(ring, static_cast<py::ssize_t>(index), x, y);
    if (closed) {
        if (index == 0) {
            write_vertex(ring, n - 1, x, y);
        } else if (index == n - 1) {
            write_vertex(ring, 0, x, y);
        }
    }
}

void insert_vertex(py::list ring, int index, double x, double y) {
    const py::ssize_t n = py::len(ring);
    if (index < 0 || index > n) {
        throw py::index_error("insert index out of range");
    }
    const bool closed = is_closed_ring(ring);
    // On a closed ring, inserting at index==n would insert AFTER the closing
    // duplicate vertex and open the ring (first != last). Treat it as insert
    // before the close, then re-close so first/last stay synchronized —
    // matches the Python fallback (cpp-core-review M15).
    int insert_at = index;
    if (closed && index == n) {
        insert_at = static_cast<int>(n) - 1;
    }
    py::list pt;
    pt.append(x);
    pt.append(y);
    ring.insert(static_cast<size_t>(insert_at), pt);
    if (closed && py::len(ring) >= 1) {
        // Re-close: keep the last point identical to the first after insert.
        py::ssize_t last = py::len(ring) - 1;
        py::object first_pt = ring[0];
        if (py::isinstance<py::list>(first_pt)) {
            py::list first = py::cast<py::list>(first_pt);
            if (py::len(first) >= 2) {
                write_vertex(ring, last, first[0].cast<double>(), first[1].cast<double>());
            }
        }
    }
}

bool delete_vertex(py::list ring, int index) {
    py::ssize_t n = py::len(ring);
    if (index < 0 || index >= n) {
        return false;
    }
    const bool closed = is_closed_ring(ring);
    if (closed) {
        const py::ssize_t unique = n - 1;
        if (unique <= 3) {
            return false;
        }
        if (index == n - 1) {
            index = 0;
        }
        ring.attr("pop")(index);
        n = py::len(ring);
        if (n >= 1) {
            py::list first = py::list(ring[0]);
            py::list last = py::list(ring[static_cast<size_t>(n - 1)]);
            set_xy(last, first[0].cast<double>(), first[1].cast<double>());
            ring[static_cast<size_t>(n - 1)] = last;
        }
        return true;
    }
    if (n <= 2) {
        return false;
    }
    ring.attr("pop")(index);
    return true;
}

double orient(
    double ax,
    double ay,
    double bx,
    double by,
    double cx,
    double cy
) {
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
}

bool segments_properly_intersect(
    double a1x,
    double a1y,
    double a2x,
    double a2y,
    double b1x,
    double b1y,
    double b2x,
    double b2y
) {
    const double o1 = orient(a1x, a1y, a2x, a2y, b1x, b1y);
    const double o2 = orient(a1x, a1y, a2x, a2y, b2x, b2y);
    const double o3 = orient(b1x, b1y, b2x, b2y, a1x, a1y);
    const double o4 = orient(b1x, b1y, b2x, b2y, a2x, a2y);

    if (((o1 > kEps && o2 < -kEps) || (o1 < -kEps && o2 > kEps))
        && ((o3 > kEps && o4 < -kEps) || (o3 < -kEps && o4 > kEps))) {
        return true;
    }
    // Proper intersection only: collinear overlaps and endpoint (T-)touches
    // are deliberately not reported (cpp-core-review M17). The Python
    // fallback `_segments_properly_intersect` additionally reports collinear
    // overlaps, so two polygonal faults sharing a collinear segment validate
    // as clean here but may surface in the Python path — intentional, since
    // the C++ hot path favours speed over the rare collinear case.
    return false;
}

py::list validate(const py::list& ring) {
    py::list issues;
    py::ssize_t n = py::len(ring);
    if (n < 4) {
        return issues;
    }
    // Segment model: sequential segments [i, i+1] over all n points. For a
    // CLOSED ring (first == last duplicated), the final segment [n-2, n-1]
    // IS the closing edge, so every edge including the close is tested —
    // and the i==0 / j==seg_count-1 adjacency skip below correctly treats
    // them as sharing the closing vertex. For an OPEN polyline there is no
    // implicit closing edge to test (cpp-core-review M14: the previous
    // comment claimed the close was untested, but it is in fact covered for
    // closed rings; open rings have no close by definition). Matches the
    // Python fallback `_validate_ring_python`.
    const py::ssize_t seg_count = n - 1;
    for (py::ssize_t i = 0; i < seg_count; ++i) {
        py::sequence a = ring[static_cast<size_t>(i)].cast<py::sequence>();
        py::sequence b = ring[static_cast<size_t>(i + 1)].cast<py::sequence>();
        const double a1x = a[0].cast<double>();
        const double a1y = a[1].cast<double>();
        const double a2x = b[0].cast<double>();
        const double a2y = b[1].cast<double>();
        for (py::ssize_t j = i + 1; j < seg_count; ++j) {
            // Skip adjacent segments (share a vertex).
            if (j == i + 1) {
                continue;
            }
            if (i == 0 && j == seg_count - 1 && is_closed_ring(ring)) {
                continue;  // first and last share closing vertex
            }
            py::sequence c = ring[static_cast<size_t>(j)].cast<py::sequence>();
            py::sequence d = ring[static_cast<size_t>(j + 1)].cast<py::sequence>();
            const double b1x = c[0].cast<double>();
            const double b1y = c[1].cast<double>();
            const double b2x = d[0].cast<double>();
            const double b2y = d[1].cast<double>();
            if (segments_properly_intersect(a1x, a1y, a2x, a2y, b1x, b1y, b2x, b2y)) {
                py::dict issue;
                issue["code"] = "self_intersection";
                issue["message"] = "ring self-intersects";
                issue["edges"] = py::make_tuple(
                    py::make_tuple(static_cast<int>(i), static_cast<int>(i + 1)),
                    py::make_tuple(static_cast<int>(j), static_cast<int>(j + 1))
                );
                issues.append(issue);
            }
        }
    }
    return issues;
}

PYBIND11_MODULE(map_edit_core, m) {
    m.doc() = "Native geometry hot path for paleo mapping editor";
    m.def(
        "hit_test",
        &hit_test,
        py::arg("features"),
        py::arg("x"),
        py::arg("y"),
        py::arg("tol") = 0.0
    );
    m.def(
        "snap",
        &snap,
        py::arg("candidates"),
        py::arg("x"),
        py::arg("y"),
        py::arg("tol") = 0.5
    );
    m.def(
        "snap_indexed",
        &snap_indexed,
        py::arg("xs"),
        py::arg("ys"),
        py::arg("x"),
        py::arg("y"),
        py::arg("tol") = 0.5
    );
    m.def(
        "move_feature",
        &move_feature,
        py::arg("coordinates"),
        py::arg("dx"),
        py::arg("dy")
    );
    m.def(
        "set_vertex",
        &set_vertex,
        py::arg("ring"),
        py::arg("index"),
        py::arg("x"),
        py::arg("y")
    );
    m.def(
        "insert_vertex",
        &insert_vertex,
        py::arg("ring"),
        py::arg("index"),
        py::arg("x"),
        py::arg("y")
    );
    m.def("delete_vertex", &delete_vertex, py::arg("ring"), py::arg("index"));
    m.def("validate", &validate, py::arg("ring"));
}
