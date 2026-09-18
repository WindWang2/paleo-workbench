#pragma once

// pwb::seismic_io — bounded LRU tile cache.
//
// Frozen semantics (parity with the Python byte-budget caches —
// paleo_workbench/viz/seismic_volume_cache.py and geoviz_seismic/cache.py —
// adapted to tiles instead of whole planes):
//   * Capacity is a BYTE BUDGET, configurable at construction and resizable
//     at runtime; shrinking evicts immediately (global LRU order) until the
//     ledger fits. Growing allocates nothing.
//   * Keys are tile indices on a fixed tile grid (the tile shape is part of
//     the config). Values are owned float buffers — exactly one tile's
//     window, C-order. Callers get shared_ptr<const Buffer>: a cached tile
//     can never be mutated through the cache, and handing a tile to N
//     readers copies nothing.
//   * Insertion evicts least-recently-used entries until the incoming tile
//     fits (budget and, if set, entry cap). A tile larger than the whole
//     budget is returned to the caller but NOT cached — a single oversized
//     request can never evict everything nor grow the cache unbounded.
//   * All methods are thread-safe (one mutex; cache misses run the loader
//     OUTSIDE the lock, exactly one loader call per key per miss — a second
//     racer waits and re-looks-up, so duplicate loads are possible under
//     contention but never duplicate loader calls for the same winner).
//   * Stats: hits / misses / evictions / bytes / peak / entries; peak is a
//     high-water mark of bytes actually held.
//
// The cache never reads I/O itself: the loader callback does. That keeps
// this class format-agnostic and unit-testable with synthetic loaders.

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <list>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::seismic_io {

struct TileCacheConfig {
    // Tile shape in elements per axis (inline, crossline, sample). The grid
    // is aligned from the origin: tile (a, b, c) covers
    // [a*shape0, (a+1)*shape0) x ... truncated at the volume bounds.
    std::array<std::int64_t, 3> tile_shape{4, 4, 2048};
    std::size_t max_bytes = 64u * 1024u * 1024u;  // 64 MiB default budget
    std::size_t max_entries = 0;                  // 0 = unlimited entries
};

class TileCache {
public:
    using Key = std::array<std::int64_t, 3>;
    using Buffer = std::vector<float>;

    explicit TileCache(TileCacheConfig config);

    TileCache(const TileCache&) = delete;
    TileCache& operator=(const TileCache&) = delete;

    // Returns the cached tile, or loads it via `loader` (loader returns
    // nullptr + *error on failure; failures are NOT cached). The loader runs
    // outside the lock.
    std::shared_ptr<const Buffer> get_or_load(
        const Key& key,
        const std::function<std::shared_ptr<Buffer>(std::string*)>& loader,
        std::string* error);

    // Resizes the budget; evicts LRU entries until the ledger fits.
    void set_budget(std::size_t max_bytes);

    [[nodiscard]] std::size_t budget() const;

    // The active configuration (tile shape consumed by tile_of/tile_origin
    // users); thread-safe.
    [[nodiscard]] TileCacheConfig config() const;

    // Drops everything (e.g. on source swap — the caller owns that policy).
    void clear();

    struct Stats {
        std::uint64_t hits = 0;
        std::uint64_t misses = 0;
        std::uint64_t evictions = 0;
        std::size_t bytes_now = 0;
        std::size_t peak_bytes = 0;
        std::size_t entries = 0;
    };

    [[nodiscard]] Stats stats() const;

    // Tile index for an element-space cell (floor division per axis).
    [[nodiscard]] static Key tile_of(const std::array<std::int64_t, 3>& cell,
                                     const std::array<std::int64_t, 3>& tile_shape);

    // The half-open element-space origin of a tile on the grid.
    [[nodiscard]] static std::array<std::int64_t, 3> tile_origin(
        const Key& tile, const std::array<std::int64_t, 3>& tile_shape);

private:
    struct KeyHash {
        // FNV-1a over the three coordinates (std::hash does not specialize
        // std::array).
        [[nodiscard]] std::size_t operator()(
            const Key& key) const noexcept {
            std::size_t hash = 1469598103934665603ull;
            for (std::int64_t value : key) {
                const auto bits = static_cast<std::uint64_t>(value);
                for (unsigned b = 0; b < 8; ++b) {
                    hash ^= static_cast<std::size_t>((bits >> (8 * b)) & 0xffu);
                    hash *= 1099511628211ull;
                }
            }
            return hash;
        }
    };

    struct Entry {
        Key key{};
        std::shared_ptr<Buffer> buffer;
        std::size_t bytes = 0;
        std::list<Key>::iterator lru;  // valid while in `order_`
    };

    void evict_while_over(std::size_t incoming_bytes);
    void insert_locked(const Key& key, std::shared_ptr<Buffer> buffer);

    TileCacheConfig config_;
    mutable std::mutex mutex_;
    std::unordered_map<Key, Entry, KeyHash> map_;
    std::list<Key> order_;  // front = least recently used
    std::size_t bytes_now_ = 0;
    std::size_t peak_bytes_ = 0;
    std::uint64_t hits_ = 0;
    std::uint64_t misses_ = 0;
    std::uint64_t evictions_ = 0;
};

}  // namespace pwb::seismic_io
