#include "pwb/ui_data_core/preview_worker.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>
#include <fstream>
#include <stdexcept>
#include <system_error>
#include <utility>

namespace pwb::ui_data_core {
namespace {

const ResourceItem* as_resource(const AssetObjectData& asset) {
    return std::get_if<ResourceItem>(&asset);
}

}  // namespace

// ---------------------------------------------------------------------------
// CacheEpoch
// ---------------------------------------------------------------------------

void CacheEpoch::advance(int generation) {
    std::lock_guard lock(lock_);
    current_ = generation;
}

bool CacheEpoch::is_current(int generation) const {
    std::lock_guard lock(lock_);
    return current_ == generation;
}

// ---------------------------------------------------------------------------
// Module-level helpers
// ---------------------------------------------------------------------------

PreviewResult build_for_request_kind(const PreviewProvider& provider,
                                     const AssetObjectData* asset,
                                     PreviewRequestKind kind) {
    switch (kind) {
        case PreviewRequestKind::Summary:
            return provider.preview_summary(asset);
        case PreviewRequestKind::Visualization:
            return provider.preview_visualization(asset);
        case PreviewRequestKind::Default:
            break;
    }
    return provider.preview(asset);
}

AssetObjectData snapshot_asset(const AssetObjectData& asset) {
    // Python: model_copy(deep=True) / deepcopy. Value alternatives deep-copy
    // natively; pointer-carrying alternatives are cloned.
    if (const auto& view =
            std::get_if<std::shared_ptr<AssetView>>(&asset)) {
        return AssetObjectData{std::make_shared<AssetView>(
            *view ? **view : AssetView{})};
    }
    if (const auto& data_asset =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&asset)) {
        return AssetObjectData{std::make_shared<catalog::DataAsset>(
            *data_asset ? **data_asset : catalog::DataAsset{})};
    }
    return asset;
}

bool needs_media_preload(const PreviewResult& result) {
    if (result.path.empty()) {
        return false;
    }
    if (result.mode == preview_mode::kImage && result.image_bytes.empty()) {
        return true;
    }
    if (result.mode == preview_mode::kGeotiff && result.image_bytes.empty()) {
        return true;
    }
    if (result.mode == preview_mode::kPdf && result.pdf_bytes.empty()) {
        return true;
    }
    return false;
}

PreviewResult preload_media(const PreviewResult& result) {
    const bool image_like = result.mode == preview_mode::kImage ||
                            result.mode == preview_mode::kGeotiff;
    const bool pdf = result.mode == preview_mode::kPdf;
    if (!image_like && !pdf) {
        return result;
    }
    if (image_like && !result.image_bytes.empty()) {
        return result;
    }
    if (pdf && !result.pdf_bytes.empty()) {
        return result;
    }
    if (result.path.empty()) {
        return result;
    }
    // path.stat().st_size > MAX → return result; OSError → return result.
    std::error_code ec;
    const auto size = std::filesystem::file_size(result.path, ec);
    if (ec || size > kMaxPreloadMediaBytes) {
        return result;
    }
    std::ifstream stream(result.path, std::ios::binary);
    if (!stream) {
        return result;  // OSError parity
    }
    std::string data(static_cast<std::size_t>(kMaxPreloadMediaBytes) + 1, '\0');
    stream.read(data.data(),
                static_cast<std::streamsize>(kMaxPreloadMediaBytes) + 1);
    data.resize(static_cast<std::size_t>(stream.gcount()));
    if (data.empty() ||
        data.size() > static_cast<std::size_t>(kMaxPreloadMediaBytes)) {
        return result;
    }
    PreviewResult out = result;
    if (image_like) {
        out.image_bytes = std::move(data);
    } else if (pdf) {
        out.pdf_bytes = std::move(data);
    }
    return out;
}

