#pragma once

// Port of paleo_workbench/mapping/geometry_planar.py + the geometry
// helper section of ui/workstation/composite_editing.py (UI-13).
//
// GeoJSON geometries travel as pwb::domain::Json objects
// ({"type": ..., "coordinates": ...}) — the same wire the Python
// VectorFeature/as_record contract uses. All helpers are pure and
// byte-faithful to the Python implementations; the shapely-backed
// operations stay behind injected backends (see topology_service).
//
// Qt-free.

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;
using pwb::ui_data_core::MapPoint;
using pwb::ui_data_core::MapRing;

// ---------------------------------------------------------------------------
// geometry_planar.py kernels
// ---------------------------------------------------------------------------

// distance_to_segment: planar point-to-segment distance; a degenerate
// (zero-length) segment falls back to point-to-endpoint distance.
double distance_to_segment(const MapPoint& point, const MapPoint& start,
                           const MapPoint& end);

// _ray_crosses / point_in_ring_scalar: even-odd ray-cast for ONE ring.
bool point_in_ring_scalar(double x, double y, const MapRing& ring);

// point_in_ring_scalar_inclusive: ray-cast + explicit on-edge test
// (cross-product threshold, epsilon semantics identical to Python).
bool point_in_ring_scalar_inclusive(double x, double y, const MapRing& ring,
                                    double epsilon = 1e-9);

// point_in_polygon_scalar: even-odd containment with hole support for
// GeoJSON Polygon/MultiPolygon. Throws std::invalid_argument for other
// geometry types (Python ValueError parity).
bool point_in_polygon_scalar(const MapPoint& point, const Json& polygon);

// extent_of_coordinates: bounding box of a coordinate stream; nullopt
// when the stream carries no finite [x, y] pair.
using MapExtent = std::array<double, 4>;
std::optional<MapExtent> extent_of_coordinates(
    const std::vector<MapPoint>& coords);

// extent_of_geometries: union bounding box over GeoJSON geometry dicts.
std::optional<MapExtent> extent_of_geometries(
    const std::vector<Json>& geometries);

// ---------------------------------------------------------------------------
// composite_editing.py geometry helpers (module §1)
// ---------------------------------------------------------------------------

// _as_float: Python float(value) over Json — numbers/bools/numeric
// strings coerce; everything else fails (nullopt).
std::optional<double> json_as_float(const Json& value);

// _point: tolerant [x, y] coercion; nullopt for malformed/falsey values.
std::optional<MapPoint> json_point(const Json& value);

// _coords_to_lists: nested-tuple -> nested-list normalization is a no-op
// on Json (arrays already are lists) — kept as a semantic alias.
Json coords_to_lists(const Json& value);

// _iter_vertices / _ring_vertices: (point, path) pairs in document order.
// The path mirrors the Python tuple index path into geometry.coordinates.
struct VertexVisit {
    MapPoint point;
    std::vector<int> path;
};
std::vector<VertexVisit> iter_vertices(const Json& geometry);
// _ring_vertices: vertices of a ring-list node (not a whole geometry).
std::vector<VertexVisit> ring_vertices(const Json& rings);

// _segments: every segment (a, b) of a nested coordinate structure.
std::vector<std::pair<MapPoint, MapPoint>> geometry_segments(
    const Json& coordinates);

// _geometry_hit: point within tolerance of any vertex/segment, or inside
// a polygon ring (uses point_in_ring_scalar).
bool geometry_hit(const MapPoint& point, const Json& geometry,
                  double tolerance);

// _geometry_equal: structural equality after coords normalization
// (Python compared thawed dicts — Json equality is the same contract).
bool geometry_equal(const Json& left, const Json& right);

// _feature_extent: union extent of feature records {"geometry": {...}};
// throws std::runtime_error("no geometry") on an empty set (Python
// ValueError parity).
MapExtent feature_extent(const std::vector<Json>& features);

// _union_extent: extent of a geometry list, plus a point unioned in.
std::optional<MapExtent> union_extent(const std::vector<Json>& geometries,
                                      const MapPoint* point = nullptr);

// _nearest_interior_ring: index of the interior ring containing point
// (>0); -1 when none (Polygon geometry only).
int nearest_interior_ring(const Json& geometry, const MapPoint& point);

// _nearest_part: outermost part index whose ring set contains point
// (Multi*) or -1; single geometries return 0/-1.
int nearest_part(const Json& geometry, const MapPoint& point);

// _plain_geometry: {"type","coordinates"} projection of an arbitrary
// geometry-ish Json (drops extra members, Python parity).
Json plain_geometry(const Json& geometry);

// _crs_parseable: non-empty declaration that survives the injected
// validator probe (no probe -> non-empty string is accepted, matching
// the Python "parseable unless pyproj rejects" contract when pyproj is
// absent — honest: hosts inject the real CRS authority).
using CrsValidator = std::function<bool(std::string_view)>;
bool crs_parseable(const std::string& crs,
                   const CrsValidator& validator = nullptr);

// _iter_layer_coords: flatten all feature geometry coordinates to a
// MapPoint stream (feature records carry {"geometry": {...}}).
std::vector<MapPoint> iter_feature_coords(const std::vector<Json>& features);

}  // namespace pwb::ui_composite
