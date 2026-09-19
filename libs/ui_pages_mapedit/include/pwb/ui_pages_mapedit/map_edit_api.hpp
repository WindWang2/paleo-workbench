// UI-08 — geoviz_plots map_edit/api.py kernels the edit scene calls:
// hit_test, set_vertex, insert_vertex, delete_vertex, closest_edge and the
// SnapCandidateIndex uniform grid. Pure-Python oracle semantics (the
// optional map_edit_core accelerator is an exact-equivalent fast path —
// this port IS the native path, so it mirrors _hit_test_python /
// _snap_point_python exactly). Qt-free; records are domain::Json dicts.
//
// Python-raise mapping: set_vertex/insert_vertex/delete_vertex return bool
// — false stands for the Python IndexError/TypeError/ValueError branches
// the scene catches (``except (IndexError, TypeError, ValueError)``).
#pragma once

#include "pwb/domain/json.hpp"
#include "pwb/ui_data_core/map_edit_geometry.hpp"

#include <cmath>
#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace pwb::ui_pages_mapedit {

using pwb::ui_data_core::MapPoint;
using pwb::ui_data_core::MapRing;

// ---------------------------------------------------------------------------
// hit_test — _hit_test_python: first (top-most ordered) feature under (x, y).
// Records carry "id" + "coordinates" (point or ring) or a GeoJSON
// "geometry" dict (Polygon/MultiPolygon). tolerance is scene units.
// ---------------------------------------------------------------------------
std::optional<std::string> hit_test(const std::vector<domain::Json>& records,
                                    double x, double y, double tolerance = 0.0);

// ---------------------------------------------------------------------------
// vertex ops — in-place ring mutations mirroring api.py semantics
// ---------------------------------------------------------------------------

// set_vertex(ring, index, x, y): syncs the closing point on closed rings.
// false = Python raise branch (ring index out of range).
bool set_vertex(MapRing& ring, int index, double x, double y);

// insert_vertex(ring, index, x, y): list.insert semantics; closed rings
// re-close (insert at the closing index maps to before the close).
// false = Python raise branch (insert index out of range).
bool insert_vertex(MapRing& ring, int index, double x, double y);

// delete_vertex(ring, index): closed rings keep >= 3 unique vertices,
// open rings >= 2. false = refused (Python return False / raise branch).
bool delete_vertex(MapRing& ring, int index);

// _is_closed_ring: first == last with >= 2 points.
bool is_closed_ring(const MapRing& ring);

// closest_edge(ring, x, y) → (edge_start_index, proj_x, proj_y, dist2).
struct ClosestEdge {
    int edge_start_index = 0;
    double proj_x = 0.0;
    double proj_y = 0.0;
    double distance2 = 0.0;
};
std::optional<ClosestEdge> closest_edge(const MapRing& ring, double x,
                                       double y);

// ---------------------------------------------------------------------------
// SnapCandidateIndex — uniform-grid index over snap candidates; built once,
// queried per mouse move. Nearest candidate within tol wins; ties resolve
// to the LAST candidate in input order; a miss returns the original point.
// ---------------------------------------------------------------------------
class SnapCandidateIndex {
public:
    SnapCandidateIndex() = default;
    explicit SnapCandidateIndex(const std::vector<MapPoint>& candidates);

    int size() const { return static_cast<int>(xs_.size()); }
    std::vector<MapPoint> candidates() const;

    // snap(x, y, tol, extra_candidates): extras act as if appended after the
    // base candidates (they win ties) without invalidating the cached grid.
    MapPoint snap(double x, double y, double tol = 0.5,
                  const std::vector<MapPoint>& extra_candidates = {}) const;

private:
    const std::map<std::pair<long long, long long>, std::vector<int>>&
    ensure_grid(double cell) const;

    std::vector<double> xs_;
    std::vector<double> ys_;
    // Lazily built per cell size (the scene's tolerance varies with zoom).
    mutable std::optional<
        std::map<std::pair<long long, long long>, std::vector<int>>>
        grid_;
    mutable double grid_cell_ = 0.0;
};

}  // namespace pwb::ui_pages_mapedit
