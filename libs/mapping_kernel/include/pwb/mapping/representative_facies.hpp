#pragma once

// pwb::mapping — well-facies descriptor leaf, a faithful C++ port of the
// pure-data parts of paleo_workbench/mapping/well_prediction_surface.py
// (full-conversion plan M6, CONV-10). Frozen against
// tools/oracle/generate_representative_facies_fixtures.py:
//   * representative_facies: per-facies (thickness, probability mass)
//     accumulation over interval dicts; winner = max by (total thickness,
//     mean probability), first-inserted wins ties; horizon filter is a
//     SUBSTRING match on stratigraphic_unit-or-horizon and is skipped
//     entirely when nothing matches;
//   * Python `or` truthy chains (facies/label/name, probability/confidence,
//     probability value chosen BEFORE the finite check — an unparseable
//     probability never falls back to confidence);
//   * point features / spatial point extraction with per-record filtering;
//   * point-to-surface polygon descriptors on the EXISTING
//     nearest_neighbor_class_grid + polygonize_class kernels (thresholds
//     [0.0] | [i+0.5], classify cap min(idx+1, n_names-1), default color
//     palette, round(v,4) half-even areas/percents/means, crs unit labels,
//     geographic area_approx_m2 with the 111320² mean-latitude scale).
// NOT ported (same precedent as the polygonization slice, recorded in the
// oracle notes): shapely repair_invalid_geometry (identity here) and the
// polygon-level clip-to-ring — the grid-level inclusive clip inside
// nearest_neighbor_class_grid is the C++ domain clip. Well-registry glue
// (well_xy / _wells_for_task / _points_from_intervals) stays Python-side.
// Qt-free, Python-free, numpy-free.

#include <pwb/mapping/class_grid.hpp>
#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/polygonization.hpp>
#include <pwb/domain/json.hpp>

#include <array>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::mapping {

using pwb::domain::Json;

// WellFaciesPoint from well_prediction_surface.py: a predicted facies at a
// planar well location (probability/thickness optional, like None).
struct WellFaciesPoint {
    double x = 0.0;
    double y = 0.0;
    std::string facies;
    std::string well_id;
    std::string well_name;
    std::optional<double> probability;
    std::string task_id;
    std::optional<double> thickness;
};

// representative_facies return: (facies, mean probability | none, thickness).
struct RepresentativeFacies {
    std::string facies;
    std::optional<double> mean_probability;
    double thickness = 0.0;
};

// Interval/region dicts (Json array of objects) → representative facies.
// Non-object entries are ignored; regions=null behaves like empty.
std::optional<RepresentativeFacies> representative_facies(
    const Json& regions, const std::string& horizon = "");

// result_summary → interval records: spatial.intervals or
// spatial.well_intervals when truthy, else predicted_regions; dicts only.
Json task_regions(const Json& result_summary);

// result_summary spatial Point features → well facies points (dicts whose
// geometry/coordinates/facies fail the filters are dropped, never errors).
std::vector<WellFaciesPoint> spatial_point_features(
    const Json& result_summary, const std::string& task_id);

// Well facies points → (geometry, properties) GeoJSON point descriptors.
// probability/thickness keys are ABSENT when unset (Python conditional keys).
std::vector<std::pair<Json, Json>> point_features(
    const std::vector<WellFaciesPoint>& points);

// Pure cores of _extent_from_workarea / _extent_from_points / _clip_ring:
// the project/workarea object stays host-side; callers pass the boundary.
// Non-finite vertices are dropped. workarea: <3 finite → nullopt, else bbox.
// points: throws std::invalid_argument when empty (Python would raise in
// min()); span clamped to >= 1.0 per axis, 10% padding outwards.
// clip ring: <4 finite vertices → empty (no clip).
std::optional<std::array<double, 4>> extent_from_workarea_boundary(
    const std::vector<Point>& boundary);
std::array<double, 4> extent_from_points(
    const std::vector<WellFaciesPoint>& points);
std::vector<Point> clip_ring_from_boundary(const std::vector<Point>& boundary);

// Well facies points → facies polygon (geometry, properties) GeoJSON
// descriptors, computed on the existing nearest_neighbor_class_grid kernel
// with the point_to_surface feature assembly of generate_facies_polygon_layer.
// The caller supplies what Python took from the project: extent (workarea
// bbox or padded points bbox), optional clip ring (grid-level NaN mask) and
// crs ("" = undeclared → "unknown-unit²"). Empty points → no features; a
// fully-clipped grid → no features.
std::vector<std::pair<Json, Json>> point_to_surface_features(
    const std::vector<WellFaciesPoint>& points,
    const std::array<double, 4>& extent,
    int grid_n = 80,
    const std::vector<Point>& clip_ring = {},
    const std::string& crs = "");

}  // namespace pwb::mapping
