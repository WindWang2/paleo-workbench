// seismic_service.service — the tiled ISeismicVolume backend against the
// frozen IO oracle fixtures: plane parity (all three axes), chunk_plan,
// cache boundedness, the spatial-context seam, and the small synthetic
// 32^3 / 64^3 smoke chain (write SEG-Y -> open -> slice -> attribute
// invariant) with no full-volume copy anywhere.

#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/seismic_io/tile_cache.hpp>
#include <pwb/seismic_service/tiled_volume.hpp>
#include <pwb/seismic_service/volume_service.hpp>
#include <pwb/viz/seismic_volume.hpp>

namespace fs = std::filesystem;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::vector<float> read_f32(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    input.seekg(0, std::ios::end);
    const std::streamsize size = input.tellg();
    input.seekg(0, std::ios::beg);
    std::vector<float> data(static_cast<std::size_t>(size / 4));
    if (!data.empty()) {
        input.read(reinterpret_cast<char*>(data.data()), size);
    }
    return data;
}

// Compares a read_slice plane against the corresponding plane extracted from
// the frozen full-volume oracle dump.
void check_plane(const pwb::viz::ISeismicVolume& volume,
                 pwb::viz::VolumeAxis axis, std::int64_t index,
                 const std::vector<float>& full,
                 const std::array<std::int64_t, 3>& shape,
                 const std::string& what) {
    const std::int64_t rows = axis == pwb::viz::VolumeAxis::inline_
                                  ? shape[1]
                                  : shape[0];
    const std::int64_t cols = axis == pwb::viz::VolumeAxis::sample_
                                  ? shape[1]
                                  : shape[2];
    std::vector<float> plane(static_cast<std::size_t>(rows * cols));
    const std::size_t got = volume.read_slice(axis, index, plane);
    check(got == plane.size(), what + ": read_slice size");
    // Extract the plane from the full C-order dump with the same canonical
    // order (rows over the first free axis, columns over the second).
    for (std::int64_t r = 0; r < rows; ++r) {
        for (std::int64_t c = 0; c < cols; ++c) {
            // Canonical order: inline plane -> (xl, t); crossline ->
            // (il, t); sample -> (il, xl).
            std::array<std::int64_t, 3> cell{0, 0, 0};
            if (axis == pwb::viz::VolumeAxis::inline_) {
                cell = {index, r, c};
            } else if (axis == pwb::viz::VolumeAxis::crossline) {
                cell = {r, index, c};
            } else {
                cell = {r, c, index};
            }
            const float want =
                full[static_cast<std::size_t>((cell[0] * shape[1] + cell[1])
                                                  * shape[2]
                                              + cell[2])];
            const float got_v = plane[static_cast<std::size_t>(r * cols + c)];
            const bool both_nan = std::isnan(want) && std::isnan(got_v);
            if (both_nan) {
                continue;
            }
            if (!(std::fabs(static_cast<double>(got_v) - static_cast<double>(want)) == 0.0)) {
                check(false, what + ": sample mismatch");
                return;
            }
        }
    }
}

