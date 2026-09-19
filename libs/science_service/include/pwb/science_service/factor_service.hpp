#pragma once

// pwb::science_service — factor interpolation service (CONV-28): the native
// composition of the production Python chain
//   paleo_workbench/workflow/factor_interpolation.py::apply_interpolation_to_task
//   (numeric core): well/sample records -> extract -> duplicate-sample
//   normalization -> interpolate -> quality -> optional contour/facies
//   products -> result envelope.
//
// Composition only — every numeric step delegates to an already-frozen
// mapping_kernel / factor_fusion kernel:
//   extract_factors (extract.hpp, M6) ->
//   normalize_factor_samples (sample_normalization.hpp, M7) ->
//   interpolate_factor (interpolator.hpp, M6: IDW kNN/radius/all, numpy-OLS
//   ordinary kriging, even-odd domain mask, D5 CRS distance policy) ->
//   grid_statistics (interpolator.hpp) ->
//   generate_contour_layer_product / generate_facies_polygon_layer_product
//   (layer_products.hpp, CONV-03) ->
//   FactorGridEnvelope descriptor/legacy codec (factor_grid_io.hpp, CONV-18).
//
// NOT ported here (stays on the host/workflow line): geoviz WLS kriging
// engine, task-record mutation, live-grid store, NPZ artifact container,
// catalog registration (the publisher seam receives the envelope instead).
//
// Cancellation: checked at stage boundaries (extract/normalize/interpolate/
// products/envelope). The kernels themselves are not interruptible; the
// stop token linearizes between stages, which is the honest granularity for
// these sub-second medium-scale kernels.

#include <pwb/mapping/constrained_idw.hpp>
#include <pwb/mapping/extract.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/mapping/layer_products.hpp>
#include <pwb/science/algorithm.hpp>
#include <pwb/science/outcome.hpp>

#include <stop_token>

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "envelope.hpp"
#include "limits.hpp"

namespace pwb::science_service {

struct FactorInterpolationRequest {
    // Factor key, exactly as the extract kernel matches it (exact name,
    // "value"/"val", casefold aliases, derived sand_ratio/
    // formation_thickness).
    std::string factor_name;
    // Inline input DTO: JSON array of well-table record objects. May be empty
    // when the caller provides records through a payload source ref instead.
    pwb::domain::Json well_records = pwb::domain::Json::array();
    // Optional declared unit: nullopt -> FACTOR_DEFAULTS table lookup
    // (extract kernel), "" -> explicitly unitless.
    std::optional<std::string> unit;
    // Dataset CRS ("" = undeclared -> planar distance policy annotation).
    std::string crs;
    // Interpolation options (method idw|kriging|ordinary_kriging|ok, grid_n,
    // power, neighborhoods, variogram, boundary mask, distance policy).
    pwb::mapping::InterpolateOptions interpolate;
    // Duplicate-sample policy: mean | first | error | keep.
    std::string duplicate_policy = "mean";
    // Constrained-IDW engine (mapping::constrained_idw kernel, CONV-05):
    // when true the interpolation stage routes to generate_constrained_idw
    // (barriers via exact EDT + LOS masking, well anchoring, declustering)
    // instead of interpolate_factor. Requires >= 3 samples and a boundary
    // polygon (constrained_boundary, falling back to interpolate.boundary).
    bool use_constrained_idw = false;
    pwb::mapping::constrained_idw::Config constrained;
    std::vector<std::vector<std::array<double, 2>>> barrier_lines;
    std::vector<std::vector<std::array<double, 2>>> direction_lines;
    std::vector<std::array<double, 2>> constrained_boundary;
    // Constrained-engine overrides. nullopt = DERIVE FROM THE SAMPLES, the
    // production Python semantics (constrained_idw_adapter):
    //   value range   <- finite sample min/max (+tiny pad)
    //   search radius <- 1.05 * sample-bbox diagonal, >= 0.75 * span
    //   decluster     <- 0.15 * search radius (forced to 0 with directions)
    //   resolution    <- grid_n clamped into [20, 200]
    // The kernel Config defaults (value [0,1], search 10000, decluster 6500)
    // are NEVER used implicitly — they would silently clamp real factor
    // fields. An explicit value here wins over the derivation — except
    // constrained_decluster_radius with active direction lines, where the
    // production recipe forces declustering off (Python parity).
    std::optional<double> constrained_value_min;
    std::optional<double> constrained_value_max;
    std::optional<double> constrained_search_radius;
    std::optional<double> constrained_decluster_radius;
    std::optional<int> constrained_grid_resolution;
    // Also produce contour + facies GeoJSON layer products.
    bool include_layer_products = false;
    pwb::mapping::ContourLayerOptions contour_options;
    pwb::mapping::FaciesLayerOptions facies_options;
    // Pass-through metadata merged into provenance (task id, horizon, ...).
    pwb::domain::Json metadata = pwb::domain::Json::object();
};

struct FactorInterpolationResult {
    ScienceEnvelope envelope;
    // Owning grid (shared so a ProducedVolume view can alias it through the
    // publish phase without a copy).
    std::shared_ptr<const pwb::mapping::FactorGrid> grid;
    pwb::domain::Json normalization_report = pwb::domain::Json::object();
    std::optional<pwb::mapping::ContourLayerProduct> contours;
    std::optional<pwb::mapping::FaciesLayerProduct> facies;
};

class FactorInterpolationService {
public:
    explicit FactorInterpolationService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    [[nodiscard]] const std::string& build_identity() const {
        return build_identity_;
    }

    // Runs the full chain. Never throws: kernel exceptions map to
    // AlgorithmError diagnostics with stable codes
    // (factor.extract / factor.normalize / factor.interpolate /
    // factor.products / resource.*).
    [[nodiscard]] science::Result<FactorInterpolationResult> run(
        const FactorInterpolationRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

}  // namespace pwb::science_service
