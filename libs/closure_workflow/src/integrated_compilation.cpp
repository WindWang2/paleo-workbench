// integrated_compilation.cpp — see include/pwb/closure_workflow/
// integrated_compilation.hpp. Line anchors cite
// paleo_workbench/workflow/integrated_compilation.py.

#include <pwb/closure_workflow/integrated_compilation.hpp>

#include <pwb/factor_host/canonical_json.hpp>
#include <pwb/mapping/geometry_units.hpp>
#include <pwb/mapping/polygonization.hpp>
#include <pwb/workflow_interpretation/compilation.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <set>
#include <stdexcept>
#include <utility>

namespace pwb::closure_workflow {

namespace {

// ValueError parity.
[[noreturn]] void refuse(const std::string& message) {
    throw std::invalid_argument(message);
}

const Json kEmptyArray = Json::array();
const Json& array_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return kEmptyArray;
    const auto it = obj.find(key);
    if (it == obj.end() || !it->is_array()) return kEmptyArray;
    return *it;
}

std::string string_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return {};
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null() || !it->is_string()) return {};
    return it->get<std::string>();
}

// _task_id_of_evidence (L91): task id of `factor:<task_id>[:<version>]`.
std::optional<std::string> task_id_of_evidence(const std::string& value) {
    // Python split(":") semantics on str(value or "").
    std::vector<std::string> parts;
    std::string current;
    for (char c : value) {
        if (c == ':') {
            parts.push_back(current);
            current.clear();
        } else {
            current += c;
        }
    }
    parts.push_back(current);
    if (parts.size() >= 2 && parts[0] == "factor" && !parts[1].empty()) {
        return parts[1];
    }
    return std::nullopt;
}

// Python repr of a string list: "['a', 'b']".
std::string repr_list(const std::vector<std::string>& values) {
    std::string out = "[";
    for (size_t i = 0; i < values.size(); ++i) {
        if (i != 0) out += ", ";
        out += "'" + values[i] + "'";
    }
    return out + "]";
}

// ---------------------------------------------------------------- stats --

struct GridStats {
    double min = 0.0;
    double max = 0.0;
    double mean = 0.0;
    double std = 0.0;
    long long valid_count = 0;
    long long total_count = 0;
};

GridStats statistics_of(const FactorGrid& grid) {
    GridStats stats;
    stats.total_count =
        static_cast<long long>(grid.grid_z.size());
    double sum = 0.0;
    double sum_sq = 0.0;
    for (float cell : grid.grid_z) {
        const double v = static_cast<double>(cell);
        if (!std::isfinite(v)) continue;
        if (stats.valid_count == 0 || v < stats.min) stats.min = v;
        if (stats.valid_count == 0 || v > stats.max) stats.max = v;
        sum += v;
        sum_sq += v * v;
        ++stats.valid_count;
    }
    if (stats.valid_count == 0) {
        stats.min = stats.max = stats.mean = stats.std =
            std::numeric_limits<double>::quiet_NaN();
        return stats;
    }
    const double n = static_cast<double>(stats.valid_count);
    stats.mean = sum / n;
    // numpy .std() population variance.
    stats.std = std::sqrt(std::max(0.0, sum_sq / n - stats.mean * stats.mean));
    return stats;
}

}  // namespace

Json grid_statistics_json(const FactorGrid& grid) {
    const GridStats stats = statistics_of(grid);
    auto json_number = [](double v) {
        return std::isfinite(v) ? Json(v) : Json(nullptr);
    };
    Json out = Json::object();
    out["min"] = json_number(stats.min);
    out["max"] = json_number(stats.max);
    out["mean"] = json_number(stats.mean);
    out["std"] = json_number(stats.std);
    out["valid_count"] = stats.valid_count;
    out["total_count"] = stats.total_count;
    return out;
}

std::string encode_grid_artifact(const FactorGrid& grid,
                                 const std::string& quantity) {
    Json artifact = Json::object();
    artifact["artifact_kind"] = "factor_grid";
    artifact["quantity"] = quantity;
    artifact["factor_name"] = grid.factor_name;
    artifact["algorithm_id"] = grid.algorithm_id;
    artifact["algorithm_parameters"] = grid.algorithm_parameters;
    artifact["crs"] =
        grid.crs.has_value() ? Json(*grid.crs) : Json(nullptr);
    artifact["unit"] =
        grid.unit.has_value() ? Json(*grid.unit) : Json(nullptr);
    artifact["generator_version"] = grid.generator_version.has_value()
                                        ? Json(*grid.generator_version)
                                        : Json(nullptr);
    artifact["run_ref"] =
        grid.run_ref.has_value() ? Json(*grid.run_ref) : Json(nullptr);
    artifact["source_refs"] = grid.source_refs;
    artifact["width"] = grid.width;
    artifact["height"] = grid.height;
    artifact["grid_x"] = grid.grid_x;
    artifact["grid_y"] = grid.grid_y;
    Json cells = Json::array();
    cells.get_ref<Json::array_t&>().reserve(grid.grid_z.size());
    for (float cell : grid.grid_z) {
        const double v = static_cast<double>(cell);
        cells.push_back(std::isfinite(v) ? Json(v) : Json("NaN"));
    }
    artifact["grid_z"] = std::move(cells);
    if (grid.variance_grid.has_value()) {
        Json variance = Json::array();
        variance.get_ref<Json::array_t&>().reserve(
            grid.variance_grid->size());
        for (float cell : *grid.variance_grid) {
            const double v = static_cast<double>(cell);
            variance.push_back(std::isfinite(v) ? Json(v) : Json("NaN"));
        }
        artifact["variance_grid"] = std::move(variance);
    }
    return pwb::domain::dump_json_python_compatible(artifact);
}

