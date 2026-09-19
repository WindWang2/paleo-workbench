#pragma once

// pwb::seismic_service — the volume-open service and the project spatial
// context seam.
//
// `SeismicVolumeService` is the ONE product surface for turning a file (or
// a catalog PWBVOL1 version path) into a viewer-ready tiled volume:
//   * open = inspect (metadata only) -> descriptor + optional bin grid;
//   * the sample bytes stay on disk and stream in through a per-volume tile
//     cache, so opening a volume costs O(1) memory, not O(volume);
//   * the cache byte budget is configurable (constructor wins over the
//     `PWB_SEISMIC_TILE_CACHE_BYTES` environment override, which wins over
//     the 64 MiB default) — the native counterpart of the Python caches'
//     `PALEO_SEISMIC_CACHE_MAX_BYTES` knob. The budget applies per opened
//     volume (the platform viewer holds one volume at a time); hosts that
//     keep many volumes open must size the budget accordingly.
//
// `SeismicSpatialContext` is the stable seam between seismic geometry and
// the project's spatial frame: a CRS string (never guessed — empty means
// "unbound") plus the optional bin-grid calibration from the SEG-Y headers.
// It is intentionally a plain value type with a JSON codec so hosts can
// persist it in catalog metadata without any libs/project ABI change.

#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <utility>

#include <pwb/domain/json.hpp>
#include <pwb/seismic_io/tile_cache.hpp>
#include <pwb/seismic_io/volume_descriptor.hpp>
#include <pwb/seismic_service/tiled_volume.hpp>

namespace pwb::seismic_service {

// Parses `PWB_SEISMIC_TILE_CACHE_BYTES` (decimal, positive). Returns the
// default (64 MiB) when unset, empty, or malformed — the env override never
// produces an invalid config.
[[nodiscard]] std::size_t tile_cache_budget_from_env(
    std::size_t default_bytes = 64u * 1024u * 1024u);

struct SeismicSpatialContext {
    std::string crs_id;  // "" = unbound; never guessed (crs_policy spirit)
    std::optional<pwb::seismic_io::BinGridGeometry> bin_grid;

    // Fractional (inline, crossline) for world (x, y); nullopt without a
    // bin grid — callers must surface "未标定", not fabricate coordinates.
    [[nodiscard]] std::optional<std::pair<double, double>> xy_to_il_xl(
        double x, double y) const;
    // World (x, y) for absolute (inline, crossline) numbers; nullopt without
    // a bin grid.
    [[nodiscard]] std::optional<std::pair<double, double>> il_xl_to_xy(
        double iline, double xline) const;
};

// Catalog-metadata codec. Keys: "spatial.crs" (string, may be absent for an
// unbound context) and "spatial.bin_grid" {x_origin, y_origin,
// il_azimuth_deg, il_spacing_m, xl_spacing_m} (absent when uncalibrated).
[[nodiscard]] pwb::domain::Json spatial_context_to_json(
    const SeismicSpatialContext& context);

// Inverse of spatial_context_to_json; nullopt on malformed input (unknown
// shapes are refused, never repaired).
[[nodiscard]] std::optional<SeismicSpatialContext> spatial_context_from_json(
    const pwb::domain::Json& json);

struct OpenedVolume {
    std::shared_ptr<pwb::viz::ISeismicVolume> volume;
    pwb::seismic_io::VolumeDescriptor descriptor;
    std::shared_ptr<pwb::seismic_io::TileCache> cache;
};

class SeismicVolumeService {
public:
    // Explicit budget/tile configuration (host-managed).
    explicit SeismicVolumeService(pwb::seismic_io::TileCacheConfig config);
    // Environment-driven budget; tiles keep the library default shape.
    SeismicVolumeService();

    SeismicVolumeService(const SeismicVolumeService&) = delete;
    SeismicVolumeService& operator=(const SeismicVolumeService&) = delete;

    // Metadata-first opens: "" return of error means success. Each volume
    // gets its own tile cache instance with this service's configuration.
    [[nodiscard]] OpenedVolume open_segy(const std::filesystem::path& path,
                                         std::string* error) const;
    [[nodiscard]] OpenedVolume open_pwbvol(const std::filesystem::path& path,
                                           std::string* error) const;

    // Applies the spatial seam: descriptor.bin_grid into a context whose
    // CRS comes from the project (host-supplied, never inferred here).
    [[nodiscard]] SeismicSpatialContext spatial_context(
        const std::string& project_crs_id,
        const pwb::seismic_io::VolumeDescriptor& descriptor) const;

private:
    pwb::seismic_io::TileCacheConfig config_;
};

}  // namespace pwb::seismic_service
