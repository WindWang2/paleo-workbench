#include "pwb/ui_pages_mapedit/map_edit_api.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>
#include <limits>

namespace pwb::ui_pages_mapedit {
namespace {

using pwb::ui_data_core::json_float;
using pwb::ui_data_core::json_is_point;

inline double point_dist2(double ax, double ay, double bx, double by) {
    const double dx = ax - bx, dy = ay - by;
    return dx * dx + dy * dy;
}

inline double point_to_segment_dist2(double px, double py, double ax,
                                     double ay, double bx, double by) {
    const double dx = bx - ax, dy = by - ay;
    if (dx == 0.0 && dy == 0.0) {
        return point_dist2(px, py, ax, ay);
    }
    double t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy);
    t = std::max(0.0, std::min(1.0, t));
    return point_dist2(px, py, ax + t * dx, ay + t * dy);
}

// Ray-cast point-in-polygon; ring may be open or closed. Operates on the
// raw JSON ring like _point_in_ring (malformed entries contribute (0,0)).
bool point_in_ring_json(double px, double py, const domain::Json& ring) {
    if (!ring.is_array()) {
        return false;
    }
    std::size_t n = ring.size();
    if (n < 3) {
        return false;
    }
    // Drop the closing duplicate for iteration.
    const auto& first = ring[0];
    const auto& last = ring[n - 1];
    if (json_is_point(first) && json_is_point(last)) {
        const auto x0 = json_float(first[0]);
        const auto y0 = json_float(first[1]);
        const auto x1 = json_float(last[0]);
        const auto y1 = json_float(last[1]);
        if (x0 && y0 && x1 && y1 && *x0 == *x1 && *y0 == *y1) {
            n -= 1;
            if (n < 3) {
                return false;
            }
        }
    }
    auto px_of = [](const domain::Json& p, std::size_t i) -> double {
        if (i >= p.size()) return 0.0;
        const auto v = json_float(p[i]);
        return v ? *v : 0.0;
    };
    bool inside = false;
    std::size_t j = n - 1;
    for (std::size_t i = 0; i < n; ++i) {
        const double xi = px_of(ring[i], 0), yi = px_of(ring[i], 1);
        const double xj = px_of(ring[j], 0), yj = px_of(ring[j], 1);
        if ((yi > py) != (yj > py) &&
            px < (xj - xi) * (py - yi) / ((yj - yi) == 0.0 ? 1e-30 : (yj - yi)) +
                     xi) {
            inside = !inside;
        }
        j = i;
    }
    return inside;
}

// Typed-ring variant used by is_closed_ring-driven PIP checks below.
bool point_in_ring(double px, double py, const MapRing& ring) {
    std::size_t n = ring.size();
    if (n < 3) {
        return false;
    }
    if (ring.front() == ring.back()) {
        n -= 1;
        if (n < 3) {
            return false;
        }
    }
    bool inside = false;
    std::size_t j = n - 1;
    for (std::size_t i = 0; i < n; ++i) {
        const double xi = ring[i][0], yi = ring[i][1];
        const double xj = ring[j][0], yj = ring[j][1];
        if ((yi > py) != (yj > py) &&
            px < (xj - xi) * (py - yi) / ((yj - yi) == 0.0 ? 1e-30 : (yj - yi)) +
                     xi) {
            inside = !inside;
        }
        j = i;
    }
    return inside;
}

// The GeoJSON geometry branch of _hit_test_python.
bool geometry_hit(const domain::Json& geometry, double px, double py,
                  double tol2_edge) {
    const auto type = geometry.value("type", "");
    if (type != "Polygon" && type != "MultiPolygon") {
        return false;
    }
    const auto coords_it = geometry.find("coordinates");
    const domain::Json empty = domain::Json::array();
    const auto& raw_polygons =
        coords_it != geometry.end() && coords_it->is_array() ? *coords_it : empty;
    // Polygon → one polygon entry; MultiPolygon → the array itself.
    std::vector<const domain::Json*> polygons;
    if (type == "Polygon") {
        polygons.push_back(&raw_polygons);
    } else {
        for (const auto& polygon : raw_polygons) {
            polygons.push_back(&polygon);
        }
    }
    for (const domain::Json* polygon : polygons) {
        if (!polygon->is_array() || polygon->empty()) {
            continue;
        }
        std::vector<const domain::Json*> rings;
        for (const auto& ring : *polygon) {
            if (ring.is_array()) {
                rings.push_back(&ring);
            }
        }
        if (rings.empty()) {
            continue;
        }
        bool inside = point_in_ring_json(px, py, *rings[0]);
        if (inside) {
            for (std::size_t h = 1; h < rings.size(); ++h) {
                if (point_in_ring_json(px, py, *rings[h])) {
                    inside = false;
                    break;
                }
            }
        }
        bool on_edge = false;
        for (const domain::Json* ring : rings) {
            if (on_edge) break;
            const std::size_t seg = ring->size() >= 1 ? ring->size() - 1 : 0;
            for (std::size_t index = 0; index < seg; ++index) {
                const auto& a = (*ring)[index];
                const auto& b = (*ring)[index + 1];
                const auto ax = json_float(a[0]), ay = json_float(a[1]);
                const auto bx = json_float(b[0]), by = json_float(b[1]);
                if (!ax || !ay || !bx || !by) continue;
                if (point_to_segment_dist2(px, py, *ax, *ay, *bx, *by) <=
                    tol2_edge) {
                    on_edge = true;
                    break;
                }
            }
        }
        if (inside || on_edge) {
            return true;
        }
    }
    return false;
}

}  // namespace