// ---------------------------------------------------- inputs resolution --

std::map<std::string, FactorGrid> fusion_inputs_from_document(
    const Json& document,
    const std::vector<std::pair<std::string, std::string>>& evidence_set,
    std::vector<std::string>* mismatches, CatalogRepository* catalog,
    const IntegratedGridSeams& seams) {
    std::map<std::string, const Json*> tasks;
    for (const Json& task : array_field(document, "factor_map_tasks")) {
        if (!task.is_object()) continue;
        const std::string id = string_field(task, "id");
        tasks[id] = &task;  // str(task.id) keying; duplicates: last wins
    }
    std::map<std::string, FactorGrid> resolved;
    std::vector<std::string> unresolvable;
    for (const auto& [label, value] : evidence_set) {
        const std::optional<std::string> task_id =
            task_id_of_evidence(value);
        if (!task_id.has_value() || resolved.count(*task_id) != 0) {
            continue;
        }
        const auto task_it = tasks.find(*task_id);
        if (task_it == tasks.end()) {
            unresolvable.push_back(label + "（" + value +
                                   "）：工程中没有该单因素任务");
            continue;
        }
        const Json& task = *task_it->second;
        // Pinned version = third colon field (parts[2] when present).
        std::string pinned_version;
        {
            const std::size_t first = value.find(':');
            const std::size_t second =
                first == std::string::npos ? std::string::npos
                                           : value.find(':', first + 1);
            if (first != std::string::npos && second != std::string::npos) {
                std::string rest = value.substr(second + 1);
                const std::size_t third = rest.find(':');
                if (third != std::string::npos) rest = rest.substr(0, third);
                pinned_version = rest;
            }
        }
        const std::string current_version =
            string_field(task, "grid_artifact_version_id");
        if (!pinned_version.empty() && pinned_version != current_version) {
            std::optional<FactorGrid> pinned;
            // Python gates the pinned load on `catalog is not None`; the
            // injected loader IS the C++ catalog face for pinned
            // artifacts, so its presence is the gate.
            if (seams.grid_from_version) {
                pinned = seams.grid_from_version(pinned_version);
            }
            if (pinned.has_value()) {
                if (mismatches != nullptr) {
                    mismatches->push_back(
                        label + "：钉住版本 " + pinned_version + " ≠ 任务当前版本 " +
                        (current_version.empty() ? "∅" : current_version) +
                        "——融合使用钉住网格");
                }
                resolved[*task_id] = std::move(*pinned);
                continue;
            }
            if (!current_version.empty()) {
                unresolvable.push_back(
                    label + "（" + value + "）：钉住版本 " + pinned_version +
                    " 无法从目录装载网格（拒绝用当前网格冒充冻结输入）");
                continue;
            }
            // No current version and pin not in catalog: legacy live token.
        }
        std::optional<FactorGrid> grid;
        if (seams.grid_for_task) {
            try {
                grid = seams.grid_for_task(task);
            } catch (const std::exception& exc) {
                unresolvable.push_back(label + "（" + value + "）：" + exc.what());
                continue;
            }
        }
        if (grid.has_value()) {
            resolved[*task_id] = std::move(*grid);
        } else {
            unresolvable.push_back(label + "（" + value +
                                   "）：网格解析失败（live 缓存 → npz 工件 → "
                                   "内联参数均不可用）");
        }
    }
    if (!unresolvable.empty()) {
        std::string joined;
        for (size_t i = 0; i < unresolvable.size(); ++i) {
            if (i != 0) joined += "；";
            joined += unresolvable[i];
        }
        refuse("以下证据因子无法解析为网格成果（pin 目录工件 → live 缓存 → "
               "npz 工件 → 内联参数均失败），拒绝在残缺证据集上融合：" +
               joined);
    }
    return resolved;
}

// --------------------------------------------------------- model build --

