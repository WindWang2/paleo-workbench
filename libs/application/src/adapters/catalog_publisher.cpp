#include <pwb/application/adapters/catalog_publisher.hpp>

#include <filesystem>
#include <fstream>

#include <pwb/application/adapters/volume_payload.hpp>
#include <pwb/data/commit_coordinator.hpp>
#include <pwb/data/run_contracts.hpp>

namespace pwb::application {

CatalogResultPublisher::CatalogResultPublisher(
    std::shared_ptr<PwbDataStore> store, std::filesystem::path staged_dir)
    : store_(std::move(store)), staged_dir_(std::move(staged_dir)) {}

void CatalogResultPublisher::set_request_context(
    const std::string& request_id, RequestContext context) {
    const std::scoped_lock lock(mutex_);
    contexts_[request_id] = std::move(context);
}

pwb::domain::RunId CatalogResultPublisher::run_id_for(
    const std::string& request_id) const {
    return pwb::domain::RunId("run_" + request_id);
}

void CatalogResultPublisher::fail(const std::string& request_id,
                                  Outcome outcome, bool terminate_run,
                                  std::string message) {
    if (terminate_run) {
        pwb::domain::Json extra = pwb::domain::Json::object();
        extra["publication_failed"] = message;
        auto finished = store_->coordinator().finish_run(
            run_id_for(request_id), pwb::data::RunTerminalStatus::Failed,
            std::move(extra));
        if (!finished.is_ok()) {
            message += "; finish_run(Failed) also failed ("
                + finished.error().message
                + ") — run left 'running' as explicit recovery pending";
        }
    }
    outcome.success = false;
    outcome.error = message;
    {
        const std::scoped_lock lock(mutex_);
        outcomes_[request_id] = std::move(outcome);
    }
    throw CatalogPublishError(std::move(message));
}

void CatalogResultPublisher::publish_success(
    const pwb::science::AlgorithmResultV1& result) {
    Outcome outcome;
    outcome.run_id = run_id_for(result.request_id).str();

    RequestContext context;
    {
        const std::scoped_lock lock(mutex_);
        const auto it = contexts_.find(result.request_id);
        if (it != contexts_.end()) context = it->second;
    }

    // Exactly one result volume per task (B enforces it too — reject early
    // and honestly, before any durable write). Reaching this method without
    // a durable publish MUST throw: the runtime's contract counts a
    // returning publish_success as "published".
    if (result.outputs.size() != 1) {
        fail(result.request_id, std::move(outcome), false,
             "expected exactly 1 result volume, got "
                 + std::to_string(result.outputs.size()));
    }
    const pwb::science::ProducedVolume& produced = result.outputs.front();
    const auto& shape = produced.volume.shape;
    if (shape[0] <= 0 || shape[1] <= 0 || shape[2] <= 0) {
        fail(result.request_id, std::move(outcome), false,
             "result volume has empty shape");
    }

    // 1) Durable "running" registration (idempotent on run id).
    pwb::data::RunRegistrationV1 registration;
    registration.run_id = run_id_for(result.request_id);
    registration.operation = result.provenance.algorithm_id;
    registration.generator = result.provenance.algorithm_id + "@"
        + result.provenance.algorithm_version + "+"
        + result.provenance.build_identity;
    pwb::domain::Json parameters = pwb::domain::Json::object();
    for (const auto& [key, value] : result.provenance.params_json) {
        parameters[key] = pwb::domain::Json::parse(
            value, nullptr, false);
        if (parameters[key].is_discarded()) parameters[key] = value;
    }
    parameters["request_id"] = result.request_id;
    parameters["approximate"] = result.provenance.approximate;
    parameters["wall_time_ms"] = result.provenance.wall_time_ms;
    registration.parameters = std::move(parameters);
    for (const std::string& version_id : context.input_version_ids) {
        registration.input_version_ids.push_back(
            pwb::domain::VersionId(version_id));
    }
    auto registered =
        store_->coordinator().register_run(registration);
    if (!registered.is_ok()) {
        fail(result.request_id, std::move(outcome), false,
             "register_run failed: " + registered.error().message);
    }

    // 2) Serialize the single result volume (PWBVOL1: shape/axes/units +
    //    float32 payload; input geometry supplies physical axis semantics).
    VolumePayload payload;
    payload.header.ni = static_cast<std::uint32_t>(shape[0]);
    payload.header.nc = static_cast<std::uint32_t>(shape[1]);
    payload.header.ns = static_cast<std::uint32_t>(shape[2]);
    const auto& geometry = context.geometry;
    payload.header.inline_start = geometry.origin[0];
    payload.header.crossline_start = geometry.origin[1];
    payload.header.sample_start = geometry.origin[2];
    payload.header.inline_step = geometry.step[0];
    payload.header.crossline_step = geometry.step[1];
    payload.header.sample_step = geometry.step[2];
    payload.header.sample_unit = geometry.unit;
    payload.header.value_unit = produced.unit;
    payload.header.algorithm_id = result.provenance.algorithm_id;
    payload.header.algorithm_version = result.provenance.algorithm_version;
    payload.header.build_identity = result.provenance.build_identity;
    payload.header.request_id = result.request_id;
    if (result.provenance.approximate) {
        payload.header.approximations.push_back("power_iteration");
    }
    payload.samples.resize(static_cast<size_t>(produced.volume.size()));
    const auto strides = produced.volume.effective_strides();
    for (std::int64_t i = 0; i < shape[0]; ++i) {
        for (std::int64_t c = 0; c < shape[1]; ++c) {
            const std::int64_t base =
                i * strides[0] + c * strides[1];
            for (std::int64_t s = 0; s < shape[2]; ++s) {
                payload.samples[static_cast<size_t>(
                    (i * shape[1] + c) * shape[2] + s)] =
                    produced.volume.data[base + s * strides[2]];
            }
        }
    }
    std::error_code ec;
    std::filesystem::create_directories(staged_dir_, ec);
    const std::filesystem::path payload_path = staged_dir_
        / (result.request_id + ".pwbvol");
    const std::string write_error =
        write_volume_payload(payload, payload_path);
    if (!write_error.empty()) {
        // The "running" run row is already durable — terminate it before
        // throwing so nothing dangles (best effort, see fail()).
        fail(result.request_id, std::move(outcome), true,
             "payload write failed: " + write_error);
    }

    // 3) Single-result publish; the run turns terminal only when durable.
    pwb::data::PublishRequestV1 publish;
    publish.operation_id =
        pwb::domain::OperationId("pub_" + result.request_id);
    publish.run_id = run_id_for(result.request_id);
    publish.new_asset_name =
        result.provenance.algorithm_id + "-" + result.request_id;
    publish.new_asset_type = "seismic_attribute_grid";
    publish.stage = pwb::domain::DataStage::Derived;
    pwb::data::StagedAssetV1 staged;
    staged.source_path = payload_path;
    staged.format = "PWBVOL1";
    publish.products.push_back(std::move(staged));
    publish.result_metadata = pwb::domain::Json::object();
    publish.result_metadata["algorithm_id"] =
        result.provenance.algorithm_id;
    publish.result_metadata["algorithm_version"] =
        result.provenance.algorithm_version;
    publish.result_metadata["build_identity"] =
        result.provenance.build_identity;
    publish.result_metadata["value_unit"] = produced.unit;
    publish.result_metadata["payload_format"] = "PWBVOL1";
    publish.result_metadata["approximate"] =
        result.provenance.approximate;
    publish.result_metadata["shape"] = {shape[0], shape[1], shape[2]};

    auto published =
        store_->coordinator().publish_run_result(publish,
                                                 store_->document());
    if (!published.is_ok()) {
        fail(result.request_id, std::move(outcome), true,
             "publish_run_result failed: " + published.error().message);
    }
    const pwb::data::PublishReceiptV1& receipt = published.value();
    if (receipt.status != pwb::data::PublishStatus::Published
        && receipt.status != pwb::data::PublishStatus::Duplicate) {
        fail(result.request_id, std::move(outcome), true,
             "publish status="
                 + std::string(pwb::data::to_string(receipt.status)));
    }
    outcome.success = true;
    outcome.version_id = receipt.new_version_id.str();
    outcome.asset_id = receipt.asset_id.str();
    {
        const std::scoped_lock lock(mutex_);
        outcomes_[result.request_id] = std::move(outcome);
    }
}

void CatalogResultPublisher::publish_failure(const Failure& failure) {
    Outcome outcome;
    outcome.run_id = run_id_for(failure.request_id).str();

    // Register (idempotent) then terminate — never a success version.
    pwb::data::RunRegistrationV1 registration;
    registration.run_id = run_id_for(failure.request_id);
    registration.operation = "algorithm";
    registration.generator = "adapter";
    pwb::domain::Json parameters = pwb::domain::Json::object();
    parameters["failure_code"] = failure.code;
    parameters["failure_message"] = failure.message;
    registration.parameters = std::move(parameters);
    auto registered =
        store_->coordinator().register_run(registration);
    if (!registered.is_ok()) {
        // Nothing durable yet — record + throw (the task's failure verdict
        // stands; the runtime adds a visibility diagnostic).
        fail(failure.request_id, std::move(outcome), false,
             "register_run(failure path) failed: "
                 + registered.error().message);
    }
    const pwb::data::RunTerminalStatus terminal =
        failure.cancelled ? pwb::data::RunTerminalStatus::Cancelled
                          : pwb::data::RunTerminalStatus::Failed;
    pwb::domain::Json extra = pwb::domain::Json::object();
    extra["failure_code"] = failure.code;
    extra["failure_message"] = failure.message;
    auto finished = store_->coordinator().finish_run(
        run_id_for(failure.request_id), terminal, std::move(extra));
    if (!finished.is_ok()) {
        fail(failure.request_id, std::move(outcome), false,
             "finish_run failed: " + finished.error().message
                 + " — run left 'running' as explicit recovery pending");
    }
    outcome.success = true;   // failure correctly persisted (visibility)
    outcome.error = failure.code + ": " + failure.message;
    const std::scoped_lock lock(mutex_);
    outcomes_[failure.request_id] = std::move(outcome);
}

CatalogResultPublisher::Outcome CatalogResultPublisher::outcome(
    const std::string& request_id) const {
    const std::scoped_lock lock(mutex_);
    const auto it = outcomes_.find(request_id);
    return it == outcomes_.end() ? Outcome{} : it->second;
}

}  // namespace pwb::application
