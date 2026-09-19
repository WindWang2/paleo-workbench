// UI-15 — Qt-free native-map scene contracts (viz/native_factor_map.py
// MapScene / ContourGeometry / PointGeometry / scalar-raster-key parity).
//
// The scene is the composition authority for the native canvas: it owns the
// LayerRegistry (compiled in from native/layer_model_core — the single
// authoritative layer state), the scalar raster payloads, and the display-only
// contour/point geometry. The Qt canvas (pwb_ui_canvas_qt) only consumes it;
// nothing here depends on Qt.
#pragma once

#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "layer_model.hpp"

namespace pwb::ui_canvas {

// Display-only contour geometry in the grid's declared coordinate space
// (Python ContourGeometry parity).
struct ContourGeometry {
    std::vector<std::vector<std::pair<double, double>>> paths;
    std::array<int, 4> color{230, 230, 230, 220};
    double width = 1.0;
};

// Display-only sample points in the grid's declared coordinate space
// (Python PointGeometry parity).
struct PointGeometry {
    std::vector<std::pair<double, double>> points;
    std::array<int, 4> color{255, 255, 255, 255};
    double radius = 3.0;
};

// Raster identity: (data_revision, style_revision) — the render-cache key.
// A style change bumps the second component so cached rasters are replaced
// without re-reading scientific input.
using RasterKey = std::pair<std::uint64_t, std::uint64_t>;

// One scalar rasterization unit handed to the native raster worker. The
// worker calls rasterize() off the GUI thread; the payload itself stays
// authoritative on the scene side (Python scalar.rasterize() parity).
class IScalarRasterSource {
public:
    virtual ~IScalarRasterSource() = default;
    // (data_revision, style_revision) used to key cached images.
    virtual RasterKey raster_key() const = 0;
    // Produce the north-up RGBA image (row 0 = north). Returns
    // {height, width, stride_bytes, rgba}; throws std::exception on failure.
    virtual std::vector<std::uint8_t> rasterize() const = 0;
    virtual int raster_width() const = 0;
    virtual int raster_height() const = 0;
    virtual int raster_stride() const { return raster_width() * 4; }
};

using ScalarRasterSourcePtr = std::shared_ptr<IScalarRasterSource>;

// One completed scalar raster (what NativeMapScene::raster_rgba returns).
struct RasterImage {
    int width = 0;
    int height = 0;
    int stride = 0;  // bytes per row (width * 4 for RGBA8888)
    std::vector<std::uint8_t> rgba;
};

// Composition authority consumed by NativeMapCanvas. Hosts subclass this to
// expose their scalar/contour/point payload maps; the default implementation
// owns the LayerRegistry and the unioned-extent computation verbatim from
// MapScene.extent().
class NativeMapScene {
public:
    virtual ~NativeMapScene() = default;

    // The authoritative layer registry — single source of truth for order,
    // visibility, opacity, hierarchy, and revisions.
    virtual pwb::layer_model::LayerRegistry& registry() = 0;
    virtual const pwb::layer_model::LayerRegistry& registry() const = 0;

    // Unioned extent of every registry layer with a positive span; falls
    // back to (0, 0, 1, 1) when empty — MapScene.extent() verbatim.
    virtual std::array<double, 4> extent() const;

    // Scalar payload for `layer_id` (nullptr when the layer is not a scalar
    // grid). Identity matters: the canvas compares pointers to detect
    // payload replacement (Python `is` parity).
    virtual ScalarRasterSourcePtr scalar_layer(
        const std::string& layer_id) const = 0;

    // The (data, style) key for the scalar payload. Throws
    // std::out_of_range when no scalar payload exists (Python KeyError).
    virtual RasterKey scalar_raster_key(const std::string& layer_id) const;

    // Synchronous rasterization for export paths (Python raster_rgba).
    // Throws std::out_of_range when no scalar payload exists.
    virtual RasterImage raster_rgba(const std::string& layer_id) const;

    // Display-only geometry lookups; nullptr when absent.
    virtual const ContourGeometry* contour_geometry(
        const std::string& layer_id) const = 0;
    virtual const PointGeometry* point_geometry(
        const std::string& layer_id) const = 0;

    // Change notification (Python add_change_listener/remove_change_listener).
    // add returns an opaque token; remove takes that token back — the C++
    // equivalent of Python's callable-identity semantics.
    using ChangeListener = std::function<void()>;
    virtual std::size_t add_change_listener(ChangeListener listener);
    virtual void remove_change_listener(std::size_t token);

protected:
    void emit_changed();

private:
    std::vector<std::pair<std::size_t, ChangeListener>> listeners_;
    std::size_t next_listener_token_ = 1;
};

}  // namespace pwb::ui_canvas
