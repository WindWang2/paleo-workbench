// UI-15 — Qt-free unified-map-canvas core.
// Python parity: ui/unified_map_canvas.py helpers +
// mapping/map_render_backend.py MapRenderBackend ABC.

#include <pwb/ui_canvas/map_render_backend.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace pwb::ui_canvas {

Extent sanitize_extent(const Extent& extent) {
    double xmin = extent[0], ymin = extent[1];
    double xmax = extent[2], ymax = extent[3];
    if (!std::isfinite(xmin) || !std::isfinite(ymin) || !std::isfinite(xmax) ||
        !std::isfinite(ymax)) {
        throw std::invalid_argument("extent coordinates must be finite");
    }
    if (xmax < xmin) std::swap(xmin, xmax);
    if (ymax < ymin) std::swap(ymin, ymax);
    const double pad_x = std::max((ymax - ymin) * 0.01, 1e-9);
    const double pad_y = std::max((xmax - xmin) * 0.01, 1e-9);
    if (xmax - xmin < 1e-12) {
        const double cx = (xmin + xmax) / 2.0;
        xmin = cx - pad_x / 2.0;
        xmax = cx + pad_x / 2.0;
    }
    if (ymax - ymin < 1e-12) {
        const double cy = (ymin + ymax) / 2.0;
        ymin = cy - pad_y / 2.0;
        ymax = cy + pad_y / 2.0;
    }
    return {xmin, ymin, xmax, ymax};
}

Extent fit_extent_to_aspect(const Extent& extent, double width,
                            double height) {
    const double xmin = extent[0], ymin = extent[1];
    const double xmax = extent[2], ymax = extent[3];
    const double w = std::max(1.0, width);
    const double h = std::max(1.0, height);
    const double world_w = xmax - xmin;
    const double world_h = ymax - ymin;
    if (world_w <= 0.0 || world_h <= 0.0) {
        return extent;
    }
    const double units_per_pixel =
        std::max(world_w / w, world_h / h);
    const double adj_w = units_per_pixel * w;
    const double adj_h = units_per_pixel * h;
    const double cx = (xmin + xmax) / 2.0;
    const double cy = (ymin + ymax) / 2.0;
    return {cx - adj_w / 2.0, cy - adj_h / 2.0,
            cx + adj_w / 2.0, cy + adj_h / 2.0};
}

Extent letterboxed_extent(const Extent& view_extent, int width_px,
                          int height_px) {
    const double xmin = view_extent[0], ymin = view_extent[1];
    const double xmax = view_extent[2], ymax = view_extent[3];
    const double span_x = xmax - xmin;
    const double span_y = ymax - ymin;
    if (width_px < 1 || height_px < 1 || span_x <= 0.0 || span_y <= 0.0) {
        return view_extent;
    }
    const double target_aspect =
        static_cast<double>(width_px) / static_cast<double>(height_px);
    const double view_aspect = span_x / span_y;
    // math.isclose(rel_tol=1e-3) parity — exact-aspect inputs pass through.
    if (std::abs(target_aspect - view_aspect) <=
        1e-3 * std::max(std::abs(target_aspect), std::abs(view_aspect))) {
        return view_extent;
    }
    if (target_aspect > view_aspect) {
        const double padded = span_y * target_aspect;
        return {xmin - (padded - span_x) / 2.0, ymin,
                xmax + (padded - span_x) / 2.0, ymax};
    }
    const double padded = span_x / target_aspect;
    return {xmin, ymin - (padded - span_y) / 2.0,
            xmax, ymax + (padded - span_y) / 2.0};
}

int default_export_height(const Extent& view_extent, int width) {
    const double xmin = view_extent[0], ymin = view_extent[1];
    const double xmax = view_extent[2], ymax = view_extent[3];
    if (xmax > xmin && ymax > ymin) {
        const long rounded =
            std::lround(static_cast<double>(width) * (ymax - ymin) /
                        (xmax - xmin));
        return static_cast<int>(std::clamp<long>(rounded, 64, 16000));
    }
    return 1600;
}

namespace {

void append_token(std::string& out, const std::string& value) {
    out += value;
    out.push_back('\x1f');
}

}  // namespace

std::string snapshot_signature(const MapRenderSnapshot& snapshot) {
    // Python: (str(project_crs), tuple((id, layer_type, int(data_revision),
    // int(style_revision), bool(visible), round(opacity, 6), scale_range,
    // str(source_version_id)) for layer in layers)).
    std::string out;
    out.reserve(256);
    append_token(out, snapshot.project_crs);
    for (const MapLayerSnapshot& layer : snapshot.layers) {
        append_token(out, layer.id);
        append_token(out, layer.layer_type);
        append_token(out, std::to_string(layer.data_revision));
        append_token(out, std::to_string(layer.style_revision));
        append_token(out, layer.visible ? "1" : "0");
        // round(opacity, 6) parity.
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%.6f", layer.opacity);
        append_token(out, buf);
        if (layer.scale_range) {
            append_token(out, std::to_string(layer.scale_range->first));
            append_token(out, std::to_string(layer.scale_range->second));
        } else {
            append_token(out, "None");
        }
        append_token(out, layer.source_version_id);
        out.push_back('\x1e');
    }
    return out;
}

