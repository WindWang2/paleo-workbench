// geology.factor_stats — C++ port of examples/provider_plugins/geology_factor_stats.py.
//
// Computes count/finite/min/max/mean/stdev over a GeologicalFactorDataset's
// valid points (finite value, qc_flag in {"ok","good",""}) and writes a JSON
// report artifact into the execution work dir; catalog-registered as an
// INTERMEDIATE when a run is bound. The verify hook is fail-closed: mean
// outside [min, max] (or empty statistics) is a contract violation.
#include <pwb/providers/builtin_adapters.hpp>
#include <pwb/providers/builtin.hpp>

#include <pwb/providers/errors.hpp>
#include <pwb/providers/schema.hpp>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <optional>
#include <stdexcept>

#include <pwb/mapping/extract.hpp>

namespace pwb::providers {

namespace {
constexpr const char* kBuildIdentity = "examples/provider-plugins@2026-09-06";

bool qc_flag_valid(const std::string& flag) {
    return flag == "ok" || flag == "good" || flag.empty();
}

// Python json.dumps(stats, ensure_ascii=False, indent=1) over the stats dict
// with the exact key order of the Python example.
std::string stats_report_json(const Json& stats) { return stats.dump(1); }

}  // namespace

FactorStatsProvider::FactorStatsProvider() {
    descriptor_.provider_id = "geology.factor_stats";
    descriptor_.family = ProviderFamily::Interpolation;
    descriptor_.version = "1.0.0";
    descriptor_.build_identity = kBuildIdentity;
    descriptor_.display_name = "地质因子统计摘要";
    descriptor_.description =
        "Compute count/finite/min/max/mean/stdev over a "
        "GeologicalFactorDataset's valid points and emit a JSON "
        "report artifact (catalog-registered when a run is bound).";
    descriptor_.capabilities = {"factor_stats"};
    descriptor_.input_types = {"GeologicalFactorDataset", "FactorDatasetRef"};
    descriptor_.output_types = {"PathRef"};
    Json report_name;
    report_name["type"] = "string";
    report_name["description"] = "报告工件名（不含扩展名）";
    report_name["pattern"] = "^[a-z0-9._-]+$";
    descriptor_.parameters_schema = Json::object();
    descriptor_.parameters_schema["type"] = "object";
    descriptor_.parameters_schema["properties"] = Json::object();
    descriptor_.parameters_schema["properties"]["report_name"] = report_name;
    descriptor_.parameters_schema["additionalProperties"] = false;
    descriptor_.resource_profile.estimated_cpu_cores = 0.5;
    descriptor_.resource_profile.estimated_ram_bytes = 64LL * 1024 * 1024;
    descriptor_.resource_profile.io_weight = 0.2;
    descriptor_.resource_profile.category = "background.compute";
    descriptor_.supports_cancel = false;
    descriptor_.deterministic = true;
}

TypedInput make_dataset_typed_input(const std::string& name,
                                    const pwb::mapping::FactorDataset& dataset) {
    TypedInput input;
    input.type_name = "GeologicalFactorDataset";
    Json payload = Json::object();
    payload["factor_name"] = dataset.factor_name;
    payload["unit"] = dataset.unit;
    payload["target_horizon"] = dataset.target_horizon;
    payload["crs"] = dataset.crs;
    payload["points"] = Json::array();
    for (const auto& point : dataset.points) {
        Json p = Json::object();
        p["name"] = point.name;
        p["value"] = point.value;
        p["unit"] = point.unit;
        p["well_id"] = point.well_id;
        p["well_name"] = point.well_name;
        p["x"] = point.x;
        p["y"] = point.y;
        p["crs"] = point.crs;
        p["formation"] = point.formation;
        p["qc_flag"] = point.qc_flag;
        p["metadata"] = point.metadata;
        payload["points"].push_back(std::move(p));
    }
    payload["metadata"] = dataset.metadata;
    input.payload = std::move(payload);
    return input;
}

ProviderResult FactorStatsProvider::execute(const ProviderInputs& inputs,
                                            const Json& parameters,
                                            ProviderContext& context) {
    const TypedInput* dataset_input = inputs.find("dataset");
    std::optional<TypedInput> resolved_storage;
    if (dataset_input == nullptr) {
        const TypedInput* ref_input = inputs.find("factor_dataset");
        if (ref_input != nullptr) {
            // Python: context.extras["factor_datasets"][ref.factor_name]
            std::string factor_name;
            if (ref_input->payload.is_object() &&
                ref_input->payload.contains("factor_name") &&
                ref_input->payload.at("factor_name").is_string()) {
                factor_name = ref_input->payload.at("factor_name").get<std::string>();
            }
            if (context.extras.is_object() &&
                context.extras.contains("factor_datasets") &&
                context.extras.at("factor_datasets").is_object() &&
                context.extras.at("factor_datasets").contains(factor_name)) {
                resolved_storage = TypedInput{
                    "GeologicalFactorDataset",
                    context.extras.at("factor_datasets").at(factor_name)};
                dataset_input = &*resolved_storage;
            }
        }
    }
    const bool looks_like_dataset = dataset_input != nullptr &&
                                    dataset_input->payload.is_object() &&
                                    dataset_input->payload.contains("points") &&
                                    dataset_input->payload.at("points").is_array();
    if (!looks_like_dataset) {
        throw ProviderRejectedInputError(
            descriptor().provider_id,
            "input 'dataset' must be a GeologicalFactorDataset");
    }
    const Json& payload = dataset_input->payload;

    std::vector<double> values;
    for (const auto& point : payload.at("points")) {
        const bool is_object = point.is_object();
        const bool finite_numeric =
            is_object && point.contains("value") &&
            (point.at("value").is_number_integer() || point.at("value").is_number_float()) &&
            std::isfinite(point.at("value").get<double>());
        const std::string qc =
            is_object && point.contains("qc_flag") && point.at("qc_flag").is_string()
                ? point.at("qc_flag").get<std::string>()
                : "ok";
        if (finite_numeric && qc_flag_valid(qc)) {
            values.push_back(point.at("value").get<double>());
        }
    }
    context.report_progress(0.3, "统计计算");

    Json stats = Json::object();
    if (!values.empty()) {
        double sum = 0.0;
        double vmin = values.front();
        double vmax = values.front();
        for (double v : values) {
            sum += v;
            vmin = std::min(vmin, v);
            vmax = std::max(vmax, v);
        }
        const double mean = sum / static_cast<double>(values.size());
        double stdev = 0.0;
        if (values.size() >= 2) {
            double variance = 0.0;
            for (double v : values) variance += (v - mean) * (v - mean);
            variance /= static_cast<double>(values.size() - 1);
            stdev = std::sqrt(variance);
        }
        stats["count"] = values.size();
        stats["finite"] = values.size();
        stats["min"] = vmin;
        stats["max"] = vmax;
        stats["mean"] = mean;
        stats["stdev"] = stdev;
    } else {
        stats["count"] = 0;
        stats["finite"] = 0;
        stats["min"] = Json(nullptr);
        stats["max"] = Json(nullptr);
        stats["mean"] = Json(nullptr);
        stats["stdev"] = Json(nullptr);
    }
    stats["factor_name"] = payload.contains("factor_name") &&
                                   payload.at("factor_name").is_string()
                               ? payload.at("factor_name").get<std::string>()
                               : "";
    stats["unit"] = payload.contains("unit") && payload.at("unit").is_string()
                        ? payload.at("unit").get<std::string>()
                        : "";
    stats["target_horizon"] = payload.contains("target_horizon") &&
                                      payload.at("target_horizon").is_string()
                                  ? payload.at("target_horizon").get<std::string>()
                                  : "";
    context.report_progress(0.7, "写报告");

    const std::string report_name =
        parameters.contains("report_name") && parameters.at("report_name").is_string() &&
                !parameters.at("report_name").get<std::string>().empty()
            ? parameters.at("report_name").get<std::string>()
            : "factor-stats";
    // Enforce the declared pattern ^[a-z0-9._-]+$ (the ported validator
    // subset has no `pattern` support; harden here so report_name cannot
    // traverse out of the work dir).
    if (report_name.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789._-") !=
        std::string::npos) {
        throw ProviderRejectedInputError(
            descriptor().provider_id,
            "parameter 'report_name' must match ^[a-z0-9._-]+$");
    }
    if (context.work_dir.empty()) {
        throw ProviderRejectedInputError(
            descriptor().provider_id,
            "context.work_dir is required (never write to the process cwd)");
    }
    std::filesystem::path work_dir(context.work_dir);
    std::error_code ec;
    std::filesystem::create_directories(work_dir, ec);
    const std::filesystem::path report_path = work_dir / (report_name + ".json");
    {
        std::ofstream out(report_path, std::ios::binary | std::ios::trunc);
        if (!out) {
            throw std::runtime_error("cannot write report " + report_path.generic_string());
        }
        const std::string body = stats_report_json(stats);
        out.write(body.data(), static_cast<std::streamsize>(body.size()));
        if (!out) {
            throw std::runtime_error("short write to " + report_path.generic_string());
        }
    }

    std::optional<Json> version;
    if (context.catalog != nullptr && !context.run_id.empty()) {
        try {
            version = context.catalog->register_intermediate(
                context.run_id, report_name, report_path.generic_string(),
                "factor_stats_report", "json");
        } catch (...) {
            // file stays on disk even when registration fails (Python parity)
        }
    }

    ProviderResult result;
    ArtifactRef artifact;
    artifact.name = report_path.filename().generic_string();
    artifact.kind = "file";
    if (version.has_value()) artifact.version = *version;
    artifact.path = report_path.generic_string();
    artifact.metadata = Json::object();
    artifact.metadata["factor"] = stats["factor_name"];
    result.artifacts.push_back(std::move(artifact));
    for (const auto& [key, value] : stats.items()) {
        if (value.is_number()) result.metrics[key] = value;
    }
    return result;
}

std::optional<Verification> FactorStatsProvider::verify(const ProviderResult& result,
                                                        ProviderContext& /*context*/) {
    // Fail-closed: mean must sit within [min, max] when present.
    const Json& metrics = result.metrics;
    const auto has = [&metrics](const char* key) {
        return metrics.contains(key) && metrics.at(key).is_number();
    };
    if (!has("count") || metrics.at("count") == 0) {
        Verification v;
        v.verdict = "fail";
        v.reasons = {"no valid points — empty statistics"};
        return v;
    }
    if (!has("mean") || !has("min") || !has("max")) {
        Verification v;
        v.verdict = "fail";
        v.reasons = {"incomplete statistics"};
        return v;
    }
    const double mean = metrics.at("mean").get<double>();
    const double vmin = metrics.at("min").get<double>();
    const double vmax = metrics.at("max").get<double>();
    if (!(vmin <= mean && mean <= vmax)) {
        Verification v;
        v.verdict = "fail";
        v.reasons = {"mean " + python_str(Json(mean)) + " outside [" +
                     python_str(Json(vmin)) + ", " + python_str(Json(vmax)) + "]"};
        return v;
    }
    return Verification{};
}

}  // namespace pwb::providers
