#include <pwb/seismic_viewer/slice_controller.hpp>

#include <algorithm>
#include <condition_variable>
#include <list>
#include <mutex>
#include <thread>
#include <unordered_map>

namespace pwb::seismic_viewer {
namespace {

struct PlaneKey {
    std::uint64_t epoch;
    std::uint8_t axis; // pwb::viz::axis_index byte
    std::int64_t index;

    bool operator==(const PlaneKey& other) const noexcept {
        return epoch == other.epoch && axis == other.axis && index == other.index;
    }
};

struct PlaneKeyHash {
    std::size_t operator()(const PlaneKey& key) const noexcept {
        const std::uint64_t mixed = key.epoch * 0x9e3779b97f4a7c15ULL +
                                    static_cast<std::uint64_t>(key.axis) * 0x100000001b3ULL +
                                    static_cast<std::uint64_t>(key.index);
        return static_cast<std::size_t>(mixed ^ (mixed >> 32));
    }
};

} // namespace

struct SliceController::Impl {
    struct Queued {
        pwb::viz::VolumeAxis axis{};
        std::int64_t index{0};
        std::optional<std::pair<double, double>> range{};
        std::uint64_t epoch{0};      // epoch captured at submit time
        std::uint64_t generation{0}; // global monotonic, assigned at submit
    };

    mutable std::mutex mutex;
    std::condition_variable work_signal;
    std::jthread worker;

    ResultSink sink;
    const std::size_t cache_capacity;

    // Guarded by mutex. The worker is the only thread that dereferences
    // `source` (ISeismicVolume carries no thread-safety promise): swaps only
    // reseat the shared_ptr and bump the epoch, and the worker's local copy
    // keeps an in-flight read's backing storage alive to its last byte.
    std::shared_ptr<pwb::viz::ISeismicVolume> source;
    std::uint64_t current_epoch{0};
    std::uint64_t next_generation{0};
    std::optional<Queued> queued;
    std::uint64_t newest_generation{0}; // generation of the newest submit
    bool shutdown{false};

    // LRU of raw float planes, front = most recent. Capacity-bounded.
    std::list<std::pair<PlaneKey, std::vector<float>>> cache;
    std::unordered_map<PlaneKey, std::list<std::pair<PlaneKey, std::vector<float>>>::iterator,
                       PlaneKeyHash>
        cache_index;
    std::size_t cache_peak{0};

    ControllerStats stats;

    explicit Impl(std::shared_ptr<pwb::viz::ISeismicVolume> src, std::size_t cap, ResultSink fn)
        : sink(std::move(fn)), cache_capacity(std::max<std::size_t>(cap, 1)),
          source(std::move(src)) {}

    void worker_loop(const std::stop_token& stop) {
        for (;;) {
            Queued request;
            std::shared_ptr<pwb::viz::ISeismicVolume> volume;
            {
                std::unique_lock<std::mutex> lock(mutex);
                work_signal.wait(lock, [&] {
                    return shutdown || stop.stop_requested() || queued.has_value();
                });
                if (shutdown || stop.stop_requested()) {
                    return;
                }
                request = *queued;
                queued.reset();
                volume = source;
            }

            const SliceResult result = execute(request, volume);

            std::unique_lock<std::mutex> lock(mutex);
            const bool stale = result.epoch != current_epoch ||
                               result.generation != newest_generation;
            if (result.ok && result.epoch == current_epoch) {
                // Cache the raw plane even when superseded: the data is valid
                // for this epoch and may serve a later request.
                const PlaneKey key{result.epoch,
                                   static_cast<std::uint8_t>(
                                       pwb::viz::axis_index(result.axis)),
                                   result.index};
                const auto found = cache_index.find(key);
                if (found != cache_index.end()) {
                    cache.erase(found->second);
                    cache_index.erase(found);
                }
                cache.emplace_front(key, result.values);
                cache_index[key] = cache.begin();
                while (cache.size() > cache_capacity) {
                    cache_index.erase(cache.back().first);
                    cache.pop_back();
                }
                cache_peak = std::max(cache_peak, cache.size());
            }
            if (stale) {
                ++stats.discarded_stale;
            } else {
                ++stats.delivered;
                if (result.degenerate) {
                    ++stats.degenerate_results;
                }
                if (sink) {
                    // Sink runs on this worker thread, outside the lock; it
                    // must not re-enter the controller synchronously.
                    lock.unlock();
                    sink(result);
                    lock.lock();
                }
            }
        }
    }

