// pwb::closure_science — mock facies providers (mock_facies.py parity).
//
// Two demo-only deterministic generators behind the stage-1 stage actions
// (run_well_facies_mock / run_seismic_facies_mock). Both carry the full
// honesty flag set (is_mock / is_replaceable / demo /
// final_scientific_prediction=false / probabilities_uncalibrated) so
// downstream gates (map-product assembly fail-closed on source_kind=mock)
// behave identically to the Python product.
//
// RNG note: Python draws from random.Random(seed); the native port freezes
// its own reproducible mt19937_64 stream (same precedent as the demo
// provider — deterministic per seed, not Python-stream-identical).
// Qt-free, Python-free, numpy-free.

#include <pwb/closure_science/providers.hpp>

#include <pwb/mapping/class_grid.hpp>
#include <pwb/mapping/layer_products.hpp>
#include <pwb/mapping/interpolator.hpp>

#include <cmath>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace pwb::closure_science {

using domain::Json;

namespace {

inline constexpr const char* kMockFaciesClasses[] = {
    "扇三角洲", "三角洲前缘", "滨浅湖", "湖相泥"};
inline constexpr std::size_t kMockFaciesClassCount = 4;
// _FALLBACK_INTERVAL — wells without a usable td get the placeholder span.
inline constexpr double kFallbackTop = 600.0;
inline constexpr double kFallbackBottom = 800.0;

[[nodiscard]] Json mock_honesty_flags() {
    return Json{{"is_mock", true},
                {"is_replaceable", true},
                {"final_scientific_prediction", false},
                {"demo", true},
                {"source", "synthetic/demo"},
                {"model_type", "mock"},
                {"probabilities_uncalibrated", true}};
}

[[nodiscard]] double round_to(double value, int digits) {
    const double scale = std::pow(10.0, digits);
    return std::round(value * scale) / scale;
}

[[nodiscard]] std::optional<double> finite_number(const Json& value) {
    if (!value.is_number()) return std::nullopt;
    const double v = value.get<double>();
    return std::isfinite(v) ? std::optional<double>(v) : std::nullopt;
}

// parameters["_wells"] or parameters["wells"] (the `_`-stripped service
// path) — Python's `parameters.get("_wells") or parameters.get("wells")`.
[[nodiscard]] const Json* param_either(const Json& parameters,
                                       const char* private_key,
                                       const char* public_key) {
    if (const Json* v = parameters.contains(private_key)
                            ? &parameters.at(private_key)
                            : nullptr;
        v != nullptr && v->is_array() && !v->empty()) {
        return v;
    }
    if (const Json* v = parameters.contains(public_key)
                            ? &parameters.at(public_key)
                            : nullptr;
        v != nullptr && v->is_array()) {
        return v;
    }
    return nullptr;
}

[[nodiscard]] std::string param_text(const Json& parameters,
                                     const char* key) {
    const Json* v =
        parameters.contains(key) ? &parameters.at(key) : nullptr;
    return v != nullptr && v->is_string() ? v->get<std::string>()
                                          : std::string();
}

[[nodiscard]] long long param_seed(const Json& parameters) {
    const Json* v =
        parameters.contains("seed") ? &parameters.at("seed") : nullptr;
    if (v == nullptr || !v->is_number()) return 0;
    return v->is_number_integer() ? v->get<long long>()
                                : static_cast<long long>(v->get<double>());
}

[[nodiscard]] std::vector<std::pair<double, double>> clip_ring_of(
    const Json& parameters) {
    const Json* ring = parameters.contains("_clip_ring")
                           ? &parameters.at("_clip_ring")
                           : (parameters.contains("clip_ring")
                                  ? &parameters.at("clip_ring")
                                  : nullptr);
    std::vector<std::pair<double, double>> out;
    if (ring == nullptr || !ring->is_array()) return out;
    for (const auto& vertex : *ring) {
        if (!vertex.is_array() || vertex.size() < 2) continue;
        const auto x = finite_number(vertex[0]);
        const auto y = finite_number(vertex[1]);
        if (x && y) out.emplace_back(*x, *y);
    }
    return out;
}

}  // namespace

