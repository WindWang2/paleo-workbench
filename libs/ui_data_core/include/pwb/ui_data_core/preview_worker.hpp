// preview_worker.py port — the Qt-free core of the async preview stack:
//
// * ``CacheEpoch`` — the cache-clear serialization epoch.
// * ``needs_media_preload`` / ``preload_media`` / ``cacheable_result``.
// * ``run_preview_job`` / ``run_media_preload_job`` — the worker run() bodies.
// * ``PreviewRequestCore`` — the UI-thread request state machine
//   (generations, single pending slot, inflight keys, LRU/disk caches).
//
// QThread/QObject/Signal mechanics stay in the Qt shell: the shell spawns
// the job bodies on a worker thread and forwards finished/failed back into
// on_finished/on_failed, and routes thread-finished through a 0ms timer
// into pump_pending (the Python #951 deferral).
#pragma once

#include "pwb/ui_data_core/preview_cache.hpp"
#include "pwb/ui_data_core/preview_disk_cache.hpp"
#include "pwb/ui_data_core/preview_provider.hpp"

#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <variant>

namespace pwb::ui_data_core {

// Keep small media payloads in the LRU so re-select is path-free on the UI.
inline constexpr long long kMaxCachedMediaBytes = 512 * 1024;
inline constexpr long long kMaxPreloadMediaBytes = 64 * 1024 * 1024;

enum class PreviewRequestKind { Default, Summary, Visualization };
enum class PendingKind { Asset, Media };

// _CacheEpoch — serialize cache clearing against request-local worker disk
// writes.
class CacheEpoch {
public:
    void advance(int generation);
    bool is_current(int generation) const;
    // write_if_current — the disk-store commit guard (same predicate, taken
    // under the epoch lock).
    bool write_if_current(int generation) const {
        return is_current(generation);
    }

private:
    mutable std::mutex lock_;
    int current_ = 0;
};

// _build_for_request_kind — provider dispatch by request kind.
PreviewResult build_for_request_kind(const PreviewProvider& provider,
                                     const AssetObjectData* asset,
                                     PreviewRequestKind kind);

// snapshot_asset — model_copy(deep=True)/deepcopy parity. The value types
// are already deep; pointer-carrying variants are cloned so worker threads
// never share mutable project state.
AssetObjectData snapshot_asset(const AssetObjectData& asset);

// needs_media_preload — true when the UI would otherwise open the file path
// for image/PDF/GeoTIFF.
bool needs_media_preload(const PreviewResult& result);

// preload_media — read image/PDF file bytes off the UI thread.
PreviewResult preload_media(const PreviewResult& result);

// cacheable_result — strip large media payloads before storing in the
// UI-thread LRU (geoviz results pass through untouched).
PreviewResult cacheable_result(const PreviewResult& result);

// _PreviewWorker.run() outcome — ``result`` carries the finished payload,
// ``error`` the failed message (Python emits f"{exc}\n{traceback}"; the
// message text is backend-defined so we carry exc.what()).
struct PreviewJobOutcome {
    int generation = 0;
    std::optional<PreviewResult> result;
    std::string error;
};

// _PreviewWorker.run() — the Qt-free body. ``request_disk`` is the
// request-local disk-cache facade (or nullptr).
PreviewJobOutcome run_preview_job(const PreviewProvider& provider,
                                  const AssetObjectData& asset,
                                  int generation,
                                  PreviewRequestKind request_kind,
                                  PreviewDiskCache* request_disk,
                                  const CacheEpoch* cache_epoch,
                                  int cache_generation);

// _MediaPreloadWorker.run() — reload bytes for a path-only cached result.
PreviewJobOutcome run_media_preload_job(const PreviewResult& result,
                                        int generation);

// The request-local disk facade — PreviewDiskCache(project_root,
// options=settings.to_geoviz_options(), comparison_crs=parent.crs) sharing
// the parent's codec binding.
PreviewDiskCache make_request_disk_cache(const PreviewDiskCache& parent,
                                         const PreviewSettings& settings);

// ---------------------------------------------------------------------------
// PreviewRequestCore — the UI-thread coordinator state machine
// ---------------------------------------------------------------------------
//
// At most one worker runs at a time. Newer cache-miss requests replace a
// single pending slot (latest-only). Stale generations never update the UI
// or the LRU cache. Assets passed to workers are deep-copied snapshots.
class PreviewRequestCore {
public:
    struct Hooks {
        // _active_job.thread is not None
        std::function<bool()> has_active_job;
        // _start_job — spawn the asset worker (snapshot already taken).
        std::function<void(int generation, const AssetObjectData& snapshot,
                           const std::string& key, int cache_generation)>
            start_job;
        // _start_media_job — spawn the media-preload worker.
        std::function<void(int generation, const PreviewResult& result,
                           const std::string& key, int cache_generation)>
            start_media_job;
        // Signals: loading / result_ready / failed.
        std::function<void()> loading;
        std::function<void(const PreviewResult&)> result_ready;
        std::function<void(const std::string&)> failed;
        // _active_job.shutdown(total_wait_ms) → bool.
        std::function<bool(long long wait_ms)> job_shutdown;
    };

