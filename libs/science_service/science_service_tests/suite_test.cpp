// science_service.suite — typed service tests (CONV-28): factor pipeline,
// well services, fusion, geomodel services, payload source, publishers,
// resource guards, cancellation, fingerprint determinism.

#include <unistd.h>

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <stop_token>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/export_contract.hpp>
#include <pwb/science_service/envelope.hpp>
#include <pwb/science_service/facies_service.hpp>
#include <pwb/science_service/factor_service.hpp>
#include <pwb/science_service/fusion_service.hpp>
#include <pwb/science_service/geomodel_service.hpp>
#include <pwb/science_service/payload.hpp>
#include <pwb/science_service/publisher.hpp>
#include <pwb/science_service/registry.hpp>
#include <pwb/science_service/well_service.hpp>

using namespace pwb::science_service;
namespace science = pwb::science;
using pwb::domain::Json;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

Json sample_records() {
    Json records = Json::array();
    records.push_back(Json{{"well_id", "w1"},
                           {"name", "Well-1"},
                           {"x", 0.0},
                           {"y", 0.0},
                           {"value", 10.0}});
    records.push_back(Json{{"well_id", "w2"},
                           {"name", "Well-2"},
                           {"x", 10.0},
                           {"y", 0.0},
                           {"value", 20.0}});
    records.push_back(Json{{"well_id", "w3"},
                           {"name", "Well-3"},
                           {"x", 0.0},
                           {"y", 10.0},
                           {"value", 30.0}});
    records.push_back(Json{{"well_id", "w4"},
                           {"name", "Well-4"},
                           {"x", 10.0},
                           {"y", 10.0},
                           {"value", 40.0}});
    return records;
}

// ---------------------------------------------------------------------------

void test_factor_pipeline() {
    FactorInterpolationService svc{"test-build"};

    FactorInterpolationRequest req;
    req.factor_name = "gr";
    req.well_records = sample_records();
    req.interpolate.grid_n = 12;
    req.include_layer_products = true;

    auto res = svc.run(req);
    check(res.has_value(), "factor: happy path has value");
    if (!res.has_value()) {
        if (res.is_error()) {
            std::fprintf(stderr, "  error: %s\n",
                         res.error().diagnostics.at(0).message.c_str());
        }
        return;
    }
    auto& value = res.value();
    check(value.grid && value.grid->grid_z.size() == 12u * 12u,
          "factor: grid size 12x12");
    check(value.envelope.result_type == "factor_grid",
          "factor: envelope result_type");
    check(value.envelope.payload.contains("descriptor"),
          "factor: payload descriptor present");
    check(value.envelope.payload.contains("grid"),
          "factor: payload grid present");
    check(value.envelope.payload.contains("contour_layer"),
          "factor: contour layer product present");
    check(value.envelope.payload.contains("facies_layer"),
          "factor: facies layer product present");
    check(value.envelope.quality.contains("grid"),
          "factor: quality grid stats");
    check(value.envelope.quality.at("normalization").at("policy") == "mean",
          "factor: normalization policy recorded");
    check(value.envelope.extent.has_value(), "factor: extent present");
    check(!value.envelope.fingerprint.empty(), "factor: fingerprint present");
    check(value.envelope.fingerprint.size() == 64, "factor: fingerprint sha256");
    // Provenance round fields.
    check(value.envelope.provenance.at("algorithm_id")
              == "mapping.factor_interpolate",
          "factor: provenance algorithm_id");

    // Fingerprint determinism: identical request -> identical fingerprint.
    auto res2 = svc.run(req);
    check(res2.has_value()
              && res2.value().envelope.fingerprint
                     == value.envelope.fingerprint,
          "factor: fingerprint deterministic");
    // Different params -> different fingerprint.
    req.interpolate.grid_n = 9;
    auto res3 = svc.run(req);
    check(res3.has_value()
              && res3.value().envelope.fingerprint
                     != value.envelope.fingerprint,
          "factor: fingerprint param-sensitive");
}