// Writes a tiny synthetic SEG-Y (format 5, sorted) with a deterministic
// pattern, returns the path.
fs::path write_synthetic(const fs::path& dir, std::int64_t ni,
                         std::int64_t nc, std::int64_t ns, float slope) {
    std::vector<unsigned char> bytes(3600);
    const auto put16 = [&bytes](std::size_t off, std::uint16_t v) {
        bytes[off] = static_cast<unsigned char>(v >> 8);
        bytes[off + 1] = static_cast<unsigned char>(v & 0xff);
    };
    put16(3200 + 16, 1000);
    put16(3200 + 20, static_cast<std::uint16_t>(ns));
    put16(3200 + 24, 5);
    for (std::int64_t il = 0; il < ni; ++il) {
        for (std::int64_t xl = 0; xl < nc; ++xl) {
            std::vector<unsigned char> trace(240
                                             + static_cast<std::size_t>(ns)
                                                   * 4);
            const auto put32 = [&trace](std::size_t off, std::int32_t v) {
                for (int b = 0; b < 4; ++b) {
                    trace[off + static_cast<std::size_t>(b)] = static_cast<
                        unsigned char>((v >> (24 - 8 * b)) & 0xff);
                }
            };
            put32(188, static_cast<std::int32_t>(100 + il));
            put32(192, static_cast<std::int32_t>(200 + xl));
            for (std::int64_t t = 0; t < ns; ++t) {
                const float value = slope * static_cast<float>(il + xl + t);
                std::uint32_t bits = 0;
                std::memcpy(&bits, &value, sizeof(bits));
                const std::size_t off =
                    240 + static_cast<std::size_t>(t) * 4;
                trace[off + 0] =
                    static_cast<unsigned char>((bits >> 24) & 0xff);
                trace[off + 1] =
                    static_cast<unsigned char>((bits >> 16) & 0xff);
                trace[off + 2] =
                    static_cast<unsigned char>((bits >> 8) & 0xff);
                trace[off + 3] =
                    static_cast<unsigned char>(bits & 0xff);
            }
            bytes.insert(bytes.end(), trace.begin(), trace.end());
        }
    }
    const fs::path path = dir / (std::string("synth_")
                                 + std::to_string(ni * nc * ns) + ".sgy");
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(bytes.data()),
              static_cast<std::streamsize>(bytes.size()));
    return path;
}

}  // namespace

