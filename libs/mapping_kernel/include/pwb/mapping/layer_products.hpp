#pragma once

// pwb::mapping — GeoJSON layer products, a faithful C++ port of the feature
// packing of paleo_workbench.mapping.geological_pipeline.contouring
// .generate_contour_layer and paleo_workbench.mapping.geological_pipeline
// .polygonization.generate_facies_polygon_layer (full-conversion plan M6,
// CONV-03 slice). Behavior is frozen against the Python implementation via
// committed oracle fixtures (tools/oracle/generate_layer_product_fixtures.py):
//   * contour properties in Python dict order: level / label_text /
//     is_index_contour / length / is_closed / factor / unit; label via
//     C "%g" formatting (Python f"{v:g}");
//   * is_index_contour: interval path uses Python `%` semantics (negative
//     operands land in [0, 5*interval)) + math.isclose(abs_tol=1e-5);
//     otherwise index % 5 == 0;
//   * is_closed via math.isclose defaults (rel_tol=1e-9) with abs_tol=1e-5;
//   * facies properties: facies_id / facies_name / facies / color / area /
//     area_unit / area_percent / mean_value (+ area_approx_m2 under a
//     geographic CRS); every rounded value uses Python round half-even at
//     4 decimals (round_to, frozen in the contouring kernel);
//   * mean_value replicates numpy's float32 mask mean (pairwise float32
//     summation, float32 division — pinned by the fixture mean_units cases);
//   * polygon_qc / contour_qc metadata incl. thresholds_source,
//     nodata_cells, total_cells, area_unit, area_warnings and
//     holes_promoted_to_exterior;
//   * CRS predicates delegate to crs_policy (geometry_units semantics: strip
//     first, unknown/empty → not geographic).
//
// NOT ported (see docs/development/cpp-conversion-swarm-20/ledgers/
// 03-decisions.md): the shapely-backed clip-to-ring path (Python hard-requires
// shapely; GEOS intersection coordinates cannot be reproduced bit-exactly in
// this Qt-free kernel) and layer styles / categories / ids (UI data).
// Shapely repair is identity-patched in the oracle freeze; this kernel
// emits the raw raster-trace geometry, exactly like polygonization.hpp.
// Qt-free, Python-free, numpy-free.

#include <pwb/domain/json.hpp>
#include <pwb/mapping/contouring.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/mapping/polygonization.hpp>

#include <optional>
#include <string>
#include <vector>

namespace pwb::mapping {

using pwb::domain::Json;

// Identity of the parent FactorGridResult that FactorGrid does not carry:
// feature properties ("factor" / "unit") and CRS-dependent unit labels.
struct LayerGridContext {
    std::string factor_name;
    std::string unit;  // "" = no unit (label_text drops the suffix)
    std::string crs;   // "" = undeclared (area_unit "unknown-unit²")
};

struct ContourLayerOptions {
    // Explicit levels (Python `levels=`); empty list → empty ladder.
    std::optional<std::vector<double>> levels;
    // Python `interval=`; used only when > 0, else quantile/nice applies.
    std::optional<double> interval;
    // "nice" | "quantile" (Python `leveling_mode=`).
    std::string leveling_mode = "nice";
    double simplify_tolerance = 0.0;
    int smooth_iterations = 0;
};

struct ContourLayerProduct {
    std::vector<double> levels;
    std::optional<double> contour_interval;
    std::vector<Json> features;  // GeoJSON Feature objects ({"type",
                                 //  "geometry", "properties"} in that order)
    Json contour_qc;             // {"clipped_to_domain": n,
                                 //  "empty_after_clip": n}
};

// Python generate_contour_layer with clip_ring/style/ids out of scope.
ContourLayerProduct generate_contour_layer_product(
    const FactorGrid& grid, const LayerGridContext& ctx,
    const ContourLayerOptions& options = {});

struct FaciesLayerOptions {
    std::optional<std::vector<double>> thresholds;
    std::optional<std::vector<std::string>> facies_names;
    std::optional<std::vector<std::string>> colors;
    std::optional<double> min_area;
};

struct FaciesLayerProduct {
    std::vector<Json> features;  // GeoJSON Feature objects (Polygon geometry)
    Json polygon_qc;
};

// Python generate_facies_polygon_layer with clip_ring/style/ids out of scope.
FaciesLayerProduct generate_facies_polygon_layer_product(
    const FactorGrid& grid, const LayerGridContext& ctx,
    const FaciesLayerOptions& options = {});

// float(np.mean(values)) on a float32 buffer: numpy pairwise float32
// summation, then a float32 division. Public so the oracle can pin the
// accumulator semantics the mean_value property depends on.
double float32_mask_mean(const std::vector<float>& values);

// geometry_units.area_unit_label: "deg²" / "{crs}-unit²" / "unknown-unit²".
std::string area_unit_label(const std::string& crs);

// geometry_units.is_geographic_crs: crs_policy predicate, unknown → false.
bool layer_crs_is_geographic(const std::string& crs);

}  // namespace pwb::mapping