PreviewResult cacheable_result(const PreviewResult& result) {
    if (result.mode == preview_mode::kGeoviz) {
        return result;
    }
    std::string image_bytes = result.image_bytes;
    std::string pdf_bytes = result.pdf_bytes;
    if (!image_bytes.empty() &&
        image_bytes.size() > static_cast<std::size_t>(kMaxCachedMediaBytes)) {
        image_bytes.clear();
    }
    if (!pdf_bytes.empty() &&
        pdf_bytes.size() > static_cast<std::size_t>(kMaxCachedMediaBytes)) {
        pdf_bytes.clear();
    }
    if (image_bytes == result.image_bytes && pdf_bytes == result.pdf_bytes) {
        return result;
    }
    PreviewResult out = result;
    out.image_bytes = std::move(image_bytes);
    out.pdf_bytes = std::move(pdf_bytes);
    return out;
}

// ---------------------------------------------------------------------------
// Worker run() bodies
// ---------------------------------------------------------------------------

PreviewJobOutcome run_preview_job(const PreviewProvider& provider,
                                  const AssetObjectData& asset,
                                  int generation,
                                  PreviewRequestKind request_kind,
                                  PreviewDiskCache* request_disk,
                                  const CacheEpoch* cache_epoch,
                                  int cache_generation) {
    try {
        const ResourceItem* resource = as_resource(asset);
        const bool use_disk = request_kind != PreviewRequestKind::Summary &&
                              request_disk != nullptr && resource != nullptr &&
                              is_disk_cacheable(*resource);
        if (use_disk) {
            if (auto hit = request_disk->try_load(*resource)) {
                return PreviewJobOutcome{generation, std::move(*hit), {}};
            }
        }
        PreviewResult result =
            build_for_request_kind(provider, &asset, request_kind);
        if (result.mode != preview_mode::kGeoviz) {
            result = preload_media(result);
        }
        if (use_disk && result.cacheable) {
            if (cache_epoch == nullptr) {
                request_disk->store(*resource, result);
            } else {
                const std::function<bool()> guard = [cache_epoch,
                                                     cache_generation] {
                    return cache_epoch->write_if_current(cache_generation);
                };
                request_disk->store(*resource, result, &guard);
            }
        }
        return PreviewJobOutcome{generation, std::move(result), {}};
    } catch (const std::exception& exc) {  // defensive UI boundary
        return PreviewJobOutcome{generation, std::nullopt, exc.what()};
    }
}

PreviewJobOutcome run_media_preload_job(const PreviewResult& result,
                                        int generation) {
    try {
        return PreviewJobOutcome{generation, preload_media(result), {}};
    } catch (const std::exception& exc) {
        return PreviewJobOutcome{generation, std::nullopt, exc.what()};
    }
}

PreviewDiskCache make_request_disk_cache(const PreviewDiskCache& parent,
                                         const PreviewSettings& settings) {
    const GeovizPreviewOptions options = settings.to_geoviz_options();
    PreviewDiskCache cache(parent.project_root(), &options,
                           parent.comparison_crs());
    cache.set_codec(parent.codec());
    return cache;
}

// ---------------------------------------------------------------------------
// PreviewRequestCore
// ---------------------------------------------------------------------------

PreviewRequestKind PreviewRequestCore::request_kind_from_string(
    std::string_view kind) {
    if (kind == "default") {
        return PreviewRequestKind::Default;
    }
    if (kind == "summary") {
        return PreviewRequestKind::Summary;
    }
    if (kind == "visualization") {
        return PreviewRequestKind::Visualization;
    }
    throw std::invalid_argument("unknown preview request kind: " +
                                std::string(kind));
}