void test_factor_duplicates_and_errors() {
    FactorInterpolationService svc;

    // Twin wells merge under "mean".
    FactorInterpolationRequest req;
    req.factor_name = "gr";
    req.well_records = sample_records();
    Json twin = Json{{"well_id", "w5"},
                     {"x", 0.0},
                     {"y", 0.0},
                     {"value", 50.0}};
    req.well_records.push_back(twin);
    auto res = svc.run(req);
    check(res.has_value(), "factor: twins mean runs");
    if (res.has_value()) {
        check(res.value().envelope.quality.at("normalization")
                  .at("n_duplicate_groups")
              == 1,
              "factor: twin duplicate group counted");
        check(res.value().envelope.quality.at("normalization")
                  .at("n_duplicates_merged")
              == 1,
              "factor: twin merged");
    }

    // "error" policy refuses the twins with the frozen Python message.
    req.duplicate_policy = "error";
    auto res_err = svc.run(req);
    check(res_err.is_error(), "factor: policy=error refuses duplicates");
    if (res_err.is_error()) {
        check(res_err.error().diagnostics.at(0).code == "factor.normalize",
              "factor: error code factor.normalize");
        check(res_err.error().diagnostics.at(0).message.find(
                  "duplicate sample locations") != std::string::npos,
              "factor: frozen duplicate message");
    }

    // Empty records -> no-samples error (not a crash, not an empty grid).
    FactorInterpolationRequest empty_req;
    empty_req.factor_name = "gr";
    auto res_empty = svc.run(empty_req);
    check(res_empty.is_error(), "factor: empty records error");
    if (res_empty.is_error()) {
        check(res_empty.error().diagnostics.at(0).code == "factor.no_samples",
              "factor: empty code factor.no_samples");
    }

    // Unknown factor name on records that carry NO value keys -> the
    // extract value lookup finds nothing -> clean no-samples error.
    FactorInterpolationRequest unknown_req;
    unknown_req.factor_name = "not_a_factor";
    unknown_req.well_records = Json::array(
        {Json{{"well_id", "w1"}, {"x", 0.0}, {"y", 0.0}, {"gr", 5.0}},
         Json{{"well_id", "w2"}, {"x", 10.0}, {"y", 10.0}, {"gr", 6.0}}});
    auto res_unknown = svc.run(unknown_req);
    check(res_unknown.is_error(), "factor: valueless records error");
    if (res_unknown.is_error()) {
        check(res_unknown.error().diagnostics.at(0).code
                  == "factor.no_samples",
              "factor: valueless records no_samples");
    }
    // ...and a factor name that IS the record key extracts directly.
    FactorInterpolationRequest keyed_req;
    keyed_req.factor_name = "thickness_m";
    keyed_req.well_records = Json::array(
        {Json{{"x", 0.0}, {"y", 0.0}, {"thickness_m", 5.0}},
         Json{{"x", 10.0}, {"y", 10.0}, {"thickness_m", 6.0}}});
    keyed_req.interpolate.grid_n = 8;
    auto keyed = svc.run(keyed_req);
    check(keyed.has_value(), "factor: keyed factor extracts");

    // Single point: the interpolation kernel refuses (< 2 valid points) with
    // the frozen Python message (pinned by the service oracle too).
    FactorInterpolationRequest single_req;
    single_req.factor_name = "gr";
    single_req.well_records = Json::array(
        {Json{{"x", 0.0}, {"y", 0.0}, {"value", 7.0}}});
    auto res_single = svc.run(single_req);
    check(res_single.is_error(), "factor: single point refused");
    if (res_single.is_error()) {
        check(res_single.error().diagnostics.at(0).code
                  == "factor.interpolate",
              "factor: single point code factor.interpolate");
    }
}

void test_factor_resource_and_cancel() {
    FactorInterpolationService svc;

    FactorInterpolationRequest req;
    req.factor_name = "gr";
    req.well_records = sample_records();
    req.interpolate.grid_n = 3000;  // > default max_grid_n (2000)
    auto res = svc.run(req);
    check(res.is_error(), "factor: grid_n guard triggers");
    if (res.is_error()) {
        check(res.error().diagnostics.at(0).code == "resource.grid_n",
              "factor: grid_n guard code");
    }

    // Cancellation at a stage boundary (pre-stopped token).
    FactorInterpolationRequest ok_req;
    ok_req.factor_name = "gr";
    ok_req.well_records = sample_records();
    std::stop_source stop_source;
    stop_source.request_stop();
    auto cancelled = svc.run(ok_req, nullptr, stop_source.get_token());
    check(cancelled.is_cancelled(), "factor: pre-stopped token cancels");
    if (cancelled.is_cancelled()) {
        check(!cancelled.cancelled().stage.empty(),
              "factor: cancelled stage named");
    }
}

