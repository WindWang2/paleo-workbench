// layer_model.cpp — implementation of the authoritative C++ layer data model.
#include "layer_model.hpp"

#include <algorithm>
#include <stdexcept>

namespace pwb::layer_model {

void MapLayer::set_name(std::string name) {
    if (name_ == name) return;
    name_ = std::move(name);
    ++style_revision_;
}

void MapLayer::set_visible(bool v) {
    if (visible_ == v) return;
    visible_ = v;
    ++style_revision_;
}

void MapLayer::set_opacity(float o) {
    if (o < 0.0f) o = 0.0f;
    else if (o > 1.0f) o = 1.0f;
    if (opacity_ == o) return;
    opacity_ = o;
    ++style_revision_;
}

void MapLayer::set_crs(std::string crs) {
    if (crs_ == crs) return;
    crs_ = std::move(crs);
    ++data_revision_;
}

void MapLayer::set_extent(Extent e) {
    if (extent_ == e) return;
    extent_ = e;
    ++data_revision_;
}

void MapLayer::set_scale_range(ScaleRange s) {
    if (scale_range_.min_scale == s.min_scale && scale_range_.max_scale == s.max_scale) {
        return;
    }
    scale_range_ = s;
    ++style_revision_;
}

void MapLayer::set_source_ref(std::string ref) {
    if (source_ref_ == ref) return;
    source_ref_ = std::move(ref);
    ++data_revision_;
}

// --- LayerRegistry -----------------------------------------------------------

MapLayer* LayerRegistry::add_layer(std::unique_ptr<MapLayer> layer,
                                   const std::string& parent_id) {
    if (!layer) return nullptr;
    if (parent_id == layer->id()) {
        throw std::invalid_argument("layer cannot be its own parent");
    }
    MapLayer* raw = layer.get();
    // Parents are created before children, which makes cycles impossible. A layer may
    // be nested only below a group; accepting any layer here would make the tree's
    // hierarchy disagree with its type metadata.
    if (!parent_id.empty()) {
        const MapLayer* parent = get(parent_id);
        if (parent == nullptr) {
            throw std::invalid_argument("parent group does not exist: " + parent_id);
        }
        if (parent->type() != LayerType::Group) {
            throw std::invalid_argument("parent is not a group: " + parent_id);
        }
    }
    if (get(raw->id()) != nullptr) {
        throw std::invalid_argument("duplicate layer id: " + raw->id());
    }
    if (!parent_id.empty()) {
        parent_of_[raw->id()] = parent_id;
    }
    layers_.emplace_back(std::move(layer));
    return raw;
}

bool LayerRegistry::remove_layer(const std::string& id) {
    auto it = std::find_if(layers_.begin(), layers_.end(),
                           [&](const std::shared_ptr<MapLayer>& l) { return l->id() == id; });
    if (it == layers_.end()) return false;
    layers_.erase(it);
    parent_of_.erase(id);
    // Orphan any children (detach rather than cascade-delete — caller decides).
    for (auto& kv : parent_of_) {
        if (kv.second == id) kv.second.clear();
    }
    return true;
}

MapLayer* LayerRegistry::get(const std::string& id) const {
    for (const auto& l : layers_) {
        if (l->id() == id) return l.get();
    }
    return nullptr;
}

std::shared_ptr<MapLayer> LayerRegistry::get_shared(const std::string& id) const {
    for (const auto& l : layers_) {
        if (l->id() == id) return l;
    }
    return nullptr;
}

std::size_t LayerRegistry::index_of(const std::string& id) const {
    for (std::size_t i = 0; i < layers_.size(); ++i) {
        if (layers_[i]->id() == id) return i;
    }
    return layers_.size();  // npos sentinel
}

bool LayerRegistry::move_layer(const std::string& id, std::size_t new_index) {
    const std::size_t cur = index_of(id);
    if (cur >= layers_.size()) return false;
    if (new_index >= layers_.size()) new_index = layers_.size() - 1;
    if (new_index == cur) return true;
    auto layer = std::move(layers_[cur]);
    layers_.erase(layers_.begin() + static_cast<std::ptrdiff_t>(cur));
    layers_.insert(layers_.begin() + static_cast<std::ptrdiff_t>(new_index),
                   std::move(layer));
    return true;
}

bool LayerRegistry::move_above(const std::string& id, const std::string& other) {
    const std::size_t i = index_of(id);
    std::size_t j = index_of(other);
    if (i >= layers_.size() || j >= layers_.size() || i == j) return false;
    // Remove id, then place it immediately ABOVE other (one index higher).
    auto layer = std::move(layers_[i]);
    layers_.erase(layers_.begin() + static_cast<std::ptrdiff_t>(i));
    if (j > i) --j;  // other shifted down because id was before it
    std::size_t target = j + 1;
    if (target > layers_.size()) target = layers_.size();
    layers_.insert(layers_.begin() + static_cast<std::ptrdiff_t>(target), std::move(layer));
    return true;
}

bool LayerRegistry::move_below(const std::string& id, const std::string& other) {
    const std::size_t i = index_of(id);
    std::size_t j = index_of(other);
    if (i >= layers_.size() || j >= layers_.size() || i == j) return false;
    // Remove id, then place it immediately BELOW other (at other's index).
    auto layer = std::move(layers_[i]);
    layers_.erase(layers_.begin() + static_cast<std::ptrdiff_t>(i));
    if (j > i) --j;
    layers_.insert(layers_.begin() + static_cast<std::ptrdiff_t>(j), std::move(layer));
    return true;
}

bool LayerRegistry::is_effectively_visible(const std::string& id,
                                           double scale_denominator) const {
    const MapLayer* l = get(id);
    if (l == nullptr) return false;
    if (!l->visible()) return false;
    if (!l->visible_at_scale(scale_denominator)) return false;
    // Walk ancestors; any hidden/off-scale group hides the descendant.
    std::string cur_parent = parent_of_.count(id) ? parent_of_.at(id) : std::string{};
    std::size_t guard = 0;
    while (!cur_parent.empty() && guard++ < layers_.size()) {
        const MapLayer* p = get(cur_parent);
        if (p == nullptr) break;
        if (!p->visible()) return false;
        if (!p->visible_at_scale(scale_denominator)) return false;
        cur_parent = parent_of_.count(p->id()) ? parent_of_.at(p->id()) : std::string{};
    }
    return true;
}

std::vector<const MapLayer*> LayerRegistry::children_of(const std::string& group_id) const {
    std::vector<const MapLayer*> out;
    for (const auto& l : layers_) {
        auto it = parent_of_.find(l->id());
        if (it != parent_of_.end() && it->second == group_id) {
            out.push_back(l.get());
        }
    }
    return out;
}

std::string LayerRegistry::parent_id(const std::string& id) const {
    const auto it = parent_of_.find(id);
    return it == parent_of_.end() ? std::string{} : it->second;
}

}  // namespace pwb::layer_model
