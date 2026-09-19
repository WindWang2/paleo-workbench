// map-edit geometry kernels — the Qt-free geometry core shared by
// map_edit_items / map_edit_snap / map_edit_topology / map_edit_draft /
// map_edit_factory.
//
// Two sources are ported here:
//
// * geoviz map_edit/api.py pure-Python kernels (snap_point, ring
//   self-intersection validation, adjacency heuristic, snap_shared_nodes,
//   rebuild_topology). The optional geoviz C++ accelerator and scipy KDTree
//   are exact-equivalent fast paths — the plain scans are byte-identical.
// * paleo_workbench/mapping/geometry_schema.py canonical_facies_geometry /
//   compact_facies_coordinates / new_feature_id + project/domain.py
//   coordinate_status_is_flagged.
//
// The shapely-bound operations (merge_rings, split_ring_by_line and the
// shape() half of validate_polygon_geometry) sit behind MapGeometryBackend;
// a null backend reproduces the no-shapely Python environment exactly.
#pragma once

#include "pwb/domain/json.hpp"

#include <array>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace pwb::ui_data_core {

// Point / ring / polygon algebra — [[x, y], ...] float pairs.
using MapPoint = std::array<double, 2>;
using MapRing = std::vector<MapPoint>;
using MapPolygon = std::vector<MapRing>;
using MapMultiPolygon = std::vector<MapPolygon>;

// ---------------------------------------------------------------------------
// Coercion (api.py _ring_to_pts / geometry_schema _is_point/_coerce_ring)
// ---------------------------------------------------------------------------

// Python float(value) — numbers, bools and numeric strings coerce;
// everything else fails (nullopt = TypeError/ValueError branch).
std::optional<double> json_float(const domain::Json& value);

// _is_point: [x, y] with >= 2 non-list elements.
bool json_is_point(const domain::Json& value);

// _ring_to_pts — best-effort coercion: malformed points are SKIPPED.
MapRing ring_to_pts(const domain::Json& ring);

// _coerce_ring — strict: any non-point entry empties the whole ring; a
// non-empty open ring is closed by appending its first point.
MapRing coerce_ring(const domain::Json& value);

MapRing json_ring(const domain::Json& ring);        // == ring_to_pts alias
domain::Json ring_to_json(const MapRing& ring);      // [[x, y], ...]
domain::Json polygon_to_json(const MapPolygon& polygon);
domain::Json multipolygon_to_json(const MapMultiPolygon& polygons);

// ---------------------------------------------------------------------------
// geoviz api.py — snap + validation kernels
// ---------------------------------------------------------------------------

// _snap_point_python: nearest candidate within tol (<= tol² boundary).
MapPoint snap_point(const std::vector<MapPoint>& candidates, double x,
                    double y, double tol = 0.5);

// _segments_properly_intersect — proper crossing or collinear overlap.
bool segments_properly_intersect(const MapPoint& a1, const MapPoint& a2,
                                 const MapPoint& b1, const MapPoint& b2);

// _ring_points_and_edges → nullopt for unvalidatable rings.
struct ParsedRing {
    std::vector<MapPoint> points;
    bool closed = false;
    int n = 0;  // unique vertex count (closing duplicate excluded)
    std::vector<std::pair<int, int>> edges;
};
std::optional<ParsedRing> ring_points_and_edges(const MapRing& ring);

// validate_ring → issue dicts [{"code","message","edges"}] (JSON array).
domain::Json validate_ring(const MapRing& ring);

// validate_ring_local — incremental check around moved vertex indices.
domain::Json validate_ring_local(
    const MapRing& ring, const std::vector<long long>& moved_vertex_indices);

// validate_adjacency → issues with {"code","message","pair":[i,j]}.
domain::Json validate_adjacency(const std::vector<MapRing>& rings,
                                double gap_tol = 0.5);

// _near_vertex_pairs — exact inclusive-boundary O(n²) scan (the KDTree
// path is an exact-equivalent candidate filter).
std::vector<std::pair<int, int>> near_vertex_pairs(
    const std::vector<MapPoint>& coords, double tol);

// snap_shared_nodes — union-find clustering; representative = mean.
std::vector<MapRing> snap_shared_nodes(const std::vector<MapRing>& rings,
                                       double tol = 0.5);

// rebuild_topology → report dict {rings, changed, ring_issues,
// adjacency_issues}. Rings stay typed for the planner; issue lists are the
// same JSON shape the Python returns.
struct TopologyRebuildReport {
    std::vector<MapRing> rings;
    bool changed = false;
    domain::Json ring_issues = domain::Json::array();
    domain::Json adjacency_issues = domain::Json::array();
};
TopologyRebuildReport rebuild_topology(
    const std::vector<MapRing>& rings, double snap_tol = 0.5,
    std::optional<double> gap_tol = std::nullopt);

// ---------------------------------------------------------------------------
// Shapely-bound seam — merge / split / whole-shape validation
// ---------------------------------------------------------------------------

class MapGeometryBackend {
public:
    virtual ~MapGeometryBackend() = default;
    // merge_rings shapely union → exterior coords or nullopt (fail/disjoint).
    virtual std::optional<MapRing> merge_rings(const MapRing& a,
                                               const MapRing& b) = 0;
    // split_ring_by_line shapely split → 2+ exterior rings or nullopt.
    virtual std::optional<std::vector<MapRing>> split_ring_by_line(
        const MapRing& ring, const MapRing& line) = 0;
    // validate_polygon_geometry shape() half — issue dicts for the
    // constructed shape (hole containment, nested shells, part interplay);
    // [] when valid.
    virtual domain::Json shape_issues(std::string_view geometry_type,
                                      const domain::Json& coordinates) = 0;
};

// api.merge_rings / api.split_ring_by_line — the length guards and
// no-shapely paths live here (backend == nullptr → Python returns None).
std::optional<MapRing> merge_rings(const MapRing& ring_a,
                                   const MapRing& ring_b,
                                   MapGeometryBackend* backend);
std::optional<std::vector<MapRing>> split_ring_by_line(
    const MapRing& ring, const MapRing& line, MapGeometryBackend* backend);

// geoviz_paleo_map.topology.validate_polygon_geometry — the unsupported-
// type check is unconditional; the shape() half needs the backend.
domain::Json validate_polygon_geometry(std::string_view geometry_type,
                                       const domain::Json& coordinates,
                                       MapGeometryBackend* backend);

// ---------------------------------------------------------------------------
// geometry_schema helpers
// ---------------------------------------------------------------------------

// canonical_facies_geometry(raw) → (geometry_type, polygons→rings→points).
std::pair<std::string, MapMultiPolygon> canonical_facies_geometry(
    const domain::Json& raw);

// compact_facies_coordinates(geometry_type, polygons) — the historic
// single-ring shape when possible.
domain::Json compact_facies_coordinates(std::string_view geometry_type,
                                        const MapMultiPolygon& polygons);

// new_feature_id(prefix) → "<prefix>_<uuid4-hex[:12]>". The injectable
// generator keeps oracle tests deterministic.
using FeatureIdFn = std::function<std::string(std::string_view prefix)>;
std::string new_feature_id(std::string_view prefix = "feat");

// coordinate_status_is_flagged(status) — anything but "ok".
bool coordinate_status_is_flagged(std::string_view status);

}  // namespace pwb::ui_data_core
