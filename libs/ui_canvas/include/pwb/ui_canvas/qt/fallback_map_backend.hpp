// mapping/map_render_backend.py FallbackMapRenderBackend — the explicit
// QPainter software renderer for tests and hosts without a QGIS bridge.
//
// Semantics frozen against the Python implementation: geometry is parsed
// once per data revision into cached flat float64 parts; every frame
// performs world→screen transforms, viewport culling, pixel-grid LOD and
// batched draws. Labels are collected as plain specs during rasterisation
// and painted in a final pass (worker threads never touch font engines).
#pragma once

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <future>
#include <memory>
#include <thread>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/cartography/vector_style.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_canvas/map_render_backend.hpp>
#include <pwb/ui_canvas/qt/unified_map_canvas.hpp>
#include <pwb/ui_canvas/revision_cache.hpp>

#include <QBrush>
#include <QImage>
#include <QPainter>
#include <QPointF>
#include <QString>

#include <map>
#include <tuple>

namespace pwb::ui_canvas::qt {

// A prepared feature: geometry classified + parsed once per layer data
// revision. `parts` holds (N,2) world-coordinate vertex arrays; polygons
// keep ring order. `properties` is the feature's property dict verbatim.
struct PreparedFeature {
    std::string feature_id;
    std::string kind;  // "point" | "line" | "polygon"
    std::vector<std::vector<std::pair<double, double>>> parts;
    Extent bbox{0, 0, 0, 0};
    Json properties = Json::object();
};

// Flat concatenated layer geometry (Python _PreparedLayer parity): the
// frame performs a handful of vectorised passes over the whole layer
// instead of per-part transforms. Feature order == draw order.
struct PreparedLayer {
    std::vector<PreparedFeature> features;
    std::int64_t revision = 0;
    std::string layer_type = "vector";
    // Flat (x,y) pairs of every path vertex.
    std::vector<double> path_xy;
    // Part boundaries into path_xy (size = parts + 1; last == vertex count).
    std::vector<std::size_t> path_offsets;
    // Feature index per path part.
    std::vector<int> path_feature;
    // Polygon parts are rings (OddEvenFill semantics).
    std::vector<bool> path_is_ring;
    // Flat (x,y) pairs of every point vertex + owning feature index.
    std::vector<double> point_xy;
    std::vector<int> point_feature;
    bool has_points = false;
    bool has_paths = false;