bool is_closed_ring(const MapRing& ring) {
    return ring.size() >= 2 && ring.front() == ring.back();
}

std::optional<std::string> hit_test(const std::vector<domain::Json>& records,
                                    double x, double y, double tolerance) {
    if (records.empty()) {
        return std::nullopt;
    }
    const double tol = std::max(0.0, tolerance);
    const double point_tol = tol > 0.0 ? tol : 1e-9;
    const double tol2 = point_tol * point_tol;

    for (const auto& record : records) {
        if (!record.is_object()) {
            continue;
        }
        const auto fid_it = record.find("id");
        if (fid_it == record.end() || fid_it->is_null()) {
            continue;
        }
        const std::string fid = ui_data_core::python_str(*fid_it);

        const auto geom_it = record.find("geometry");
        if (geom_it != record.end() && geom_it->is_object()) {
            const auto gtype = geom_it->value("type", "");
            if (gtype == "Polygon" || gtype == "MultiPolygon") {
                const double edge_tol2 = std::max(tol * tol, 1e-18);
                if (geometry_hit(*geom_it, x, y, edge_tol2)) {
                    return fid;
                }
                continue;
            }
        }

        const auto coords_it = record.find("coordinates");
        if (coords_it == record.end() || !coords_it->is_array() ||
            coords_it->empty()) {
            continue;
        }
        const auto& coords = *coords_it;
        const auto& first = coords[0];
        // Point: [x, y] — first element is a scalar number.
        if (first.is_number()) {
            if (coords.size() >= 2) {
                const auto cx = json_float(coords[0]);
                const auto cy = json_float(coords[1]);
                if (cx && cy && point_dist2(x, y, *cx, *cy) <= tol2) {
                    return fid;
                }
            }
            continue;
        }
        // Ring / line: list of [x, y] entries.
        MapRing ring;
        for (const auto& p : coords) {
            if (p.is_array() && p.size() >= 2) {
                const auto px = json_float(p[0]);
                const auto py = json_float(p[1]);
                if (px && py) {
                    ring.push_back({*px, *py});
                }
            }
        }
        if (ring.size() < 2) {
            continue;
        }
        const bool closed = is_closed_ring(ring);
        if (closed && point_in_ring(x, y, ring)) {
            return fid;
        }
        const double edge_tol2 = tol > 0.0 ? tol * tol : 0.0;
        if (edge_tol2 <= 0.0 && !closed) {
            // Open lines with zero tol: only exact vertex hits.
            for (const auto& p : ring) {
                if (point_dist2(x, y, p[0], p[1]) <= 1e-18) {
                    return fid;
                }
            }
            continue;
        }
        for (std::size_t i = 0; i + 1 < ring.size(); ++i) {
            if (point_to_segment_dist2(x, y, ring[i][0], ring[i][1],
                                       ring[i + 1][0], ring[i + 1][1]) <=
                std::max(edge_tol2, 1e-18)) {
                return fid;
            }
        }
    }
    return std::nullopt;
}

bool set_vertex(MapRing& ring, int index, double x, double y) {
    const int n = static_cast<int>(ring.size());
    if (index < 0 || index >= n) {
        return false;
    }
    const bool closed = is_closed_ring(ring);
    ring[static_cast<std::size_t>(index)] = {x, y};
    if (closed) {
        if (index == 0) {
            ring.back() = {x, y};
        } else if (index == n - 1) {
            ring.front() = {x, y};
        }
    }
    return true;
}

bool insert_vertex(MapRing& ring, int index, double x, double y) {
    int n = static_cast<int>(ring.size());
    if (index < 0 || index > n) {
        return false;
    }
    const bool closed = is_closed_ring(ring);
    // On a closed ring the last point duplicates the first — never insert
    // after the close (would open the ring); map to before the close.
    if (closed && index == n) {
        index = n - 1;
    }
    ring.insert(ring.begin() + index, {x, y});
    if (closed && !ring.empty()) {
        ring.back() = ring.front();
    }
    return true;
}

bool delete_vertex(MapRing& ring, int index) {
    int n = static_cast<int>(ring.size());
    if (index < 0 || index >= n) {
        return false;
    }
    const bool closed = is_closed_ring(ring);
    if (closed) {
        const int unique = n - 1;
        if (unique <= 3) {
            return false;
        }
        // The closing duplicate is the same geometric vertex as index 0.
        if (index == n - 1) {
            index = 0;
        }
        ring.erase(ring.begin() + index);
        if (!ring.empty()) {
            ring.back() = ring.front();
        }
        return true;
    }
    if (n <= 2) {
        return false;
    }
    ring.erase(ring.begin() + index);
    return true;
}

