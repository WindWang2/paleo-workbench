// UI-15 — Qt-free unified-map-canvas contracts.
//
// Frozen semantics are shared by two Python modules:
//   * mapping/map_render_backend.py — MapLayerSnapshot / MapRenderSnapshot /
//     RenderFrame records and the MapRenderBackend ABC (initialize/status/
//     set_extent/set_output_size/set_dpi/request_render/take_completed_frame/
//     render_active/cancel_render/render_sync/export_map_body/identify/
//     shutdown contract). That file belongs to the `mapping` migration area;
//     UI-15 ports only the *contract* it consumes — concrete fallback/QGIS
//     renderers stay owned by the mapping slice (the QGIS target ships
//     QgisSnapshotRenderBackend for UI-15's canvas surfaces).
//   * ui/unified_map_canvas.py — the canvas-side helpers (_sanitize_extent,
//     _letterboxed_extent, _default_export_height, _snapshot_signature,
//     _snapshot_source_version_ids) ported below as free functions.
#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_map/map_chrome_core.hpp>

namespace pwb::ui_canvas {

using Json = pwb::domain::Json;
using Extent = pwb::ui_map::Extent;

// One immutable host-owned render layer (map_render_backend.py
// MapLayerSnapshot parity). `features` uses GeoJSON-compatible dicts (a Json
// array). `renderer_payload` is opaque renderer-owned data — never serialized
// into project state or treated as scientific data.
struct MapLayerSnapshot {
    std::string id;
    std::string name;
    std::string layer_type;
    Extent extent{0.0, 0.0, 1.0, 1.0};
    std::string crs;
    std::uint64_t data_revision = 0;
    std::uint64_t style_revision = 0;
    Json features = Json::array();
    Json style = Json::object();
    bool visible = true;
    double opacity = 1.0;
    std::shared_ptr<void> renderer_payload;
    // Catalog provenance: the DataVersion id this layer was produced from.
    std::string source_version_id;
    std::map<std::string, std::string> metadata;
    // Optional 1:N scale-denominator visibility window (min, max); nullopt
    // renders at every scale.
    std::optional<std::pair<double, double>> scale_range;
    // Raster wire fields (kind:"raster" QGIS snapshot entries):
    //   * raster_source layers set source_path — Python reads it from the
    //     opaque renderer_payload; the C++ contract makes it explicit.
    //   * scalar_grid producers set source_path (the resolved mirror path)
    //     and optionally raster_renderer_xml (the v7 §5 DATA-path payload
    //     authored by the bridge). The mirror caches that produce these
    //     files stay owned by the mapping slice; when a scalar_grid layer
    //     reaches the encoder without a source_path it raises the same
    //     "raster mirror" error Python raises without its cache.
    std::string source_path;
    std::string raster_renderer_xml;
};

// Immutable composition input from LayerRegistry/project state.
struct MapRenderSnapshot {
    std::string project_crs;
    std::vector<MapLayerSnapshot> layers;
};

// Copied RGBA output shared by render adapters (RGBA8888).
struct RenderFrame {
    std::uint64_t generation = 0;
    int width = 0;
    int height = 0;
    int stride = 0;
    std::vector<std::uint8_t> rgba;  // stride * height
    double render_ms = 0.0;
};

// ---------------------------------------------------------------------------
// Pure math helpers — one authority shared by canvas + export + tests.
// ---------------------------------------------------------------------------

// UnifiedMapCanvas._sanitize_extent (#1166): finite check, swap inverted
// axes, pad a degenerate axis by max(other_axis * 1%, 1e-9) around its
// center. Throws std::invalid_argument (Python ValueError parity).
Extent sanitize_extent(const Extent& extent);

// mapping/map_render_backend.fit_extent_to_aspect (#522): letterbox `extent`
// to the `width`/`height` output aspect — the world axis that would be
// compressed is EXPANDED (centered) so units-per-pixel stays uniform.
// Degenerate world spans return the extent unchanged.
Extent fit_extent_to_aspect(const Extent& extent, double width,
                            double height);

// UnifiedMapCanvas._letterboxed_extent: same letterbox as the canvas method —
// exact-aspect inputs (isclose rel_tol=1e-3) and degenerate targets return
// the view extent unchanged.
Extent letterboxed_extent(const Extent& view_extent, int width_px,
                          int height_px);

// UnifiedMapCanvas._default_export_height: derive export height from the raw
// view extent aspect; fallback 1600, clamp [64, 16000]. No sanitizing —
// degenerate extents fall back (Python parity).
int default_export_height(const Extent& view_extent, int width);

// UnifiedMapCanvas._snapshot_signature: dedup key =
// (project_crs, [(id, layer_type, data_revision, style_revision, visible,
// round(opacity, 6), scale_range, source_version_id)]). Features/style are
// deliberately NOT in the key — they ride the revisions (Python parity).
std::string snapshot_signature(const MapRenderSnapshot& snapshot);

// UnifiedMapCanvas.snapshot_source_version_ids: unique non-empty ids in
// first-seen order (dict.fromkeys parity).
std::vector<std::string> snapshot_source_version_ids(
    const MapRenderSnapshot& snapshot);

// map_units_per_pixel on the letterboxed (fitted) extent:
// max(dx / max(1, w), dy / max(1, h)) — the Python canvas property verbatim.
double fitted_map_units_per_pixel(const Extent& view_extent, int width_px,
                                  int height_px);

// screen → fitted world coordinates (Python screen_to_map).
std::pair<double, double>
screen_to_map(const Extent& view_extent, int width_px, int height_px,
              std::pair<double, double> screen_xy);

// fitted world → screen. Degenerate fitted span → nullopt (the widget
// returns the canvas center instead — Python map_to_screen #1166 parity).
std::optional<std::pair<double, double>>
map_to_screen(const Extent& view_extent, int width_px, int height_px,
              std::pair<double, double> map_xy);

// Map-click hit tolerance in screen pixels (Python MAP_CLICK_PX = 6.0).
inline constexpr double kMapClickTolerancePx = 6.0;

// ---------------------------------------------------------------------------
// MapRenderBackend — renderer-neutral frame contract (Python ABC parity).
// ---------------------------------------------------------------------------

class MapRenderBackend {
public:
    virtual ~MapRenderBackend() = default;

