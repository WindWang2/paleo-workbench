#include <pwb/closure_science/providers.hpp>

#include <pwb/closure_science/model_seed.hpp>
#include <pwb/prediction/model_package_runtime.hpp>
#include <pwb/prediction/prediction_input.hpp>
#include <pwb/prediction/prediction_service.hpp>
#include <pwb/prediction/run_spec.hpp>

#include <atomic>
#include <cmath>
#include <mutex>
#include <cstdint>

namespace pwb::closure_science {

using domain::Json;

namespace {

[[nodiscard]] std::string json_text(const Json& value,
                                    const std::string& fallback = {}) {
    return value.is_string() ? value.get<std::string>() : fallback;
}

[[nodiscard]] double round3(double value) {
    return std::round(value * 1000.0) / 1000.0;
}

// Deterministic pseudo-random in [0, 1) derived from (seed, index) — the
// C++-frozen demo sequence (the Python template uses random.Random; the
// native demo freezes its own reproducible sequence instead of claiming
// MT19937 stream equality across runtimes).
[[nodiscard]] double demo_unit_uniform(long long seed, int index) {
    // D7: unsigned arithmetic — the signed multiply/xor-shift above
    // overflowed (UB) for hostile seeds; uint64 wraparound is defined and
    // deterministic on every toolchain. Hash outputs are unchanged for
    // in-range inputs (identical bit pattern on two's-complement hosts).
    std::uint64_t x =
        (static_cast<std::uint64_t>(seed) + 0x9E3779B97F4A7C15ULL) *
            (static_cast<std::uint64_t>(
                 static_cast<long long>(index)) +
             0xBF58476D1CE4E5B9ULL) +
        0x94D049BB133111EBULL;
    x ^= x >> 33;
    x *= 0xFF51AFD7ED558CCDULL;
    x ^= x >> 33;
    x *= 0xC4CEB9FE1A85EC53ULL;
    x ^= x >> 33;
    return static_cast<double>(x % 1000000ULL) / 1000000.0;
}

}  // namespace

ProviderRun make_demo_facies_provider() {
    return [](const Json& inputs, Json parameters,
              const std::function<bool()>& /*cancel*/)
               -> domain::Result<Json> {
        (void)inputs;  // the demo template is data-independent by design
                       // (Python parity: it reads only the seed).
        long long seed = 0;
        if (parameters.contains("seed") && parameters["seed"].is_number()) {
            seed = parameters["seed"].is_number_integer()
                       ? parameters["seed"].get<long long>()
                       : static_cast<long long>(
                             parameters["seed"].get<double>());
        }
        static const char* kFacies[] = {
            "三角洲前缘砂体", "水下分流河道砂体", "滨岸砂体",
            "河道砂体",       "分流间湾泥",       "前三角洲泥",
            "滨岸泥",         "泛滥平原泥"};
        Json predicted = Json::array();
        double probability_sum = 0.0;
        for (int i = 0; i < 4; ++i) {
            const double probability =
                round3(0.55 + demo_unit_uniform(seed, i) * 0.35);
            probability_sum += probability;
            predicted.push_back(Json{
                {"region_id", "demo_region_" + std::to_string(i + 1)},
                {"facies", kFacies[i % 8]},
                {"probability", probability}});
        }
        const double mean_p = round3(probability_sum / 4.0);

        Json review_areas = Json::array();
        for (const auto& region : predicted) {
            if (region["probability"].get<double>() < 0.7) {
                review_areas.push_back(region);
            }
        }

        Json result = Json::object();
        result["adapter_kind"] = "mock";
        result["demo"] = true;
        result["source"] = "synthetic/demo";
        result["result_summary"] = Json{
            {"predicted_regions", std::move(predicted)},
            {"is_mock", true},
            {"is_replaceable", true},
            {"final_scientific_prediction", false},
            {"demo", true},
            {"source", "synthetic/demo"},
            {"model_type", "demo"},
            {"probabilities_uncalibrated", true}};
        result["probability_summary"] = Json{{"mean_probability", mean_p}};
        result["evidence_contribution"] = Json::array(
            {Json{{"name", "sand_thickness"}, {"weight", 0.45}},
             Json{{"name", "target_horizon"}, {"weight", 0.30}},
             Json{{"name", "neighbor_wells"}, {"weight", 0.25}}});
        result["review_areas"] = std::move(review_areas);
        result["seed"] = seed;
        return result;
    };
}

ProviderRun make_tiled_onnx_provider(const TiledOnnxProviderConfig& config) {
    return [config](const Json& inputs, Json parameters,
                    const std::function<bool()>& cancel)
               -> domain::Result<Json> {
        // Input selection (tiled_onnx.py parity: one seismic input version;
        // an empty or unreadable input fails loudly).
        if (inputs.empty() || !inputs.is_object()) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "tiled inference needs a seismic input version");
        }
        const Json* input = nullptr;
        std::string input_version_id;
        for (auto it = inputs.begin(); it != inputs.end(); ++it) {
            if (it.value().is_object()) {
                input = &it.value();
                input_version_id = it.key();
                break;
            }
        }
        if (input == nullptr) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "tiled inference needs a seismic input version");
        }
        const std::string path =
            json_text(input->contains("path") ? (*input)["path"]
                                              : Json(nullptr));
        if (path.empty() || !std::filesystem::exists(path)) {
            return domain::DataError(domain::ErrorCode::NotFound,
                                     "input volume not found: " + path);
        }

        // Model package resolution: the run's registered model identity
        // carries the package manifest as artifact_uri. A bare ONNX file is
        // refused — the native pipeline's preprocessing/normalization
        // contract lives in the package manifest and must not be guessed.
        if (!parameters.is_object() ||
            !parameters.contains("_registered_model") ||
            !parameters["_registered_model"].is_object()) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "parameters must include the registered model identity "
                "(_registered_model)");
        }
        const Json& registered = parameters["_registered_model"];
        const std::string manifest_path =
            registered.contains("artifact_uri")
                ? json_text(registered["artifact_uri"])
                : std::string();
        if (manifest_path.empty()) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "registered model has no artifact_uri; the tiled ONNX "
                "provider needs a validated model package (manifest.json)");
        }
        if (!std::filesystem::exists(manifest_path)) {
            return domain::DataError(domain::ErrorCode::NotFound,
                                     "ONNX model not found: " + manifest_path);
        }

        // Grid descriptor from the input version's recorded metadata —
        // shape/dtype/CRS/geotransform are declared facts, not guesses.
        if (!input->contains("version_metadata") ||
            !(*input)["version_metadata"].is_object() ||
            !(*input)["version_metadata"].contains("grid_descriptor") ||
            !(*input)["version_metadata"]["grid_descriptor"].is_object()) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "seismic input version " + input_version_id +
                    " has no recorded grid_descriptor (shape/dtype/crs/"
                    "geotransform are required for tiled inference)");
        }
        const Json& descriptor = (*input)["version_metadata"]["grid_descriptor"];
        const auto field = [&descriptor](const char* key) -> const Json {
            static const Json null_value = Json(nullptr);
            return descriptor.contains(key) ? descriptor[key] : null_value;
        };
        pwb::prediction::SeismicGridDescriptor grid;
        grid.uri = path;
        grid.name = json_text(field("name"), "amplitude");
        grid.dtype = json_text(field("dtype"), "float32");
        grid.crs = json_text(field("crs"));
        grid.unit = json_text(field("unit"));
        grid.has_geotransform = field("geotransform").is_array() &&
                                field("geotransform").size() == 6;
        if (grid.has_geotransform) {
            int i = 0;
            for (const auto& value : field("geotransform")) {
                if (value.is_number() && i < 6) {
                    grid.geotransform[static_cast<std::size_t>(i)] =
                        value.get<double>();
                }
                ++i;
            }
        }
        if (field("nodata").is_number()) {
            grid.nodata = field("nodata").get<double>();
        }
        if (field("shape").is_array() && field("shape").size() == 3) {
            int i = 0;
            for (const auto& value : field("shape")) {
                if (value.is_number_integer() && i < 3) {
                    grid.shape[static_cast<std::size_t>(i)] =
                        value.get<int>();
                }
                ++i;
            }
        }

        // Runtime availability is an honest explicit failure — never a
        // stub session.
        if (config.fail_fast_without_onnx &&
            !pwb::prediction::onnx_runtime_available()) {
            return domain::DataError(
                domain::ErrorCode::NotFound,
                "ONNX Runtime 执行器不可用（未找到可加载的 "
                "libonnxruntime，请配置 PALEO_ONNXRUNTIME_LIBRARY）");
        }

        pwb::prediction::PredictionTaskRequest request;
        request.manifest_path = manifest_path;
        request.input = grid;
        request.options.output_dir =
            (config.work_root / ("inference_" + input_version_id)).string();
        request.options.resume = true;
        request.options.cancel = cancel;
        // RunSpec parameter truth (predict.params): the UI-edited spec rides
        // the run parameters verbatim; the SAME mapping the params panel
        // previews is the only place tile/batch/budget become options. The
        // legacy flat prefer_gpu key stays for page-started runs.
        if (parameters.contains("_run_spec") &&
            parameters["_run_spec"].is_object() &&
            parameters["_run_spec"].contains("params") &&
            parameters["_run_spec"]["params"].is_object()) {
            pwb::prediction::apply_prediction_params(
                parameters["_run_spec"]["params"], request.options);
        } else if (parameters.contains("prefer_gpu") &&
                   parameters["prefer_gpu"].is_boolean()) {
            request.options.prefer_gpu =
                parameters["prefer_gpu"].get<bool>();
        }
        try {
            pwb::prediction::PredictionTaskRuntime runtime(request);
            Json errors = runtime.validate();
            if (errors.is_array() && !errors.empty()) {
                std::string joined;
                for (const auto& item : errors) {
                    if (!joined.empty()) joined += "; ";
                    joined += item.is_string() ? item.get<std::string>()
                                               : item.dump();
                }
                return domain::DataError(domain::ErrorCode::InvalidArgument,
                                         joined);
            }
            pwb::prediction::PredictionTaskResult result = runtime.execute();
            if (result.status ==
                pwb::prediction::PredictionTaskStatus::Cancelled) {
                Json cancelled = Json::object();
                cancelled["cancelled"] = true;
                cancelled["tiles"] = result.stats.tiles_done;
                cancelled["elapsed_s"] = result.elapsed_s;
                return cancelled;
            }
            if (!result.succeeded()) {
                return domain::DataError(
                    domain::ErrorCode::Unknown,
                    "tiled inference failed: " +
                        json_text(result.summary["error"], "unknown error"));
            }

            // Result dict parity with the Python tiled provider: the
            // service envelope re-asserts identity; this payload carries
            // the device/binding/tiles facts, the bounded summary, the
            // spatial result and the artifact descriptors.
            Json provider_result = Json::object();
            provider_result["source"] = std::string(kProviderTiledOnnx);
            provider_result["generator_version"] = "tiled-onnx-v1";
            provider_result["adapter_kind"] = "tiled_onnx";
            provider_result["device_mode"] =
                !result.stats.mode.empty() ? result.stats.mode
                                           : json_text(result.summary["device_mode"]);
            provider_result["tiles"] = result.stats.tiles_done;
            provider_result["elapsed_s"] = result.elapsed_s;
            provider_result["outputs_written"] = result.outputs_written;
            provider_result["result_summary"] = result.summary;
            provider_result["probability_summary"] =
                result.summary.contains("probability_summary")
                    ? result.summary["probability_summary"]
                    : Json::object();
            // "spatial" mirror: the service-level spatial validator reads
            // the CLASSIFIED_RASTER contract from payload.spatial /
            // payload.result_summary.spatial (spatial_result.py parity).
            provider_result["spatial"] = result.spatial_result;
            provider_result["spatial_result"] = result.spatial_result;
            provider_result["output_descriptor"] = result.output_descriptor;
            provider_result["provenance"] = result.provenance;
            provider_result["diagnostics"] = result.diagnostics;
            provider_result["model_binding"] =
                result.summary.contains("model_binding")
                    ? result.summary["model_binding"]
                    : Json::object();
            return provider_result;
        } catch (const std::exception& exc) {
            return domain::DataError(domain::ErrorCode::Unknown, exc.what());
        }
    };
}

}  // namespace pwb::closure_science
