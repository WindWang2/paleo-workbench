// Prediction task runtime service — see
// include/pwb/prediction/prediction_service.hpp.

#include <pwb/prediction/prediction_service.hpp>

#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

#include <pwb/domain/diagnostics.hpp>
#include <pwb/domain/ids.hpp>

#include <pwb/prediction/integration_seams.hpp>

namespace pwb::prediction {
namespace {

using Clock = std::chrono::steady_clock;

double seconds_since(const Clock::time_point& start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

Json require_object(const Json& value, const char* what) {
    if (!value.is_object()) {
        throw InputContractError(std::string("prediction node ") + what
                                 + " must be an object");
    }
    return value;
}

std::string get_string(const Json& object, const char* key,
                       const std::string& fallback) {
    const auto it = object.find(key);
    if (it == object.end() || it->is_null()) return fallback;
    if (!it->is_string()) {
        throw InputContractError(std::string("prediction node field '") + key
                                 + "' must be a string");
    }
    return it->get<std::string>();
}

bool get_bool(const Json& object, const char* key, bool fallback) {
    const auto it = object.find(key);
    if (it == object.end() || it->is_null()) return fallback;
    if (!it->is_boolean()) {
        throw InputContractError(std::string("prediction node field '") + key
                                 + "' must be a boolean");
    }
    return it->get<bool>();
}

long long get_integer(const Json& object, const char* key,
                      long long fallback) {
    const auto it = object.find(key);
    if (it == object.end() || it->is_null()) return fallback;
    if (it->is_number_unsigned()) {
        const unsigned long long number = it->get<unsigned long long>();
        if (number <= static_cast<unsigned long long>(
                          std::numeric_limits<long long>::max())) {
            return static_cast<long long>(number);
        }
    } else if (it->is_number_integer()) {
        return it->get<long long>();
    } else if (it->is_number_float()) {
        const double number = it->get<double>();
        if (number >= -9.0e18 && number <= 9.0e18
            && number == std::floor(number)) {
            return static_cast<long long>(number);
        }
    }
    throw InputContractError(std::string("prediction node field '") + key
                             + "' must be an integer in range");
}

// 32-bit narrowing with an explicit range check: a wrapped classes/batch
// value would silently change semantics (e.g. 2^32 -> 0 -> "unset").
int get_int32(const Json& object, const char* key, int fallback) {
    const long long value = get_integer(object, key, fallback);
    if (value < std::numeric_limits<int>::min()
        || value > std::numeric_limits<int>::max()) {
        throw InputContractError(std::string("prediction node field '") + key
                                 + "' is out of the 32-bit range");
    }
    return static_cast<int>(value);
}

SeismicGridDescriptor parse_grid_descriptor(const Json& value) {
    const Json input = require_object(value, "input grid descriptor");
    SeismicGridDescriptor descriptor;
    descriptor.name = get_string(input, "name", "amplitude");
    descriptor.uri = get_string(input, "uri", "");
    descriptor.dtype = get_string(input, "dtype", "float32");
    descriptor.crs = get_string(input, "crs", "");
    descriptor.unit = get_string(input, "unit", "");
    descriptor.quality_mask_uri = get_string(input, "quality_mask_uri", "");

    const auto shape_it = input.find("shape");
    if (shape_it == input.end() || !shape_it->is_array()
        || shape_it->size() != 3) {
        throw InputContractError(
            "prediction node input.shape must be a 3-element array");
    }
    for (std::size_t i = 0; i < 3; ++i) {
        const Json& dim = (*shape_it)[i];
        long long value = 0;
        if (dim.is_number_unsigned()) {
            const unsigned long long raw = dim.get<unsigned long long>();
            if (raw > static_cast<unsigned long long>(
                          std::numeric_limits<int>::max())) {
                throw InputContractError(
                    "prediction node input.shape entry is out of the 32-bit "
                    "range");
            }
            value = static_cast<long long>(raw);
        } else if (dim.is_number_integer()) {
            value = dim.get<long long>();
        } else {
            throw InputContractError(
                "prediction node input.shape entries must be integers");
        }
        if (value < std::numeric_limits<int>::min()
            || value > std::numeric_limits<int>::max()) {
            throw InputContractError(
                "prediction node input.shape entry is out of the 32-bit "
                "range");
        }
        descriptor.shape[i] = static_cast<int>(value);
    }

    const auto nodata_it = input.find("nodata");
    if (nodata_it != input.end() && !nodata_it->is_null()) {
        if (!nodata_it->is_number()) {
            throw InputContractError(
                "prediction node input.nodata must be a number or null");
        }
        descriptor.nodata = nodata_it->get<double>();
    }

    const auto geotransform_it = input.find("geotransform");
    if (geotransform_it != input.end() && !geotransform_it->is_null()) {
        if (!geotransform_it->is_array() || geotransform_it->size() != 6) {
            throw InputContractError(
                "prediction node input.geotransform must be a 6-element "
                "array");
        }
        for (std::size_t i = 0; i < 6; ++i) {
            if (!(*geotransform_it)[i].is_number()) {
                throw InputContractError(
                    "prediction node input.geotransform entries must be "
                    "numbers");
            }
            descriptor.geotransform[i] = (*geotransform_it)[i].get<double>();
        }
        descriptor.has_geotransform = true;
    }

    const auto metadata_it = input.find("metadata");
    if (metadata_it != input.end() && metadata_it->is_object()) {
        descriptor.metadata = *metadata_it;
    }
    return descriptor;
}

PredictionPipelineOptions parse_pipeline_options(const Json& value) {
    const Json options = require_object(value, "options");
    PredictionPipelineOptions parsed;
    parsed.classes = get_int32(options, "classes", 0);
    const auto tile_it = options.find("tile");
    if (tile_it != options.end() && !tile_it->is_null()) {
        if (!tile_it->is_array() || tile_it->size() != 3) {
            throw InputContractError(
                "prediction node options.tile must be a 3-element array");
        }
        for (std::size_t i = 0; i < 3; ++i) {
            const Json& entry = (*tile_it)[i];
            long long value = 0;
            if (entry.is_number_unsigned()) {
                const unsigned long long raw =
                    entry.get<unsigned long long>();
                if (raw > static_cast<unsigned long long>(
                              std::numeric_limits<int>::max())) {
                    throw InputContractError(
                        "prediction node options.tile entries must be "
                        "integers in the 32-bit range");
                }
                value = static_cast<long long>(raw);
            } else if (entry.is_number_integer()) {
                value = entry.get<long long>();
            } else {
                throw InputContractError(
                    "prediction node options.tile entries must be integers "
                    "in the 32-bit range");
            }
            if (value < std::numeric_limits<int>::min()
                || value > std::numeric_limits<int>::max()) {
                throw InputContractError(
                    "prediction node options.tile entries must be integers "
                    "in the 32-bit range");
            }
            parsed.tile[i] = static_cast<int>(value);
        }
    }
    parsed.overlap = get_int32(options, "overlap", -1);
    parsed.batch = get_int32(options, "batch", 0);
    parsed.prefer_gpu = get_bool(options, "prefer_gpu", false);
    parsed.keep_probmap = get_bool(options, "keep_probmap", true);
    parsed.write_mask = get_bool(options, "write_mask", false);
    parsed.write_outputs = get_bool(options, "write_outputs", true);
    parsed.resume = get_bool(options, "resume", true);
    parsed.output_dir = get_string(options, "output_dir", "");
    parsed.work_root = get_string(options, "work_root", "");
    parsed.output_budget_bytes = get_integer(
        options, "output_budget_bytes", kDefaultOutputBudgetBytes);
    return parsed;
}

std::string status_string(PredictionTaskStatus status) {
    switch (status) {
        case PredictionTaskStatus::Created: return "created";
        case PredictionTaskStatus::Validated: return "validated";
        case PredictionTaskStatus::Running: return "running";
        case PredictionTaskStatus::Succeeded: return "succeeded";
        case PredictionTaskStatus::Cancelled: return "cancelled";
        case PredictionTaskStatus::Failed: return "failed";
    }
    return "failed";
}

Json failure_descriptor(const PredictionTaskRequest& request,
                        const std::string& run_id, double elapsed,
                        const std::string& message) {
    Json out = Json::object();
    out["kind"] = "pwb-prediction-result";
    out["result_version"] = kPredictionResultVersion;
    out["generator_version"] = kPredictionGeneratorVersion;
    out["run_id"] = run_id;
    out["status"] = "failed";
    out["created_at"] = pwb::domain::now_iso8601();
    out["elapsed_s"] = elapsed;
    out["error"] = message;
    out["manifest_path"] = request.manifest_path;
    return out;
}

}  // namespace

std::string_view to_string(PredictionTaskStatus status) {
    switch (status) {
        case PredictionTaskStatus::Created: return "created";
        case PredictionTaskStatus::Validated: return "validated";
        case PredictionTaskStatus::Running: return "running";
        case PredictionTaskStatus::Succeeded: return "succeeded";
        case PredictionTaskStatus::Cancelled: return "cancelled";
        case PredictionTaskStatus::Failed: return "failed";
    }
    return "failed";
}

Json PredictionTaskSnapshot::to_json() const {
    Json out = Json::object();
    out["status"] = std::string(to_string(status));
    out["tiles_done"] = tiles_done;
    out["tiles_total"] = tiles_total;
    out["ratio"] = ratio;
    out["message"] = message;
    out["elapsed_s"] = elapsed_s;
    return out;
}

PredictionTaskRuntime::PredictionTaskRuntime(PredictionTaskRequest request)
    : request_(std::move(request)) {}

void PredictionTaskRuntime::update_snapshot(PredictionTaskStatus status,
                                            int tiles_done, int tiles_total,
                                            double ratio,
                                            std::string message) {
    std::lock_guard<std::mutex> lock(mutex_);
    snapshot_.status = status;
    snapshot_.tiles_done = tiles_done;
    snapshot_.tiles_total = tiles_total;
    snapshot_.ratio = ratio;
    snapshot_.message = std::move(message);
}

void PredictionTaskRuntime::request_cancel() {
    cancel_requested_.store(true);
}

PredictionTaskSnapshot PredictionTaskRuntime::snapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return snapshot_;
}

Json PredictionTaskRuntime::to_json() const {
    std::lock_guard<std::mutex> lock(mutex_);
    Json out = result_descriptor_;
    out["snapshot"] = snapshot_.to_json();
    return out;
}

Json PredictionTaskRuntime::validate() {
    Json errors = Json::array();
    update_snapshot(PredictionTaskStatus::Running, 0, 0, 0.0, "validating");
    std::string runtime_error;
    if (!onnx_runtime_available(&runtime_error)) {
        errors.push_back("ONNX Runtime is unavailable: " + runtime_error);
    }
    try {
        LoadedModelPackage package = load_model_package(
            request_.manifest_path, request_.package_options);
        const Json input_errors = validate_prediction_input(
            request_.input, package, request_.input_options);
        for (const Json& error : input_errors) errors.push_back(error);
        const int package_classes = package.prediction.classes;
        if (request_.options.classes > 0 && package_classes > 0
            && request_.options.classes != package_classes) {
            errors.push_back(
                "run declares classes="
                + std::to_string(request_.options.classes)
                + " but the model package declares classes="
                + std::to_string(package_classes));
        }
        if (request_.options.classes <= 0 && package_classes <= 0) {
            errors.push_back(
                "prediction run must declare classes (> 0): the model "
                "package does not declare them and the run did not supply "
                "them");
        }
        if (request_.input.crs.empty()) {
            errors.push_back(
                "prediction result requires an input CRS for "
                "CLASSIFIED_RASTER publication (set input.crs)");
        }
        update_snapshot(errors.empty() ? PredictionTaskStatus::Validated
                                       : PredictionTaskStatus::Failed,
                        0, 0, 0.0,
                        errors.empty() ? "validated" : "validation failed");
    } catch (const std::exception& exc) {
        errors.push_back(exc.what());
        update_snapshot(PredictionTaskStatus::Failed, 0, 0, 0.0, exc.what());
    }
    return errors;
}

PredictionTaskResult PredictionTaskRuntime::execute() {
    if (running_.exchange(true)) {
        throw InputContractError(
            "PredictionTaskRuntime::execute is not reentrant; a task runs "
            "one execute() at a time (request_cancel() only affects the "
            "running execute)");
    }
    struct RunningGuard {
        std::atomic<bool>* flag;
        ~RunningGuard() { flag->store(false); }
    } guard{&running_};

    const Clock::time_point start = Clock::now();
    cancel_requested_.store(false);
    update_snapshot(PredictionTaskStatus::Running, 0, 0, 0.0,
                    "loading model package");

    const std::string run_id = request_.run_id.empty()
                                   ? pwb::domain::make_id("pred")
                                   : request_.run_id;

    LoadedModelPackage package;
    PredictionPipelineResult pipeline;
    try {
        package = load_model_package(request_.manifest_path,
                                     request_.package_options);

        PredictionPipelineOptions options = request_.options;
        // validate() and execute() must agree: forward the caller's grid
        // contract (require_crs/require_geotransform/max_voxels).
        options.input_options = request_.input_options;
        // Compose the caller's cancel seam (e.g. a workflow CancelToken
        // bridged by PredictionWorkflowNode::run) with request_cancel().
        const auto user_cancel = options.cancel;
        options.cancel = [this, user_cancel]() {
            if (cancel_requested_.load()) return true;
            return user_cancel ? user_cancel() : false;
        };
        const auto user_progress = options.progress;
        options.progress = [this, user_progress](
                               double ratio, const std::string& message) {
            update_snapshot(PredictionTaskStatus::Running, 0, 0, ratio,
                            message);
            if (user_progress) user_progress(ratio, message);
        };

        update_snapshot(PredictionTaskStatus::Running, 0, 0, 0.0,
                        "running tiled inference");
        pipeline = run_prediction_pipeline(package, request_.input, options);
    } catch (const std::exception& exc) {
        const double elapsed = seconds_since(start);
        const Json descriptor =
            failure_descriptor(request_, run_id, elapsed, exc.what());
        {
            std::lock_guard<std::mutex> lock(mutex_);
            result_descriptor_ = descriptor;
            snapshot_.status = PredictionTaskStatus::Failed;
            snapshot_.message = exc.what();
            snapshot_.elapsed_s = elapsed;
        }
        throw;
    }

    const double elapsed = seconds_since(start);
    const bool cancelled = pipeline.stats.cancelled;

    PredictionTaskResult result;
    result.status = cancelled ? PredictionTaskStatus::Cancelled
                              : PredictionTaskStatus::Succeeded;
    result.summary = pipeline.summary;
    result.spatial_result = pipeline.spatial_result;
    result.output_descriptor = pipeline.output_descriptor;
    result.provenance = pipeline.provenance;
    result.paths = pipeline.paths;
    result.stats = pipeline.stats;
    result.outputs_written = pipeline.outputs_written;
    result.elapsed_s = elapsed;

    Json diagnostics = package.diagnostics;
    for (const Json& warning : pipeline.compatibility_warnings) {
        Json entry = Json::object();
        entry["code"] = "model_compatibility";
        entry["severity"] = "warning";
        entry["message"] = warning;
        diagnostics.push_back(std::move(entry));
    }
    result.diagnostics = std::move(diagnostics);

    const std::string asset_name =
        request_.input.name.empty()
            ? std::string("prediction-result")
            : request_.input.name + "-prediction";

    Json descriptor = Json::object();
    descriptor["kind"] = "pwb-prediction-result";
    descriptor["result_version"] = kPredictionResultVersion;
    descriptor["generator_version"] = kPredictionGeneratorVersion;
    descriptor["run_id"] = run_id;
    descriptor["status"] = status_string(result.status);
    descriptor["created_at"] = pwb::domain::now_iso8601();
    descriptor["elapsed_s"] = elapsed;
    descriptor["manifest_path"] = request_.manifest_path;
    descriptor["model"] = pipeline.provenance.value("model_package", Json::object());
    descriptor["model_binding"] =
        pipeline.provenance.value("model_binding", Json::object());
    descriptor["runtime"] = pipeline.provenance.value("runtime", Json::object());
    descriptor["input"] = pipeline.provenance.value("input", Json::object());
    descriptor["tiles"] = pipeline.provenance.value("tiles", Json::object());
    descriptor["outputs"] = pipeline.output_descriptor;
    descriptor["summary"] = pipeline.summary;
    descriptor["spatial_result"] = pipeline.spatial_result;
    descriptor["diagnostics"] = result.diagnostics;
    if (!cancelled) {
        const PredictionOutputVersion version = build_prediction_output_version(
            asset_name, pipeline.output_descriptor, pipeline.provenance,
            pipeline.summary);
        descriptor["output_version"] = version.to_json();
        descriptor["map_layers"] = version.map_layers;
    } else {
        descriptor["output_version"] = Json();
        descriptor["map_layers"] = Json::array();
    }
    result.result_descriptor = descriptor;

    {
        std::lock_guard<std::mutex> lock(mutex_);
        result_descriptor_ = descriptor;
        snapshot_.status = result.status;
        snapshot_.tiles_done = pipeline.stats.tiles_done;
        snapshot_.tiles_total = pipeline.stats.tiles_total;
        snapshot_.ratio =
            pipeline.stats.tiles_total > 0
                ? static_cast<double>(pipeline.stats.tiles_done)
                      / static_cast<double>(pipeline.stats.tiles_total)
                : (cancelled ? 0.0 : 1.0);
        snapshot_.message = cancelled ? "cancelled" : "succeeded";
        snapshot_.elapsed_s = elapsed;
    }
    return result;
}

PredictionTaskRequest prediction_task_request_from_json(const Json& parameters) {
    const Json root = require_object(parameters, "parameters");
    PredictionTaskRequest request;
    request.manifest_path = get_string(root, "manifest_path", "");
    if (request.manifest_path.empty()) {
        throw InputContractError(
            "prediction node requires a manifest_path");
    }
    request.run_id = get_string(root, "run_id", "");
    const auto input_it = root.find("input");
    if (input_it == root.end()) {
        throw InputContractError(
            "prediction node requires an input grid descriptor");
    }
    request.input = parse_grid_descriptor(*input_it);
    const auto options_it = root.find("options");
    if (options_it != root.end() && !options_it->is_null()) {
        request.options = parse_pipeline_options(*options_it);
    }
    const auto package_options_it = root.find("package_options");
    if (package_options_it != root.end() && package_options_it->is_object()) {
        request.package_options.require_artifact = get_bool(
            *package_options_it, "require_artifact", true);
        request.package_options.allow_non_scientific = get_bool(
            *package_options_it, "allow_non_scientific", false);
        request.package_options.enforce_within_root = get_bool(
            *package_options_it, "enforce_within_root", true);
    }
    const auto input_options_it = root.find("input_options");
    if (input_options_it != root.end() && input_options_it->is_object()) {
        request.input_options.require_source_uri = get_bool(
            *input_options_it, "require_source_uri", true);
        request.input_options.require_crs =
            get_bool(*input_options_it, "require_crs", false);
        request.input_options.require_geotransform =
            get_bool(*input_options_it, "require_geotransform", false);
        request.input_options.max_voxels = get_integer(
            *input_options_it, "max_voxels", 0);
    }
    return request;
}

Json PredictionWorkflowNode::descriptor() {
    Json out = Json::object();
    out["id"] = "prediction.tiled_onnx";
    out["version"] = kPredictionGeneratorVersion;
    out["display_name"] = "Tiled ONNX facies prediction";
    out["family"] = "prediction";
    out["deterministic"] = true;
    out["device"] = "cpu_primary_gpu_best_effort";
    Json inputs = Json::array();
    inputs.push_back(Json{{"name", "manifest_path"}, {"type", "path"}});
    inputs.push_back(
        Json{{"name", "input"}, {"type", "seismic_grid_descriptor"}});
    out["inputs"] = std::move(inputs);
    Json outputs = Json::array();
    outputs.push_back(Json{{"name", "result"}, {"type", "prediction_result"}});
    out["outputs"] = std::move(outputs);
    Json parameters = Json::array();
    parameters.push_back(
        Json{{"name", "classes"}, {"type", "integer"}, {"required", false}});
    parameters.push_back(
        Json{{"name", "tile"}, {"type", "integer[3]"}, {"required", false}});
    parameters.push_back(
        Json{{"name", "overlap"}, {"type", "integer"}, {"required", false}});
    parameters.push_back(
        Json{{"name", "batch"}, {"type", "integer"}, {"required", false}});
    parameters.push_back(
        Json{{"name", "resume"}, {"type", "boolean"}, {"required", false}});
    parameters.push_back(Json{{"name", "prefer_gpu"},
                              {"type", "boolean"},
                              {"required", false}});
    parameters.push_back(Json{{"name", "keep_probmap"},
                              {"type", "boolean"},
                              {"required", false}});
    parameters.push_back(
        Json{{"name", "write_mask"}, {"type", "boolean"}, {"required", false}});
    parameters.push_back(Json{{"name", "write_outputs"},
                              {"type", "boolean"},
                              {"required", false}});
    parameters.push_back(Json{{"name", "output_dir"},
                              {"type", "path"},
                              {"required", true}});
    parameters.push_back(Json{{"name", "work_root"},
                              {"type", "path"},
                              {"required", false}});
    parameters.push_back(Json{{"name", "output_budget_bytes"},
                              {"type", "integer"},
                              {"required", false}});
    parameters.push_back(Json{{"name", "input_options"},
                              {"type", "object"},
                              {"required", false}});
    parameters.push_back(Json{{"name", "package_options"},
                              {"type", "object"},
                              {"required", false}});
    out["parameters"] = std::move(parameters);
    out["error_classes"] = Json::array(
        {"InputContractError", "ModelPackageError", "TiledInferenceError"});
    return out;
}

Json PredictionWorkflowNode::run(const Json& parameters) {
    return run(parameters, std::function<bool()>(),
               std::function<void(double, const std::string&)>());
}

Json PredictionWorkflowNode::run(
    const Json& parameters, std::function<bool()> cancel,
    std::function<void(double, const std::string&)> progress) {
    PredictionTaskRequest request =
        prediction_task_request_from_json(parameters);
    if (cancel) request.options.cancel = std::move(cancel);
    if (progress) request.options.progress = std::move(progress);
    PredictionTaskRuntime runtime(std::move(request));
    const PredictionTaskResult result = runtime.execute();
    return result.result_descriptor;
}

Json PredictionWorkflowNode::run_observed(const Json& parameters,
                                          IPredictionTaskSink* sink,
                                          std::function<bool()> cancel) {
    PredictionTaskRequest request =
        prediction_task_request_from_json(parameters);
    const std::string manifest_path = request.manifest_path;
    if (cancel) request.options.cancel = std::move(cancel);
    if (sink != nullptr) {
        request.options.progress = [sink](double ratio,
                                          const std::string& message) {
            Json progress = Json::object();
            progress["status"] = "running";
            progress["ratio"] = ratio;
            progress["message"] = message;
            sink->on_progress(progress);
        };
    }
    PredictionTaskRuntime runtime(std::move(request));
    if (sink != nullptr) {
        Json started = Json::object();
        started["status"] = "running";
        started["manifest_path"] = manifest_path;
        sink->on_started(started);
    }
    try {
        const PredictionTaskResult result = runtime.execute();
        if (sink != nullptr) {
            notify_prediction_sink(result.result_descriptor, sink);
        }
        return result.result_descriptor;
    } catch (const std::exception& exc) {
        if (sink != nullptr) {
            Json failure = Json::object();
            failure["status"] = "failed";
            failure["error"] = exc.what();
            sink->on_failed(failure);
        }
        throw;
    }
}

}  // namespace pwb::prediction