    // Provider name for status/debug ("qgis", "fallback", ...).
    virtual std::string backend_name() const { return "unknown"; }

    // Whether frames render on a light background — canvas chrome picks dark
    // ink for light bodies. Both built-in backends are light (Python parity).
    virtual bool light_frame_background() const { return true; }

    // Backend availability. Python's is_available property.
    virtual bool is_available() const { return true; }

    // "ready" once initialized, "not initialized" before (Python status).
    virtual std::string status() const {
        return initialized() ? "ready" : "not initialized";
    }

    // Acquire native resources; repeated calls are no-ops. Throws
    // std::runtime_error("{name} renderer is unavailable: {status}") when
    // unavailable (Python RuntimeError parity).
    virtual void initialize();

    // Latest layer snapshot. The backend stores it verbatim; identical-
    // signature dedup is the canvas's job (Python parity).
    virtual void set_layer_snapshot(const MapRenderSnapshot& snapshot) {
        snapshot_ = snapshot;
    }

    const MapRenderSnapshot& snapshot() const { return snapshot_; }

    // World extent (xmin, ymin, xmax, ymax): four finite values, positive
    // width/height — std::invalid_argument on violation (Python ValueError).
    virtual void set_extent(const Extent& extent);

    const Extent& extent() const { return extent_; }

    // Pixel dimensions for the next frame; each must be >= 1.
    virtual void set_output_size(int width, int height);

    std::pair<int, int> output_size() const {
        return {output_width_, output_height_};
    }

    // Output resolution; must be finite and positive.
    virtual void set_dpi(double dpi);

    double dpi() const { return dpi_; }

    // Render the newest generation and discard any preceding completed frame.
    // The base implementation is synchronous (fallback parity); the QGIS
    // adapter overrides with its native parallel job. Returns the generation.
    virtual std::uint64_t request_render();

    // Returns and clears the latest completed frame (nullptr when none).
    virtual std::optional<RenderFrame> take_completed_frame();

    // Whether a later poll can still produce a frame (async backends).
    virtual bool render_active() const { return false; }

    // Drop the pending completed frame (Python cancel_render).
    virtual void cancel_render() { completed_.reset(); }

    // Render the current snapshot exactly once into an owned RGBA frame.
    virtual RenderFrame render_sync() = 0;

    // Export the map body (no host chrome) as a vector file using this
    // backend's own renderer interpretation. Returns false when the backend
    // has no vector exporter — callers fall back to their painter pipeline.
    virtual bool export_map_body(const std::string& /*path*/,
                                 const std::string& /*format*/,
                                 int /*width*/, int /*height*/,
                                 double /*dpi*/) {
        return false;
    }

    // Optional backend-assisted identify hook; host selection remains
    // authoritative (returns nullptr when unsupported).
    virtual std::shared_ptr<void> identify(double /*x*/, double /*y*/) {
        return nullptr;
    }

    // Release native resources. Idempotent.
    virtual void shutdown() {
        cancel_render();
        initialized_ = false;
    }

    bool initialized() const { return initialized_; }
    std::uint64_t generation() const { return generation_; }

protected:
    void mark_initialized(bool value) { initialized_ = value; }
    std::uint64_t next_generation() { return ++generation_; }
    void store_completed(RenderFrame frame) { completed_ = std::move(frame); }
    const std::optional<RenderFrame>& completed() const { return completed_; }

private:
    bool initialized_ = false;
    MapRenderSnapshot snapshot_;
    Extent extent_{0.0, 0.0, 1.0, 1.0};
    int output_width_ = 1;
    int output_height_ = 1;
    double dpi_ = 96.0;
    std::uint64_t generation_ = 0;
    std::optional<RenderFrame> completed_;
};

// ---------------------------------------------------------------------------
// Backend factory registry (create_map_render_backend parity).
// ---------------------------------------------------------------------------

// Factories are tried in registration order; the first backend that
// constructs AND initializes wins. The QGIS target installs its factory via
// qgis::install_qgis_backend_factory(); fallback providers register their
// own (a future mapping-slice port, or a host/test double). When nothing
// produces a usable backend, create_map_render_backend throws — the same
// RuntimeError surface as the Python selector.
using BackendFactory = std::shared_ptr<MapRenderBackend> (*)();

// `is_qgis` marks factories that provide the native QGIS path; they are
// skipped when callers pass prefer_qgis=false (Python parity).
void register_backend_factory(BackendFactory factory, bool is_qgis = false);

std::shared_ptr<MapRenderBackend> create_map_render_backend(
    bool prefer_qgis = true);

// Only qgis-marked factories — nullptr when none registered or usable. The
// export worker's prefer_native_renderer attempt uses this so a missing
// QGIS path degrades honestly (map_export_worker._render_frame_native
// parity — the direct-construction + initialize-failure surface maps onto
// "factory produced nothing").
std::shared_ptr<MapRenderBackend> create_native_map_render_backend();

}  // namespace pwb::ui_canvas