void test_factor_constrained_engine() {
    FactorInterpolationService svc;

    FactorInterpolationRequest req;
    req.factor_name = "gr";
    req.well_records = sample_records();  // values 10..40
    req.use_constrained_idw = true;
    req.interpolate.grid_n = 25;  // maps to engine resolution 25
    req.interpolate.power = 3.0;  // task power feeds the engine too
    req.constrained_boundary = {{0.0, 0.0},
                                {12.0, 0.0},
                                {12.0, 12.0},
                                {0.0, 12.0}};
    auto res = svc.run(req);
    check(res.has_value(), "constrained: runs");
    if (res.has_value()) {
        auto& value = res.value();
        // The derived value range [~10, ~40] must NOT clamp the surface to
        // the kernel's [0,1] default (the Python host-integration contract).
        const auto& stats = value.grid->statistics;
        check(stats.max > 5.0,
              "constrained: values not clamped to [0,1]");
        check(stats.min >= 9.0 && stats.max <= 41.0,
              "constrained: values within derived sample range");
        check(value.envelope.provenance.at("engine") == "constrained_idw",
              "constrained: engine provenance");
        check(std::fabs(value.grid->power - 3.0) < 1e-12,
              "constrained: task power reaches the engine");
        check(value.grid->algorithm_id == "constrained_idw",
              "constrained: algorithm id");
        check(static_cast<int>(value.grid->grid_x.size()) == 25,
              "constrained: resolution from grid_n");
        check(value.envelope.quality.contains("engine_diagnostics"),
              "constrained: engine diagnostics recorded");
    }

    // keep policy refused with the frozen Python message.
    FactorInterpolationRequest keep_req = req;
    keep_req.duplicate_policy = "keep";
    auto keep = svc.run(keep_req);
    check(keep.is_error(), "constrained: keep policy refused");
    if (keep.is_error()) {
        check(keep.error().diagnostics.at(0).code
                  == "factor.constrained_policy",
              "constrained: keep policy code");
        check(keep.error().diagnostics.at(0).message.find(
                  "duplicate_policy='keep'")
                  != std::string::npos,
              "constrained: keep policy frozen message");
    }

    // Boundary is mandatory for this engine.
    FactorInterpolationRequest no_boundary;
    no_boundary.factor_name = "gr";
    no_boundary.well_records = sample_records();
    no_boundary.use_constrained_idw = true;
    auto missing = svc.run(no_boundary);
    check(missing.is_error(), "constrained: boundary required");
    if (missing.is_error()) {
        check(missing.error().diagnostics.at(0).code
                  == "factor.constrained_boundary",
              "constrained: boundary code");
    }
}

