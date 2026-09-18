// pwb::science_service — well facies surface service implementation.

#include <pwb/science_service/facies_service.hpp>

#include <utility>

#include "support.hpp"

namespace pwb::science_service {

using pwb::domain::Json;
using pwb::mapping::WellFaciesPoint;

namespace {

// well_points DTO rows -> WellFaciesPoint list (kernel-tolerant: rows that
// fail the shape filters are dropped, mirroring spatial_point_features).
std::vector<WellFaciesPoint> parse_points(const Json& rows) {
    std::vector<WellFaciesPoint> out;
    if (!rows.is_array()) {
        return out;
    }
    for (const auto& row : rows) {
        if (!row.is_object() || !row.contains("facies")) {
            continue;
        }
        const Json& fx = row.contains("x") ? row.at("x") : Json(nullptr);
        const Json& fy = row.contains("y") ? row.at("y") : Json(nullptr);
        if (!fx.is_number() || !fy.is_number()) {
            continue;
        }
        WellFaciesPoint p;
        p.x = fx.get<double>();
        p.y = fy.get<double>();
        p.facies = row.at("facies").get<std::string>();
        if (row.contains("well_id") && row.at("well_id").is_string()) {
            p.well_id = row.at("well_id").get<std::string>();
        }
        if (row.contains("well_name") && row.at("well_name").is_string()) {
            p.well_name = row.at("well_name").get<std::string>();
        }
        if (row.contains("probability") && row.at("probability").is_number()) {
            p.probability = row.at("probability").get<double>();
        }
        if (row.contains("thickness") && row.at("thickness").is_number()) {
            p.thickness = row.at("thickness").get<double>();
        }
        if (row.contains("task_id") && row.at("task_id").is_string()) {
            p.task_id = row.at("task_id").get<std::string>();
        }
        out.push_back(std::move(p));
    }
    return out;
}

Json feature_pairs_to_json(
    const std::vector<std::pair<Json, Json>>& pairs) {
    Json features = Json::array();
    for (const auto& [geometry, properties] : pairs) {
        features.push_back(Json{{"type", "Feature"},
                                {"geometry", geometry},
                                {"properties", properties}});
    }
    return features;
}

}  // namespace

FaciesSurfaceService::FaciesSurfaceService(std::string build_identity,
                                           ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<FaciesSurfaceResult> FaciesSurfaceService::run(
    const FaciesSurfaceRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    const std::int64_t cells = static_cast<std::int64_t>(request.grid_n)
                               * request.grid_n;
    if (request.grid_n < 2 || request.grid_n > limits_.max_grid_n
        || static_cast<std::size_t>(cells) > limits_.max_grid_cells) {
        return detail::make_error(
            detail::limit_code("grid_n"),
            "grid_n " + std::to_string(request.grid_n) + " outside limits");
    }
    if (request.well_points.size() > limits_.max_input_records) {
        return detail::make_error(
            detail::limit_code("input_records"),
            "well_points size exceeds limit "
                + std::to_string(limits_.max_input_records));
    }
    if (detail::stage_guard(stop, progress, 0.1, "validate")) {
        return science::TaskCancelled{"validate"};
    }

    // Points: direct rows, or spatial features out of the result summary.
    std::vector<WellFaciesPoint> points;
    if (request.well_points.is_array() && !request.well_points.empty()) {
        points = parse_points(request.well_points);
    } else if (request.result_summary.is_object()) {
        points = pwb::mapping::spatial_point_features(request.result_summary,
                                                      request.task_id);
    }
    if (points.empty()) {
        return detail::make_error(
            "facies.no_points",
            "no well facies points (well_points empty and result_summary "
            "carried no spatial features)");
    }
    if (detail::stage_guard(stop, progress, 0.35, "points")) {
        return science::TaskCancelled{"points"};
    }

    // Representative facies vote over interval records (task_regions of the
    // summary, or none when only points were given).
    std::optional<pwb::mapping::RepresentativeFacies> representative;
    if (request.result_summary.is_object()) {
        representative = pwb::mapping::representative_facies(
            pwb::mapping::task_regions(request.result_summary),
            request.horizon);
    }

    // Extent: given or derived from the points (padded bbox).
    std::array<double, 4> extent =
        request.extent ? *request.extent
                       : pwb::mapping::extent_from_points(points);

    // Point layer descriptors.
    auto point_layer = pwb::mapping::point_features(points);

    // Surface polygons on the class-grid kernel.
    std::vector<pwb::mapping::Point> clip_ring;
    if (request.clip_ring) {
        for (const auto& p : *request.clip_ring) {
            clip_ring.push_back({p[0], p[1]});
        }
    }
    auto surface_layer = detail::catch_kernel<
        std::vector<std::pair<Json, Json>>>(
        "facies.surface", [&] {
            return pwb::mapping::point_to_surface_features(
                points, extent, request.grid_n, clip_ring, request.crs);
        });
    if (surface_layer.is_error()) {
        return surface_layer.error();
    }
    if (detail::stage_guard(stop, progress, 0.8, "surface")) {
        return science::TaskCancelled{"surface"};
    }

    ScienceEnvelope envelope;
    envelope.result_type = "facies_surface";
    envelope.crs = request.crs;
    envelope.extent = extent;
    Json quality = Json::object();
    quality["n_points"] = static_cast<std::uint64_t>(points.size());
    Json facies_counts = Json::object();
    for (const auto& p : points) {
        facies_counts[p.facies] = facies_counts.value(p.facies, 0) + 1;
    }
    quality["facies_counts"] = std::move(facies_counts);
    if (representative) {
        quality["representative_facies"] = Json{
            {"facies", representative->facies},
            {"mean_probability",
             representative->mean_probability
                 ? Json(*representative->mean_probability)
                 : Json(nullptr)},
            {"thickness", representative->thickness}};
    }
    envelope.quality = std::move(quality);

    Json payload = Json::object();
    payload["point_features"] = feature_pairs_to_json(point_layer);
    payload["surface_features"] = feature_pairs_to_json(surface_layer.value());
    envelope.payload = std::move(payload);
    Json provenance = Json::object();
    provenance["algorithm_id"] = "mapping.facies_surface";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    provenance["grid_n"] = request.grid_n;
    provenance["task_id"] = request.task_id;
    envelope.provenance = std::move(provenance);
    envelope.compute_fingerprint();

    FaciesSurfaceResult result;
    result.envelope = std::move(envelope);
    result.representative = representative;
    result.points = std::move(points);
    result.point_layer = std::move(point_layer);
    result.surface_layer = std::move(surface_layer.value());
    result.extent = extent;
    detail::stage_guard(stop, progress, 1.0, "envelope");
    return result;
}

}  // namespace pwb::science_service