std::vector<std::string> snapshot_source_version_ids(
    const MapRenderSnapshot& snapshot) {
    std::vector<std::string> ids;
    for (const MapLayerSnapshot& layer : snapshot.layers) {
        if (layer.source_version_id.empty()) {
            continue;
        }
        if (std::find(ids.begin(), ids.end(), layer.source_version_id) ==
            ids.end()) {
            ids.push_back(layer.source_version_id);
        }
    }
    return ids;
}

double fitted_map_units_per_pixel(const Extent& view_extent, int width_px,
                                  int height_px) {
    const Extent fitted =
        fit_extent_to_aspect(view_extent, width_px, height_px);
    const double dx = fitted[2] - fitted[0];
    const double dy = fitted[3] - fitted[1];
    return std::max(dx / std::max(1, width_px),
                    dy / std::max(1, height_px));
}

std::pair<double, double>
screen_to_map(const Extent& view_extent, int width_px, int height_px,
              std::pair<double, double> screen_xy) {
    const Extent fitted =
        fit_extent_to_aspect(view_extent, width_px, height_px);
    const double xmin = fitted[0], ymax = fitted[3];
    const double dx = fitted[2] - fitted[0];
    const double dy = fitted[3] - fitted[1];
    return {xmin + screen_xy.first * dx / std::max(1, width_px),
            ymax - screen_xy.second * dy / std::max(1, height_px)};
}

std::optional<std::pair<double, double>>
map_to_screen(const Extent& view_extent, int width_px, int height_px,
              std::pair<double, double> map_xy) {
    const Extent fitted =
        fit_extent_to_aspect(view_extent, width_px, height_px);
    const double dx = fitted[2] - fitted[0];
    const double dy = fitted[3] - fitted[1];
    if (dx == 0.0 || dy == 0.0 ||
        !(std::isfinite(dx) && std::isfinite(dy))) {
        return std::nullopt;
    }
    return std::make_pair(
        (map_xy.first - fitted[0]) * width_px / dx,
        (fitted[3] - map_xy.second) * height_px / dy);
}

// ---------------------------------------------------------------------------
// MapRenderBackend
// ---------------------------------------------------------------------------

void MapRenderBackend::initialize() {
    if (!is_available()) {
        throw std::runtime_error(backend_name() +
                                 " renderer is unavailable: " + status());
    }
    initialized_ = true;
}

void MapRenderBackend::set_extent(const Extent& extent) {
    for (double value : extent) {
        if (!std::isfinite(value)) {
            throw std::invalid_argument(
                "extent must contain four finite values");
        }
    }
    if (extent[2] <= extent[0] || extent[3] <= extent[1]) {
        throw std::invalid_argument(
            "extent must have positive width and height");
    }
    extent_ = extent;
}

void MapRenderBackend::set_output_size(int width, int height) {
    if (width < 1 || height < 1) {
        throw std::invalid_argument("output size must be positive");
    }
    output_width_ = width;
    output_height_ = height;
}

void MapRenderBackend::set_dpi(double dpi) {
    if (!std::isfinite(dpi) || dpi <= 0.0) {
        throw std::invalid_argument("dpi must be finite and positive");
    }
    dpi_ = dpi;
}

std::uint64_t MapRenderBackend::request_render() {
    RenderFrame frame = render_sync();
    const std::uint64_t generation = frame.generation;
    store_completed(std::move(frame));
    return generation;
}

std::optional<RenderFrame> MapRenderBackend::take_completed_frame() {
    std::optional<RenderFrame> frame = std::move(completed_);
    completed_.reset();
    return frame;
}

// ---------------------------------------------------------------------------
// Factory registry
// ---------------------------------------------------------------------------

namespace {

struct FactoryEntry {
    BackendFactory factory;
    bool is_qgis;
};

std::vector<FactoryEntry>& factories() {
    static std::vector<FactoryEntry> list;
    return list;
}

}  // namespace

void register_backend_factory(BackendFactory factory, bool is_qgis) {
    if (factory != nullptr) {
        factories().push_back({factory, is_qgis});
    }
}

std::shared_ptr<MapRenderBackend> create_map_render_backend(
    bool prefer_qgis) {
    for (const FactoryEntry& entry : factories()) {
        if (entry.is_qgis && !prefer_qgis) {
            continue;
        }
        std::shared_ptr<MapRenderBackend> candidate;
        try {
            candidate = entry.factory();
        } catch (...) {
            continue;
        }
        if (!candidate) {
            continue;
        }
        try {
            candidate->initialize();
        } catch (...) {
            continue;
        }
        return candidate;
    }
    throw std::runtime_error("no map render backend is available");
}

std::shared_ptr<MapRenderBackend> create_native_map_render_backend() {
    for (const FactoryEntry& entry : factories()) {
        if (!entry.is_qgis) {
            continue;
        }
        std::shared_ptr<MapRenderBackend> candidate;
        try {
            candidate = entry.factory();
        } catch (...) {
            continue;
        }
        if (!candidate) {
            continue;
        }
        try {
            candidate->initialize();
        } catch (...) {
            continue;
        }
        return candidate;
    }
    return nullptr;
}

}  // namespace pwb::ui_canvas