void test_well_services() {
    CurveOperationService curve_svc;
    CurveOperationRequest req;
    req.operation = "resample";
    req.params = Json{{"step", 0.5}};
    req.depth = {0.0, 0.3, 0.7, 1.1, 1.6};
    req.values = {10.0, 11.0, 12.0, 13.0, 14.0};
    auto res = curve_svc.run(req);
    check(res.has_value(), "curve: resample runs");
    if (res.has_value()) {
        auto& value = res.value();
        check(value.depth.size() == 4, "curve: resampled axis length 4");
        check(std::fabs(value.depth.at(0) - 0.0) < 1e-12
                  && std::fabs(value.depth.at(3) - 1.5) < 1e-12,
              "curve: resampled axis values");
        check(value.values.size() == 4, "curve: resampled curve length");
        check(std::fabs(value.values.at(1) - 11.5) < 1e-9,
              "curve: interpolated value at 0.5");
        check(value.envelope.result_type == "curve_operation",
              "curve: envelope type");
    }

    // Unknown operation -> stable error listing registry names.
    CurveOperationRequest bad;
    bad.operation = "quantize";
    bad.values = {1.0, 2.0};
    auto bad_res = curve_svc.run(bad);
    check(bad_res.is_error(), "curve: unknown op rejected");
    if (bad_res.is_error()) {
        check(bad_res.error().diagnostics.at(0).code == "well.unknown_operation",
              "curve: unknown op code");
    }

    // Length mismatch -> error before kernel.
    CurveOperationRequest mismatch;
    mismatch.operation = "median_filter";
    mismatch.params = Json{{"window", 3}};
    mismatch.depth = {0.0, 0.5};
    mismatch.values = {1.0, 2.0, 3.0};
    auto mismatch_res = curve_svc.run(mismatch);
    check(mismatch_res.is_error(), "curve: length mismatch rejected");

    // Depth shift on a foot axis converts the metre delta (kernel contract).
    CurveOperationRequest shift;
    shift.operation = "depth_shift";
    shift.params = Json{{"delta_m", 1.0}};
    shift.depth = {100.0, 101.0};
    shift.values = {5.0, 6.0};
    shift.axis_unit = "ft";
    auto shift_res = curve_svc.run(shift);
    check(shift_res.has_value(), "curve: depth_shift ft runs");
    if (shift_res.has_value()) {
        // 1 m = 3.280839895013123 ft
        check(std::fabs(shift_res.value().depth.at(0)
                        - (100.0 + 1.0 / 0.3048))
                  < 1e-9,
              "curve: depth_shift ft conversion");
    }

    // Unit conversion whitelist: m -> ft known factor.
    CurveOperationRequest convert;
    convert.operation = "unit_conversion";
    convert.params = Json{{"unused", true}};
    convert.values = {1.0, 2.0};
    convert.from_unit = "m";
    convert.to_unit = "ft";
    auto convert_res = curve_svc.run(convert);
    check(convert_res.has_value(), "curve: convert m->ft runs");
    if (convert_res.has_value()) {
        check(std::fabs(convert_res.value().values.at(0) - (1.0 / 0.3048))
                  < 1e-9,
              "curve: convert m->ft factor");
    }

    // Missing required param (resample needs step).
    CurveOperationRequest no_param;
    no_param.operation = "resample";
    no_param.depth = {0.0, 1.0};
    no_param.values = {1.0, 2.0};
    auto no_param_res = curve_svc.run(no_param);
    check(no_param_res.is_error(), "curve: missing param rejected");
    if (no_param_res.is_error()) {
        check(no_param_res.error().diagnostics.at(0).code == "well.missing_param",
              "curve: missing param code");
    }

    // Log match: correlated curves -> finite cost, non-empty path.
    LogMatchService match_svc;
    LogMatchRequest match;
    match.reference = {0.0, 1.0, 2.0, 1.0, 0.0, -1.0, 0.0, 1.0};
    match.target = {0.0, 1.0, 2.0, 1.0, 0.0, -1.0, 0.0};
    auto match_res = match_svc.run(match);
    check(match_res.has_value(), "log_match: runs");
    if (match_res.has_value()) {
        auto& value = match_res.value();
        check(std::isfinite(value.cost) && value.cost >= 0.0,
              "log_match: finite non-negative cost");
        check(!value.path_reference.empty(), "log_match: path non-empty");
        check(value.path_reference.size() == value.path_target.size(),
              "log_match: path lengths equal");
        const std::int64_t top = LogMatchService::transfer_top(value, 3);
        check(top >= 0 && top < static_cast<std::int64_t>(match.target.size()),
              "log_match: transfer_top in range");
    }

    // Empty curves -> kernel guard: cost=+inf, empty paths (no fabrication).
    LogMatchRequest empty_match;
    auto empty_res = match_svc.run(empty_match);
    check(empty_res.has_value(), "log_match: empty runs");
    if (empty_res.has_value()) {
        check(std::isinf(empty_res.value().cost)
                  && empty_res.value().path_reference.empty(),
              "log_match: empty stays +inf with no path");
    }
}

