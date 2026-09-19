#include "pwb/ui_review/composite_layers.hpp"

#include <algorithm>

namespace pwb::ui_review {

int composite_layer_index(const CompositeLayers& layers,
                          const std::string& id) {
    for (std::size_t i = 0; i < layers.size(); ++i) {
        if (composite_layer_id(layers[i]) == id) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

bool composite_set_visible(CompositeLayers& layers,
                           const std::string& id, bool visible) {
    const int idx = composite_layer_index(layers, id);
    if (idx < 0) {
        return false;
    }
    layers[std::size_t(idx)]["visible"] = visible;
    return true;
}

bool composite_set_opacity(CompositeLayers& layers,
                           const std::string& id, double opacity) {
    const int idx = composite_layer_index(layers, id);
    if (idx < 0) {
        return false;
    }
    // replace(layer, opacity=max(0.05, opacity))
    layers[std::size_t(idx)]["opacity"] = std::max(0.05, opacity);
    return true;
}

bool composite_move_layer(CompositeLayers& layers,
                          const std::string& id, int direction) {
    const int index = composite_layer_index(layers, id);
    if (index < 0) {
        return false;
    }
    // 渲染自底向上；上移 = 提前
    const int target = index - direction;
    if (target < 0 || target >= static_cast<int>(layers.size())) {
        return false;
    }
    std::swap(layers[std::size_t(index)], layers[std::size_t(target)]);
    return true;
}

domain::Json composite_snapshot_json(const std::string& project_crs,
                                     const CompositeLayers& layers) {
    domain::Json snap = domain::Json::object();
    snap["project_crs"] = project_crs;
    domain::Json arr = domain::Json::array();
    for (const auto& layer : layers) {
        arr.push_back(layer);
    }
    snap["layers"] = std::move(arr);
    return snap;
}

bool composite_layer_visible(const domain::Json& layer) {
    return layer.value("visible", true);
}

double composite_layer_opacity(const domain::Json& layer) {
    return layer.value("opacity", 1.0);
}

std::string composite_layer_id(const domain::Json& layer) {
    return layer.value("id", std::string{});
}

std::string composite_layer_name(const domain::Json& layer) {
    return layer.value("name", composite_layer_id(layer));
}

}  // namespace pwb::ui_review