namespace {

// _unique_factor_names (L185): task-id-ordered evidence names,
// de-duplicated with an explicit "(task_id)" suffix.
std::map<std::string, std::string> unique_factor_names(
    const std::map<std::string, FactorGrid>& factor_results) {
    std::map<std::string, std::string> names;
    std::set<std::string> seen;
    for (const auto& [task_id, grid] : factor_results) {
        std::string base =
            grid.factor_name.empty() ? task_id : grid.factor_name;
        const std::string name =
            seen.count(base) == 0 ? base : base + "(" + task_id + ")";
        seen.insert(name);
        names[task_id] = name;
    }
    return names;
}

struct WeightsResult {
    std::map<std::string, double> resolved;
    Json record;
};

WeightsResult resolve_weights(
    const std::vector<std::string>& task_ids,
    const std::optional<std::map<std::string, double>>& weights) {
    WeightsResult result;
    if (!weights.has_value()) {
        Json record = Json::object();
        record["policy"] = "equal";
        record["value"] = 1.0;
        result.record = std::move(record);
        for (const std::string& task_id : task_ids) {
            result.resolved[task_id] = 1.0;
        }
        return result;
    }
    std::vector<std::string> unknown;
    for (const auto& [key, value] : *weights) {
        if (std::find(task_ids.begin(), task_ids.end(), key) ==
            task_ids.end()) {
            unknown.push_back(key);
        }
    }
    if (!unknown.empty()) {
        refuse("weights 引用了未知任务 " + repr_list(unknown) + "；可用任务 id：" +
               repr_list(task_ids));
    }
    Json values = Json::object();
    for (const std::string& task_id : task_ids) {
        const auto it = weights->find(task_id);
        if (it == weights->end()) {
            refuse("weights 缺少任务 '" + task_id + "' 的权重");
        }
        const double value = it->second;
        if (!std::isfinite(value) || value <= 0.0) {
            refuse("任务 '" + task_id + "' 的权重必须为有限正数，得到 " +
                   pwb::factor_host::python_repr_double(value));
        }
        result.resolved[task_id] = value;
        values[task_id] = value;
    }
    Json record = Json::object();
    record["policy"] = "explicit";
    record["values"] = std::move(values);
    result.record = std::move(record);
    return result;
}

struct ClassesResult {
    std::vector<std::string> names;
    std::vector<double> thresholds;
    Json record;
};

ClassesResult resolve_classes(
    const std::optional<std::vector<std::string>>& class_names,
    const std::optional<std::vector<double>>& class_thresholds) {
    ClassesResult result;
    if (!class_names.has_value() && !class_thresholds.has_value()) {
        for (const char* name : kDefaultFusionClassNames) {
            result.names.emplace_back(name);
        }
        for (double t : kDefaultFusionClassThresholds) {
            result.thresholds.push_back(t);
        }
        Json record = Json::object();
        record["policy"] = "default_equal_thirds";
        record["class_names"] = result.names;
        record["class_thresholds"] = result.thresholds;
        result.record = std::move(record);
        return result;
    }
    if (!class_names.has_value() || !class_thresholds.has_value()) {
        refuse(std::string("class_names 与 class_thresholds 必须同时提供（得到 "
                           "names=") +
               (class_names.has_value() ? "True" : "False") + ", thresholds=" +
               (class_thresholds.has_value() ? "True" : "False") +
               "）；或同时省略以使用低/中/高三分默认");
    }
    result.names = *class_names;
    result.thresholds = *class_thresholds;
    if (result.thresholds.size() != result.names.size() - 1) {
        refuse("class_thresholds 需要 len(class_names)-1=" +
               std::to_string(result.names.size() - 1) + " 个阈值，得到 " +
               std::to_string(result.thresholds.size()));
    }
    Json record = Json::object();
    record["policy"] = "explicit";
    record["class_names"] = result.names;
    record["class_thresholds"] = result.thresholds;
    result.record = std::move(record);
    return result;
}

struct NormsResult {
    std::map<std::string, Normalization> resolved;
    Json record;
};

Json normalization_dict(const std::map<std::string, Normalization>& resolved) {
    // Python: {k: v.to_dict() for k, v in sorted(resolved.items())}.
    Json bounds = Json::object();
    for (const auto& [task_id, normalization] : resolved) {
        bounds[task_id] = normalization.to_dict();
    }
    return bounds;
}

NormsResult resolve_normalizations(
    const std::map<std::string, FactorGrid>& factor_results,
    const std::map<std::string, std::string>& names,
    const std::optional<std::map<std::string, Normalization>>& normalizations) {
    NormsResult result;
    if (normalizations.has_value()) {
        std::vector<std::string> unknown;
        for (const auto& [key, value] : *normalizations) {
            if (factor_results.count(key) == 0) unknown.push_back(key);
        }
        if (!unknown.empty()) {
            std::vector<std::string> known;
            for (const auto& [task_id, grid] : factor_results) {
                known.push_back(task_id);
            }
            refuse("normalizations 引用了未知任务 " + repr_list(unknown) +
                   "；可用任务 id：" + repr_list(known));
        }
        result.resolved = *normalizations;
        Json record = Json::object();
        record["policy"] = "explicit";
        record["bounds"] = normalization_dict(result.resolved);
        result.record = std::move(record);
        return result;
    }
    for (const auto& [task_id, grid] : factor_results) {
        const GridStats stats = statistics_of(grid);
        if (!std::isfinite(stats.min) || !std::isfinite(stats.max)) {
            refuse("因子 '" + names.at(task_id) + "'（任务 " + task_id +
                   "）没有有限值——无法从数据确定归一化范围；请显式提供 "
                   "normalizations");
        }
        if (!(stats.max > stats.min)) {
            refuse("因子 '" + names.at(task_id) + "'（任务 " + task_id +
                   "）是常数网格（min == max == " +
                   pwb::factor_host::python_repr_double(stats.min) +
                   "）——归一化需要 high > low；请显式提供 normalizations");
        }
        result.resolved.emplace(task_id,
                                Normalization("minmax", stats.min, stats.max));
    }
    Json record = Json::object();
    record["policy"] = "per_factor_finite_range";
    record["bounds"] = normalization_dict(result.resolved);
    result.record = std::move(record);
    return result;
}

Json defaults_record(
    const std::vector<std::pair<std::string, std::string>>& evidence_set,
    const std::map<std::string, FactorGrid>& factor_results,
    const std::optional<std::map<std::string, double>>& weights,
    const std::optional<std::map<std::string, Normalization>>& normalizations,
    const std::optional<std::vector<std::string>>& class_names,
    const std::optional<std::vector<double>>& class_thresholds) {
    // Mirror build_fusion_model's applied policies (L407).
    std::set<std::string> wanted;
    for (const auto& [label, value] : evidence_set) {
        const std::optional<std::string> task_id = task_id_of_evidence(value);
        if (task_id.has_value()) wanted.insert(*task_id);
    }
    std::map<std::string, FactorGrid> subset;
    for (const std::string& task_id : wanted) {
        subset[task_id] = factor_results.at(task_id);
    }
    const std::map<std::string, std::string> names = unique_factor_names(subset);
    const WeightsResult weights_result = resolve_weights(
        std::vector<std::string>(wanted.begin(), wanted.end()), weights);
    const ClassesResult classes_result =
        resolve_classes(class_names, class_thresholds);
    const NormsResult norms_result =
        resolve_normalizations(subset, names, normalizations);
    Json out = Json::object();
    out["weights"] = weights_result.record;
    out["classes"] = classes_result.record;
    out["normalization"] = norms_result.record;
    return out;
}

Json fusion_scalar_descriptor(const FactorGrid& grid, const FusionResult& result,
                              const std::string& quantity,
                              const std::string& title,
                              const std::string& catalog_version_id) {
    // Scalar-grid descriptor in the factor_layer_products vocabulary
    // (L436); grid arrays never cross into the descriptor.
    const std::string fingerprint = result.model.fingerprint();
    Json fusion_meta = Json::object();
    fusion_meta["model_name"] = result.model.name;
    fusion_meta["model_fingerprint"] = fingerprint;
    fusion_meta["fusion_kind"] = result.model.kind;
    fusion_meta["class_names"] = result.class_names;
    fusion_meta["class_thresholds"] = result.model.class_thresholds;
    fusion_meta["evidence_count"] = result.model.evidences.size();
    Json evidences = Json::array();
    for (const pwb::factor_fusion::FactorEvidence& ev : result.model.evidences) {
        evidences.push_back(ev.factor_name);
    }
    fusion_meta["evidences"] = std::move(evidences);

    const GridStats stats = statistics_of(grid);
    const double xmin =
        grid.grid_x.empty() ? 0.0 : grid.grid_x.front();
    const double xmax =
        grid.grid_x.empty() ? 0.0 : grid.grid_x.back();
    const double ymin =
        grid.grid_y.empty() ? 0.0 : grid.grid_y.front();
    const double ymax =
        grid.grid_y.empty() ? 0.0 : grid.grid_y.back();

    Json metadata = Json::object();
    metadata["layer_type"] = "scalar_grid";
    metadata["quantity"] = quantity;
    metadata["source"] = "factor_fusion";
    metadata["algorithm_id"] = grid.algorithm_id;
    metadata["crs"] = grid.crs.has_value() ? Json(*grid.crs) : Json(nullptr);
    metadata["unit"] = grid.unit.has_value() ? Json(*grid.unit) : Json(nullptr);
    Json extent = Json::array();
    extent.push_back(xmin);
    extent.push_back(ymin);
    extent.push_back(xmax);
    extent.push_back(ymax);
    metadata["extent"] = std::move(extent);
    metadata["width"] = grid.width;
    metadata["height"] = grid.height;
    metadata["statistics"] = grid_statistics_json(grid);
    metadata["artifact_version_id"] = catalog_version_id;
    metadata["run_ref"] =
        grid.run_ref.has_value() ? Json(*grid.run_ref) : Json(nullptr);
    metadata["fusion"] = std::move(fusion_meta);
    (void)stats;

    Json payload = Json::object();
    payload["layer_type"] = "scalar_grid";
    payload["factor_task_id"] = "";
    payload["quantity"] = quantity;
    payload["source"] = "factor_fusion";
    // grid.to_descriptor() parity (factor_grid_result.py L617) — metadata
    // only, never grid arrays.
    payload["descriptor"] = Json::object();
    Json& descriptor = payload["descriptor"];
    descriptor["factor_name"] = grid.factor_name;
    descriptor["algorithm_id"] = grid.algorithm_id;
    descriptor["algorithm_parameters"] = grid.algorithm_parameters;
    descriptor["crs"] = metadata["crs"];
    descriptor["crs_is_known"] = grid.crs.has_value();
    descriptor["unit"] = metadata["unit"];
    descriptor["width"] = grid.width;
    descriptor["height"] = grid.height;
    descriptor["extent"] = metadata["extent"];
    descriptor["generator_version"] =
        grid.generator_version.has_value() ? Json(*grid.generator_version)
                                           : Json(nullptr);
    descriptor["source_refs"] = grid.source_refs;
    descriptor["input_version_ids"] = grid.source_refs;
    descriptor["run_ref"] = metadata["run_ref"];
    descriptor["run_id"] = metadata["run_ref"];
    descriptor["created_at"] = Json(nullptr);
    descriptor["has_variance_grid"] = grid.variance_grid.has_value();
    descriptor["has_boundary"] = false;
    descriptor["statistics"] = metadata["statistics"];
    payload["metadata"] = metadata;

    Json out = Json::object();
    out["layer_id"] = quantity + ":" + fingerprint.substr(0, 12);
    out["role"] = "analysis_aid";  // LayerRole.ANALYSIS_AID 分析辅助
    out["title"] = title;
    out["geometry_kind"] = "raster";
    out["payload"] = std::move(payload);
    out["metadata"] = metadata;
    return out;
}

// Polygonised fused classification ((geometry, properties), qc) — L496.
// Reuses the single-factor polygonization kernel on the fused likelihood
// with the model's own thresholds/names; failures are honest emptiness.
// Python round(x, 4): decimal half-to-even of the exact binary value via
// %.4f formatting (the receipt.cpp round3 pattern).
double python_round4(double value) {
    char buffer[64];
    std::snprintf(buffer, sizeof buffer, "%.4f", value);
    return std::strtod(buffer, nullptr);
}

std::pair<Json, Json> classification_features(const FusionResult& result) {
    Json qc = Json::object();
    qc["feature_count"] = 0;
    Json features = Json::array();
    try {
        // FactorGrid → mapping::Grid conversion (float32 → float64).
        pwb::mapping::Grid grid;
        grid.w = static_cast<std::size_t>(result.likelihood.width);
        grid.h = static_cast<std::size_t>(result.likelihood.height);
        grid.grid_x = result.likelihood.grid_x;
        grid.grid_y = result.likelihood.grid_y;
        grid.grid_z.reserve(result.likelihood.grid_z.size());
        for (float cell : result.likelihood.grid_z) {
            grid.grid_z.push_back(static_cast<double>(cell));
        }
        const double xmin = grid.grid_x.empty() ? 0.0 : grid.grid_x.front();
        const double xmax = grid.grid_x.empty() ? 0.0 : grid.grid_x.back();
        const double ymin = grid.grid_y.empty() ? 0.0 : grid.grid_y.front();
        const double ymax = grid.grid_y.empty() ? 0.0 : grid.grid_y.back();
        const double total_grid_area =
            std::max(1e-12, (xmax - xmin) * (ymax - ymin));
        const std::optional<std::string> crs = result.likelihood.crs;

        // Python classify: 0, 1, ..., len(names)-1 over the explicit
        // thresholds (mapping_kernel classify_grid, same loop).
        const int n_classes = static_cast<int>(result.class_names.size());
        const std::vector<std::int16_t> class_grid =
            pwb::mapping::classify_grid(grid, result.model.class_thresholds,
                                        n_classes);
        const std::vector<std::string>& names = result.class_names;
        // Default palette (polygonization.py L450).
        static const char* const kPalette[] = {"#b0bec5", "#ffe082",
                                               "#d73027", "#81c784",
                                               "#4fc3f7", "#ba68c8"};
        int holes_promoted = 0;
        for (int c_idx = 0; c_idx < n_classes; ++c_idx) {
            const auto [polygons, hole_qc] =
                pwb::mapping::polygonize_class(grid, class_grid, c_idx);
            holes_promoted += hole_qc.holes_promoted_to_exterior;
            const std::string facies_name =
                names[static_cast<std::size_t>(c_idx)];
            const std::string color =
                kPalette[static_cast<std::size_t>(c_idx) %
                         (sizeof kPalette / sizeof kPalette[0])];
            // mean over the class's finite cells.
            double sum = 0.0;
            long long count = 0;
            for (std::size_t i = 0; i < grid.grid_z.size(); ++i) {
                if (class_grid[i] == c_idx &&
                    std::isfinite(grid.grid_z[i])) {
                    sum += grid.grid_z[i];
                    ++count;
                }
            }
            const double mean_val =
                count > 0 ? sum / static_cast<double>(count) : 0.0;
            for (const pwb::mapping::Polygon& polygon : polygons) {
                double raw_area =
                    pwb::mapping::shoelace_area(polygon.exterior);
                for (const pwb::mapping::Ring& hole : polygon.holes) {
                    raw_area -= pwb::mapping::shoelace_area(hole);
                }
                raw_area = std::max(raw_area, 0.0);
                const double area_pct =
                    (raw_area / total_grid_area) * 100.0;

                Json geometry = Json::object();
                geometry["type"] = "Polygon";
                Json rings = Json::array();
                Json exterior = Json::array();
                for (const pwb::mapping::Point& point : polygon.exterior) {
                    Json xy = Json::array();
                    xy.push_back(point[0]);
                    xy.push_back(point[1]);
                    exterior.push_back(std::move(xy));
                }
                rings.push_back(std::move(exterior));
                for (const pwb::mapping::Ring& hole : polygon.holes) {
                    Json hole_ring = Json::array();
                    for (const pwb::mapping::Point& point : hole) {
                        Json xy = Json::array();
                        xy.push_back(point[0]);
                        xy.push_back(point[1]);
                        hole_ring.push_back(std::move(xy));
                    }
                    rings.push_back(std::move(hole_ring));
                }
                geometry["coordinates"] = std::move(rings);

                Json properties = Json::object();
                properties["facies_id"] = c_idx + 1;
                properties["facies_name"] = facies_name;
                properties["facies"] = facies_name;
                properties["color"] = color;
                properties["area"] = python_round4(raw_area);
                properties["area_unit"] =
                    pwb::mapping::area_unit_label(crs);
                properties["area_percent"] = python_round4(area_pct);
                properties["mean_value"] = python_round4(mean_val);

                Json pair = Json::array();  // (geometry, properties) tuple
                pair.push_back(std::move(geometry));
                pair.push_back(std::move(properties));
                features.push_back(std::move(pair));
            }
        }
        // Full polygon_qc parity (polygonization.py L460-477): the
        // classification thresholds ARE part of the product and the nodata
        // extent must be visible.
        Json polygon_qc = Json::object();
        polygon_qc["small_polygon_threshold"] = Json(nullptr);
        polygon_qc["small_polygons_dropped"] = 0;
        polygon_qc["clipped_to_domain"] = 0;
        polygon_qc["empty_after_clip"] = 0;
        polygon_qc["thresholds"] = result.model.class_thresholds;
        polygon_qc["thresholds_source"] = "explicit";
        long long nodata_cells = 0;
        for (double cell : grid.grid_z) {
            if (!std::isfinite(cell)) ++nodata_cells;
        }
        polygon_qc["nodata_cells"] = nodata_cells;
        polygon_qc["total_cells"] =
            static_cast<long long>(grid.grid_z.size());
        polygon_qc["area_unit"] = pwb::mapping::area_unit_label(crs);
        Json area_warnings = Json::array();
        if (pwb::mapping::is_geographic_crs(crs)) {
            area_warnings.push_back(
                "geographic CRS: per-feature areas are local-scale "
                "approximations");
        }
        const std::string stripped_crs =
            crs.has_value() ? *crs : std::string();
        if (stripped_crs.find_first_not_of(" \t\r\n") == std::string::npos) {
            area_warnings.push_back(
                "CRS undeclared: area unit unknown (not metres)");
            // The per-feature ring warning spells it differently (the
            // Python near-duplicate quirk, polygonization.py L476 vs the
            // ring helper) — both survive the dedup.
            area_warnings.push_back(
                "CRS undeclared: area unit is unknown (not metres)");
        }
        polygon_qc["area_warnings"] = area_warnings;
        polygon_qc["holes_promoted_to_exterior"] = holes_promoted;
        qc["polygon_qc"] = std::move(polygon_qc);
        qc["feature_count"] = features.size();
    } catch (const std::exception& exc) {
        qc["absent_reason"] =
            std::string("polygonization failed: ") + exc.what();
        qc["feature_count"] = features.size();
    }
    return {features, qc};
}

}  // namespace