void test_fusion_service() {
    // Build two tiny legacy grids (2x2).
    auto legacy = [](std::vector<std::vector<double>> z) {
        return Json{
            {"grid_x", Json::array({0.0, 1.0})},
            {"grid_y", Json::array({0.0, 1.0})},
            {"grid_z", Json::array({Json::array({z[0][0], z[0][1]}),
                                    Json::array({z[1][0], z[1][1]})})}};
    };
    FactorFusionRequest req;
    req.model_dict = Json{
        {"name", "m1"},
        {"kind", "weighted_evidence"},
        {"default_class", "undetermined"},
        {"class_names", Json::array({"sand", "shale"})},
        {"class_thresholds", Json::array({0.5})},
        {"evidences",
         Json::array({Json{{"factor_name", "sand"},
                           {"weight", 1.0},
                           {"normalization",
                            Json{{"kind", "minmax"}, {"low", 0.0}, {"high", 1.0}}}},
                      Json{{"factor_name", "shale"},
                           {"weight", 1.0},
                           {"normalization",
                            Json{{"kind", "minmax"}, {"low", 0.0}, {"high", 1.0}}}}})}};
    req.grids = Json{{"sand", legacy({{0.2, 0.4}, {0.6, 0.8}})},
                     {"shale", legacy({{0.8, 0.6}, {0.4, 0.2}})}};

    FactorFusionService svc;
    auto res = svc.run(req);
    check(res.has_value(), "fusion: weighted runs");
    if (res.has_value()) {
        auto& value = res.value();
        check(value.envelope.result_type == "factor_fusion",
              "fusion: envelope type");
        check(value.envelope.payload.contains("likelihood"),
              "fusion: likelihood present");
        check(value.fusion.class_names.size() >= 2,
              "fusion: class names populated");
    }

    // Missing grid -> frozen ValueError path (error, not crash).
    req.grids = Json{{"sand", legacy({{0.2, 0.4}, {0.6, 0.8}})}};
    auto missing = svc.run(req);
    check(missing.is_error(), "fusion: missing grid errors");
}

Json horizon(double z_value) {
    return Json{{"rows", 3},
                {"cols", 3},
                {"origin", Json::array({0.0, 0.0})},
                {"spacing", Json::array({1.0, 1.0})},
                {"vertical_domain", "depth"},
                {"unit", "m"},
                {"z", Json::array({Json::array({z_value, z_value, z_value}),
                                   Json::array({z_value, z_value, z_value}),
                                   Json::array({z_value, z_value, z_value})})}};
}

