#pragma once

// UI-10 — Qt shell for pages/preview_worker.py PreviewRequestController:
// the UI-thread coordinator for async previews over the Qt-free
// ui_data_core::PreviewRequestCore state machine.
//
// The core owns generations, the single pending slot, inflight keys and
// the LRU/disk caches; this shell owns the worker-thread mechanics the
// header leaves to Qt: a PwbTaskOwner submits run_preview_job /
// run_media_preload_job bodies through QgsTaskManager, completions hop
// back onto the GUI thread as queued outcome deliveries, and the
// thread-finished hook defers pump_pending() through a 0ms timer (the
// Python #951 deferral verbatim).

#include <QObject>
#include <QString>

#include <memory>
#include <optional>
#include <string>

#include <pwb/qgis_processing/task_bridge.hpp>
#include <pwb/ui_data_core/preview_worker.hpp>

namespace pwb::qgis_processing {
struct CompatJobOutcome;  // job_compat.hpp (implementation-side seam)
}

namespace pwb::ui_seqviz::qt {

class PreviewRequestController : public QObject {
    Q_OBJECT
public:
    explicit PreviewRequestController(
        ui_data_core::PreviewProvider provider,
        QObject* parent = nullptr,
        ui_data_core::PreviewRequestKind request_kind =
            ui_data_core::PreviewRequestKind::Default,
        long long cache_max_size = 32,
        long long shutdown_wait_ms = 10'000);
    ~PreviewRequestController() override;

    const ui_data_core::PreviewProvider& provider() const {
        return provider_;
    }
    ui_data_core::PreviewRequestCore& core() { return core_; }
    int generation() const { return core_.generation(); }

    void set_project_root(std::optional<std::string> root);
    bool set_comparison_crs(const std::optional<std::string>& crs);
    void clear_disk_cache();
    bool set_settings(const ui_data_core::PreviewSettings& settings);
    void invalidate();
    // CLOSURE-PREVIEW (task 04, function-level lease via the wave
    // coordination registry): swap the provider after construction (the
    // shell binds the real parser-registry provider over its message
    // stub). In-flight results from the old provider are invalidated and
    // never land.
    void set_provider(ui_data_core::PreviewProvider provider);

    // asset == nullptr → the Python preview(None) path.
    void request(const ui_data_core::AssetObjectData* asset);
    bool shutdown(long long wait_ms = -1);

signals:
    void loading();
    void result_ready(const pwb::ui_data_core::PreviewResult& result);
    void failed(const QString& message);

private:
    void start_asset_job(int generation,
                         const ui_data_core::AssetObjectData& snapshot,
                         const std::string& key, int cache_generation);
    void start_media_job(int generation,
                         const ui_data_core::PreviewResult& result,
                         const std::string& key, int cache_generation);
    void on_job_finished(
        const pwb::qgis_processing::CompatJobOutcome& outcome);

    ui_data_core::PreviewProvider provider_;
    ui_data_core::PreviewRequestCore core_;
    pwb::qgis_processing::PwbTaskOwner job_owner_;
};

}  // namespace pwb::ui_seqviz::qt
