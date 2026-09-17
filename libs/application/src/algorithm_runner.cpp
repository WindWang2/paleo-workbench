#include <pwb/application/algorithm_runner.hpp>

#include <atomic>
#include <chrono>
#include <filesystem>

#include <pwb/application/adapters/volume_payload.hpp>
#include <pwb/science/types.hpp>

namespace pwb::application {
namespace {

std::atomic<std::uint64_t> g_request_counter{0};

pwb::viz::VolumeGeometryV1 geometry_of(
    const pwb::application::VolumePayloadHeader& header) {
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {static_cast<std::int64_t>(header.ni),
                      static_cast<std::int64_t>(header.nc),
                      static_cast<std::int64_t>(header.ns)};
    geometry.strides = {0, 0, 0};  // PWBVOL1 payloads are packed C-order
    geometry.origin = {header.inline_start, header.crossline_start,
                       header.sample_start};
    geometry.step = {header.inline_step, header.crossline_step,
                     header.sample_step};
    geometry.unit = header.sample_unit;
    return geometry;
}

// Locates one catalog version and reads its PWBVOL1 payload; the version's
// project-relative path resolves against the store's project directory.
std::string load_version_volume(
    const std::shared_ptr<PwbDataStore>& store,
    const std::string& version_id, pwb::application::VolumePayload* payload,
    pwb::viz::VolumeGeometryV1* geometry) {
    auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) {
        return "store snapshot failed: " + snapshot.error().message;
    }
    const std::filesystem::path project_dir =
        store->project_file().parent_path();
    for (const auto& version : snapshot.value().catalog_versions) {
        if (version.id.str() != version_id) continue;
        if (version.format != "PWBVOL1") {
            return "version " + version_id + " is not a PWBVOL1 volume ("
                + version.format + ")";
        }
        const std::filesystem::path payload_path = project_dir / version.path;
        const std::string read_error =
            pwb::application::read_volume_payload(payload_path, payload);
        if (!read_error.empty()) return read_error;
        *geometry = geometry_of(payload->header);
        return "";
    }
    return "version not found in catalog: " + version_id;
}

}  // namespace

AlgorithmRunner::AlgorithmRunner() = default;

AlgorithmRunner::~AlgorithmRunner() {
    runtime_.shutdown();
}

std::string AlgorithmRunner::register_kernel(
    std::unique_ptr<pwb::science::IAlgorithm> kernel) {
    if (kernel == nullptr) return "null kernel";
    const std::string id = kernel->descriptor().algorithm_id;
    if (id.empty()) return "kernel has no algorithm id";
    const std::scoped_lock lock(mutex_);
    if (kernels_.count(id) != 0) {
        return "duplicate algorithm id: " + id;
    }
    kernels_[id] = std::shared_ptr<pwb::science::IAlgorithm>(std::move(kernel));
    return "";
}

std::vector<AlgorithmRunner::AlgorithmInfo> AlgorithmRunner::algorithms()
    const {
    std::vector<AlgorithmInfo> infos;
    for (const auto& [id, kernel] : kernels_) {
        infos.push_back({id, kernel->descriptor().display_name,
                         kernel->descriptor().version});
    }
    return infos;
}

std::string AlgorithmRunner::submit(
    const std::shared_ptr<PwbDataStore>& store, const std::string& algorithm_id,
    const std::map<std::string, std::string>& params,
    const std::string& input_version_id, std::string* error) {
    if (store == nullptr) {
        if (error != nullptr) *error = "no project store attached";
        return "";
    }
    std::shared_ptr<pwb::science::IAlgorithm> kernel;
    {
        const std::scoped_lock lock(mutex_);
        const auto it = kernels_.find(algorithm_id);
        if (it != kernels_.end()) kernel = it->second;
    }
    if (kernel == nullptr) {
        if (error != nullptr) {
            *error = "unknown algorithm id: " + algorithm_id;
        }
        return "";
    }

    pwb::application::VolumePayload payload;
    pwb::viz::VolumeGeometryV1 geometry;
    const std::string load_error =
        load_version_volume(store, input_version_id, &payload, &geometry);
    if (!load_error.empty()) {
        if (error != nullptr) *error = load_error;
        return "";
    }

    const std::string request_id =
        "run-" + algorithm_id + "-" + std::to_string(
            g_request_counter.fetch_add(1));

    auto samples = std::make_shared<std::vector<float>>(
        std::move(payload.samples));
    pwb::science::AlgorithmRequestV1 request;
    request.request_id = request_id;
    request.algorithm_id = kernel->descriptor().algorithm_id;
    request.algorithm_version = kernel->descriptor().version;
    request.params_json = params;
    request.input_volumes.push_back(
        {samples->data(), geometry.shape, {0, 0, 0}, samples});

    const std::filesystem::path staged_dir =
        store->project_file().parent_path() / ".pwb-runs";
    auto publisher = std::make_shared<pwb::application::CatalogResultPublisher>(
        store, staged_dir);
    pwb::application::RequestContext context;
    context.geometry = geometry;
    context.input_version_ids = {input_version_id};
    context.params_json = params;
    publisher->set_request_context(request_id, std::move(context));

    pwb::workflow::TaskHandle handle =
        runtime_.submit(kernel, request, publisher);
    if (handle.snapshot().status == pwb::workflow::TaskStatus::failed
        && handle.snapshot().error_code == "runtime.shutdown") {
        if (error != nullptr) *error = "runtime is shutting down";
        return "";
    }
    {
        const std::scoped_lock lock(mutex_);
        Pending& pending = pending_[request_id];
        pending.handle = std::move(handle);
        pending.publisher = std::move(publisher);
        pending.samples = std::move(samples);
    }
    return request_id;
}

AlgorithmRunner::Outcome AlgorithmRunner::outcome(
    const std::string& request_id) {
    const std::scoped_lock lock(mutex_);
    {
        const auto done = finished_.find(request_id);
        if (done != finished_.end()) return done->second;
    }
    const auto it = pending_.find(request_id);
    if (it == pending_.end()) return Outcome{};
    Outcome outcome;
    outcome.known = true;
    const pwb::workflow::TaskSnapshot snapshot = it->second.handle.snapshot();
    outcome.status = pwb::workflow::to_string(snapshot.status);
    outcome.error_code = snapshot.error_code;
    const auto publisher_outcome =
        it->second.publisher->outcome(request_id);
    outcome.run_id = publisher_outcome.run_id;
    if (snapshot.status == pwb::workflow::TaskStatus::succeeded) {
        outcome.version_id = publisher_outcome.version_id;
    } else if (snapshot.status == pwb::workflow::TaskStatus::failed) {
        outcome.error = publisher_outcome.error.empty()
            ? snapshot.error_code
            : publisher_outcome.error;
    }
    if (snapshot.status == pwb::workflow::TaskStatus::succeeded
        || snapshot.status == pwb::workflow::TaskStatus::failed
        || snapshot.status == pwb::workflow::TaskStatus::cancelled) {
        finished_[request_id] = outcome;
        pending_.erase(it);   // releases the input payload keep-alive
    }
    return outcome;
}

}  // namespace pwb::application