void test_geomodel_services() {
    GeomodelBuildService build_svc;
    GeomodelBuildRequest req;
    req.top = horizon(10.0);
    req.base = horizon(20.0);
    req.object_id = "vol:test";
    req.build_hex = true;
    auto res = build_svc.run(req);
    check(res.has_value(), "geomodel: build runs");
    if (res.has_value()) {
        auto& value = res.value();
        check(value.shell.thicknesses.size() == 4,
              "geomodel: 2x2 cell thicknesses");
        for (double t : value.shell.thicknesses) {
            check(std::fabs(t - 10.0) < 1e-12, "geomodel: thickness 10");
        }
        check(std::fabs(value.envelope.quality.at("volume").get<double>()
                        - 40.0)
                  < 1e-6,
              "geomodel: closed volume 40");
        check(value.hex.has_value() && value.hex->info.n_hexes == 16,
              "geomodel: hex 2x2x4=16");
        check(value.shell.qc.closed, "geomodel: shell closed");
    }

    // Crossed horizons -> columns dropped + counted, never reordered.
    GeomodelBuildRequest crossed;
    crossed.top = horizon(30.0);
    crossed.base = horizon(20.0);
    auto crossed_res = build_svc.run(crossed);
    check(crossed_res.has_value(), "geomodel: crossed runs (drops columns)");
    if (crossed_res.has_value()) {
        check(crossed_res.value().shell.qc.dropped_crossed >= 1,
              "geomodel: crossed columns dropped");
    }

    // Section extraction through the x=1 plane.
    GeomodelSectionService section_svc;
    GeomodelSectionRequest section;
    section.source = horizon(10.0);
    section.plane = Json{{"axis", "x"}, {"value", 1.0}};
    auto section_res = section_svc.run(section);
    check(section_res.has_value(), "geomodel: section runs");
    if (section_res.has_value()) {
        check(!section_res.value().polylines.empty(),
              "geomodel: section polylines non-empty");
        check(section_res.value().polylines.at(0).size() == 3,
              "geomodel: section line spans 3 nodes");
    }

    // Fault displacement moves vertices near the line.
    FaultDisplacementService fault_svc;
    FaultDisplacementRequest fault;
    fault.mesh = Json{{"verts", Json::array({Json::array({0.0, 0.0, 5.0}),
                                             Json::array({5.0, 0.0, 5.0})})},
                      {"faces", Json::array()}};
    fault.spec = Json{{"fault_line", Json::array({Json::array({0.0, -10.0}),
                                                  Json::array({0.0, 10.0})})},
                       {"throw_z", 5.0},
                       {"throw_x", 0.0},
                       {"dip_deg", 90.0},
                       {"strike_deg", 0.0},
                       {"decay_radius", 100.0}};
    auto fault_res = fault_svc.run(fault);
    check(fault_res.has_value(), "geomodel: fault runs");
    if (fault_res.has_value()) {
        const Json& verts = fault_res.value().payload.at("verts");
        check(verts.size() == 2, "geomodel: fault vertices out");
        bool moved = false;
        for (const auto& v : verts) {
            if (std::fabs(v.at(2).get<double>() - 5.0) > 1e-9) {
                moved = true;
            }
        }
        check(moved, "geomodel: fault throw applied");
    }

    // Export: volume obj bytes + sidecar; read-back counts agree.
    GeomodelExportService export_svc;
    GeomodelExportRequest export_req;
    export_req.object = Json{{"kind", "volume"},
                             {"top", horizon(10.0)},
                             {"base", horizon(20.0)},
                             {"object_id", "volume:export"},
                             {"crs", "EPSG:32633"}};
    export_req.format = "obj";
    export_req.out_name = "model.obj";
    auto export_res = export_svc.run(export_req);
    check(export_res.has_value(), "geomodel: export obj runs");
    if (export_res.has_value()) {
        auto& value = export_res.value();
        check(value.file_bytes.find("v ") != std::string::npos,
              "geomodel: obj has vertices");
        check(!value.sidecar.is_null(), "geomodel: sidecar present");
        // Read-back validator parses the exact bytes we produced.
        const Json read =
            pwb::geomodel::read_obj(value.file_bytes, "model.obj");
        check(read.at("vertex_count").get<long long>() > 0,
              "geomodel: obj read-back vertex count");
    }

    // QC gate: an empty-mesh object must refuse the export.
    GeomodelExportRequest bad;
    bad.object = Json{{"kind", "volume"},
                      {"top", horizon(30.0)},
                      {"base", horizon(20.0)},
                      {"object_id", "volume:crossed"},
                             {"crs", "EPSG:32633"}};
    bad.format = "obj";
    bad.out_name = "bad.obj";
    auto bad_res = export_svc.run(bad);
    check(bad_res.is_error(), "geomodel: export gate refuses empty mesh");
}