PreviewRequestCore::PreviewRequestCore(PreviewProvider provider,
                                       Hooks hooks,
                                       const PreviewSettings* settings,
                                       long long cache_max_size,
                                       long long shutdown_wait_ms,
                                       PreviewRequestKind request_kind)
    : provider_(std::move(provider)),
      hooks_(std::move(hooks)),
      settings_(settings != nullptr ? *settings : provider_.settings()),
      cache_(cache_max_size),
      disk_cache_(std::nullopt),
      request_kind_(request_kind),
      shutdown_wait_ms_(shutdown_wait_ms) {
    disk_cache_.set_options(settings_.to_geoviz_options());
    comparison_crs_ = disk_cache_.comparison_crs();
}

void PreviewRequestCore::set_project_root(
    std::optional<std::filesystem::path> root) {
    disk_cache_.set_project_root(std::move(root));
}

bool PreviewRequestCore::set_comparison_crs(
    const std::optional<std::string>& comparison_crs) {
    // str(comparison_crs).strip() if comparison_crs else None — a truthy
    // string is kept even when stripping leaves "".
    std::optional<std::string> normalized;
    if (comparison_crs.has_value() && !comparison_crs->empty()) {
        normalized = strip_copy(*comparison_crs);
    }
    if (disk_cache_.comparison_crs() == normalized) {
        return false;
    }
    comparison_crs_ = normalized;
    disk_cache_.set_comparison_crs(normalized);
    cache_.clear();
    invalidate();
    return true;
}

void PreviewRequestCore::clear_disk_cache() {
    if (shutting_down_) {
        return;
    }
    advance_cache_generation();
    disk_cache_.clear();
    cache_.clear();
}

bool PreviewRequestCore::set_settings(const PreviewSettings& settings) {
    if (settings == settings_) {
        return false;
    }
    settings_ = settings;
    advance_generation();
    pending_.reset();
    cache_.clear();
    disk_cache_.set_options(settings.to_geoviz_options());
    return true;
}

void PreviewRequestCore::invalidate() {
    if (shutting_down_) {
        return;
    }
    advance_generation();
    pending_.reset();
}

void PreviewRequestCore::request(const AssetObjectData* asset) {
    if (shutting_down_) {
        return;
    }
    const int generation = advance_generation();
    const int cache_generation = cache_generation_;

    if (asset == nullptr) {
        pending_.reset();
        const PreviewProvider configured = provider_.with_settings(settings_);
        emit_result(
            build_for_request_kind(configured, nullptr, request_kind_));
        return;
    }

    const auto* resource = std::get_if<ResourceItem>(asset);
    const auto* artifact = std::get_if<ExportArtifact>(asset);
    if (resource == nullptr && artifact == nullptr) {
        // make_preview_cache_key only admits ResourceItem | ExportArtifact.
        throw std::invalid_argument(
            "preview request asset must be a resource or artifact");
    }
    const std::string key =
        resource != nullptr
            ? make_preview_cache_key(*resource, settings_.fingerprint(),
                                     comparison_crs_)
            : make_preview_cache_key(*artifact, settings_.fingerprint(),
                                     comparison_crs_);

    if (const PreviewResult* hit = cache_.get(key)) {
        if (needs_media_preload(*hit)) {
            // Path-only cache: re-read media off-thread, skip rebuild.
            emit_loading();
            if (hooks_.has_active_job()) {
                pending_ = Pending{PendingKind::Media, generation, *hit, key,
                                   cache_generation};
                return;
            }
            start_media_job(generation, *hit, key, cache_generation);
            return;
        }
        pending_.reset();
        emit_result(*hit);
        return;
    }

    AssetObjectData snap = snapshot_asset(*asset);
    emit_loading();
    if (hooks_.has_active_job()) {
        pending_ = Pending{PendingKind::Asset, generation, std::move(snap),
                           key, cache_generation};
        return;
    }
    start_asset_job(generation, snap, key, cache_generation);
}

