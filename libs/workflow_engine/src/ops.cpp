#include <pwb/workflow_engine/ops.hpp>

#include <pwb/mapping/extract.hpp>
#include <pwb/mapping/interpolator.hpp>

#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace pwb::workflow_engine {
namespace {

using pwb::mapping::FactorDataset;
using pwb::mapping::FactorGrid;
using pwb::mapping::InterpolateOptions;
using pwb::mapping::SamplePoint;

double json_number_or_nan(const Json& value) {
    if (value.is_null()) return std::numeric_limits<double>::quiet_NaN();
    if (!value.is_number()) {
        throw std::invalid_argument("sample value must be a number or null");
    }
    return value.get<double>();
}

InterpolateOptions idw_options_from_json(const Json& params) {
    InterpolateOptions options;
    options.method = "idw";
    options.grid_n = params.value("grid_n", 50);
    options.power = params.value("power", 2.0);
    options.min_neighbors = params.value("min_neighbors", 1);
    if (params.contains("max_neighbors") && !params["max_neighbors"].is_null()) {
        options.max_neighbors = params["max_neighbors"].get<int>();
    }
    if (params.contains("search_radius") && !params["search_radius"].is_null()) {
        options.search_radius = params["search_radius"].get<double>();
    }
    options.crs = params.value("crs", std::string());
    return options;
}

// Fixture-shaped point rows: [x, y, value, qc_flag?].
std::vector<SamplePoint> sample_points_from_json(const Json& points) {
    if (!points.is_array()) {
        throw std::invalid_argument("samples must be an array of point rows");
    }
    std::vector<SamplePoint> out;
    out.reserve(points.size());
    for (const Json& row : points) {
        if (!row.is_array() || row.size() < 3) {
            throw std::invalid_argument(
                "sample row must be [x, y, value, qc_flag?]");
        }
        SamplePoint sample;
        sample.x = json_number_or_nan(row[0]);
        sample.y = json_number_or_nan(row[1]);
        sample.value = json_number_or_nan(row[2]);
        sample.qc_flag = row.size() >= 4 && !row[3].is_null()
            ? row[3].get<std::string>()
            : "ok";
        out.push_back(std::move(sample));
    }
    return out;
}

Json factor_dataset_points_to_json(
    const std::vector<pwb::mapping::FactorPoint>& points) {
    Json rows = Json::array();
    for (const pwb::mapping::FactorPoint& point : points) {
        rows.push_back(Json::array({
            point.x,
            point.y,
            std::isfinite(point.value) ? Json(point.value) : Json(nullptr),
            point.qc_flag,
        }));
    }
    return rows;
}

}  // namespace

void register_builtin_ops(NodeRegistry& registry) {
    registry.register_op(
        "test.noop",
        [](const Json&, const CancelToken& token) -> NodeResult {
            token.throw_if_cancelled();
            NodeResult result;
            result.outputs = Json{{"ok", true}};
            return result;
        });
}

void register_mapping_ops(NodeRegistry& registry) {
    registry.register_op(
        "map.extract_factors",
        [](const Json& params, const CancelToken& token) -> NodeResult {
            token.throw_if_cancelled();
            const auto records_it = params.find("records");
            if (records_it == params.end() || !records_it->is_array()) {
                throw std::invalid_argument(
                    "map.extract_factors requires params.records (array)");
            }
            const auto factor_it = params.find("factor_name");
            if (factor_it == params.end() || !factor_it->is_string()) {
                throw std::invalid_argument(
                    "map.extract_factors requires params.factor_name");
            }
            pwb::mapping::ExtractOptions options;
            if (auto it = params.find("target_horizon");
                it != params.end() && it->is_string()) {
                options.target_horizon = it->get<std::string>();
            }
            if (auto it = params.find("crs"); it != params.end()
                && it->is_string()) {
                options.crs = it->get<std::string>();
            }
            if (auto it = params.find("unit"); it != params.end()
                && it->is_string()) {
                options.unit = it->get<std::string>();
            }  // null/absent → FACTOR_DEFAULTS (ExtractOptions contract)

            const FactorDataset dataset = pwb::mapping::extract_factors(
                *records_it, factor_it->get<std::string>(), options);

            NodeResult result;
            Json& outputs = result.outputs;
            outputs["factor_name"] = dataset.factor_name;
            outputs["unit"] = dataset.unit;
            outputs["target_horizon"] = dataset.target_horizon;
            outputs["crs"] = dataset.crs;
            outputs["point_count"] = static_cast<int>(dataset.points.size());
            outputs["points"] = factor_dataset_points_to_json(dataset.points);
            outputs["diagnostics"] = dataset.metadata;
            result.payload = dataset;
            return result;
        });

    registry.register_op(
        "map.interpolate_idw",
        [](const Json& params, const CancelToken& token) -> NodeResult {
            token.throw_if_cancelled();
            const auto samples_it = params.find("samples");
            if (samples_it == params.end()) {
                throw std::invalid_argument(
                    "map.interpolate_idw requires params.samples");
            }
            const std::vector<SamplePoint> points =
                sample_points_from_json(*samples_it);
            const InterpolateOptions options = idw_options_from_json(params);
            const FactorGrid grid = pwb::mapping::interpolate_factor(
                points, options);  // invalid_argument on unusable samples

            NodeResult result;
            Json& outputs = result.outputs;
            outputs["algorithm_id"] = grid.algorithm_id;
            outputs["grid_n"] = grid.grid_n;
            outputs["n_samples"] = grid.n_samples;
            outputs["grid_x"] = grid.grid_x;
            outputs["grid_y"] = grid.grid_y;
            Json rows = Json::array();
            const int width = grid.grid_n;
            for (int row = 0; row < width; ++row) {
                Json cells = Json::array();
                for (int col = 0; col < width; ++col) {
                    const float value =
                        grid.grid_z[static_cast<std::size_t>(row * width + col)];
                    cells.push_back(std::isfinite(value)
                        ? Json(static_cast<double>(value))
                        : Json(nullptr));
                }
                rows.push_back(std::move(cells));
            }
            outputs["grid_z"] = std::move(rows);
            Json statistics = Json::object();
            statistics["min"] = std::isfinite(grid.statistics.min)
                ? Json(grid.statistics.min) : Json(nullptr);
            statistics["max"] = std::isfinite(grid.statistics.max)
                ? Json(grid.statistics.max) : Json(nullptr);
            statistics["mean"] = std::isfinite(grid.statistics.mean)
                ? Json(grid.statistics.mean) : Json(nullptr);
            statistics["std"] = std::isfinite(grid.statistics.std)
                ? Json(grid.statistics.std) : Json(nullptr);
            statistics["valid_count"] = grid.statistics.valid_count;
            statistics["total_count"] = grid.statistics.total_count;
            outputs["statistics"] = std::move(statistics);
            outputs["distance_policy"] = grid.distance_policy;
            outputs["distance_policy_annotation"] =
                grid.distance_policy_annotation;
            result.payload = grid;
            return result;
        });
}

}  // namespace pwb::workflow_engine
