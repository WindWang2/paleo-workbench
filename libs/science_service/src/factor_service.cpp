// pwb::science_service — factor interpolation service implementation.
// Composition of frozen kernels only; see factor_service.hpp for the chain
// map and the deliberate non-goals.

#include <pwb/factor_fusion/factor_units.hpp>
#include <pwb/factor_host/fingerprint.hpp>
#include <pwb/mapping/crs_contract.hpp>
#include <pwb/mapping/factor_grid_io.hpp>
#include <pwb/mapping/sample_normalization.hpp>
#include <pwb/science_service/factor_service.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

#include "support.hpp"

namespace pwb::science_service {

using pwb::domain::Json;
using pwb::mapping::FactorGrid;
using pwb::mapping::SamplePoint;

namespace {

// extract output -> the JSON record shape normalize_factor_samples consumes
// (x / y / value / well_id / qc_flag — the production sample_points shape).
Json points_to_sample_records(const std::vector<pwb::mapping::FactorPoint>& pts) {
    Json out = Json::array();
    for (const auto& p : pts) {
        Json rec = Json::object();
        rec["x"] = p.x;
        rec["y"] = p.y;
        rec["value"] = p.value;
        if (!p.well_id.empty()) {
            rec["well_id"] = p.well_id;
        }
        if (!p.qc_flag.empty() && p.qc_flag != "ok") {
            rec["qc_flag"] = p.qc_flag;
        }
        out.push_back(std::move(rec));
    }
    return out;
}

std::vector<SamplePoint> sample_records_to_points(const Json& records) {
    std::vector<SamplePoint> out;
    out.reserve(records.size());
    for (const auto& rec : records) {
        SamplePoint p;
        p.x = rec.value("x", 0.0);
        p.y = rec.value("y", 0.0);
        p.value = rec.value("value", rec.value("z", 0.0));
        p.qc_flag = rec.value("qc_flag", "ok");
        out.push_back(p);
    }
    return out;
}

Json normalization_report_json(const pwb::mapping::SampleNormalizationReport& r) {
    Json out = Json::object();
    out["policy"] = r.policy;
    out["n_input"] = r.n_input;
    out["n_valid"] = r.n_valid;
    out["n_nonfinite_dropped"] = r.n_nonfinite_dropped;
    out["n_duplicate_groups"] = r.n_duplicate_groups;
    out["n_duplicates_merged"] = r.n_duplicates_merged;
    out["n_qc_flagged"] = r.n_qc_flagged;
    out["duplicates_present"] = r.duplicates_present();
    return out;
}

}  // namespace

const ResourceLimits& ResourceLimits::defaults() {
    static const ResourceLimits kDefaults;
    return kDefaults;
}

std::string limit_code(const std::string& limit_name) {
    return "resource." + limit_name;
}

FactorInterpolationService::FactorInterpolationService(std::string build_identity,
                                                       ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<FactorInterpolationResult> FactorInterpolationService::run(
    const FactorInterpolationRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    // ---- stage 0: resource guards (fail closed before allocating) ----------
    if (request.well_records.size() > limits_.max_input_records) {
        return detail::make_error(
            limit_code("input_records"),
            "well_records size " + std::to_string(request.well_records.size())
                + " exceeds limit " + std::to_string(limits_.max_input_records));
    }
    if (!request.well_records.is_array() && !request.well_records.is_null()) {
        return detail::make_error("factor.records",
                                  "well_records must be a JSON array of records");
    }
    const int grid_n = request.interpolate.grid_n;
    if (grid_n < 2 || grid_n > limits_.max_grid_n) {
        return detail::make_error(
            limit_code("grid_n"),
            "grid_n " + std::to_string(grid_n) + " outside [2, "
                + std::to_string(limits_.max_grid_n) + "]");
    }
    if (static_cast<std::size_t>(grid_n) * static_cast<std::size_t>(grid_n)
        > limits_.max_grid_cells) {
        return detail::make_error(limit_code("grid_cells"),
                                  "grid_n^2 exceeds limit "
                                      + std::to_string(limits_.max_grid_cells));
    }
    if (request.use_constrained_idw) {
        const int res = request.constrained.grid_resolution;
        if (res < 4 || res > limits_.max_grid_n) {
            return detail::make_error(
                limit_code("grid_n"),
                "constrained grid_resolution " + std::to_string(res)
                    + " outside [4, " + std::to_string(limits_.max_grid_n)
                    + "]");
        }
        const bool has_boundary = !request.constrained_boundary.empty()
                                  || !request.interpolate.boundary.empty();
        if (!has_boundary) {
            return detail::make_error(
                "factor.constrained_boundary",
                "constrained_idw requires a boundary polygon "
                "(constrained_boundary or interpolate.boundary)");
        }
    }
    if (detail::stage_guard(stop, progress, 0.0, "validate")) {
        return science::TaskCancelled{"validate"};
    }

    // ---- stage 1: extract (well-table records -> factor dataset) ------------
    pwb::mapping::ExtractOptions extract_opts;
    extract_opts.unit = request.unit;
    extract_opts.crs = request.crs;
    const Json records =
        request.well_records.is_null() ? Json::array() : request.well_records;
    auto dataset = detail::catch_kernel<pwb::mapping::FactorDataset>(
        "factor.extract", [&] {
            return pwb::mapping::extract_factors(records, request.factor_name,
                                                 extract_opts);
        });
    if (dataset.is_error()) {
        return dataset.error();
    }
    if (dataset.is_cancelled()) {
        return dataset.cancelled();
    }
    if (detail::stage_guard(stop, progress, 0.15, "extract")) {
        return science::TaskCancelled{"extract"};
    }
    if (dataset.value().points.empty()) {
        return detail::make_error(
            "factor.no_samples",
            "factor '" + request.factor_name
                + "' produced no sample points from "
                + std::to_string(records.size()) + " records");
    }

    // ---- stage 2: duplicate-sample normalization ---------------------------
    const Json sample_records = points_to_sample_records(dataset.value().points);
    auto normalized = detail::catch_kernel<std::pair<Json, pwb::mapping::SampleNormalizationReport>>(
        "factor.normalize", [&] {
            return pwb::mapping::normalize_factor_samples(sample_records,
                                                          request.duplicate_policy);
        });
    if (normalized.is_error()) {
        return normalized.error();
    }
    if (normalized.is_cancelled()) {
        return normalized.cancelled();
    }
    if (detail::stage_guard(stop, progress, 0.35, "normalize")) {
        return science::TaskCancelled{"normalize"};
    }
    const auto& [points_json, norm_report] = normalized.value();
    const std::vector<SamplePoint> points = sample_records_to_points(points_json);

    // ---- stage 3: interpolate ----------------------------------------------
    std::shared_ptr<const FactorGrid> grid;
    Json constrained_diagnostics;
    if (request.use_constrained_idw) {
        // Engine B: the Haiyou constrained-IDW surface kernel (barriers via
        // exact EDT + LOS masking, well anchoring, declustering, gap fill).
        // Wells come from the normalized sample set; boundary/barriers/
        // directions pass through as geometry (host resolves task layers).
        auto constrained = detail::catch_kernel<
            pwb::mapping::constrained_idw::Result>(
            "factor.interpolate_constrained", [&] {
                std::vector<pwb::mapping::constrained_idw::Well> wells;
                wells.reserve(points.size());
                for (std::size_t i = 0; i < points.size(); ++i) {
                    pwb::mapping::constrained_idw::Well w;
                    const Json& rec = points_json.is_array()
                                          && i < points_json.size()
                                          ? points_json.at(i)
                                          : Json(nullptr);
                    w.well_id = rec.is_object()
                                    ? rec.value("well_id",
                                                std::string("w")
                                                    + std::to_string(i))
                                    : "w" + std::to_string(i);
                    w.x = points[i].x;
                    w.y = points[i].y;
                    w.value = points[i].value;
                    wells.push_back(std::move(w));
                }
                pwb::mapping::constrained_idw::BoundaryPolygon polygon;
                for (const auto& p : !request.constrained_boundary.empty()
                                          ? request.constrained_boundary
                                          : request.interpolate.boundary) {
                    polygon.exterior.push_back(
                        {p[0], p[1]});
                }
                std::vector<pwb::mapping::constrained_idw::BarrierLine>
                    barriers;
                for (std::size_t i = 0; i < request.barrier_lines.size();
                     ++i) {
                    pwb::mapping::constrained_idw::BarrierLine line;
                    line.line_id = "barrier_" + std::to_string(i);
                    for (const auto& p : request.barrier_lines[i]) {
                        line.points.push_back({p[0], p[1]});
                    }
                    barriers.push_back(std::move(line));
                }
                std::vector<pwb::mapping::constrained_idw::DirectionLine>
                    directions;
                for (std::size_t i = 0; i < request.direction_lines.size();
                     ++i) {
                    pwb::mapping::constrained_idw::DirectionLine line;
                    line.line_id = "direction_" + std::to_string(i);
                    for (const auto& p : request.direction_lines[i]) {
                        line.points.push_back({p[0], p[1]});
                    }
                    directions.push_back(std::move(line));
                }
                return pwb::mapping::constrained_idw::
                    generate_constrained_idw(wells, {polygon}, barriers,
                                             directions,
                                             request.constrained);
            });
        if (constrained.is_error()) {
            return constrained.error();
        }
        if (detail::stage_guard(stop, progress, 0.65, "interpolate")) {
            return science::TaskCancelled{"interpolate"};
        }
        FactorGrid fused;
        fused.grid_x = constrained.value().grid_x;
        fused.grid_y = constrained.value().grid_y;
        fused.grid_z.reserve(constrained.value().grid_z.size());
        for (double v : constrained.value().grid_z) {
            const float f = static_cast<float>(v);
            fused.grid_z.push_back(
                std::isfinite(f) ? f
                                 : std::numeric_limits<float>::quiet_NaN());
        }
        fused.algorithm_id = pwb::factor_host::kConstrainedIdwLabel;
        fused.method = "constrained_idw";
        fused.power = request.constrained.power;
        fused.grid_n = request.constrained.grid_resolution;
        fused.n_samples = static_cast<int>(points.size());
        fused.duplicates_merged = norm_report.n_duplicates_merged;
        fused.statistics =
            pwb::mapping::grid_statistics(fused.grid_z);
        for (const auto& [key, value] :
             constrained.value().diagnostics) {
            constrained_diagnostics[key] = value;
        }
        grid = std::make_shared<const FactorGrid>(std::move(fused));
    } else {
        auto grid_result =
            detail::catch_kernel<FactorGrid>("factor.interpolate", [&] {
                return pwb::mapping::interpolate_factor(points,
                                                        request.interpolate);
            });
        if (grid_result.is_error()) {
            return grid_result.error();
        }
        if (detail::stage_guard(stop, progress, 0.65, "interpolate")) {
            return science::TaskCancelled{"interpolate"};
        }
        grid = std::make_shared<const FactorGrid>(std::move(grid_result.value()));
    }

    // ---- stage 4: optional layer products ----------------------------------
    std::vector<science::Diagnostic> warnings;
    std::optional<pwb::mapping::ContourLayerProduct> contours;
    std::optional<pwb::mapping::FaciesLayerProduct> facies;
    if (request.include_layer_products) {
        pwb::mapping::LayerGridContext ctx;
        ctx.factor_name = dataset.value().factor_name;
        ctx.unit = dataset.value().unit;
        ctx.crs = dataset.value().crs;
        auto contour_res = detail::catch_kernel<pwb::mapping::ContourLayerProduct>(
            "factor.products", [&] {
                return pwb::mapping::generate_contour_layer_product(
                    *grid, ctx, request.contour_options);
            });
        if (contour_res.is_error()) {
            return contour_res.error();
        }
        if (contour_res.is_cancelled()) {
            return contour_res.cancelled();
        }
        contours = std::move(contour_res.value());
        auto facies_res = detail::catch_kernel<pwb::mapping::FaciesLayerProduct>(
            "factor.products", [&] {
                return pwb::mapping::generate_facies_polygon_layer_product(
                    *grid, ctx, request.facies_options);
            });
        if (facies_res.is_error()) {
            return facies_res.error();
        }
        if (facies_res.is_cancelled()) {
            return facies_res.cancelled();
        }
        facies = std::move(facies_res.value());
    }
    if (detail::stage_guard(stop, progress, 0.85, "products")) {
        return science::TaskCancelled{"products"};
    }

    // ---- stage 5: envelope --------------------------------------------------
    const std::array<double, 4> extent = pwb::mapping::dataset_extent(points);

    // Unit validation (factor_units whitelist) — Python collects problems as
    // task quality warnings, not failures; mirror that as warnings here.
    {
        std::vector<double> values;
        values.reserve(points.size());
        for (const auto& p : points) {
            values.push_back(p.value);
        }
        for (const std::string& problem : pwb::factor_fusion::
                 validate_factor_unit_against_values(
                     request.factor_name, dataset.value().unit, values)) {
            warnings.push_back(detail::warning_diag("factor.unit", problem));
        }
    }
    // CRS domain mismatch check — fail-open detection only (crs_contract).
    if (!dataset.value().crs.empty()) {
        if (auto mismatch = pwb::mapping::coordinate_domain_mismatch(
                dataset.value().crs, extent)) {
            warnings.push_back(detail::warning_diag("factor.crs_domain",
                                                    mismatch->describe()));
        }
    }

    ScienceEnvelope envelope;
    envelope.result_type = "factor_grid";
    envelope.units = dataset.value().unit;
    envelope.crs = dataset.value().crs;
    envelope.extent = extent;

    Json quality = Json::object();
    quality["grid"] = pwb::mapping::grid_statistics_to_json(grid->statistics);
    quality["normalization"] = normalization_report_json(norm_report);
    quality["n_samples"] = points.size();
    if (!constrained_diagnostics.is_null()) {
        quality["engine_diagnostics"] = constrained_diagnostics;
    }
    envelope.quality = std::move(quality);

    Json payload = Json::object();
    // Grid envelope descriptor (CONV-18 codec — metadata only, no arrays).
    pwb::mapping::FactorGridEnvelope grid_envelope;
    grid_envelope.height = static_cast<int>(grid->grid_y.size());
    grid_envelope.width = static_cast<int>(grid->grid_x.size());
    grid_envelope.grid_z = grid->grid_z;
    grid_envelope.variance_grid = grid->variance_grid;
    grid_envelope.grid_x = grid->grid_x;
    grid_envelope.grid_y = grid->grid_y;
    grid_envelope.factor_name = dataset.value().factor_name;
    grid_envelope.algorithm_id = grid->algorithm_id;
    grid_envelope.crs = dataset.value().crs.empty()
                            ? Json(nullptr)
                            : Json(dataset.value().crs);
    grid_envelope.unit = dataset.value().unit.empty()
                              ? Json(nullptr)
                              : Json(dataset.value().unit);
    grid_envelope.statistics = grid->statistics;
    payload["descriptor"] = pwb::mapping::to_descriptor(grid_envelope);
    const std::size_t grid_cells = grid->grid_z.size();
    if (grid_cells <= limits_.max_envelope_grid_cells) {
        payload["grid"] = pwb::mapping::to_legacy_dict(grid_envelope);
    } else {
        warnings.push_back(detail::warning_diag(
            "envelope.grid_omitted",
            "grid of " + std::to_string(grid_cells)
                + " cells exceeds envelope limit "
                + std::to_string(limits_.max_envelope_grid_cells)
                + "; descriptor-only envelope"));
    }
    if (contours) {
        Json contour_json = Json::object();
        contour_json["levels"] = contours->levels;
        contour_json["features"] = contours->features;
        contour_json["qc"] = contours->contour_qc;
        payload["contour_layer"] = std::move(contour_json);
    }
    if (facies) {
        Json facies_json = Json::object();
        facies_json["features"] = facies->features;
        facies_json["qc"] = facies->polygon_qc;
        payload["facies_layer"] = std::move(facies_json);
    }
    envelope.payload = std::move(payload);

    Json provenance = Json::object();
    provenance["algorithm_id"] = "mapping.factor_interpolate";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    provenance["factor_name"] = request.factor_name;
    provenance["engine"] = request.use_constrained_idw
                               ? pwb::factor_host::kConstrainedIdwLabel
                               : "interpolate_factor";
    provenance["interpolate"] = Json{
        {"method", request.interpolate.method},
        {"grid_n", request.interpolate.grid_n},
        {"power", request.interpolate.power},
        {"min_neighbors", request.interpolate.min_neighbors},
        {"variogram_model", request.interpolate.variogram_model},
        {"distance_policy", request.interpolate.distance_policy},
        {"boundary_points",
         static_cast<int>(request.interpolate.boundary.size())},
    };
    provenance["duplicate_policy"] = request.duplicate_policy;
    provenance["n_input_records"] = records.size();
    provenance["metadata"] = request.metadata;
    provenance["distance_policy_annotation"] =
        grid->distance_policy_annotation.empty()
            ? Json(nullptr)
            : Json(grid->distance_policy_annotation);
    envelope.provenance = std::move(provenance);

    for (const auto& w : warnings) {
        envelope.diagnostics.push_back(Json{
            {"code", w.code},
            {"severity", w.severity},
            {"message", w.message},
        });
    }
    envelope.compute_fingerprint();

    FactorInterpolationResult result;
    result.envelope = std::move(envelope);
    result.grid = std::move(grid);
    result.normalization_report = normalization_report_json(norm_report);
    result.contours = std::move(contours);
    result.facies = std::move(facies);

    detail::stage_guard(stop, progress, 1.0, "envelope");
    return result;
}

}  // namespace pwb::science_service