void test_facies_surface_service() {
    FaciesSurfaceService svc;
    FaciesSurfaceRequest req;
    req.grid_n = 20;
    req.well_points = Json::array(
        {Json{{"x", 0.0}, {"y", 0.0}, {"facies", "sand"}, {"well_id", "w1"}},
         Json{{"x", 10.0}, {"y", 0.0}, {"facies", "shale"}, {"well_id", "w2"}},
         Json{{"x", 0.0}, {"y", 10.0}, {"facies", "sand"}, {"well_id", "w3"}},
         Json{{"x", 10.0}, {"y", 10.0}, {"facies", "sand"}, {"well_id", "w4"}}});
    auto res = svc.run(req);
    check(res.has_value(), "facies: surface runs");
    if (res.has_value()) {
        auto& value = res.value();
        check(value.points.size() == 4, "facies: 4 points parsed");
        check(!value.surface_layer.empty(), "facies: surface polygons");
        check(!value.point_layer.empty(), "facies: point features");
        check(value.envelope.quality.at("n_points") == 4,
              "facies: quality n_points");
        check(value.envelope.result_type == "facies_surface",
              "facies: envelope type");
    }

    // No points anywhere -> clean error.
    FaciesSurfaceRequest empty_req;
    empty_req.grid_n = 10;
    auto empty = svc.run(empty_req);
    check(empty.is_error(), "facies: no points errors");
    if (empty.is_error()) {
        check(empty.error().diagnostics.at(0).code == "facies.no_points",
              "facies: no points code");
    }

    // Representative facies vote over interval records via result summary.
    FaciesSurfaceRequest vote_req;
    vote_req.grid_n = 10;
    // thickness derives from top/bottom depth keys (kernel contract), not
    // a literal thickness field.
    Json intervals = Json::array(
        {Json{{"stratigraphic_unit", "S1"},
              {"facies", "sand"},
              {"top", 100.0},
              {"bottom", 112.0},
              {"probability", 0.8}},
         Json{{"stratigraphic_unit", "S1"},
              {"facies", "shale"},
              {"top", 112.0},
              {"bottom", 116.0},
              {"probability", 0.9}}});
    Json features = Json::array(
        {Json{{"geometry",
               Json{{"type", "Point"},
                    {"coordinates", Json::array({0.0, 0.0})}}},
              {"properties", Json{{"facies", "sand"},
                                   {"well_id", "w1"}}}}});
    vote_req.result_summary =
        Json{{"spatial", Json{{"intervals", intervals},
                              {"features", features}}}};
    auto vote = svc.run(vote_req);
    check(vote.has_value(), "facies: summary vote runs");
    if (vote.has_value()) {
        check(vote.value().representative.has_value()
                  && vote.value().representative->facies == "sand",
              "facies: representative sand wins by thickness");
        check(vote.value().points.size() == 1,
              "facies: spatial point extracted");
    }
}

void test_payload_source_and_publisher() {
    InMemoryPayloadSource source;
    source.put_table("dver_1", sample_records());
    science::VersionRef ref;
    ref.version_id = "dver_1";
    auto payload = source.resolve(ref);
    check(payload.has_value() && payload.value().kind == Payload::Kind::table,
          "payload: table resolves");
    check(payload.value().table.size() == 4, "payload: table rows");

    science::VersionRef missing;
    missing.version_id = "dver_absent";
    auto missing_payload = source.resolve(missing);
    check(missing_payload.is_error(), "payload: missing ref errors");

    // Unavailable source fails closed with a stable code.
    UnavailablePayloadSource unavailable;
    auto unavailable_payload = unavailable.resolve(ref);
    check(unavailable_payload.is_error(), "payload: unavailable source errors");

    // Directory publisher layout + failure path.
    const std::filesystem::path tmp =
        std::filesystem::temp_directory_path()
        / ("pwb-science-service-test-"
           + std::to_string(::getpid()));
    std::filesystem::remove_all(tmp);
    {
        DirectoryEnvelopePublisher publisher(tmp);
        science::AlgorithmResultV1 result;
        result.request_id = "req-abc/../x";
        result.records.push_back(
            science::ProducedRecord{"envelope", "application/json", "{}"});
        publisher.publish_success(result);
        science::IResultPublisherV1::Failure failure;
        failure.request_id = "req-fail";
        failure.code = "factor.no_samples";
        failure.message = "no samples";
        publisher.publish_failure(failure);

        const std::filesystem::path dir =
            tmp / "req-abc_.._x";  // '/' sanitized away
        check(std::filesystem::exists(dir / "envelope.json"),
              "publisher: sanitized request dir + envelope.json");
        check(std::filesystem::exists(dir / "result.json"),
              "publisher: result.json");
        check(std::filesystem::exists(tmp / "req-fail" / "failure.json"),
              "publisher: failure.json");
    }
    std::filesystem::remove_all(tmp);
}