    std::size_t vertex_count() const {
        return path_xy.size() / 2 + point_xy.size() / 2;
    }
};

// CRS reprojection seam — Python's make_crs_transformer (pyproj
// always_xy). The factory maps (layer_crs, project_crs) to a vertex
// transform; returns nullptr for the identity case, throws
// std::invalid_argument when either name is unresolvable or no transform
// engine is wired (the pyproj-missing degradation → crs_warnings path is
// identical). Install via set_crs_transformer_factory.
using CrsTransformer = std::function<void(double& x, double& y)>;
using CrsTransformerFactory =
    std::function<CrsTransformer(const std::string& layer_crs,
                                 const std::string& project_crs)>;

class FallbackMapRenderBackend final : public MapRenderBackend,
                                       public VectorPaintCapableBackend {
public:
    explicit FallbackMapRenderBackend(bool threaded = false);
    ~FallbackMapRenderBackend() override;

    std::string backend_name() const override { return "fallback"; }

    std::uint64_t request_render() override;
    std::optional<RenderFrame> take_completed_frame() override;
    bool render_active() const override;
    void cancel_render() override;
    void shutdown() override;
    RenderFrame render_sync() override;

    // VectorPaintCapableBackend parity: paint the current composition into
    // any QPaintDevice target (QSvgGenerator/QPdfWriter vector exports go
    // through the same pipeline as the screen frame).
    bool render_to_painter(QPainter& painter, int width, int height,
                           double dpi) override;

    // Public per-frame warnings (#1051): layers whose CRS differs from the
    // project CRS and could not be reprojected. Rebuilt by every
    // composition paint.
    std::vector<std::string> crs_warnings() const {
        std::lock_guard<std::mutex> lock(diag_mutex_);
        return crs_warnings_;
    }

    // render_diagnostics parity — counters describing caches, culling,
    // LOD (a locked copy; the worker thread owns the live map).
    std::map<std::string, double> render_diagnostics() const;
    // Legacy counter surface (map-perf #461 regression tests):
    // rasterization_count / frame_cache_hits / strip_reuse_count(0) /
    // culled_feature_count.
    std::map<std::string, double> fallback_diagnostics() const;

    // CRS transform engine install (host wires PROJ/QGIS; uninstalled →
    // the pyproj-missing degradation path).
    static void set_crs_transformer_factory(CrsTransformerFactory factory);

    // Facies pattern tile directory (FACIES_PATTERN_DIR parity). Missing
    // dir → no pattern brushes, identical to absent assets.
    static void set_facies_pattern_dir(const QString& dir);

private:
    struct LabelSpec {
        double x = 0.0, y = 0.0;
        std::string text;
        double size = 9.0;
        bool bold = false;
        std::string family;
        std::string color;
        std::string halo_color;
        double halo_width = 0.0;
        double dpi_scale = 1.0;
    };

    // _frame_key() parity — one comparable record per frame.
    struct LayerKey {
        std::string id;
        std::string layer_type;
        std::int64_t data_revision = 0;
        std::int64_t style_revision = 0;
        bool visible = true;
        double opacity = 1.0;
        std::optional<std::pair<double, double>> scale_range;
        std::string crs;
        bool operator==(const LayerKey&) const = default;
    };
    struct FrameKey {
        Extent extent;
        int width = 1, height = 1;
        double dpi = 96.0;
        std::vector<LayerKey> layers;
        std::string project_crs;
        bool operator==(const FrameKey&) const = default;
    };

    struct RasterizeResult {
        QImage image;
        FrameKey key;
        std::vector<LabelSpec> specs;
        double elapsed_ms = 0.0;
    };

    // drop the pending completed frame (base cancel_render's completed_
    // reset, reached from request_render without the generation bump).
    void cancel_completed() { MapRenderBackend::cancel_render(); }

    FrameKey frame_key() const;
    const RenderFrame* cached_frame() const;
    std::shared_ptr<const PreparedLayer> prepared_layer(
        const MapLayerSnapshot& layer);
    std::shared_ptr<const PreparedLayer> reprojected_prepared(
        std::shared_ptr<const PreparedLayer> prepared,
        const MapLayerSnapshot& layer);
    std::shared_ptr<const PreparedLayer> lod_prepared(
        std::shared_ptr<const PreparedLayer> prepared,
        const MapLayerSnapshot& layer, double mupp);

    void prepare_layers();
    RasterizeResult rasterize_frame_offthread();
    RenderFrame finalize_frame(RasterizeResult&& result,
                               std::uint64_t generation);
    void maybe_submit_pending();

    double scale_denominator(int width) const;
    void paint_composition(QPainter& painter, int width, int height,
                           double dpi, std::vector<LabelSpec>* label_specs);
    void warn_raster_unprojected(const MapLayerSnapshot& layer,
                                 const std::string& project_crs);
    void paint_vector_layer(QPainter& painter,
                            const MapLayerSnapshot& layer,
                            double xmin, double ymin, double span_x,
                            double span_y, int width, int height,
                            double dpi_scale,
                            std::vector<LabelSpec>* label_specs);
    void paint_layer_paths(QPainter& painter, const PreparedLayer& prepared,
                           const std::vector<bool>& visible_features,
                           const cartography::VectorStyle& style,
                           double xmin, double ymin, double scale_x,
                           double scale_y, int width, int height,
                           double marker_radius, double stroke_width,
                           bool transparent_fill, const QColor& fill,
                           double dpi_scale);
    void paint_layer_points(QPainter& painter, const PreparedLayer& prepared,
                            const std::vector<bool>& visible_features,
                            const cartography::VectorStyle& style,
                            double xmin, double ymin, double scale_x,
                            double scale_y, int width, int height,
                            double marker_radius, double stroke_width,
                            bool transparent_fill, const QColor& fill,
                            double dpi_scale,
                            std::vector<LabelSpec>* label_specs);
    void draw_dots(QPainter& painter,
                   const std::vector<QPointF>& points, double radius);
    void draw_point_symbol(QPainter& painter, const QPointF& centre,
                           double radius, cartography::MarkerSymbol marker);
    void draw_label_text(QPainter& painter, const QPointF& anchor,
                         const PreparedFeature& feature,
                         const std::string& field,
                         const cartography::VectorStyle& style,
                         double dpi_scale,
                         std::vector<LabelSpec>* label_specs);
    void paint_label_specs(QPainter& painter,
                           const std::vector<LabelSpec>& specs);
    // scalar_grid + raster_source share the image path: the C++ contract
    // resolves the Python rasterize() payload into source_path upstream.
    void draw_image_layer(QPainter& painter, const MapLayerSnapshot& layer);
    std::optional<QPointF> screen_point(double x, double y) const;

    static QColor color_of(const std::string& value, const char* fallback);

    void diag_add(const char* key, double delta);
    void diag_set(const char* key, double value);

    bool threaded_ = false;
    int vertex_budget_ = 150000;
    bool vector_lod_disabled_ = false;
    bool facies_batch_disabled_ = false;

    std::optional<RenderFrame> completed_override_;
    std::optional<std::pair<FrameKey, RenderFrame>> frame_cache_;

    mutable std::mutex prepared_mutex_;
    using PreparedKey = std::int64_t;
    LatestRevisionCache<std::string, PreparedKey,
                        std::shared_ptr<const PreparedLayer>>
        prepared_;
    using ReprojectKey =
        std::tuple<std::int64_t, std::string, std::string>;
    LatestRevisionCache<std::string, ReprojectKey,
                        std::shared_ptr<const PreparedLayer>>
        reprojected_;
    using LodKey = std::tuple<std::int64_t, double, std::string>;
    LatestRevisionCache<std::string, LodKey,
                        std::shared_ptr<const PreparedLayer>>
        lod_cache_;
    struct ScalarImageEntry {
        QImage image;
    };
    using ScalarKey =
        std::tuple<std::string, std::int64_t, std::int64_t>;
    LatestRevisionCache<std::string, ScalarKey, ScalarImageEntry>
        scalar_images_;

    std::vector<std::string> crs_warnings_;
    std::map<std::string, double> diagnostics_;
    // Guards diagnostics_ + crs_warnings_ (mutated on the render worker).
    mutable std::mutex diag_mutex_;

    // Threaded render state — ThreadPoolExecutor(max_workers=1) parity:
    // a persistent single worker thread; submitted jobs serialize;
    // dropping the packaged_task future detaches the result (never
    // blocks — std::async futures would join on destruction, breaking
    // cancel_render's "cannot be interrupted" contract).
    void ensure_worker();
    void worker_loop();
    void submit_render_job();

    mutable std::mutex worker_mutex_;
    std::condition_variable worker_cv_;
    std::deque<std::packaged_task<RasterizeResult()>> worker_queue_;
    std::thread worker_;
    bool worker_started_ = false;
    bool worker_stop_ = false;
    std::optional<std::future<RasterizeResult>> render_future_;
    std::optional<std::uint64_t> render_generation_;
    bool render_pending_ = false;

    class Impl;  // facies pattern brush cache (QtSvg)
    std::unique_ptr<Impl> facies_patterns_;
};

// shutdown_live_fallback_backends parity: join every live fallback's
// executor (test teardown safety).
void shutdown_live_fallback_backends();

// Install the fallback factory into the backend registry (is_qgis=false —
// the prefer_qgis=false path picks it; Python create_map_render_backend
// order parity puts it behind any registered QGIS factory).
void install_fallback_backend_factory();

}  // namespace pwb::ui_canvas::qt