    [[nodiscard]] SliceResult execute(
        const Queued& request, const std::shared_ptr<pwb::viz::ISeismicVolume>& volume) {
        SliceResult result;
        result.axis = request.axis;
        result.index = request.index;
        result.epoch = request.epoch;
        result.generation = request.generation;

        if (!volume) {
            result.diagnostic = "no source volume set";
            return result;
        }
        const pwb::viz::VolumeGeometryV1& geometry = volume->geometry();
        const std::size_t axis_no = pwb::viz::axis_index(request.axis);
        if (geometry.shape[0] <= 0 || geometry.shape[1] <= 0 || geometry.shape[2] <= 0) {
            result.diagnostic = "empty volume (zero extent on some axis)";
            return result;
        }
        if (request.index < 0 || request.index >= geometry.shape[axis_no]) {
            result.diagnostic = "slice index out of bounds";
            return result;
        }

        // rows/cols follow ISeismicVolume canonical order for this axis.
        const std::size_t row_axis = axis_no == 0 ? 1 : 0;
        const std::size_t col_axis = axis_no == 2 ? 1 : 2;
        result.rows = geometry.shape[row_axis];
        result.cols = geometry.shape[col_axis];
        const std::size_t plane_size =
            static_cast<std::size_t>(result.rows * result.cols);

        const PlaneKey key{result.epoch, static_cast<std::uint8_t>(axis_no), request.index};
        bool served_from_cache = false;
        {
            std::lock_guard<std::mutex> lock(mutex);
            const auto found = cache_index.find(key);
            if (found != cache_index.end()) {
                result.values = found->second->second; // result owns its plane copy
                cache.splice(cache.begin(), cache, found->second);
                cache_index[key] = cache.begin();
                served_from_cache = true;
                ++stats.cache_hits;
            } else {
                ++stats.cache_misses;
            }
        }

        if (!served_from_cache) {
            {
                std::lock_guard<std::mutex> lock(mutex);
                ++stats.executed; // exactly one read_slice per cache miss
            }
            result.values.assign(plane_size, 0.0f);
            const std::size_t written =
                volume->read_slice(request.axis, request.index, result.values);
            if (written != plane_size) {
                result.values.clear();
                std::lock_guard<std::mutex> lock(mutex);
                ++stats.read_failures;
                result.diagnostic = "read_slice rejected the request (bounds/span)";
                return result;
            }
        }

        const pwb::viz::IndexedSlice mapped =
            pwb::viz::map_slice_to_indexed8(result.values, request.range);
        result.ok = true;
        result.degenerate = mapped.degenerate;
        result.indexed = std::move(mapped.pixels);
        result.value_min = mapped.value_min;
        result.value_max = mapped.value_max;
        if (mapped.degenerate) {
            result.diagnostic = "degenerate stretch (constant or all-invalid plane)";
        }
        return result;
    }
};

SliceController::SliceController(std::shared_ptr<pwb::viz::ISeismicVolume> source,
                                 std::size_t cache_planes, ResultSink sink)
    : impl_(std::make_unique<Impl>(std::move(source), cache_planes, std::move(sink))) {
    impl_->worker = std::jthread(
        [this](const std::stop_token& token) { impl_->worker_loop(token); });
}

SliceController::~SliceController() { request_shutdown(); }

void SliceController::set_source(std::shared_ptr<pwb::viz::ISeismicVolume> source) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->source = std::move(source);
    ++impl_->current_epoch;
    impl_->queued.reset();
    impl_->cache.clear();
    impl_->cache_index.clear();
    impl_->work_signal.notify_all();
}

void SliceController::submit(pwb::viz::VolumeAxis axis, std::int64_t index,
                             std::optional<std::pair<double, double>> value_range) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->shutdown) {
        return;
    }
    if (impl_->queued.has_value()) {
        ++impl_->stats.coalesced;
    }
    ++impl_->stats.submitted;
    Impl::Queued request;
    request.axis = axis;
    request.index = index;
    request.range = std::move(value_range);
    request.epoch = impl_->current_epoch;
    request.generation = ++impl_->next_generation;
    impl_->queued = request;
    impl_->newest_generation = request.generation;
    impl_->work_signal.notify_all();
}

void SliceController::request_shutdown() {
    {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        if (impl_->shutdown) {
            return;
        }
        impl_->shutdown = true;
        impl_->queued.reset();
        impl_->work_signal.notify_all();
    }
    if (impl_->worker.joinable()) {
        impl_->worker.request_stop();
        impl_->worker.join();
    }
}

ControllerStats SliceController::stats() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->stats;
}

std::uint64_t SliceController::epoch() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->current_epoch;
}

std::size_t SliceController::cache_size() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->cache.size();
}

} // namespace pwb::seismic_viewer