ProviderRun make_mock_well_facies_provider() {
    return [](const Json& /*inputs*/, Json parameters,
              const std::function<bool()>& /*cancel*/)
               -> domain::Result<Json> {
        const long long seed = param_seed(parameters);
        const std::string horizon = param_text(parameters, "target_horizon");
        const Json* wells = param_either(parameters, "_wells", "wells");
        if (wells == nullptr || wells->empty()) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "mock 测井相预测需要至少一口井（_wells 为空）");
        }
        std::mt19937_64 rng(static_cast<std::uint64_t>(seed));
        std::uniform_real_distribution<double> unit(0.0, 1.0);

        Json regions = Json::array();
        Json detail = Json::array();
        int index = 0;
        for (const auto& well : *wells) {
            ++index;
            double top = kFallbackTop;
            double bottom = kFallbackBottom;
            if (well.is_object()) {
                if (const auto td =
                        well.contains("td") ? finite_number(well.at("td"))
                                            : std::nullopt;
                    td && *td > 0.0) {
                    top = round_to(0.6 * *td, 2);
                    bottom = round_to(0.8 * *td, 2);
                }
            }
            const double draw = unit(rng);
            const std::string& facies = kMockFaciesClasses[std::min(
                static_cast<int>(draw * kMockFaciesClassCount),
                static_cast<int>(kMockFaciesClassCount) - 1)];
            const double probability = round_to(0.55 + unit(rng) * 0.35, 3);
            Json region = Json{
                {"region_id",
                 "mock_well_region_" + std::to_string(index)},
                {"well_id",
                 well.is_object() ? param_text(well, "well_id") : ""},
                {"well_name",
                 well.is_object() ? param_text(well, "well_name") : ""},
                {"stratigraphic_unit", horizon},
                {"horizon", horizon},
                {"top", top},
                {"bottom", bottom},
                {"facies", facies},
                {"probability", probability}};
            detail.push_back(region);
            detail.back()["rng_draw"] = round_to(draw, 6);
            regions.push_back(std::move(region));
        }
        double probability_sum = 0.0;
        Json review_areas = Json::array();
        for (const auto& region : regions) {
            const double p = region["probability"].get<double>();
            probability_sum += p;
            if (p < 0.7) review_areas.push_back(region);
        }
        Json summary = mock_honesty_flags();
        summary["predicted_regions"] = std::move(regions);
        summary["target_horizon"] = horizon;
        return Json{
            {"adapter_kind", "mock"},
            {"generator_version", kMockFaciesGeneratorVersion},
            {"demo", true},
            {"source", "synthetic/demo"},
            {"result_summary", std::move(summary)},
            {"probability_summary",
             Json{{"mean_probability",
                   round_to(probability_sum /
                                static_cast<double>(index),
                            3)}}},
            {"review_areas", std::move(review_areas)},
            {"seed", seed},
            // Intermediate file content: the stage handler pops and
            // registers it as an INTERMEDIATE version.
            {"well_detail", std::move(detail)}};
    };
}

