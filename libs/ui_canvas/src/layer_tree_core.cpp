// UI-15 — Qt-free layer-tree semantics (native_layer_tree.py parity).

#include <pwb/ui_canvas/layer_tree_core.hpp>

#include <algorithm>

namespace pwb::ui_canvas {

std::vector<const pwb::layer_model::MapLayer*> display_children(
    const pwb::layer_model::LayerRegistry& registry,
    const std::string& parent_id) {
    std::vector<const pwb::layer_model::MapLayer*> out;
    const auto& layers = registry.layers();
    for (auto it = layers.rbegin(); it != layers.rend(); ++it) {
        const pwb::layer_model::MapLayer* layer = it->get();
        if (layer != nullptr &&
            registry.parent_id(layer->id()) == parent_id) {
            out.push_back(layer);
        }
    }
    return out;
}

std::optional<DropResolution> resolve_drop(
    const pwb::layer_model::LayerRegistry& registry,
    const std::string& dragged_id, const std::string& drop_parent_id,
    int row) {
    const pwb::layer_model::MapLayer* dragged = registry.get(dragged_id);
    if (dragged == nullptr) {
        return std::nullopt;
    }
    std::string parent_id = drop_parent_id;
    if (!parent_id.empty()) {
        const pwb::layer_model::MapLayer* target = registry.get(parent_id);
        if (target == nullptr) {
            return std::nullopt;
        }
        if (target->type() != pwb::layer_model::LayerType::Group) {
            parent_id = registry.parent_id(parent_id);
        }
    }
    const std::vector<const pwb::layer_model::MapLayer*> siblings =
        display_children(registry, parent_id);
    int effective_row = row;
    if (effective_row < 0) {
        effective_row = static_cast<int>(siblings.size());
    }
    effective_row = std::clamp(
        effective_row, 0, static_cast<int>(siblings.size()));

    DropResolution out;
    out.parent_id = parent_id;
    if (!siblings.empty()) {
        if (effective_row >= static_cast<int>(siblings.size())) {
            out.absolute_index = 0;
        } else {
            const pwb::layer_model::MapLayer* landed =
                siblings[static_cast<std::size_t>(effective_row)];
            out.absolute_index =
                landed != nullptr ? registry.index_of(landed->id()) : 0;
        }
    } else {
        out.absolute_index =
            registry.size() > 0 ? registry.size() - 1 : 0;
    }
    return out;
}

}  // namespace pwb::ui_canvas
