#include <pwb/ui_seqviz/qt/preview_controller.hpp>

#include <QTimer>

#include <pwb/job_runtime/job_scheduler.hpp>

namespace pwb::ui_seqviz::qt {

namespace job = pwb::job;
using ui_data_core::AssetObjectData;
using ui_data_core::PreviewJobOutcome;
using ui_data_core::PreviewResult;

PreviewRequestController::PreviewRequestController(
    ui_data_core::PreviewProvider provider, QObject* parent,
    ui_data_core::PreviewRequestKind request_kind, long long cache_max_size,
    long long shutdown_wait_ms)
    : QObject(parent), provider_(std::move(provider)),
      core_(
          provider_,
          ui_data_core::PreviewRequestCore::Hooks{
              .has_active_job =
                  [this] { return job_owner_.is_running(); },
              .start_job =
                  [this](int generation, const AssetObjectData& snapshot,
                         const std::string& key, int cache_generation) {
                      start_asset_job(generation, snapshot, key,
                                      cache_generation);
                  },
              .start_media_job =
                  [this](int generation, const PreviewResult& result,
                         const std::string& key, int cache_generation) {
                      start_media_job(generation, result, key,
                                      cache_generation);
                  },
              .loading = [this] { emit loading(); },
              .result_ready =
                  [this](const PreviewResult& result) {
                      emit result_ready(result);
                  },
              .failed =
                  [this](const std::string& message) {
                      emit failed(QString::fromStdString(message));
                  },
              .job_shutdown =
                  [this](long long wait_ms) {
                      return job_owner_.shutdown(
                          static_cast<int>(wait_ms));
                  },
          },
          nullptr, cache_max_size, shutdown_wait_ms, request_kind) {
    // Python `_on_thread_finished` — the next pending request starts only
    // after the worker thread is fully released, deferred through a 0ms
    // timer (#951: terminal signal and thread.finished ordering).
    connect(&job_owner_, &job::qtbridge::JobOwner::released, this, [this] {
        QTimer::singleShot(0, this, [this] { core_.pump_pending(); });
    });
}

PreviewRequestController::~PreviewRequestController() {
    shutdown();
}

void PreviewRequestController::set_project_root(
    std::optional<std::string> root) {
    core_.set_project_root(std::move(root));
}

bool PreviewRequestController::set_comparison_crs(
    const std::optional<std::string>& crs) {
    return core_.set_comparison_crs(crs);
}

void PreviewRequestController::clear_disk_cache() {
    core_.clear_disk_cache();
}

bool PreviewRequestController::set_settings(
    const ui_data_core::PreviewSettings& settings) {
    return core_.set_settings(settings);
}

void PreviewRequestController::invalidate() { core_.invalidate(); }

void PreviewRequestController::set_provider(
    ui_data_core::PreviewProvider provider) {
    provider_ = std::move(provider);
    // Results built by the previous provider never land (the generation
    // bump drops deliveries; cached entries built by the old builder are
    // dropped with the cache).
    core_.clear_disk_cache();
    core_.invalidate();
}

void PreviewRequestController::request(const AssetObjectData* asset) {
    core_.request(asset);
}

bool PreviewRequestController::shutdown(long long wait_ms) {
    return core_.shutdown(
        wait_ms < 0 ? std::nullopt
                    : std::optional<long long>(wait_ms));
}

void PreviewRequestController::start_asset_job(
    int generation, const AssetObjectData& snapshot, const std::string& key,
    int cache_generation) {
    // The request-local disk facade mirrors Python's per-worker
    // PreviewDiskCache(project_root, options=..., comparison_crs=...).
    auto request_disk = std::make_shared<ui_data_core::PreviewDiskCache>(
        ui_data_core::make_request_disk_cache(core_.disk_cache(),
                                              core_.settings()));
    const auto* epoch = &core_.cache_epoch();
    const auto request_kind = core_.request_kind();

    job::JobSpec spec;
    spec.kind = "io";
    spec.title = "preview";
    spec.run = [provider = provider_, snapshot, generation, request_kind,
                request_disk, epoch,
                cache_generation](job::JobContext&) -> std::any {
        return ui_data_core::run_preview_job(
            provider, snapshot, generation, request_kind,
            request_disk.get(), epoch, cache_generation);
    };
    job_owner_.start(
        job::global_scheduler(), std::move(spec),
        [this, generation](const job::qtbridge::JobOutcome& outcome) {
            on_job_finished(outcome);
        });
}

void PreviewRequestController::start_media_job(
    int generation, const PreviewResult& result, const std::string& key,
    int cache_generation) {
    job::JobSpec spec;
    spec.kind = "io";
    spec.title = "preview-media";
    spec.run = [result, generation](job::JobContext&) -> std::any {
        return ui_data_core::run_media_preload_job(result, generation);
    };
    job_owner_.start(
        job::global_scheduler(), std::move(spec),
        [this, generation](const job::qtbridge::JobOutcome& outcome) {
            on_job_finished(outcome);
        });
}

void PreviewRequestController::on_job_finished(
    const job::qtbridge::JobOutcome& outcome) {
    if (outcome.state == job::JobState::cancelled) {
        // Python has no cancelled handler for previews — drop the
        // delivery (invalidate() semantics).
        return;
    }
    const auto* payload =
        std::any_cast<PreviewJobOutcome>(&outcome.result);
    if (outcome.state == job::JobState::failed || payload == nullptr) {
        core_.on_failed(payload != nullptr ? payload->generation : 0,
                        outcome.error);
        return;
    }
    if (payload->result.has_value()) {
        core_.on_finished(payload->generation, *payload->result);
    } else {
        core_.on_failed(payload->generation,
                        payload->error.empty() ? outcome.error
                                               : payload->error);
    }
}

}  // namespace pwb::ui_seqviz::qt
