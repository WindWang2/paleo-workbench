#include <pwb/seismic_service/volume_service.hpp>

#include <cstdlib>
#include <string>

namespace pwb::seismic_service {

std::size_t tile_cache_budget_from_env(std::size_t default_bytes) {
    const char* raw = std::getenv("PWB_SEISMIC_TILE_CACHE_BYTES");
    if (raw == nullptr || *raw == '\0') {
        return default_bytes;
    }
    try {
        const unsigned long long parsed = std::stoull(raw);
        if (parsed == 0) {
            return default_bytes;
        }
        return static_cast<std::size_t>(parsed);
    } catch (...) {
        return default_bytes;
    }
}

std::optional<std::pair<double, double>> SeismicSpatialContext::xy_to_il_xl(
    double x, double y) const {
    if (!bin_grid.has_value()) {
        return std::nullopt;
    }
    return bin_grid->xy_to_il_xl(x, y);
}

std::optional<std::pair<double, double>> SeismicSpatialContext::il_xl_to_xy(
    double iline, double xline) const {
    if (!bin_grid.has_value()) {
        return std::nullopt;
    }
    return bin_grid->il_xl_to_xy(iline, xline);
}

pwb::domain::Json spatial_context_to_json(const SeismicSpatialContext& context) {
    pwb::domain::Json json = pwb::domain::Json::object();
    if (!context.crs_id.empty()) {
        json["spatial.crs"] = context.crs_id;
    }
    if (context.bin_grid.has_value()) {
        pwb::domain::Json grid = pwb::domain::Json::object();
        grid["x_origin"] = context.bin_grid->x_origin;
        grid["y_origin"] = context.bin_grid->y_origin;
        grid["il_azimuth_deg"] = context.bin_grid->il_azimuth_deg;
        grid["il_spacing_m"] = context.bin_grid->il_spacing_m;
        grid["xl_spacing_m"] = context.bin_grid->xl_spacing_m;
        json["spatial.bin_grid"] = std::move(grid);
    }
    return json;
}

std::optional<SeismicSpatialContext> spatial_context_from_json(
    const pwb::domain::Json& json) {
    if (!json.is_object()) {
        return std::nullopt;
    }
    SeismicSpatialContext context;
    if (json.contains("spatial.crs")) {
        if (!json["spatial.crs"].is_string()) {
            return std::nullopt;
        }
        context.crs_id = json["spatial.crs"].get<std::string>();
    }
    if (json.contains("spatial.bin_grid")) {
        const pwb::domain::Json& grid = json["spatial.bin_grid"];
        static const char* kFields[5] = {"x_origin", "y_origin",
                                         "il_azimuth_deg", "il_spacing_m",
                                         "xl_spacing_m"};
        if (!grid.is_object()) {
            return std::nullopt;
        }
        for (const char* field : kFields) {
            if (!grid.contains(field) || !grid[field].is_number()) {
                return std::nullopt;
            }
        }
        pwb::seismic_io::BinGridGeometry bin_grid;
        bin_grid.x_origin = grid["x_origin"].get<double>();
        bin_grid.y_origin = grid["y_origin"].get<double>();
        bin_grid.il_azimuth_deg = grid["il_azimuth_deg"].get<double>();
        bin_grid.il_spacing_m = grid["il_spacing_m"].get<double>();
        bin_grid.xl_spacing_m = grid["xl_spacing_m"].get<double>();
        if (bin_grid.il_spacing_m == 0.0 || bin_grid.xl_spacing_m == 0.0) {
            return std::nullopt;  // degenerate calibration refused
        }
        context.bin_grid = bin_grid;
    }
    return context;
}

SeismicVolumeService::SeismicVolumeService(
    pwb::seismic_io::TileCacheConfig config)
    : config_(config) {}

SeismicVolumeService::SeismicVolumeService() : SeismicVolumeService([] {
    pwb::seismic_io::TileCacheConfig config;
    config.max_bytes = tile_cache_budget_from_env();
    return config;
}()) {}

OpenedVolume SeismicVolumeService::open_segy(const std::filesystem::path& path,
                                             std::string* error) const {
    OpenedVolume opened;
    std::string inspect_error;
    auto layout = pwb::seismic_io::inspect_segy(path, &inspect_error);
    if (!layout.has_value()) {
        if (error != nullptr) *error = inspect_error;
        return opened;
    }
    opened.descriptor = layout->descriptor;
    opened.cache = std::make_shared<pwb::seismic_io::TileCache>(config_);
    opened.volume = make_tiled_volume(std::move(*layout), opened.cache);
    return opened;
}

OpenedVolume SeismicVolumeService::open_pwbvol(
    const std::filesystem::path& path, std::string* error) const {
    OpenedVolume opened;
    std::string inspect_error;
    auto layout = pwb::seismic_io::inspect_pwbvol(path, &inspect_error);
    if (!layout.has_value()) {
        if (error != nullptr) *error = inspect_error;
        return opened;
    }
    opened.descriptor = layout->descriptor;
    opened.cache = std::make_shared<pwb::seismic_io::TileCache>(config_);
    opened.volume = make_tiled_volume(std::move(*layout), opened.cache);
    return opened;
}

SeismicSpatialContext SeismicVolumeService::spatial_context(
    const std::string& project_crs_id,
    const pwb::seismic_io::VolumeDescriptor& descriptor) const {
    SeismicSpatialContext context;
    context.crs_id = project_crs_id;
    context.bin_grid = descriptor.bin_grid;
    return context;
}

}  // namespace pwb::seismic_service