int main() {
    const fs::path fixtures = [] {
#ifdef PWB_SEISMIC_IO_FIXTURE_ROOT
        return fs::path(PWB_SEISMIC_IO_FIXTURE_ROOT);
#else
        const char* env = std::getenv("PWB_SEISMIC_IO_FIXTURE_ROOT");
        if (env != nullptr && env[0] != '\0') {
            return fs::path(env);
        }
        return fs::path("libs/seismic_io/seismic_io_tests/fixtures");
#endif
    }();
    const fs::path work = fs::temp_directory_path() / "pwb-seismic-service";
    std::error_code ec;
    fs::create_directories(work, ec);

    // ---- Tiled planes vs frozen full-volume dump ---------------------------
    {
        pwb::seismic_service::SeismicVolumeService service;
        std::string error;
        auto opened = service.open_segy(fixtures / "io_oracle.sgy", &error);
        check(opened.volume != nullptr, "open_segy: " + error);
        if (opened.volume != nullptr) {
            const auto& geometry = opened.volume->geometry();
            check(geometry.shape[0] == 6 && geometry.shape[1] == 4
                      && geometry.shape[2] == 10,
                  "tiled geometry shape");
            check(geometry.unit == "ms", "tiled geometry unit");
            const std::vector<float> full =
                read_f32(fixtures / "io_oracle.sgy.full.f32");
            check_plane(*opened.volume, pwb::viz::VolumeAxis::inline_, 3,
                        full, {6, 4, 10}, "inline plane 3");
            check_plane(*opened.volume, pwb::viz::VolumeAxis::crossline, 1,
                        full, {6, 4, 10}, "crossline plane 1");
            check_plane(*opened.volume, pwb::viz::VolumeAxis::sample, 7,
                        full, {6, 4, 10}, "sample plane 7");
            // chunk_plan reflects the tile grid.
            const auto plan = opened.volume->chunk_plan();
            check(!plan.empty(), "chunk_plan non-empty");
            std::int64_t covered = 0;
            for (const auto& chunk : plan) {
                covered += chunk.extent[0] * chunk.extent[1]
                           * chunk.extent[2];
            }
            check(covered == 6 * 4 * 10, "chunk_plan covers the volume");
            // Cache boundedness: repeated plane reads keep the ledger under
            // the configured budget.
            for (int repeat = 0; repeat < 5; ++repeat) {
                for (std::int64_t i = 0; i < 6; ++i) {
                    std::vector<float> plane(4 * 10);
                    opened.volume->read_slice(pwb::viz::VolumeAxis::inline_,
                                              i, plane);
                }
            }
            check(opened.cache->stats().bytes_now
                      <= opened.cache->budget(),
                  "tile ledger within budget");
            check(opened.cache->stats().hits > 0, "cache hits observed");
        }
    }

    // ---- Depth-domain PWBVOL1 open -----------------------------------------
    {
        pwb::seismic_service::SeismicVolumeService service;
        std::string error;
        auto opened = service.open_pwbvol(fixtures / "io_oracle.pwbvol",
                                          &error);
        check(opened.volume != nullptr, "open_pwbvol: " + error);
        if (opened.volume != nullptr) {
            check(opened.descriptor.sample_domain
                          == pwb::seismic_io::SampleDomain::depth,
                  "pwbvol depth domain");
            const std::vector<float> full =
                read_f32(fixtures / "io_oracle.pwbvol.full.f32");
            check_plane(*opened.volume, pwb::viz::VolumeAxis::sample, 5,
                        full, {3, 5, 7}, "pwbvol sample plane 5");
        }
    }

    // ---- Spatial context seam ----------------------------------------------
    {
        pwb::seismic_service::SeismicVolumeService service;
        std::string error;
        auto opened = service.open_segy(fixtures / "io_oracle_bins.sgy",
                                        &error);
        check(opened.volume != nullptr, "open bins: " + error);
        const auto context = service.spatial_context("EPSG:32650",
                                                     opened.descriptor);
        check(context.crs_id == "EPSG:32650", "context carries the CRS");
        check(context.bin_grid.has_value(), "context carries the bin grid");
        const auto round_trip = pwb::seismic_service::spatial_context_from_json(
            pwb::seismic_service::spatial_context_to_json(context));
        check(round_trip.has_value() && round_trip->crs_id == "EPSG:32650",
              "spatial JSON round trip");
        check(round_trip.has_value() && round_trip->bin_grid.has_value()
                  && std::fabs(round_trip->bin_grid->il_spacing_m - 25.0)
                         < 0.5,
              "spatial JSON bin grid survives");
        // An uncalibrated volume yields no conversions (never fabricated).
        auto plain = service.open_segy(fixtures / "io_oracle.sgy", &error);
        const auto unbound = service.spatial_context("", plain.descriptor);
        check(!unbound.xy_to_il_xl(1.0, 2.0).has_value(),
              "no fabricated coordinates without a bin grid");
        // Malformed JSON refused.
        check(!pwb::seismic_service::spatial_context_from_json(
                   pwb::domain::Json::parse("{\"spatial.bin_grid\": {}}",
                                            nullptr, false))
                   .has_value(),
              "degenerate bin-grid JSON refused");
    }

    // ---- Synthetic 32^3 / 64^3 smoke (no full-volume copy anywhere) --------
    {
        pwb::seismic_io::TileCacheConfig config;
        config.max_bytes = 64 * 1024;  // deliberately tiny: 64 KiB budget
        pwb::seismic_service::SeismicVolumeService service(config);
        for (const std::int64_t n : {32, 64}) {
            const fs::path path = write_synthetic(work, n, n, n, 0.001f);
            std::string error;
            auto opened = service.open_segy(path, &error);
            check(opened.volume != nullptr,
                  "smoke open " + std::to_string(n) + "^3: " + error);
            if (opened.volume == nullptr) {
                continue;
            }
            // Slanted plane: sample slice value = 0.001 * (il + xl + t).
            std::vector<float> plane(static_cast<std::size_t>(n * n));
            check(opened.volume->read_slice(pwb::viz::VolumeAxis::sample,
                                            n / 2, plane)
                      == plane.size(),
                  "smoke sample plane read");
            const float t = static_cast<float>(n / 2);
            bool ok = true;
            for (std::int64_t i = 0; i < n && ok; ++i) {
                for (std::int64_t j = 0; j < n && ok; ++j) {
                    const float want = 0.001f
                        * static_cast<float>(i + j) + 0.001f * t;
                    ok = plane[static_cast<std::size_t>(i * n + j)] == want;
                }
            }
            check(ok, "smoke plane values exact");
            // The tiny budget must hold: peak bytes never exceed it.
            check(opened.cache->stats().peak_bytes
                      <= opened.cache->budget(),
                  "smoke peak cache within budget");
        }
    }

    std::printf("%s: %d failure(s)\n", g_failures == 0 ? "PASS" : "FAIL",
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