ProviderRun make_mock_seismic_facies_provider() {
    return [](const Json& /*inputs*/, Json parameters,
              const std::function<bool()>& /*cancel*/)
               -> domain::Result<Json> {
        const long long seed = param_seed(parameters);
        const std::string horizon = param_text(parameters, "target_horizon");
        const Json* extent = parameters.contains("_extent")
                                 ? &parameters.at("_extent")
                                 : (parameters.contains("extent")
                                        ? &parameters.at("extent")
                                        : nullptr);
        if (extent == nullptr || !extent->is_array() || extent->size() < 4) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "mock 地震相面预测需要有效平面范围（_extent 缺失）");
        }
        const double xmin = (*extent)[0].get<double>();
        const double ymin = (*extent)[1].get<double>();
        const double xmax = (*extent)[2].get<double>();
        const double ymax = (*extent)[3].get<double>();
        if (!std::isfinite(xmin) || !std::isfinite(ymin) ||
            !std::isfinite(xmax) || !std::isfinite(ymax) || xmax <= xmin ||
            ymax <= ymin) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "mock 地震相面预测的平面范围无效");
        }
        const std::string crs =
            param_text(parameters, "_crs").empty()
                ? param_text(parameters, "crs")
                : param_text(parameters, "_crs");
        int grid_n = 80;
        if (const Json* n = parameters.contains("grid_n")
                                ? &parameters.at("grid_n")
                                : nullptr;
            n != nullptr && n->is_number()) {
            grid_n = std::max(2, static_cast<int>(n->get<double>()));
        }
        const auto ring_pairs = clip_ring_of(parameters);
        std::vector<mapping::Point> clip_ring;
        clip_ring.reserve(ring_pairs.size());
        for (const auto& [x, y] : ring_pairs) {
            clip_ring.push_back({x, y});
        }

        std::mt19937_64 rng(static_cast<std::uint64_t>(seed));
        std::uniform_real_distribution<double> ux(xmin, xmax);
        std::uniform_real_distribution<double> uy(ymin, ymax);
        std::uniform_int_distribution<int> ui(
            0, static_cast<int>(kMockFaciesClassCount) - 1);
        struct Anchor {
            double x;
            double y;
            int klass;
        };
        std::vector<Anchor> anchors;
        anchors.reserve(12);
        for (int i = 0; i < 12; ++i) {
            anchors.push_back({ux(rng), uy(rng), ui(rng)});
        }

        const std::vector<double> grid_x =
            mapping::linspace(xmin, xmax, grid_n);
        const std::vector<double> grid_y =
            mapping::linspace(ymin, ymax, grid_n);
        const bool clip = clip_ring.size() >= 4;
        std::vector<float> grid_z(
            static_cast<std::size_t>(grid_n) * grid_n);
        for (int row = 0; row < grid_n; ++row) {
            for (int col = 0; col < grid_n; ++col) {
                const double x = grid_x[col];
                const double y = grid_y[row];
                float klass = std::numeric_limits<float>::quiet_NaN();
                if (!clip ||
                    mapping::point_in_ring_inclusive(x, y, clip_ring)) {
                    double best = std::numeric_limits<double>::max();
                    int best_klass = 0;
                    for (const Anchor& anchor : anchors) {
                        const double dx = x - anchor.x;
                        const double dy = y - anchor.y;
                        const double d2 = dx * dx + dy * dy;
                        if (d2 < best) {
                            best = d2;
                            best_klass = anchor.klass;
                        }
                    }
                    klass = static_cast<float>(best_klass);
                }
                grid_z[static_cast<std::size_t>(row) * grid_n + col] =
                    klass;
            }
        }

        mapping::FactorGrid grid;
        grid.grid_x = grid_x;
        grid.grid_y = grid_y;
        grid.grid_z = grid_z;
        grid.algorithm_id = "mock_nearest_neighbor";
        grid.method = "mock_nearest_neighbor";
        grid.grid_n = grid_n;
        mapping::LayerGridContext ctx;
        ctx.factor_name = "地震相面预测（mock）";
        ctx.crs = crs;
        mapping::FaciesLayerOptions options;
        options.thresholds = std::vector<double>{0.5, 1.5, 2.5};
        options.facies_names = std::vector<std::string>(
            std::begin(kMockFaciesClasses), std::end(kMockFaciesClasses));
        const auto product =
            mapping::generate_facies_polygon_layer_product(grid, ctx,
                                                           options);

        std::uniform_real_distribution<double> unit(0.0, 1.0);
        Json features = Json::array();
        double probability_sum = 0.0;
        for (const auto& record : product.features) {
            if (!record.is_object()) continue;
            const Json* geometry =
                record.contains("geometry") ? &record.at("geometry")
                                            : nullptr;
            if (geometry == nullptr || !geometry->is_object()) continue;
            const std::string type =
                geometry->contains("type") &&
                        geometry->at("type").is_string()
                    ? geometry->at("type").get<std::string>()
                    : "";
            if (type != "Polygon" && type != "MultiPolygon") continue;
            Json properties =
                record.contains("properties") &&
                        record.at("properties").is_object()
                    ? record.at("properties")
                    : Json::object();
            if (!properties.contains("facies") ||
                !properties["facies"].is_string() ||
                properties["facies"].get<std::string>().empty()) {
                const std::string name =
                    properties.contains("facies_name") &&
                            properties["facies_name"].is_string()
                        ? properties["facies_name"].get<std::string>()
                        : "";
                properties["facies"] = name;
            }
            properties["horizon"] = horizon;
            const double probability =
                round_to(0.55 + unit(rng) * 0.35, 3);
            properties["probability"] = probability;
            probability_sum += probability;
            features.push_back(Json{{"type", "Feature"},
                                    {"geometry", *geometry},
                                    {"properties", std::move(properties)}});
        }
        if (features.empty()) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "mock 地震相面预测未产出任何相区多边形（范围过小？）");
        }

        Json summary = mock_honesty_flags();
        summary["spatial"] = Json{{"type", "VECTOR_POLYGONS"},
                                  {"crs", crs},
                                  {"features", features}};
        summary["target_horizon"] = horizon;
        Json grid_x_json = Json::array();
        Json grid_y_json = Json::array();
        Json grid_z_json = Json::array();
        for (double v : grid_x) grid_x_json.push_back(v);
        for (double v : grid_y) grid_y_json.push_back(v);
        for (float v : grid_z) grid_z_json.push_back(v);
        Json names = Json::array();
        for (const char* n : kMockFaciesClasses) names.push_back(n);
        return Json{
            {"adapter_kind", "mock"},
            {"generator_version", kMockFaciesGeneratorVersion},
            {"demo", true},
            {"source", "synthetic/demo"},
            {"result_summary", std::move(summary)},
            {"probability_summary",
             Json{{"mean_probability",
                   round_to(probability_sum /
                                static_cast<double>(features.size()),
                            3)}}},
            {"review_areas", Json::array()},
            {"seed", seed},
            // Intermediate file content: the stage handler pops and
            // registers it as an INTERMEDIATE grid version.
            {"mock_grid",
             Json{{"grid_z", std::move(grid_z_json)},
                  {"grid_x", std::move(grid_x_json)},
                  {"grid_y", std::move(grid_y_json)},
                  {"names", std::move(names)},
                  {"extent",
                   Json::array({xmin, ymin, xmax, ymax})},
                  {"crs", crs},
                  {"grid_n", grid_n}}}};
    };
}

}  // namespace pwb::closure_science