FusionModel build_fusion_model(
    const std::vector<std::pair<std::string, std::string>>& evidence_set,
    const std::map<std::string, FactorGrid>& factor_results,
    const std::optional<std::map<std::string, double>>& weights,
    const std::optional<std::map<std::string, Normalization>>& normalizations,
    const std::string& default_class,
    std::optional<std::vector<std::string>> class_names,
    std::optional<std::vector<double>> class_thresholds,
    const std::string& name, const Json& weight_provenance) {
    std::vector<std::string> wanted;
    for (const auto& [label, value] : evidence_set) {
        const std::optional<std::string> task_id = task_id_of_evidence(value);
        if (!task_id.has_value()) continue;
        if (factor_results.count(*task_id) == 0) {
            std::vector<std::string> loaded;
            for (const auto& [task, grid] : factor_results) {
                loaded.push_back(task);
            }
            std::sort(loaded.begin(), loaded.end());
            refuse("证据 '" + label + "'（" + value + "）引用的任务 '" +
                   *task_id + "' 不在已加载网格中（已加载：" +
                   repr_list(loaded) + "）——拒绝静默丢弃证据");
        }
        if (std::find(wanted.begin(), wanted.end(), *task_id) ==
            wanted.end()) {
            wanted.push_back(*task_id);
        }
    }
    if (wanted.empty()) {
        refuse("证据集中没有 factor:<task>:<version> 条目——加权证据融合至少"
               "需要一个单因素网格");
    }
    std::vector<std::string> ordered = wanted;
    std::sort(ordered.begin(), ordered.end());
    std::map<std::string, FactorGrid> ordered_grids;
    for (const std::string& task_id : ordered) {
        ordered_grids[task_id] = factor_results.at(task_id);
    }
    const std::map<std::string, std::string> names =
        unique_factor_names(ordered_grids);
    const WeightsResult weights_result = resolve_weights(ordered, weights);
    const NormsResult norms_result =
        resolve_normalizations(ordered_grids, names, normalizations);
    const ClassesResult classes_result =
        resolve_classes(class_names, class_thresholds);

    std::vector<pwb::factor_fusion::FactorEvidence> evidences;
    evidences.reserve(ordered.size());
    for (const std::string& task_id : ordered) {
        evidences.emplace_back(names.at(task_id), ordered_grids.at(task_id),
                               weights_result.resolved.at(task_id),
                               norms_result.resolved.at(task_id));
    }
    FusionModel model;
    model.name = name;
    model.kind = "weighted_evidence";
    model.evidences = std::move(evidences);
    model.default_class = default_class;
    model.class_thresholds = classes_result.thresholds;
    model.class_names = classes_result.names;
    // V8 M5 weight provenance: WHO chose the weights and WHY travels with
    // the model.
    if (weight_provenance.is_object()) {
        Json record = Json::object();
        for (auto it = weight_provenance.begin();
             it != weight_provenance.end(); ++it) {
            if (!it->is_null()) record[it.key()] = *it;
        }
        if (!record.empty()) model.weight_provenance = std::move(record);
    }
    return model;
}

