// UI-15 — Qt-free native-map scene base implementation
// (viz/native_factor_map.py MapScene parity).

#include <pwb/ui_canvas/layer_scene.hpp>

#include <algorithm>
#include <limits>

namespace pwb::ui_canvas {

std::array<double, 4> NativeMapScene::extent() const {
    // MapScene.extent() verbatim: union every registry layer with a positive
    // span; (0, 0, 1, 1) when none qualify.
    double xmin = std::numeric_limits<double>::max();
    double ymin = std::numeric_limits<double>::max();
    double xmax = std::numeric_limits<double>::lowest();
    double ymax = std::numeric_limits<double>::lowest();
    bool any = false;
    for (const auto& layer : registry().layers()) {
        const pwb::layer_model::Extent e = layer->extent();
        if (!(e[0] < e[2] && e[1] < e[3])) {
            continue;
        }
        any = true;
        xmin = std::min(xmin, e[0]);
        ymin = std::min(ymin, e[1]);
        xmax = std::max(xmax, e[2]);
        ymax = std::max(ymax, e[3]);
    }
    if (!any) {
        return {0.0, 0.0, 1.0, 1.0};
    }
    return {xmin, ymin, xmax, ymax};
}

RasterKey NativeMapScene::scalar_raster_key(
    const std::string& layer_id) const {
    ScalarRasterSourcePtr scalar = scalar_layer(layer_id);
    if (!scalar) {
        throw std::out_of_range("no scalar grid payload for layer " +
                                layer_id);
    }
    return scalar->raster_key();
}

RasterImage NativeMapScene::raster_rgba(const std::string& layer_id) const {
    ScalarRasterSourcePtr scalar = scalar_layer(layer_id);
    if (!scalar) {
        throw std::out_of_range("no scalar grid payload for layer " +
                                layer_id);
    }
    RasterImage image;
    image.width = scalar->raster_width();
    image.height = scalar->raster_height();
    image.stride = scalar->raster_stride();
    image.rgba = scalar->rasterize();
    return image;
}

std::size_t NativeMapScene::add_change_listener(ChangeListener listener) {
    const std::size_t token = next_listener_token_++;
    listeners_.emplace_back(token, std::move(listener));
    return token;
}

void NativeMapScene::remove_change_listener(std::size_t token) {
    listeners_.erase(
        std::remove_if(listeners_.begin(), listeners_.end(),
                       [token](const auto& entry) {
                           return entry.first == token;
                       }),
        listeners_.end());
}

void NativeMapScene::emit_changed() {
    for (const auto& entry : listeners_) {
        if (entry.second) {
            entry.second();
        }
    }
}

}  // namespace pwb::ui_canvas
