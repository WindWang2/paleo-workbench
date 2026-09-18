#include <pwb/seismic_io/tile_cache.hpp>

#include <algorithm>
#include <utility>

namespace pwb::seismic_io {

TileCache::TileCache(TileCacheConfig config) : config_(config) {}

TileCache::Key TileCache::tile_of(
    const std::array<std::int64_t, 3>& cell,
    const std::array<std::int64_t, 3>& tile_shape) {
    Key tile{0, 0, 0};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const std::int64_t shape = tile_shape[axis] > 0 ? tile_shape[axis] : 1;
        tile[axis] = cell[axis] / shape;  // floor division; cell >= 0
    }
    return tile;
}

std::array<std::int64_t, 3> TileCache::tile_origin(
    const Key& tile, const std::array<std::int64_t, 3>& tile_shape) {
    std::array<std::int64_t, 3> origin{0, 0, 0};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const std::int64_t shape = tile_shape[axis] > 0 ? tile_shape[axis] : 1;
        origin[axis] = tile[axis] * shape;
    }
    return origin;
}

void TileCache::evict_while_over(std::size_t incoming_bytes) {
    const bool fits_budget = incoming_bytes <= config_.max_bytes;
    while (!order_.empty()
           && (!fits_budget || bytes_now_ + incoming_bytes > config_.max_bytes
               || (config_.max_entries != 0 && map_.size() + 1 > config_.max_entries))) {
        const Key evicted_key = order_.front();
        order_.pop_front();
        const auto it = map_.find(evicted_key);
        if (it == map_.end()) {
            continue;
        }
        bytes_now_ -= it->second.bytes;
        map_.erase(it);
        ++evictions_;
    }
}

void TileCache::insert_locked(const Key& key,
                              std::shared_ptr<Buffer> buffer) {
    const std::size_t bytes = buffer->size() * sizeof(float);
    // A tile larger than the whole budget is served but never cached: it
    // cannot be evicted into compliance, and caching it would let one odd
    // request pin the ledger.
    if (bytes > config_.max_bytes) {
        return;
    }
    evict_while_over(bytes);
    Entry entry;
    entry.key = key;
    entry.buffer = std::move(buffer);
    entry.bytes = bytes;
    order_.push_back(key);
    entry.lru = std::prev(order_.end());
    bytes_now_ += bytes;
    peak_bytes_ = std::max(peak_bytes_, bytes_now_);
    map_[key] = std::move(entry);
}

std::shared_ptr<const TileCache::Buffer> TileCache::get_or_load(
    const Key& key,
    const std::function<std::shared_ptr<Buffer>(std::string*)>& loader,
    std::string* error) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto it = map_.find(key);
        if (it != map_.end()) {
            order_.splice(order_.end(), order_, it->second.lru);
            ++hits_;
            return it->second.buffer;
        }
        ++misses_;
    }
    // Loader runs outside the lock (I/O must not block lookups). A racing
    // caller for the same key may load twice; both results are correct and
    // the ledger stays consistent.
    std::string load_error;
    std::shared_ptr<Buffer> buffer = loader(&load_error);
    if (buffer == nullptr) {
        if (error != nullptr) {
            *error = load_error.empty() ? "tile load failed" : load_error;
        }
        return nullptr;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto it = map_.find(key);
        if (it != map_.end()) {
            // Racer won the race: serve the winner, discard ours.
            order_.splice(order_.end(), order_, it->second.lru);
            ++hits_;
            return it->second.buffer;
        }
        insert_locked(key, buffer);
        return buffer;
    }
}

void TileCache::set_budget(std::size_t max_bytes) {
    std::lock_guard<std::mutex> lock(mutex_);
    config_.max_bytes = max_bytes;
    while (bytes_now_ > config_.max_bytes && !order_.empty()) {
        const Key evicted_key = order_.front();
        order_.pop_front();
        const auto it = map_.find(evicted_key);
        if (it == map_.end()) {
            continue;
        }
        bytes_now_ -= it->second.bytes;
        map_.erase(it);
        ++evictions_;
    }
}

std::size_t TileCache::budget() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return config_.max_bytes;
}

TileCacheConfig TileCache::config() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return config_;
}

void TileCache::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    map_.clear();
    order_.clear();
    bytes_now_ = 0;
}

TileCache::Stats TileCache::stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    Stats stats;
    stats.hits = hits_;
    stats.misses = misses_;
    stats.evictions = evictions_;
    stats.bytes_now = bytes_now_;
    stats.peak_bytes = peak_bytes_;
    stats.entries = map_.size();
    return stats;
}

}  // namespace pwb::seismic_io