IntegratedRunOutput run_integrated_fusion(
    const Json& document,
    const std::vector<std::pair<std::string, std::string>>& evidence_set,
    CatalogRepository* catalog, const IntegratedGridSeams& seams,
    const std::optional<std::map<std::string, double>>& weights,
    const std::optional<std::map<std::string, Normalization>>& normalizations,
    std::optional<std::vector<std::string>> class_names,
    std::optional<std::vector<double>> class_thresholds,
    bool register_output, const std::string& name,
    const Json& weight_provenance) {
    using pwb::workflow_interpretation::active_input_set;

    // Freeze gate: fusion runs only on a frozen Compilation Input Set.
    const std::optional<pwb::workflow_interpretation::CompilationInputSet>
        input_set = active_input_set(document);
    if (input_set.has_value() && !input_set->frozen) {
        refuse("请先冻结 Compilation Input Set 再运行融合");
    }
    std::vector<std::string> pin_mismatches;
    const std::map<std::string, FactorGrid> factor_results =
        fusion_inputs_from_document(document, evidence_set, &pin_mismatches,
                                    catalog, seams);
    FusionModel model =
        build_fusion_model(evidence_set, factor_results, weights,
                           normalizations, kDefaultFusionDefaultClass,
                           class_names, class_thresholds, name,
                           weight_provenance);
    FusionResult result = pwb::factor_fusion::fuse(model);

    // V9 (P1-7): pin-vs-current mismatch rides the QC — the fusion used
    // the current grid while the evidence set pinned older versions.
    if (!pin_mismatches.empty()) {
        result.qc["pinned_version_mismatches"] = pin_mismatches;
    }

    // Confidence coverage (L583): finite fraction + mean of finite cells.
    {
        double finite_count = 0;
        double finite_sum = 0.0;
        const double total =
            static_cast<double>(result.confidence.grid_z.size());
        for (float cell : result.confidence.grid_z) {
            const double v = static_cast<double>(cell);
            if (std::isfinite(v)) {
                ++finite_count;
                finite_sum += v;
            }
        }
        Json coverage = Json::object();
        coverage["finite_fraction"] =
            total > 0 ? Json(finite_count / total) : Json(0.0);
        coverage["mean"] =
            finite_count > 0 ? Json(finite_sum / finite_count)
                             : Json(nullptr);
        result.qc["confidence_coverage"] = std::move(coverage);
    }
    result.qc["defaults"] = defaults_record(
        evidence_set, factor_results, weights, normalizations, class_names,
        class_thresholds);
    auto [features, classification_qc] = classification_features(result);
    result.qc["classification"] = classification_qc;

    // Registration (L600): honest outcome either way.
    Json registration = Json::object();
    registration["requested"] = register_output;
    registration["registered"] = false;
    std::string catalog_version_id;
    std::string confidence_version_id;
    std::string variance_version_id;
    Json sensitivity = Json(nullptr);
    if (register_output && catalog != nullptr) {
        // register_output parity (factor_fusion.py L693): parents = the
        // union of every evidence's declared source_refs; the run
        // parameters carry the full model provenance.
        std::set<std::string> parent_set;
        for (const pwb::factor_fusion::FactorEvidence& ev :
             result.model.evidences) {
            for (const std::string& ref : ev.grid.source_refs) {
                parent_set.insert(ref);
            }
        }
        std::vector<std::string> parents(parent_set.begin(), parent_set.end());
        Json provenance = result.provenance();
        if (provenance.contains("qc") && provenance["qc"].is_object()) {
            Json cleaned = Json::object();
            for (auto it = provenance["qc"].begin();
                 it != provenance["qc"].end(); ++it) {
                if (!it.key().empty() && it.key()[0] == '_') continue;
                cleaned[it.key()] = *it;
            }
            provenance["qc"] = std::move(cleaned);
        }
        // V6 §16 (P1-11): sensitivity is part of the product's honesty
        // record; computed once and reused for the summary below.
        // Best-effort (Python factor_fusion.py register_output): a
        // sensitivity failure must not abort the registration.
        try {
            sensitivity = pwb::factor_fusion::sensitivity_report(
                result.model, result);
        } catch (...) {
            sensitivity = Json(nullptr);
        }
        if (!sensitivity.is_null()) {
            provenance["sensitivity_leave_one_factor_out"] = sensitivity;
        }

        const std::string run_id = catalog->register_run(
            "factor_fusion", parents, provenance,
            std::string(pwb::factor_fusion::kFusionGeneratorVersion),
            "running");
        try {
            Json asset_metadata = Json::object();
            asset_metadata["model_name"] = result.model.name;
            asset_metadata["model_fingerprint"] = result.model.fingerprint();
            Json version_metadata = Json::object();
            version_metadata["generator"] =
                std::string(pwb::factor_fusion::kFusionGeneratorVersion);
            const pwb::workflow_runtime::RegisteredAssetVersion version =
                catalog->register_result_asset(
                    result.model.name + " 融合成果", "factor_map", "json",
                    asset_metadata,
                    encode_grid_artifact(result.likelihood, "fusion_likelihood"),
                    "derived", run_id, version_metadata);
            catalog->attach_run_output(run_id, version.version_id);
            catalog_version_id = version.version_id;
            // Confidence / variance sibling versions ride the same asset.
            confidence_version_id = catalog->register_version(
                version.asset_id,
                encode_grid_artifact(result.confidence, "fusion_confidence"),
                "derived", {version.version_id}, run_id, version_metadata);
            if (result.variance.has_value()) {
                variance_version_id = catalog->register_version(
                    version.asset_id,
                    encode_grid_artifact(*result.variance, "fusion_variance"),
                    "derived", {version.version_id}, run_id,
                    version_metadata);
            }
        } catch (...) {
            try {
                catalog->update_run_status(run_id, "failed");
            } catch (...) {
            }
            throw;
        }
        catalog->update_run_status(run_id, "complete");
        result.qc["confidence_version_id"] = confidence_version_id;
        if (!variance_version_id.empty()) {
            result.qc["variance_version_id"] = variance_version_id;
        }
        registration["registered"] = true;
        registration["catalog_version_id"] = catalog_version_id;
        registration["confidence_version_id"] = confidence_version_id;
        registration["variance_version_id"] = variance_version_id;
    } else if (!register_output) {
        registration["reason"] = "register=False";
    } else {
        registration["reason"] =
            "catalog service unavailable (no project catalog wired) — "
            "product not version-pinned; re-run with a catalog to register";
    }

    if (sensitivity.is_null()) {
        // V8 M5 degraded path: no registration cached it — compute now.
        // Best-effort like the registration path above (#1451 B-08): a
        // throwing sensitivity must degrade the summary, not abort the
        // whole fusion run.
        try {
            sensitivity =
                pwb::factor_fusion::sensitivity_report(result.model, result);
        } catch (const std::exception& exc) {
            sensitivity = Json::object();
            sensitivity["error"] = std::string("sensitivity degraded: ") + exc.what();
        } catch (...) {
            sensitivity = Json::object();
            sensitivity["error"] = "sensitivity degraded: unknown exception";
        }
    }
    Json qc = result.qc;
    qc["registration"] = registration;

    Json summary = Json::object();
    summary["model_name"] = result.model.name;
    summary["n_factors"] = result.model.evidences.size();
    summary["likelihood_descriptor"] = fusion_scalar_descriptor(
        result.likelihood, result, "fusion_likelihood",
        result.model.name + "·融合似然", catalog_version_id);
    summary["confidence_descriptor"] = fusion_scalar_descriptor(
        result.confidence, result, "fusion_confidence",
        result.model.name + "·融合置信度", confidence_version_id);
    if (result.variance.has_value()) {
        summary["variance_descriptor"] = fusion_scalar_descriptor(
            *result.variance, result, "fusion_variance",
            result.model.name + "·融合方差", variance_version_id);
    } else {
        summary["variance_descriptor"] = Json(nullptr);
    }
    summary["variance_available"] = result.variance.has_value();
    summary["class_names"] = result.class_names;
    summary["classification_features"] = features;
    summary["registered"] = registration["registered"];
    summary["catalog_version_id"] = catalog_version_id;
    summary["qc"] = std::move(qc);
    summary["sensitivity"] = sensitivity;

    return {std::move(summary), std::move(result)};
}

}  // namespace pwb::closure_workflow
