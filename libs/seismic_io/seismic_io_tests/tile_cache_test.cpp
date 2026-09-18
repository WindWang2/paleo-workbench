// seismic_io.tile_cache — bounded LRU semantics: byte-budget eviction,
// runtime budget shrink, oversized-tile policy, stats, and concurrent
// get_or_load safety. Synthetic loaders only — no I/O.

#include <atomic>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

#include <pwb/seismic_io/tile_cache.hpp>

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

pwb::seismic_io::TileCache::Buffer make_tile(std::size_t elements,
                                             float seed) {
    pwb::seismic_io::TileCache::Buffer buffer(elements, seed);
    return buffer;
}

}  // namespace

int main() {
    using pwb::seismic_io::TileCache;
    using pwb::seismic_io::TileCacheConfig;

    // ---- LRU eviction under a byte budget ---------------------------------
    {
        TileCacheConfig config;
        config.max_bytes = 4 * sizeof(float) * 3;  // exactly 3 tiles
        config.tile_shape = {1, 1, 4};
        TileCache cache(config);
        int loads = 0;
        auto loader = [&](std::string*) {
            ++loads;
            return std::make_shared<TileCache::Buffer>(make_tile(4, 1.0f));
        };
        std::string error;
        for (int round = 0; round < 3; ++round) {
            for (int tile = 0; tile < 4; ++tile) {
                cache.get_or_load({tile, 0, 0}, loader, &error);
            }
        }
        const auto stats = cache.stats();
        check(stats.entries <= 3, "entry cap respected");
        check(stats.evictions >= 4, "evictions happened");
        check(stats.misses == 12, "12 misses total");
        // Round-robin over a 3-entry cache defeats LRU: no hits.
        check(stats.hits == 0, "round-robin defeats the small cache");
        // The tile touched last in each round must be retained: re-request
        // it and see no new load.
        const int loads_before = loads;
        cache.get_or_load({3, 0, 0}, loader, &error);
        check(loads == loads_before, "recent tile still cached");
    }

    // ---- set_budget shrink evicts immediately ------------------------------
    {
        TileCacheConfig config;
        config.max_bytes = 4 * sizeof(float) * 8;
        config.tile_shape = {1, 1, 4};
        TileCache cache(config);
        std::string error;
        auto loader = [&](std::string*) {
            return std::make_shared<TileCache::Buffer>(make_tile(4, 1.0f));
        };
        for (int tile = 0; tile < 8; ++tile) {
            cache.get_or_load({tile, 0, 0}, loader, &error);
        }
        check(cache.stats().bytes_now == 8 * 4 * sizeof(float),
              "8 tiles cached");
        cache.set_budget(4 * sizeof(float) * 2);
        check(cache.stats().bytes_now <= 2 * 4 * sizeof(float),
              "shrink evicted immediately");
        check(cache.stats().entries <= 2, "entries fit the new budget");
    }

    // ---- Oversized tile: served, never cached ------------------------------
    {
        TileCacheConfig config;
        config.max_bytes = 4 * sizeof(float);
        TileCache cache(config);
        int loads = 0;
        auto loader = [&](std::string*) {
            ++loads;
            return std::make_shared<TileCache::Buffer>(make_tile(64, 2.0f));
        };
        std::string error;
        const auto first = cache.get_or_load({0, 0, 0}, loader, &error);
        check(first != nullptr && first->size() == 64,
              "oversized tile served");
        check(cache.stats().entries == 0, "oversized tile not cached");
        cache.get_or_load({0, 0, 0}, loader, &error);
        check(loads == 2, "oversized tile reloads every time");
    }

    // ---- Loader failure is not cached --------------------------------------
    {
        TileCache cache(TileCacheConfig{});
        int attempts = 0;
        auto failing = [&](std::string* error) {
            ++attempts;
            if (error != nullptr) *error = "disk on strike";
            return std::shared_ptr<TileCache::Buffer>{};
        };
        std::string error;
        check(cache.get_or_load({1, 2, 3}, failing, &error) == nullptr,
              "failed load returns null");
        check(error == "disk on strike", "error propagated");
        cache.get_or_load({1, 2, 3}, failing, &error);
        check(attempts == 2, "failure not cached");
    }

    // ---- Concurrent get_or_load keeps the ledger consistent ----------------
    {
        TileCacheConfig config;
        config.max_bytes = 4 * sizeof(float) * 100;
        TileCache cache(config);
        std::atomic<int> loads{0};
        auto loader = [&](std::string*) {
            ++loads;
            return std::make_shared<TileCache::Buffer>(make_tile(4, 3.0f));
        };
        std::vector<std::thread> threads;
        for (int t = 0; t < 4; ++t) {
            threads.emplace_back([&cache, &loader, t]() {
                std::string error;
                for (int i = 0; i < 50; ++i) {
                    cache.get_or_load({(i + t) % 20, 0, 0}, loader, &error);
                }
            });
        }
        for (std::thread& thread : threads) {
            thread.join();
        }
        const auto stats = cache.stats();
        check(stats.hits + stats.misses == 200, "all lookups accounted");
        check(stats.bytes_now <= 100 * 4 * sizeof(float),
              "ledger within budget");
    }

    // ---- tile_of / tile_origin grid math -----------------------------------
    {
        const std::array<std::int64_t, 3> shape{4, 4, 2048};
        const auto tile = TileCache::tile_of({5, 7, 3000}, shape);
        check(tile[0] == 1 && tile[1] == 1 && tile[2] == 1, "tile_of");
        const auto origin = TileCache::tile_origin({1, 1, 1}, shape);
        check(origin[0] == 4 && origin[1] == 4 && origin[2] == 2048,
              "tile_origin");
    }

    std::printf("%s: %d failure(s)\n", g_failures == 0 ? "PASS" : "FAIL",
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