    // settings == nullptr → provider.settings() (the Python getattr path).
    explicit PreviewRequestCore(
        PreviewProvider provider,
        Hooks hooks,
        const PreviewSettings* settings = nullptr,
        long long cache_max_size = 32,
        long long shutdown_wait_ms = 10'000,
        PreviewRequestKind request_kind = PreviewRequestKind::Default);

    // Python: unknown request kind → ValueError.
    static PreviewRequestKind request_kind_from_string(std::string_view kind);

    int generation() const { return generation_; }
    PreviewRequestKind request_kind() const { return request_kind_; }
    const PreviewSettings& settings() const { return settings_; }
    PreviewCache& cache() { return cache_; }
    PreviewDiskCache& disk_cache() { return disk_cache_; }
    CacheEpoch& cache_epoch() { return cache_epoch_; }
    const std::optional<std::string>& comparison_crs() const {
        return comparison_crs_;
    }
    bool shutting_down() const { return shutting_down_; }

    void set_project_root(std::optional<std::filesystem::path> root);
    // Invalidate prepared previews when their CRS comparison changes.
    bool set_comparison_crs(const std::optional<std::string>& comparison_crs);
    // Clear project disk preview cache and the in-memory LRU.
    void clear_disk_cache();
    // Invalidate old generations and install a new immutable profile.
    bool set_settings(const PreviewSettings& settings);
    // Invalidate pending/result delivery without starting another request.
    void invalidate();

    void request(const AssetObjectData* asset);  // nullptr = Python None
    // Stop accepting work and wait for the active worker (no force-kill).
    bool shutdown(std::optional<long long> wait_ms = std::nullopt);

    // Signal sinks — the Qt shell forwards worker signals here.
    void on_finished(int generation, PreviewResult result);
    void on_failed(int generation, const std::string& message);
    // _on_thread_finished — the Qt shell defers via a 0ms timer then calls
    // pump_pending(); tests may call pump_pending() directly.
    void pump_pending();

private:
    int advance_generation();
    int advance_cache_generation();
    void emit_loading() const;
    void emit_result(const PreviewResult& result) const;
    void emit_failed(const std::string& message) const;
    void start_asset_job(int generation, const AssetObjectData& snapshot,
                         const std::string& key, int cache_generation);
    void start_media_job(int generation, const PreviewResult& result,
                         const std::string& key, int cache_generation);

    PreviewProvider provider_;
    Hooks hooks_;
    PreviewSettings settings_;
    PreviewCache cache_;
    PreviewDiskCache disk_cache_;
    std::optional<std::string> comparison_crs_;
    PreviewRequestKind request_kind_;
    long long shutdown_wait_ms_;
    int generation_ = 0;
    CacheEpoch cache_epoch_;
    int cache_generation_ = 0;

    // Latest pending carries request generation and cache generation.
    struct Pending {
        PendingKind kind;
        int generation;
        std::variant<AssetObjectData, PreviewResult> payload;
        std::string key;
        int cache_generation;
    };
    std::optional<Pending> pending_;
    std::unordered_map<int, std::pair<std::string, int>> inflight_keys_;
    bool shutting_down_ = false;
};

}  // namespace pwb::ui_data_core
