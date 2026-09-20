// pwb-bench — seismic slice/preview scenarios (cpp-close wave line 14).
//   slice       PWBVOL1 window reads: inspect + a deterministic walk of
//               (inline, crossline, sample) windows — the preview hot path
//   tile-cache  TileCache get_or_load over a tile grid with a small byte
//               budget — cold pass (all misses) then warm pass (hits)
//
// Fixture is a real PWBVOL1 file (the repo's own verification payload —
// magic + u32 header size + JSON header + little-endian f32, C-order).
#include "bench_common.hpp"

#include <pwb/seismic_io/tile_cache.hpp>
#include <pwb/seismic_io/tile_read.hpp>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

namespace pwb::bench {
namespace {

namespace fs = std::filesystem;
using pwb::seismic_io::CancelFlag;
using pwb::seismic_io::PwbvolLayout;
using pwb::seismic_io::TileCache;
using pwb::seismic_io::TileCacheConfig;
using pwb::seismic_io::WindowSpec;

fs::path ensure_pwbvol(const fs::path& work, std::int64_t ni, std::int64_t nc,
                       std::int64_t ns) {
    const fs::path file = work / "volume.pwbvol1";
    const std::uint64_t payload =
        static_cast<std::uint64_t>(ni) * nc * ns * 4u;
    if (fs::is_regular_file(file)
        && fs::file_size(file) > payload) {
        return file;  // regenerated only when the shape grows via --fresh
    }

    Json header = Json::object();
    header["version"] = 1;
    header["shape"] = {ni, nc, ns};
    header["axes"] = {"inline", "crossline", "sample"};
    header["axis_starts"] = {1.0, 1.0, 0.0};
    header["axis_steps"] = {1.0, 1.0, 2.0};
    header["axis_units"] = {"", "", "ms"};
    header["value_unit"] = "1";
    header["layout"] = "c-order-f32";
    const std::string header_text = header.dump();

    std::ofstream out(file, std::ios::binary | std::ios::trunc);
    out.write("PWBVOL1\0", 8);
    const std::uint32_t hsize =
        static_cast<std::uint32_t>(header_text.size());
    out.write(reinterpret_cast<const char*>(&hsize), 4);
    out.write(header_text.data(), static_cast<std::streamsize>(hsize));

    std::vector<float> block(1u << 18);  // 1 MiB
    std::uint64_t left = static_cast<std::uint64_t>(ni) * nc * ns;
    std::uint64_t base = 0;
    while (left > 0) {
        const std::size_t n =
            static_cast<std::size_t>(std::min<std::uint64_t>(left,
                                                             block.size()));
        for (std::size_t i = 0; i < n; ++i) block[i] = synth_float(base + i);
        out.write(reinterpret_cast<const char*>(block.data()),
                  static_cast<std::streamsize>(n * sizeof(float)));
        left -= n;
        base += n;
    }
    return file;
}

Json bench_slice(const Args& args) {
    const auto shape = args.get_triple("shape", {64, 64, 1024});
    const auto win = args.get_triple("window", {8, 16, 512});
    const int reads = static_cast<int>(args.get_int("reads", 128));
    const int samples = static_cast<int>(args.get_int("samples", 5));
    const fs::path work = args.get("work", "bench-out/slice");
    std::error_code ec;
    fs::create_directories(work, ec);
    const fs::path file = ensure_pwbvol(work, shape[0], shape[1], shape[2]);

    std::string error;
    const auto layout = pwb::seismic_io::inspect_pwbvol(file, &error);
    if (!layout) {
        throw std::runtime_error("slice: inspect_pwbvol failed: " + error);
    }

    std::uint64_t digest = 0;
    std::size_t elements_read = 0;
    const Measured m = measure(samples, [&](int) {
        std::vector<float> out(
            static_cast<std::size_t>(win[0]) * win[1] * win[2]);
        const CancelFlag cancel;
        for (int r = 0; r < reads; ++r) {
            WindowSpec w;
            // Deterministic stride so windows spread across the file —
            // realistic seek traffic instead of a hot loop on one tile.
            w.origin = {
                (r * 7) % (shape[0] - win[0] + 1),
                (r * 11) % (shape[1] - win[1] + 1),
                (r * 3) % (shape[2] - win[2] + 1)};
            w.extent = {win[0], win[1], win[2]};
            const std::size_t got = pwb::seismic_io::read_pwbvol_window(
                *layout, w, out, cancel, &error);
            if (got == 0) {
                throw std::runtime_error("slice: read failed: " + error);
            }
            elements_read += got;
            digest ^=
                fnv1a64(out.data(), got * sizeof(float), digest);
        }
    });

    Json out = measured_to_json(m);
    out["shape"] = {shape[0], shape[1], shape[2]};
    out["window"] = {win[0], win[1], win[2]};
    out["reads_per_sample"] = reads;
    out["elements_read"] = elements_read;
    out["digest"] = std::to_string(digest);
    return out;
}

Json bench_tile_cache(const Args& args) {
    const auto shape = args.get_triple("shape", {64, 64, 1024});
    const auto tile = args.get_triple("tile", {8, 8, 256});
    const std::size_t budget_mib = args.get_size("budget-mib", 32);
    const int samples = static_cast<int>(args.get_int("samples", 5));
    const fs::path work = args.get("work", "bench-out/tile-cache");
    std::error_code ec;
    fs::create_directories(work, ec);
    const fs::path file = ensure_pwbvol(work, shape[0], shape[1], shape[2]);

    std::string error;
    const auto layout = pwb::seismic_io::inspect_pwbvol(file, &error);
    if (!layout) {
        throw std::runtime_error("tile-cache: inspect failed: " + error);
    }

    // Visit every tile in the grid once per sample — with the budget held
    // below the working set, each sample is a cold pass (all misses +
    // evictions); holding it above would make later samples warm.
    std::vector<TileCache::Key> keys;
    for (std::int64_t a = 0; a < shape[0]; a += tile[0]) {
        for (std::int64_t b = 0; b < shape[1]; b += tile[1]) {
            for (std::int64_t c = 0; c < shape[2]; c += tile[2]) {
                keys.push_back({a / tile[0], b / tile[1], c / tile[2]});
            }
        }
    }

    std::uint64_t digest = 0;
    TileCache::Stats last_stats;
    const Measured m = measure(samples, [&](int) {
        TileCacheConfig cfg;
        cfg.tile_shape = {tile[0], tile[1], tile[2]};
        cfg.max_bytes = budget_mib << 20;
        TileCache cache(cfg);
        const CancelFlag cancel;
        for (const auto& key : keys) {
            const auto origin =
                TileCache::tile_origin(key, cfg.tile_shape);
            auto buf = cache.get_or_load(
                key,
                [&](std::string* load_error)
                    -> std::shared_ptr<TileCache::Buffer> {
                    WindowSpec w;
                    w.origin = {origin[0], origin[1], origin[2]};
                    w.extent = {std::min<std::int64_t>(tile[0],
                                                       shape[0] - origin[0]),
                                std::min<std::int64_t>(tile[1],
                                                       shape[1] - origin[1]),
                                std::min<std::int64_t>(tile[2],
                                                       shape[2] - origin[2])};
                    auto data =
                        std::make_shared<TileCache::Buffer>(
                            static_cast<std::size_t>(w.elements()));
                    const std::size_t got =
                        pwb::seismic_io::read_pwbvol_window(
                            *layout, w, *data, cancel, load_error);
                    if (got == 0) return nullptr;
                    return data;
                },
                &error);
            if (!buf) {
                throw std::runtime_error("tile-cache: load failed: " + error);
            }
            digest ^= fnv1a64(buf->data(), buf->size() * sizeof(float));
        }
        last_stats = cache.stats();
    });

    Json out = measured_to_json(m);
    out["tiles_per_sample"] = keys.size();
    out["budget_mib"] = budget_mib;
    out["cache_hits"] = last_stats.hits;
    out["cache_misses"] = last_stats.misses;
    out["cache_evictions"] = last_stats.evictions;
    out["cache_peak_bytes"] = last_stats.peak_bytes;
    out["digest"] = std::to_string(digest);
    return out;
}

}  // namespace

void register_seismic_scenarios(ScenarioMap& map) {
    map["slice"] = &bench_slice;
    map["tile-cache"] = &bench_tile_cache;
}

}  // namespace pwb::bench
