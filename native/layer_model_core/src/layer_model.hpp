// layer_model.hpp — authoritative C++ layer data model for the native map engine.
//
// Pure C++ (no Qt / no pybind11). Holds the layer metadata + ordered registry that the
// goal (§7/§8) requires to be the *single authoritative* map render state, with style
// revisions independent of data revisions (so a style change never triggers a re-render
// of the underlying data). Field set follows the goal's §7 layer-metadata list.
//
// bindings.cpp wraps it for Python; standalone_test.cpp verifies behaviour with g++.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace pwb::layer_model {

enum class LayerType : std::uint8_t {
    ScalarGrid = 0,
    Raster = 1,
    Contour = 2,
    Vector = 3,
    Point = 4,
    Annotation = 5,
    Group = 6,
};

// Axis-aligned extent in the layer's CRS: {xmin, ymin, xmax, ymax}.
using Extent = std::array<double, 4>;

// Scale-visibility bounds. A non-positive value means "unbounded" on that side.
struct ScaleRange {
    double min_scale = 0.0;  // denominator; <=0 == no lower bound
    double max_scale = 0.0;  // denominator; <=0 == no upper bound

    bool visible_at(double scale_denominator) const noexcept {
        if (min_scale > 0.0 && scale_denominator < min_scale) return false;
        if (max_scale > 0.0 && scale_denominator > max_scale) return false;
        return true;
    }
};

// A single map layer's metadata + render-state. Rendering payloads (grid bytes, vector
// geometry) are held externally and referenced by ``source_ref``; this struct is the
// lightweight authoritative state, not a data container.
class MapLayer {
public:
    MapLayer(std::string id, std::string name, LayerType type)
        : id_(std::move(id)), name_(std::move(name)), type_(type) {}

    // identity (immutable)
    const std::string& id() const noexcept { return id_; }
    LayerType type() const noexcept { return type_; }

    // display
    const std::string& name() const noexcept { return name_; }
    void set_name(std::string name) { name_ = std::move(name); ++style_revision_; }

    bool visible() const noexcept { return visible_; }
    void set_visible(bool v) { visible_ = v; ++style_revision_; }

    // opacity 0..1, clamped.
    float opacity() const noexcept { return opacity_; }
    void set_opacity(float o);

    // spatial
    const std::string& crs() const noexcept { return crs_; }
    void set_crs(std::string crs) { crs_ = std::move(crs); ++data_revision_; }
    Extent extent() const noexcept { return extent_; }
    void set_extent(Extent e) { extent_ = e; ++data_revision_; }

    const ScaleRange& scale_range() const noexcept { return scale_range_; }
    void set_scale_range(ScaleRange s) { scale_range_ = s; ++style_revision_; }

    // True if this layer should draw at the given scale (ignores the on/off toggle).
    bool visible_at_scale(double scale_denominator) const noexcept {
        return scale_range_.visible_at(scale_denominator);
    }

    // payload reference (external data) — changing it is a DATA change.
    const std::string& source_ref() const noexcept { return source_ref_; }
    void set_source_ref(std::string ref) { source_ref_ = std::move(ref); ++data_revision_; }

    // revisions (the render-cache key components)
    std::uint64_t data_revision() const noexcept { return data_revision_; }
    std::uint64_t style_revision() const noexcept { return style_revision_; }
    void bump_data_revision() { ++data_revision_; }
    void bump_style_revision() { ++style_revision_; }

    bool dirty() const noexcept { return dirty_; }
    void set_dirty(bool d) { dirty_ = d; }

    // free-form metadata + provenance (display only; does not affect revisions).
    const std::map<std::string, std::string>& metadata() const noexcept { return metadata_; }
    void set_metadata(std::string key, std::string value) { metadata_[std::move(key)] = std::move(value); }
    const std::string& provenance_ref() const noexcept { return provenance_ref_; }
    void set_provenance_ref(std::string ref) { provenance_ref_ = std::move(ref); }

private:
    std::string id_;
    std::string name_;
    LayerType type_;
    bool visible_ = true;
    float opacity_ = 1.0f;
    std::string crs_;
    Extent extent_ = {0.0, 0.0, 0.0, 0.0};
    ScaleRange scale_range_;
    std::string source_ref_;
    std::string provenance_ref_;
    std::map<std::string, std::string> metadata_;
    std::uint64_t data_revision_ = 1;
    std::uint64_t style_revision_ = 1;
    bool dirty_ = false;
};

// Ordered layer registry — the authoritative render state. Vector index IS the z-order
// (index 0 = bottom, drawn first). Group layers (LayerType::Group) carry children via the
// ``parent_id`` association; the registry stores a flat ordered list and resolves groups
// on demand. Stable layer ids are unique and never recycled within a session.
class LayerRegistry {
public:
    LayerRegistry() = default;

    // Add a layer at the top of the stack. Returns a raw pointer that remains valid as
    // long as the layer is in the registry. ``parent_id`` (optional) attaches it under a
    // group layer.
    MapLayer* add_layer(std::unique_ptr<MapLayer> layer, const std::string& parent_id = "");

    // Remove by id. Returns true if removed.
    bool remove_layer(const std::string& id);

    MapLayer* get(const std::string& id) const;
    std::size_t size() const noexcept { return layers_.size(); }
    bool empty() const noexcept { return layers_.empty(); }

    // z-order: index 0 = bottom.
    const std::vector<std::unique_ptr<MapLayer>>& layers() const noexcept { return layers_; }
    std::size_t index_of(const std::string& id) const;

    // Move ``id`` to absolute z-position ``new_index`` (clamped). Returns false if not found.
    bool move_layer(const std::string& id, std::size_t new_index);

    // Move ``id`` relative to ``other`` (before/after). Returns false if either missing.
    bool move_above(const std::string& id, const std::string& other);
    bool move_below(const std::string& id, const std::string& other);

    // Resolve the effective visibility of a layer at a scale, honouring group visibility
    // propagation (a layer is effectively visible only if it AND all ancestor groups are
    // visible and within scale range).
    bool is_effectively_visible(const std::string& id, double scale_denominator) const;

    // Children of a group, in z-order.
    std::vector<const MapLayer*> children_of(const std::string& group_id) const;

private:
    std::vector<std::unique_ptr<MapLayer>> layers_;
    std::map<std::string, std::string> parent_of_;  // layer id -> parent group id
};

}  // namespace pwb::layer_model
