// UI-15 — Qt-free map-export spec (map_export_worker.py parity).

#include <pwb/ui_canvas/export_core.hpp>

#include <filesystem>
#include <system_error>

namespace pwb::ui_canvas {

MapExportSpec make_export_spec(MapRenderSnapshot snapshot,
                               const Extent& view_extent, std::string path,
                               int width, std::optional<int> height,
                               double dpi, Json decorations,
                               bool prefer_native_renderer) {
    const int resolved_height =
        height.has_value() ? *height
                           : default_export_height(view_extent, width);
    if (width < 1 || resolved_height < 1) {
        throw std::invalid_argument("export size must be positive");
    }
    MapExportSpec spec;
    spec.snapshot = std::move(snapshot);
    spec.extent = view_extent;
    spec.width = width;
    spec.height = resolved_height;
    spec.dpi = dpi;
    spec.decorations =
        decorations.is_object() ? std::move(decorations) : Json::object();
    spec.path = std::move(path);
    spec.prefer_native_renderer = prefer_native_renderer;
    return spec;
}

void discard_partial_export_file(const std::string& path) {
    // Path.unlink(missing_ok=True) + except OSError parity.
    std::error_code error;
    std::filesystem::remove(std::filesystem::path(path), error);
}

}  // namespace pwb::ui_canvas
