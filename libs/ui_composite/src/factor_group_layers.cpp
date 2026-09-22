#include "pwb/ui_composite/factor_group_layers.hpp"

#include "pwb/mapping/contouring.hpp"
#include "pwb/mapping/layer_products.hpp"
#include "pwb/ui_composite/layer_groups.hpp"
#include "pwb/ui_composite/roles.hpp"

#include <algorithm>
#include <cmath>
#include <optional>
#include <string_view>

namespace pwb::ui_composite {
namespace {

using pwb::mapping::FactorGrid;

// ---------------------------------------------------------------- Json ----

const Json* field(const Json& object, const char* key) {
    if (!object.is_object()) return nullptr;
    const auto it = object.find(key);
    return it != object.end() ? &*it : nullptr;
}

std::string str_of(const Json& object, const char* key) {
    const Json* v = field(object, key);
    if (v == nullptr || v->is_null()) return "";
    if (v->is_string()) return v->get<std::string>();
    if (v->is_boolean()) return v->get<bool>() ? "True" : "False";
    if (v->is_number_integer()) return std::to_string(v->get<long long>());
    if (v->is_number_unsigned())
        return std::to_string(v->get<unsigned long long>());
    if (v->is_number()) return std::to_string(v->get<double>());
    return "";
}

std::optional<double> finite(const Json& value) {
    double number;
    if (value.is_number()) {
        number = value.get<double>();
    } else if (value.is_string()) {
        try {
            number = std::stod(value.get<std::string>());
        } catch (const std::exception&) {
            return std::nullopt;
        }
    } else {
        return std::nullopt;
    }
    return std::isfinite(number) ? std::optional<double>{number}
                                 : std::nullopt;
}

Json number_or_null(std::optional<double> value) {
    return value ? Json(*value) : Json(nullptr);
}

Json dict_of(const Json& object, const char* key) {
    const Json* v = field(object, key);
    return v != nullptr && v->is_object() ? *v : Json::object();
}

Json array_of(const Json& object, const char* key) {
    const Json* v = field(object, key);
    return v != nullptr && v->is_array() ? *v : Json::array();
}

// _task_parameters / _task_quality_metrics / _task_grid_metadata parity.
Json task_parameters(const Json& task) { return dict_of(task, "parameters"); }
Json task_quality_metrics(const Json& task) {
    return dict_of(task, "quality_metrics");
}
Json task_grid_metadata(const Json& task) {
    return dict_of(task, "grid_metadata");
}

Json sample_points(const Json& task) {
    const Json* points = field(task_parameters(task), "sample_points");
    Json out = Json::array();
    if (points != nullptr && points->is_array()) {
        for (const Json& p : *points) {
            if (p.is_object()) out.push_back(p);
        }
    }
    return out;
}

// _well_table parity — resolve the task's WellTable inside the document.
const Json* well_table(const Json& document, const Json& task) {
    const std::string table_id = str_of(task, "well_table_id");
    if (table_id.empty()) return nullptr;
    const Json* tables = field(document, "well_tables");
    if (tables == nullptr || !tables->is_array()) return nullptr;
    for (const Json& candidate : *tables) {
        if (str_of(candidate, "id") == table_id) return &candidate;
    }
    return nullptr;
}

// _anchor_xy parity — grid extent centre, else finite-sample centroid.
std::optional<std::pair<double, double>> anchor_xy(
    const FactorGroupGridView& grid, const Json& task) {
    if (grid.live != nullptr && !grid.live->grid_x.empty()
        && !grid.live->grid_y.empty()) {
        const auto& xs = grid.live->grid_x;
        const auto& ys = grid.live->grid_y;
        const double xmin = *std::min_element(xs.begin(), xs.end());
        const double xmax = *std::max_element(xs.begin(), xs.end());
        const double ymin = *std::min_element(ys.begin(), ys.end());
        const double ymax = *std::max_element(ys.begin(), ys.end());
        return std::pair{(xmin + xmax) / 2.0, (ymin + ymax) / 2.0};
    }
    double sx = 0.0, sy = 0.0;
    int n = 0;
    for (const Json& p : sample_points(task)) {
        const auto x = finite(p.contains("x") ? p["x"] : Json());
        const auto y = finite(p.contains("y") ? p["y"] : Json());
        if (!x || !y) continue;
        sx += *x;
        sy += *y;
        ++n;
    }
    if (n == 0) return std::nullopt;
    return std::pair{sx / n, sy / n};
}

// Extent/statistics for the scalar payload: live grid → computed, else
// the task.grid_metadata descriptor fields (verbatim).
Json scalar_extent(const FactorGroupGridView& grid, const Json& meta) {
    if (grid.live != nullptr && !grid.live->grid_x.empty()
        && !grid.live->grid_y.empty()) {
        const auto& xs = grid.live->grid_x;
        const auto& ys = grid.live->grid_y;
        return Json::array(
            {*std::min_element(xs.begin(), xs.end()),
             *std::min_element(ys.begin(), ys.end()),
             *std::max_element(xs.begin(), xs.end()),
             *std::max_element(ys.begin(), ys.end())});
    }
    const Json* extent = field(meta, "extent");
    if (extent != nullptr && extent->is_array() && extent->size() == 4) {
        Json out = Json::array();
        for (const Json& v : *extent) out.push_back(v);
        return out;
    }
    return Json::array();
}

Json scalar_statistics(const FactorGroupGridView& grid, const Json& meta) {
    if (grid.live != nullptr) {
        const auto stats =
            pwb::mapping::grid_statistics(grid.live->grid_z);
        Json out = Json::object();
        const auto put = [&](const char* key, double v) {
            out[key] = std::isfinite(v) ? Json(v) : Json(nullptr);
        };
        put("min", stats.min);
        put("max", stats.max);
        put("mean", stats.mean);
        put("std", stats.std);
        out["valid_count"] = stats.valid_count;
        out["total_count"] = stats.total_count;
        return out;
    }
    return dict_of(meta, "statistics");
}

// _scalar_payload parity — the FactorGridResult-derived info the scalar
// publish path needs. Grid arrays never enter the payload.
Json scalar_payload(const Json& task, const FactorGroupGridView& grid,
                    const std::string& task_id, const std::string& quantity,
                    const Json& extra_metadata = Json()) {
    Json descriptor;
    std::string source;
    if (grid.live != nullptr) {
        source = "live_grid";
        descriptor = grid.metadata.is_object() ? grid.metadata
                                              : Json::object();
    } else {
        const Json meta = task_grid_metadata(task);
        source = meta.empty() ? "absent" : "task_grid_metadata";
        descriptor = meta;
    }
    Json payload = Json::object();
    payload["layer_type"] = kScalarGridLayerType;
    payload["factor_task_id"] = task_id;
    payload["quantity"] = quantity;
    payload["source"] = source;
    payload["descriptor"] = descriptor;

    Json metadata = Json::object();
    metadata["factor_task_id"] = task_id;
    metadata["layer_type"] = kScalarGridLayerType;
    metadata["quantity"] = quantity;
    metadata["source"] = source;
    metadata["algorithm_id"] =
        grid.live != nullptr ? Json(grid.live->algorithm_id)
                             : Json(str_of(descriptor, "algorithm_id"));
    const Json* crs_v = field(descriptor, "crs");
    const Json* unit_v = field(descriptor, "unit");
    metadata["crs"] = crs_v != nullptr ? *crs_v : Json(nullptr);
    metadata["unit"] = unit_v != nullptr ? *unit_v : Json(nullptr);
    metadata["extent"] = scalar_extent(grid, descriptor);
    metadata["width"] =
        grid.live != nullptr
            ? Json(static_cast<long long>(grid.live->grid_x.size()))
            : (field(descriptor, "width") != nullptr
                   ? *field(descriptor, "width")
                   : Json(0));
    metadata["height"] =
        grid.live != nullptr
            ? Json(static_cast<long long>(grid.live->grid_y.size()))
            : (field(descriptor, "height") != nullptr
                   ? *field(descriptor, "height")
                   : Json(0));
    metadata["statistics"] = scalar_statistics(grid, descriptor);
    metadata["artifact_version_id"] =
        str_of(task, "grid_artifact_version_id");
    metadata["artifact_path"] = str_of(task, "grid_artifact_path");
    const Json* run_ref = field(descriptor, "run_ref");
    metadata["run_ref"] = run_ref != nullptr ? *run_ref : Json(nullptr);
    if (extra_metadata.is_object()) {
        for (const auto& [key, value] : extra_metadata.items()) {
            metadata[key] = value;
        }
    }
    if (quantity == "stddev" && metadata.contains("stddev_statistics")) {
        // R1-F4: the uncertainty descriptor's `statistics` must describe
        // the stddev quantity it carries — not the parent factor stats.
        metadata["factor_statistics"] = metadata["statistics"];
        metadata["statistics"] = metadata["stddev_statistics"];
    }
    payload["metadata"] = metadata;
    return payload;
}

// ------------------------------------------------------- child builders ---

// _input_child parity — WellTable rows first, task
// parameters.sample_points fallback.
Json input_child(const Json& document, const Json& task,
                 const std::string& task_id, const std::string& title) {
    Json features = Json::array();
    std::string source;
    const Json* table = well_table(document, task);
    const Json* rows =
        table != nullptr ? field(*table, "rows") : nullptr;
    if (rows != nullptr && rows->is_array() && !rows->empty()) {
        source = "well_table";
        for (const Json& row : *rows) {
            const auto x = finite(row.contains("x") ? row["x"] : Json());
            const auto y = finite(row.contains("y") ? row["y"] : Json());
            if (!x || !y) continue;
            auto value =
                finite(row.contains("value") ? row["value"] : Json());
            if (!value) {
                const Json attrs = dict_of(row, "attributes");
                value = finite(attrs.contains("value") ? attrs["value"]
                                                       : Json());
            }
            Json properties = Json::object();
            properties["well_id"] = str_of(row, "well_id");
            properties["well"] = str_of(row, "name");
            properties["value"] = number_or_null(value);
            const std::string qc = str_of(row, "qc_flag");
            properties["qc_flag"] = qc.empty() ? "ok" : qc;
            Json feature = Json::object();
            feature["geometry"] = Json::object(
                {{"type", "Point"},
                 {"coordinates", Json::array({*x, *y})}});
            feature["properties"] = std::move(properties);
            features.push_back(std::move(feature));
        }
    }
    if (features.empty()) {
        const Json points = sample_points(task);
        if (!points.empty()) {
            source = "task_parameters";
            int index = 0;
            for (const Json& point : points) {
                ++index;
                const auto x =
                    finite(point.contains("x") ? point["x"] : Json());
                const auto y =
                    finite(point.contains("y") ? point["y"] : Json());
                if (!x || !y) continue;
                std::string well_id = str_of(point, "well_id");
                if (well_id.empty()) well_id = str_of(point, "well");
                if (well_id.empty()) {
                    well_id = "sample_" + std::to_string(index);
                }
                Json properties = Json::object();
                properties["well_id"] = well_id;
                properties["well"] = str_of(point, "well").empty()
                                         ? str_of(point, "well_name")
                                         : str_of(point, "well");
                properties["value"] = number_or_null(
                    finite(point.contains("value") ? point["value"]
                                                   : Json()));
                const std::string qc = str_of(point, "qc_flag");
                properties["qc_flag"] = qc.empty() ? "ok" : qc;
                Json feature = Json::object();
                feature["geometry"] = Json::object(
                    {{"type", "Point"},
                     {"coordinates", Json::array({*x, *y})}});
                feature["properties"] = std::move(properties);
                features.push_back(std::move(feature));
            }
        }
    }
    Json descriptor = Json::object();
    descriptor["layer_id"] = "factor_input:" + task_id;
    descriptor["role"] = std::string(layer_role::kFactorInput);
    descriptor["title"] = title + "·井点";
    descriptor["geometry_kind"] = "point";
    descriptor["features"] = std::move(features);
    descriptor["metadata"] = Json::object(
        {{"factor_task_id", task_id},
         {"well_source", source},
         {"feature_count", static_cast<long long>(
                               descriptor["features"].size())}});
    return descriptor;
}

// _grid_child parity — scalar descriptor for the factor grid itself.
Json grid_child(const Json& task, const FactorGroupGridView& grid,
                const std::string& task_id, const std::string& title) {
    Json payload =
        scalar_payload(task, grid, task_id, "factor_value");
    payload["metadata"]["has_variance_grid"] =
        grid.live != nullptr && !grid.live->variance_grid.empty();
    Json descriptor = Json::object();
    descriptor["layer_id"] = "factor_grid:" + task_id;
    descriptor["role"] = std::string(layer_role::kFactorGrid);
    descriptor["title"] = title + "·栅格";
    descriptor["geometry_kind"] = "raster";
    descriptor["payload"] = payload;
    descriptor["metadata"] = payload["metadata"];
    return descriptor;
}

// Live-grid → kernel view for the contour/polygonization products.
pwb::mapping::LayerGridContext layer_context(
    const FactorGroupGridView& grid, const Json& task) {
    pwb::mapping::LayerGridContext ctx;
    const Json meta = grid.live != nullptr && grid.metadata.is_object()
                          ? grid.metadata
                          : task_grid_metadata(task);
    ctx.factor_name = str_of(meta, "factor_name");
    if (ctx.factor_name.empty()) {
        ctx.factor_name = str_of(task, "factor_type");
        if (ctx.factor_name.empty()) ctx.factor_name = str_of(task, "name");
    }
    ctx.unit = str_of(meta, "unit");
    ctx.crs = str_of(meta, "crs");
    return ctx;
}

// _contour_child parity — contours from the live grid (marching
// squares); honest emptiness when the grid is not resident.
Json contour_child(const FactorGroupGridView& grid, const Json& task,
                   const std::string& task_id, const std::string& title,
                   int contour_limit) {
    std::string absent_reason;
    Json features = Json::array();
    Json metadata = Json::object({{"factor_task_id", task_id}});
    if (grid.live == nullptr) {
        absent_reason =
            "no live factor grid (open the preparation page to load)";
    } else {
        const auto stats =
            pwb::mapping::grid_statistics(grid.live->grid_z);
        Json records = Json::array();
        Json contour_qc = Json::object();
        try {
            const auto levels =
                pwb::mapping::nice_contour_levels(stats.min, stats.max);
            pwb::mapping::ContourLayerOptions options;
            if (!levels.empty()) options.levels = levels;
            const auto product =
                pwb::mapping::generate_contour_layer_product(
                    *grid.live, layer_context(grid, task), options);
            for (const Json& record : product.features) {
                Json feature = Json::object();
                feature["geometry"] = dict_of(record, "geometry");
                feature["properties"] = dict_of(record, "properties");
                records.push_back(std::move(feature));
            }
            contour_qc = product.contour_qc.is_object()
                             ? product.contour_qc
                             : Json::object();
        } catch (const std::exception& exc) {
            absent_reason =
                std::string("contour extraction failed: ") + exc.what();
        }
        const long long total = static_cast<long long>(records.size());
        const long long limit = std::max(0, contour_limit);
        if (limit > 0 && total > limit) {
            Json kept = Json::array();
            for (long long i = 0; i < limit; ++i) {
                kept.push_back(records[i]);
            }
            features = std::move(kept);
        } else {
            features = std::move(records);
        }
        metadata["feature_count_total"] = total;
        metadata["truncated"] = total > static_cast<long long>(
                                            features.size());
        metadata["contour_qc"] = std::move(contour_qc);
    }
    if (!absent_reason.empty()) metadata["absent_reason"] = absent_reason;
    metadata["feature_count"] = static_cast<long long>(features.size());
    Json descriptor = Json::object();
    descriptor["layer_id"] = "factor_contour:" + task_id;
    descriptor["role"] = std::string(layer_role::kFactorContour);
    descriptor["title"] = title + "·等值线";
    descriptor["geometry_kind"] = "line";
    descriptor["features"] = std::move(features);
    descriptor["metadata"] = std::move(metadata);
    return descriptor;
}

// _classification_child parity — threshold classification polygons
// from the live grid.
Json classification_child(const FactorGroupGridView& grid,
                          const Json& task, const std::string& task_id,
                          const std::string& title) {
    std::string absent_reason;
    Json features = Json::array();
    Json metadata = Json::object({{"factor_task_id", task_id}});
    if (grid.live == nullptr) {
        absent_reason =
            "no live factor grid (open the preparation page to load)";
    } else {
        try {
            const auto product =
                pwb::mapping::generate_facies_polygon_layer_product(
                    *grid.live, layer_context(grid, task));
            for (const Json& record : product.features) {
                Json feature = Json::object();
                feature["geometry"] = dict_of(record, "geometry");
                feature["properties"] = dict_of(record, "properties");
                features.push_back(std::move(feature));
            }
            metadata["polygon_qc"] = product.polygon_qc.is_object()
                                         ? product.polygon_qc
                                         : Json::object();
        } catch (const std::exception& exc) {
            absent_reason =
                std::string("polygonization failed: ") + exc.what();
        }
    }
    if (!absent_reason.empty()) metadata["absent_reason"] = absent_reason;
    metadata["feature_count"] = static_cast<long long>(features.size());
    Json descriptor = Json::object();
    descriptor["layer_id"] = "factor_classification:" + task_id;
    descriptor["role"] = std::string(layer_role::kFactorClassification);
    descriptor["title"] = title + "·分级";
    descriptor["geometry_kind"] = "polygon";
    descriptor["features"] = std::move(features);
    descriptor["metadata"] = std::move(metadata);
    return descriptor;
}

// _uncertainty_child parity — stddev surface descriptor from
// variance_grid; null (honest absence) without one.
Json uncertainty_child(const FactorGroupGridView& grid,
                       const std::string& task_id,
                       const std::string& title) {
    if (grid.live == nullptr || grid.live->variance_grid.empty()) {
        return Json();
    }
    double vmin = 0.0, vmax = 0.0, sum = 0.0;
    long long valid = 0;
    std::vector<double> stddevs;
    stddevs.reserve(grid.live->variance_grid.size());
    for (const float v : grid.live->variance_grid) {
        if (!std::isfinite(v) || v < 0.0f) continue;
        const double sd = std::sqrt(static_cast<double>(v));
        stddevs.push_back(sd);
        if (valid == 0 || sd < vmin) vmin = sd;
        if (valid == 0 || sd > vmax) vmax = sd;
        sum += sd;
        ++valid;
    }
    double mean = 0.0, std = 0.0;
    if (valid > 0) {
        mean = sum / static_cast<double>(valid);
        double sq = 0.0;
        for (const double sd : stddevs) {
            const double d = sd - mean;
            sq += d * d;
        }
        std = std::sqrt(sq / static_cast<double>(valid));
    }
    Json stddev_stats = Json::object();
    stddev_stats["min"] = valid > 0 ? Json(vmin) : Json(nullptr);
    stddev_stats["max"] = valid > 0 ? Json(vmax) : Json(nullptr);
    stddev_stats["mean"] = valid > 0 ? Json(mean) : Json(nullptr);
    stddev_stats["std"] = valid > 0 ? Json(std) : Json(nullptr);
    stddev_stats["valid_count"] = valid;
    stddev_stats["total_count"] =
        static_cast<long long>(grid.live->variance_grid.size());
    const Json params =
        grid.metadata.is_object()
            ? dict_of(grid.metadata, "algorithm_parameters")
            : Json::object();
    Json extra = Json::object();
    extra["derivation"] = "stddev = sqrt(variance_grid)";
    extra["has_variance_grid"] = true;
    const Json* vmin_p = field(params, "variance_min");
    const Json* vmax_p = field(params, "variance_max");
    extra["variance_min"] = vmin_p != nullptr ? *vmin_p : Json(nullptr);
    extra["variance_max"] = vmax_p != nullptr ? *vmax_p : Json(nullptr);
    extra["stddev_statistics"] = stddev_stats;
    // Python calls _scalar_payload(None, grid, ...) — task=None means the
    // uncertainty child's artifact ids stay empty (honest absence, the
    // parent grid's pin lives on the factor_value child).
    Json payload = scalar_payload(Json(), grid, task_id, "stddev", extra);
    Json descriptor = Json::object();
    descriptor["layer_id"] = "factor_uncertainty:" + task_id;
    descriptor["role"] = std::string(layer_role::kFactorUncertainty);
    descriptor["title"] = title + "·不确定性";
    descriptor["geometry_kind"] = "raster";
    descriptor["payload"] = payload;
    descriptor["metadata"] = payload["metadata"];
    return descriptor;
}

// _constraint_diagnostics parity — merged requested/applied/ignored
// record (task parameters carry the engine-merged copy; the grid
// carries the raw evaluation).
Json constraint_diagnostics(const Json& task,
                            const FactorGroupGridView& grid) {
    Json merged = Json::object();
    if (grid.live != nullptr && grid.metadata.is_object()) {
        const Json raw = dict_of(
            dict_of(grid.metadata, "algorithm_parameters"),
            "constraint_diagnostics");
        for (const auto& [key, value] : raw.items()) merged[key] = value;
    }
    const Json task_side =
        dict_of(task_parameters(task), "constraint_diagnostics");
    for (const auto& [key, value] : task_side.items()) {
        merged[key] = value;
    }
    return merged;
}

// _qc_markers parity — known quality markers (rule/severity/reason).
Json qc_markers(const Json& task, const FactorGroupGridView& grid,
                bool uncertainty_present) {
    Json markers = Json::array();
    const Json diagnostics = constraint_diagnostics(task, grid);
    const auto push = [&](const Json& kinds, const std::string& rule_prefix,
                          const std::string& severity,
                          const std::string& reason_template) {
        if (!kinds.is_array()) return;
        for (const Json& kind : kinds) {
            if (!kind.is_string()) continue;
            const std::string k = kind.get<std::string>();
            Json marker = Json::object();
            marker["rule"] = rule_prefix + k;
            marker["severity"] = severity;
            // The Python templates embed the kind in the middle of the
            // sentence — the template here uses "{kind}" placeholders.
            std::string reason = reason_template;
            const auto pos = reason.find("{kind}");
            if (pos != std::string::npos) reason.replace(pos, 5, k);
            marker["reason"] = reason;
            markers.push_back(std::move(marker));
        }
    };
    push(array_of(diagnostics, "ignored_constraints"),
         "constraint_ignored:", "warning",
         "requested constraint {kind} was dropped silently by the "
         "backend");
    push(array_of(diagnostics, "unsupported_constraints"),
         "constraint_unsupported:", "warning",
         "interpolation method cannot honor requested constraint "
         "{kind}");
    push(array_of(diagnostics, "partial_constraints"),
         "constraint_partial:", "info",
         "requested constraint {kind} applied only partially");
    const Json quality = task_quality_metrics(task);
    const Json params =
        grid.metadata.is_object()
            ? dict_of(grid.metadata, "algorithm_parameters")
            : Json::object();
    const Json* dup = field(quality, "duplicate_wells_dropped");
    if (dup == nullptr) dup = field(params, "duplicate_wells_dropped");
    int duplicates = 0;
    if (dup != nullptr) {
        const auto v = finite(*dup);
        if (v) duplicates = static_cast<int>(*v);
    }
    if (duplicates > 0) {
        markers.push_back(Json::object(
            {{"rule", "duplicate_wells_dropped"},
             {"severity", "warning"},
             {"reason", std::to_string(duplicates) +
                            " duplicate wells were dropped before "
                            "interpolation"}}));
    }
    if (grid.live == nullptr) {
        markers.push_back(Json::object(
            {{"rule", "grid_unavailable"},
             {"severity", "info"},
             {"reason",
              "no live factor grid resident — grid/contour/"
              "classification children are empty (open the preparation "
              "page to load)"}}));
    } else if (!uncertainty_present) {
        markers.push_back(Json::object(
            {{"rule", "uncertainty_missing"},
             {"severity", "info"},
             {"reason",
              "algorithm produced no variance grid (kriging-only "
              "output) — uncertainty child not created"}}));
    }
    return markers;
}

// _qc_child parity — QC markers as anchor-point features.
Json qc_child(const Json& task, const FactorGroupGridView& grid,
              const std::string& task_id, const std::string& title,
              bool uncertainty_present) {
    const Json markers = qc_markers(task, grid, uncertainty_present);
    const auto anchor = anchor_xy(grid, task);
    Json features = Json::array();
    if (anchor.has_value()) {
        for (const Json& marker : markers) {
            Json properties = Json::object();
            properties["rule"] = str_of(marker, "rule");
            properties["severity"] = str_of(marker, "severity");
            properties["reason"] = str_of(marker, "reason");
            properties["factor_task_id"] = task_id;
            Json feature = Json::object();
            feature["geometry"] = Json::object(
                {{"type", "Point"},
                 {"coordinates",
                  Json::array({anchor->first, anchor->second})}});
            feature["properties"] = std::move(properties);
            features.push_back(std::move(feature));
        }
    }
    Json descriptor = Json::object();
    descriptor["layer_id"] = "factor_qc:" + task_id;
    descriptor["role"] = std::string(layer_role::kFactorQc);
    descriptor["title"] = title + "·QC";
    descriptor["geometry_kind"] = "point";
    descriptor["features"] = features;
    descriptor["metadata"] = Json::object(
        {{"factor_task_id", task_id},
         {"markers", markers},
         {"feature_count", static_cast<long long>(features.size())},
         {"anchor_available", anchor.has_value()}});
    return descriptor;
}

// _iter_polygon_rings parity — [x,y] rings (exterior first, holes after)
// of a Polygon/MultiPolygon geometry.
std::vector<const Json*> polygon_rings(const Json& geometry) {
    std::vector<const Json*> rings;
    const std::string gtype = str_of(geometry, "type");
    const Json* coordinates = field(geometry, "coordinates");
    if (coordinates == nullptr || !coordinates->is_array()
        || coordinates->empty())
        return rings;
    if (gtype == "Polygon") {
        for (const Json& ring : *coordinates) rings.push_back(&ring);
    } else if (gtype == "MultiPolygon") {
        for (const Json& poly : *coordinates) {
            if (!poly.is_array()) continue;
            for (const Json& ring : poly) rings.push_back(&ring);
        }
    }
    std::vector<const Json*> out;
    for (const Json* ring : rings) {
        if (ring->is_array() && ring->size() >= 3) out.push_back(ring);
    }
    return out;
}

// _probability_of parity — first finite probability/confidence field.
std::optional<double> probability_of(const Json& properties) {
    static constexpr std::string_view kFields[] = {
        "probability", "confidence", "confidence_probability",
        "mean_probability"};
    for (const std::string_view key : kFields) {
        const Json* v = field(properties, std::string(key).c_str());
        if (v == nullptr) continue;
        const auto value = finite(*v);
        if (value.has_value()) {
            return std::clamp(*value, 0.0, 1.0);
        }
    }
    return std::nullopt;
}

// _prediction_polygon_features parity — spatial.features preferred,
// spatial.polygons fallback (extract_polygon_features filter shape:
// Feature dicts carrying Polygon/MultiPolygon geometry).
Json prediction_polygon_features(const Json& task) {
    const Json summary = dict_of(task, "result_summary");
    const Json* spatial = field(summary, "spatial");
    if (spatial != nullptr && spatial->is_object()) {
        const Json* features = field(*spatial, "features");
        if (features != nullptr && features->is_array()
            && !features->empty()) {
            Json out = Json::array();
            for (const Json& f : *features) {
                if (f.is_object()) out.push_back(f);
            }
            if (!out.empty()) return out;
        }
        const Json* polygons = field(*spatial, "polygons");
        if (polygons != nullptr && polygons->is_array()) {
            Json out = Json::array();
            for (const Json& f : *polygons) {
                if (f.is_object()) out.push_back(f);
            }
            if (!out.empty()) return out;
        }
    }
    return Json::array();
}

}  // namespace

std::vector<Json> factor_group_layers(
    const Json& document, const Json& task,
    const FactorGroupGridView& grid, int contour_limit) {
    const std::string task_id = str_of(task, "id");
    const std::string title =
        factor_group_title(str_of(task, "name"), str_of(task, "factor_type"));
    std::vector<Json> descriptors;
    descriptors.push_back(input_child(document, task, task_id, title));
    descriptors.push_back(grid_child(task, grid, task_id, title));
    descriptors.push_back(
        contour_child(grid, task, task_id, title, contour_limit));
    descriptors.push_back(
        classification_child(grid, task, task_id, title));
    const Json uncertainty = uncertainty_child(grid, task_id, title);
    if (!uncertainty.is_null()) descriptors.push_back(uncertainty);
    descriptors.push_back(qc_child(task, grid, task_id, title,
                                   !uncertainty.is_null()));
    return descriptors;
}

std::string classify_prediction_task(const Json& task) {
    const Json refs = dict_of(task, "input_refs");
    std::string keys;
    for (const auto& [key, value] : refs.items()) {
        if (value.is_null() || (value.is_boolean() && !value.get<bool>())
            || (value.is_string() && value.get<std::string>().empty()))
            continue;
        std::string lower = key;
        std::transform(lower.begin(), lower.end(), lower.begin(),
                       [](unsigned char c) {
                           return static_cast<char>(std::tolower(c));
                       });
        keys += lower;
        keys += ' ';
    }
    if (keys.find("seis") != std::string::npos) return "seismic";
    if (keys.find("well") != std::string::npos
        || keys.find("log") != std::string::npos)
        return "well";
    std::string name = str_of(task, "name");
    std::transform(name.begin(), name.end(), name.begin(),
                   [](unsigned char c) {
                       return static_cast<char>(std::tolower(c));
                   });
    if (name.find("seis") != std::string::npos
        || name.find("地震") != std::string::npos)
        return "seismic";
    if (name.find("well") != std::string::npos
        || name.find("测井") != std::string::npos
        || name.find("井") != std::string::npos)
        return "well";
    return "unknown";
}

std::vector<Json> confidence_overlay_layers(
    const Json& document, const Json& prediction_task) {
    (void)document;  // spatial results travel on the task
    const std::string category = classify_prediction_task(prediction_task);
    std::string role;
    if (category == "well") {
        role = std::string(layer_role::kWellFaciesConfidence);
    } else if (category == "seismic") {
        role = std::string(layer_role::kSeismicFaciesConfidence);
    } else {
        return {};
    }
    const std::string task_id = str_of(prediction_task, "id");
    const std::string name = str_of(prediction_task, "name");
    Json features = Json::array();
    std::vector<double> probabilities;
    for (const Json& record : prediction_polygon_features(prediction_task)) {
        const Json* geometry = field(record, "geometry");
        if (geometry == nullptr || !geometry->is_object()) continue;
        const std::string gtype = str_of(*geometry, "type");
        if (gtype != "Polygon" && gtype != "MultiPolygon") continue;
        const Json properties = dict_of(record, "properties");
        const auto probability = probability_of(properties);
        if (!probability.has_value()) continue;
        probabilities.push_back(*probability);
        Json attributes = Json::object();
        attributes["probability"] = *probability;
        attributes["facies"] = str_of(properties, "facies");
        std::string region_id = str_of(properties, "region_id");
        if (region_id.empty()) region_id = str_of(record, "id");
        attributes["region_id"] = region_id;
        attributes["prediction_task_id"] = task_id;
        for (const char* extra :
             {"confidence", "merged_sample_count", "stratigraphic_unit"}) {
            const Json* v = field(properties, extra);
            if (v != nullptr && !v->is_null()) attributes[extra] = *v;
        }
        Json feature = Json::object();
        feature["geometry"] = *geometry;
        feature["properties"] = std::move(attributes);
        features.push_back(std::move(feature));
    }
    if (features.empty()) return {};
    double pmin = probabilities.front(), pmax = probabilities.front(),
           sum = 0.0;
    for (const double p : probabilities) {
        pmin = std::min(pmin, p);
        pmax = std::max(pmax, p);
        sum += p;
    }
    const std::string label = category == "well" ? "测井" : "地震";
    Json descriptor = Json::object();
    descriptor["layer_id"] = "prediction_confidence:" + task_id;
    descriptor["role"] = role;
    descriptor["title"] = name + "（" + label + "预测置信度）";
    descriptor["geometry_kind"] = "polygon";
    descriptor["features"] = features;
    descriptor["metadata"] = Json::object(
        {{"prediction_task_id", task_id},
         {"category", category},
         {"feature_count", static_cast<long long>(features.size())},
         {"probability_min", pmin},
         {"probability_max", pmax},
         {"probability_mean",
          sum / static_cast<double>(probabilities.size())}});
    return {descriptor};
}

std::vector<std::pair<Json, Json>> boundary_features_from_polygons(
    const std::vector<std::pair<Json, Json>>& features,
    const std::string& source_layer_id) {
    std::vector<std::pair<Json, Json>> out;
    for (const auto& [geometry, properties] : features) {
        if (!geometry.is_object()) continue;
        int ring_index = 0;
        for (const Json* ring : polygon_rings(geometry)) {
            Json points = Json::array();
            for (const Json& point : *ring) {
                if (!point.is_array() || point.size() < 2) continue;
                const auto x = finite(point[0]);
                const auto y = finite(point[1]);
                if (!x || !y) continue;
                points.push_back(Json::array({*x, *y}));
            }
            if (points.size() < 3) continue;
            std::string facies = str_of(properties, "facies");
            if (facies.empty()) facies = str_of(properties, "facies_name");
            Json attributes = Json::object();
            attributes["facies"] = facies;
            attributes["ring"] = ring_index == 0
                                     ? "exterior"
                                     : "hole_" + std::to_string(ring_index);
            attributes["source_layer_id"] = source_layer_id;
            out.emplace_back(
                Json::object({{"type", "LineString"},
                              {"coordinates", std::move(points)}}),
                std::move(attributes));
            ++ring_index;
        }
    }
    return out;
}

Json integrated_boundary_action_helpers(
    const Json& document, const std::string& source_layer_id) {
    const Json* layer = nullptr;
    const Json* layers = field(document, "user_vector_layers");
    if (layers != nullptr && layers->is_array()) {
        for (const Json& candidate : *layers) {
            if (str_of(candidate, "id") == source_layer_id) {
                layer = &candidate;
                break;
            }
        }
    }
    if (layer == nullptr) return Json();
    std::vector<std::pair<Json, Json>> features;
    const Json* raw = field(*layer, "features");
    if (raw != nullptr && raw->is_array()) {
        for (const Json& feature : *raw) {
            const Json* geometry = field(feature, "geometry");
            if (geometry == nullptr || !geometry->is_object()) continue;
            const Json* props = field(feature, "properties");
            features.emplace_back(
                *geometry,
                props != nullptr && props->is_object() ? *props
                                                       : Json::object());
        }
    }
    const auto boundary =
        boundary_features_from_polygons(features, source_layer_id);
    if (boundary.empty()) return Json();
    Json descriptor = Json::object();
    descriptor["layer_id"] = "integrated_boundary:" + source_layer_id;
    descriptor["role"] = std::string(layer_role::kIntegratedBoundary);
    descriptor["title"] = "综合相带边界";
    descriptor["geometry_kind"] = "line";
    descriptor["features"] = Json::array();
    for (const auto& [geometry, properties] : boundary) {
        descriptor["features"].push_back(
            Json::object({{"geometry", geometry},
                          {"properties", properties}}));
    }
    descriptor["metadata"] = Json::object(
        {{"source_layer_id", source_layer_id},
         {"feature_count",
          static_cast<long long>(boundary.size())}});
    return descriptor;
}

}  // namespace pwb::ui_composite