bool PreviewRequestCore::shutdown(std::optional<long long> wait_ms) {
    shutting_down_ = true;
    pending_.reset();
    advance_generation();
    advance_cache_generation();
    inflight_keys_.clear();

    if (!hooks_.has_active_job()) {
        return true;
    }
    // Preserve the former two-stage finite wait as one total deadline.
    const long long deadline =
        wait_ms.has_value() ? *wait_ms : shutdown_wait_ms_;
    const long long initial_wait_ms = std::max(deadline, 0LL);
    const long long second_wait_ms = std::min(initial_wait_ms + 500, 2'000LL);
    return hooks_.job_shutdown(initial_wait_ms + second_wait_ms);
}

void PreviewRequestCore::on_finished(int generation, PreviewResult result) {
    std::optional<std::string> key;
    int cache_generation = -1;
    if (const auto it = inflight_keys_.find(generation);
        it != inflight_keys_.end()) {
        key = it->second.first;
        cache_generation = it->second.second;
        inflight_keys_.erase(it);
    }
    if (!shutting_down_ && generation == generation_) {
        if (key.has_value() && result.cacheable &&
            cache_epoch_.is_current(cache_generation)) {
            cache_.put(*key, cacheable_result(result));
        }
        emit_result(result);
    }
    // Do not start the next job here — wait for thread.finished.
}

void PreviewRequestCore::on_failed(int generation,
                                   const std::string& message) {
    inflight_keys_.erase(generation);
    if (!shutting_down_ && generation == generation_) {
        emit_failed(message);
    }
}

void PreviewRequestCore::pump_pending() {
    if (shutting_down_ || hooks_.has_active_job()) {
        return;
    }
    const std::optional<Pending> pending = pending_;
    pending_.reset();
    if (!pending.has_value()) {
        return;
    }
    if (pending->generation != generation_) {
        return;
    }
    if (pending->kind == PendingKind::Media) {
        const auto& payload = std::get<PreviewResult>(pending->payload);
        if (const PreviewResult* hit = cache_.get(pending->key)) {
            if (!needs_media_preload(*hit)) {
                emit_result(*hit);
                return;
            }
            emit_loading();
            start_media_job(pending->generation, *hit, pending->key,
                            pending->cache_generation);
            return;
        }
        emit_loading();
        start_media_job(pending->generation, payload, pending->key,
                        pending->cache_generation);
        return;
    }
    const auto& payload = std::get<AssetObjectData>(pending->payload);
    if (const PreviewResult* hit = cache_.get(pending->key)) {
        if (needs_media_preload(*hit)) {
            emit_loading();
            start_media_job(pending->generation, *hit, pending->key,
                            pending->cache_generation);
            return;
        }
        emit_result(*hit);
        return;
    }
    emit_loading();
    start_asset_job(pending->generation, payload, pending->key,
                    pending->cache_generation);
}

int PreviewRequestCore::advance_generation() {
    generation_ += 1;
    return generation_;
}

int PreviewRequestCore::advance_cache_generation() {
    cache_generation_ += 1;
    cache_epoch_.advance(cache_generation_);
    return cache_generation_;
}

void PreviewRequestCore::emit_loading() const {
    if (hooks_.loading) {
        hooks_.loading();
    }
}

void PreviewRequestCore::emit_result(const PreviewResult& result) const {
    if (hooks_.result_ready) {
        hooks_.result_ready(result);
    }
}

void PreviewRequestCore::emit_failed(const std::string& message) const {
    if (hooks_.failed) {
        hooks_.failed(message);
    }
}

void PreviewRequestCore::start_asset_job(int generation,
                                         const AssetObjectData& snapshot,
                                         const std::string& key,
                                         int cache_generation) {
    inflight_keys_[generation] = {key, cache_generation};
    hooks_.start_job(generation, snapshot, key, cache_generation);
}

void PreviewRequestCore::start_media_job(int generation,
                                         const PreviewResult& result,
                                         const std::string& key,
                                         int cache_generation) {
    inflight_keys_[generation] = {key, cache_generation};
    hooks_.start_media_job(generation, result, key, cache_generation);
}

}  // namespace pwb::ui_data_core