void test_capture_publisher() {
    // In-memory capture: workflow adapters that keep results in-process.
    InMemoryCapturePublisher capture;
    science::AlgorithmResultV1 result;
    result.request_id = "req-cap";
    result.records.push_back(
        science::ProducedRecord{"envelope", "application/json", "{}"});
    capture.publish_success(result);
    science::IResultPublisherV1::Failure failure;
    failure.request_id = "req-cap-f";
    failure.code = "x";
    failure.message = "m";
    capture.publish_failure(failure);
    check(capture.successes().size() == 1
              && capture.successes().at(0).request_id == "req-cap",
          "capture: success captured");
    check(capture.failures().size() == 1
              && capture.failures().at(0).code == "x",
          "capture: failure captured");
}

void test_registry_and_node_request() {
    auto source = std::make_shared<InMemoryPayloadSource>();
    science::AlgorithmRegistry registry;
    const std::vector<std::string> ids =
        register_science_services(registry, source, "test-build");
    check(ids.size() == 10, "registry: 10 services registered");
    check(registry.find("mapping.factor_interpolate") != nullptr,
          "registry: factor interpolate findable");
    check(registry.find("geomodel.export") != nullptr,
          "registry: geomodel export findable");

    // Descriptor shape validation happens in the SDK registry.
    const auto* factor = registry.find("mapping.factor_interpolate");
    check(factor->descriptor().supports_cancel, "registry: factor cancelable");
    check(factor->descriptor().build_identity == "test-build",
          "registry: build identity stamped");
    const auto* geomodel_export = registry.find("geomodel.export");
    check(geomodel_export != nullptr
              && geomodel_export->descriptor().build_identity
                     == "test-build",
          "registry: geomodel build identity stamped");
    check(registry.find("geomodel.fault_displacement") != nullptr,
          "registry: fault displacement registered");

    // node_request mapping: object values copied as JSON texts.
    const Json node_params = Json{{"factor_name", "gr"},
                                  {"grid_n", 12},
                                  {"include_layer_products", true},
                                  {"metadata", Json{{"task", "t1"}}}};
    auto request = node_request("mapping.factor_interpolate", node_params,
                                {}, "req-node-1");
    check(request.params_json.at("factor_name") == "\"gr\"",
          "node_request: string JSON-encoded");
    check(request.params_json.at("grid_n") == "12",
          "node_request: int JSON-encoded");
    check(request.params_json.at("include_layer_products") == "true",
          "node_request: bool JSON-encoded");
    check(request.input_refs.empty(), "node_request: refs default empty");
}

void test_envelope_roundtrip() {
    ScienceEnvelope env;
    env.result_type = "curve_operation";
    env.units = "m";
    env.crs = "EPSG:32633";
    env.extent = std::array<double, 4>{0.0, 0.0, 1.0, 1.0};
    env.quality = Json{{"n", 1}};
    env.payload = Json{{"values", Json::array({1.0, 2.0})}};
    env.compute_fingerprint();

    const Json json = env.to_json();
    const ScienceEnvelope back = ScienceEnvelope::from_json(json);
    check(back.result_type == env.result_type, "envelope: roundtrip type");
    check(back.fingerprint == env.fingerprint, "envelope: roundtrip fingerprint");
    check(back.fingerprint_of_payload() == env.fingerprint,
          "envelope: fingerprint verifies over payload");
    check(back.units == "m" && back.crs == "EPSG:32633",
          "envelope: roundtrip units/crs");

    // Undeclared units/CRS stay empty (never guessed).
    ScienceEnvelope bare;
    bare.result_type = "log_match";
    bare.payload = Json{{"cost", 1.5}};
    bare.compute_fingerprint();
    check(bare.to_json().at("units").is_null()
              && bare.to_json().at("crs").is_null(),
          "envelope: undeclared units/crs serialize as null");
}

}  // namespace

int main() {
    test_factor_pipeline();
    test_factor_duplicates_and_errors();
    test_factor_resource_and_cancel();
    test_factor_constrained_engine();
    test_well_services();
    test_fusion_service();
    test_facies_surface_service();
    test_geomodel_services();
    test_payload_source_and_publisher();
    test_capture_publisher();
    test_registry_and_node_request();
    test_envelope_roundtrip();
    if (g_failures != 0) {
        std::fprintf(stderr, "science_service.suite: %d failure(s)\n",
                     g_failures);
        return 1;
    }
    std::printf("science_service.suite OK\n");
    return 0;
}