std::optional<ClosestEdge> closest_edge(const MapRing& ring, double x,
                                       double y) {
    if (ring.size() < 2) {
        return std::nullopt;
    }
    std::optional<ClosestEdge> best;
    for (std::size_t i = 0; i + 1 < ring.size(); ++i) {
        const double ax = ring[i][0], ay = ring[i][1];
        const double bx = ring[i + 1][0], by = ring[i + 1][1];
        const double dx = bx - ax, dy = by - ay;
        double qx, qy;
        if (dx == 0.0 && dy == 0.0) {
            qx = ax;
            qy = ay;
        } else {
            double t = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy);
            t = std::max(0.0, std::min(1.0, t));
            qx = ax + t * dx;
            qy = ay + t * dy;
        }
        const double dist2 = (x - qx) * (x - qx) + (y - qy) * (y - qy);
        if (!best || dist2 < best->distance2) {
            best = ClosestEdge{static_cast<int>(i), qx, qy, dist2};
        }
    }
    return best;
}

// ---------------------------------------------------------------------------
// SnapCandidateIndex
// ---------------------------------------------------------------------------

SnapCandidateIndex::SnapCandidateIndex(
    const std::vector<MapPoint>& candidates) {
    xs_.reserve(candidates.size());
    ys_.reserve(candidates.size());
    for (const auto& p : candidates) {
        if (std::isfinite(p[0]) && std::isfinite(p[1])) {
            xs_.push_back(p[0]);
            ys_.push_back(p[1]);
        }
    }
}

std::vector<MapPoint> SnapCandidateIndex::candidates() const {
    std::vector<MapPoint> out(xs_.size());
    for (std::size_t i = 0; i < xs_.size(); ++i) {
        out[i] = {xs_[i], ys_[i]};
    }
    return out;
}

const std::map<std::pair<long long, long long>, std::vector<int>>&
SnapCandidateIndex::ensure_grid(double cell) const {
    if (grid_ && grid_cell_ == cell) {
        return *grid_;
    }
    std::map<std::pair<long long, long long>, std::vector<int>> grid;
    for (std::size_t i = 0; i < xs_.size(); ++i) {
        grid[{static_cast<long long>(std::floor(xs_[i] / cell)),
              static_cast<long long>(std::floor(ys_[i] / cell))}]
            .push_back(static_cast<int>(i));
    }
    grid_ = std::move(grid);
    grid_cell_ = cell;
    return *grid_;
}

MapPoint SnapCandidateIndex::snap(
    double x, double y, double tol,
    const std::vector<MapPoint>& extra_candidates) const {
    const double tol_f = std::max(0.0, tol);
    std::vector<MapPoint> extras;
    for (const auto& raw : extra_candidates) {
        if (std::isfinite(raw[0]) && std::isfinite(raw[1])) {
            extras.push_back(raw);
        }
    }
    double best_d2 = tol_f * tol_f;
    int best_idx = -1;
    MapPoint best{0.0, 0.0};
    if (!xs_.empty()) {
        const double cell = std::max(tol_f, 1e-9);
        const auto& grid = ensure_grid(cell);
        const auto cx0 =
            static_cast<long long>(std::floor((x - tol_f) / cell));
        const auto cx1 =
            static_cast<long long>(std::floor((x + tol_f) / cell));
        const auto cy0 =
            static_cast<long long>(std::floor((y - tol_f) / cell));
        const auto cy1 =
            static_cast<long long>(std::floor((y + tol_f) / cell));
        for (long long cx = cx0; cx <= cx1; ++cx) {
            for (long long cy = cy0; cy <= cy1; ++cy) {
                const auto it = grid.find({cx, cy});
                if (it == grid.end()) continue;
                for (const int idx : it->second) {
                    const double dx = xs_[idx] - x;
                    const double dy = ys_[idx] - y;
                    const double d2 = dx * dx + dy * dy;
                    // Reproduce the linear scan's <= update: smallest d2
                    // wins; among equals the LAST candidate in order.
                    if (d2 < best_d2 || (d2 == best_d2 && idx > best_idx)) {
                        best_d2 = d2;
                        best = {xs_[idx], ys_[idx]};
                        best_idx = idx;
                    }
                }
            }
        }
    }
    for (std::size_t i = 0; i < extras.size(); ++i) {
        const int idx = static_cast<int>(xs_.size() + i);
        const double dx = extras[i][0] - x;
        const double dy = extras[i][1] - y;
        const double d2 = dx * dx + dy * dy;
        if (d2 < best_d2 || (d2 == best_d2 && idx > best_idx)) {
            best_d2 = d2;
            best = extras[i];
            best_idx = idx;
        }
    }
    return best_idx >= 0 ? best : MapPoint{x, y};
}

}  // namespace pwb::ui_pages_mapedit
