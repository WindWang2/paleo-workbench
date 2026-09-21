// mapping/map_render_backend.py FallbackMapRenderBackend — native port
// smoke. Offscreen Qt; deterministic assertions on frame pixels,
// cache behaviour, factory selection, vector-lod math and the
// revision cache. Python-source parity anchors are cited inline.

#include <QApplication>
#include <QImage>
#include <QPainter>
#include <QTemporaryDir>
#include <QThread>

#include <cmath>
#include <memory>
#include <string>

#include "ui_canvas_test.hpp"

#include <pwb/ui_canvas/qt/fallback_map_backend.hpp>
#include <pwb/ui_canvas/revision_cache.hpp>
#include <pwb/ui_canvas/vector_lod.hpp>

namespace {

using namespace pwb::ui_canvas;
using namespace pwb::ui_canvas::qt;

std::size_t non_white_pixels(const RenderFrame& frame) {
    std::size_t count = 0;
    for (int y = 0; y < frame.height; ++y) {
        for (int x = 0; x < frame.width; ++x) {
            const std::uint8_t* px =
                frame.rgba.data() + y * frame.stride + x * 4;
            if (px[0] != 255 || px[1] != 255 || px[2] != 255) ++count;
        }
    }
    return count;
}

MapLayerSnapshot point_layer(const std::string& id, double x, double y) {
    MapLayerSnapshot layer;
    layer.id = id;
    layer.name = id;
    layer.layer_type = "vector";
    layer.crs = "EPSG:4326";
    layer.data_revision = 1;
    layer.features = Json::array({Json::object(
        {{"id", "f1"},
         {"geometry",
          Json::object({{"type", "Point"},
                        {"coordinates", Json::array({x, y})}})},
         {"properties", Json::object()}})});
    layer.style = Json::object({{"marker_size", 12.0},
                                {"fill", "#e02020"},
                                {"stroke", "#202020"},
                                {"stroke_width", 1.0},
                                {"marker", "circle"}});
    return layer;
}

MapRenderSnapshot point_snapshot() {
    MapRenderSnapshot snapshot;
    snapshot.project_crs = "EPSG:4326";
    snapshot.layers.push_back(point_layer("points", 0.5, 0.5));
    return snapshot;
}

std::shared_ptr<FallbackMapRenderBackend> make_backend(
    const MapRenderSnapshot& snapshot) {
    auto backend = std::make_shared<FallbackMapRenderBackend>();
    backend->initialize();
    backend->set_layer_snapshot(snapshot);
    backend->set_extent(Extent{0.0, 0.0, 1.0, 1.0});
    backend->set_output_size(64, 64);
    backend->set_dpi(96.0);
    return backend;
}

}  // namespace

PWB_TEST(factory_returns_fallback_backend) {
    install_fallback_backend_factory();
    auto backend = create_map_render_backend(/*prefer_qgis=*/false);
    CHECK(backend != nullptr);
    CHECK_EQ(backend->backend_name(), std::string("fallback"));
}

PWB_TEST(render_sync_draws_point) {
    auto backend = make_backend(point_snapshot());
    const RenderFrame frame = backend->render_sync();
    CHECK_EQ(frame.width, 64);
    CHECK_EQ(frame.height, 64);
    CHECK_EQ(static_cast<long long>(frame.stride),
             static_cast<long long>(frame.width) * 4);
    CHECK_EQ(static_cast<long long>(frame.rgba.size()),
             static_cast<long long>(frame.stride) * frame.height);
    CHECK(non_white_pixels(frame) > 0);
}

PWB_TEST(render_sync_uses_frame_cache) {
    auto backend = make_backend(point_snapshot());
    const RenderFrame first = backend->render_sync();
    const RenderFrame second = backend->render_sync();
    CHECK_EQ(static_cast<long long>(first.generation),
             static_cast<long long>(second.generation) - 1);
    const auto diag = backend->render_diagnostics();
    const auto it = diag.find("frames_from_cache");
    CHECK(it != diag.end());
    CHECK_EQ(static_cast<long long>(it->second), 1);
}

PWB_TEST(render_sync_after_revision_change_redraws) {
    auto backend = make_backend(point_snapshot());
    backend->render_sync();
    MapRenderSnapshot snapshot = point_snapshot();
    snapshot.layers[0].data_revision = 2;
    backend->set_layer_snapshot(snapshot);
    const RenderFrame frame = backend->render_sync();
    CHECK(non_white_pixels(frame) > 0);
    const auto diag = backend->render_diagnostics();
    const auto it = diag.find("frames_from_cache");
    CHECK_EQ(static_cast<long long>(it->second), 0);
}

PWB_TEST(polygon_feature_fills_extent) {
    MapRenderSnapshot snapshot;
    snapshot.project_crs = "EPSG:4326";
    MapLayerSnapshot layer;
    layer.id = "poly";
    layer.name = "poly";
    layer.layer_type = "vector";
    layer.data_revision = 1;
    layer.features = Json::array({Json::object(
        {{"id", "p1"},
         {"geometry",
          Json::object({{"type", "Polygon"},
                        {"coordinates",
                         Json::array({Json::array(
                             {Json::array({0.1, 0.1}),
                              Json::array({0.9, 0.1}),
                              Json::array({0.9, 0.9}),
                              Json::array({0.1, 0.9}),
                              Json::array({0.1, 0.1})})})}})},
         {"properties", Json::object()}})});
    layer.style = Json::object({{"fill", "#e02020"},
                                {"stroke", "#202020"},
                                {"stroke_width", 1.0}});
    snapshot.layers.push_back(layer);
    auto backend = make_backend(snapshot);
    const RenderFrame frame = backend->render_sync();
    // A polygon spanning 80% of the view must cover well over half.
    CHECK(non_white_pixels(frame) > 64 * 64 / 2);
}

PWB_TEST(invisible_layer_renders_blank) {
    MapRenderSnapshot snapshot = point_snapshot();
    snapshot.layers[0].visible = false;
    auto backend = make_backend(snapshot);
    const RenderFrame frame = backend->render_sync();
    CHECK_EQ(non_white_pixels(frame), 0);
}

PWB_TEST(render_to_painter_paints_vector_body) {
    auto backend = make_backend(point_snapshot());
    QImage target(64, 64, QImage::Format_ARGB32);
    target.fill(Qt::transparent);
    QPainter painter(&target);
    CHECK(backend->render_to_painter(painter, 64, 64, 96.0));
    painter.end();
    std::size_t painted = 0;
    for (int y = 0; y < 64; ++y) {
        for (int x = 0; x < 64; ++x) {
            const QColor c = target.pixelColor(x, y);
            if (c.alpha() > 0 &&
                (c.red() != 255 || c.green() != 255 ||
                 c.blue() != 255)) {
                ++painted;
            }
        }
    }
    CHECK(painted > 0);
}

PWB_TEST(raster_source_layer_draws_image) {
    QTemporaryDir dir;
    CHECK(dir.isValid());
    const QString path = dir.filePath("tile.png");
    QImage tile(8, 8, QImage::Format_ARGB32);
    tile.fill(QColor("#3080ff"));
    CHECK(tile.save(path));
    MapRenderSnapshot snapshot;
    snapshot.project_crs = "EPSG:4326";
    MapLayerSnapshot layer;
    layer.id = "ras";
    layer.name = "ras";
    layer.layer_type = "raster_source";
    layer.data_revision = 1;
    layer.extent = Extent{0.0, 0.0, 1.0, 1.0};
    layer.source_path = path.toStdString();
    snapshot.layers.push_back(layer);
    auto backend = make_backend(snapshot);
    const RenderFrame frame = backend->render_sync();
    CHECK(non_white_pixels(frame) > 64 * 64 / 2);
}

PWB_TEST(threaded_request_delivers_frame) {
    auto backend =
        std::make_shared<FallbackMapRenderBackend>(/*threaded=*/true);
    backend->initialize();
    backend->set_layer_snapshot(point_snapshot());
    backend->set_extent(Extent{0.0, 0.0, 1.0, 1.0});
    backend->set_output_size(64, 64);
    backend->set_dpi(96.0);
    const std::uint64_t generation = backend->request_render();
    std::optional<RenderFrame> frame;
    for (int i = 0; i < 500 && !frame.has_value(); ++i) {
        frame = backend->take_completed_frame();
        if (!frame.has_value()) QThread::msleep(2);
    }
    CHECK(frame.has_value());
    if (frame.has_value()) {
        CHECK_EQ(static_cast<long long>(frame->generation),
                 static_cast<long long>(generation));
        CHECK(non_white_pixels(*frame) > 0);
    }
    backend->shutdown();
}

PWB_TEST(revision_cache_serves_exact_revision_only) {
    LatestRevisionCache<std::string, std::int64_t, int> cache;
    cache.store("a", 3, 42);
    CHECK(cache.get("a", 3) != nullptr);
    CHECK_EQ(*cache.get("a", 3), 42);
    CHECK(cache.get("a", 2) == nullptr);
    CHECK(cache.get("b", 3) == nullptr);
    cache.store("a", 4, 7);
    CHECK(cache.get("a", 3) == nullptr);
    CHECK_EQ(*cache.get("a", 4), 7);
    cache.prune(std::vector<std::string>{"a"});
    CHECK(cache.get("a", 4) != nullptr);
    cache.prune(std::vector<std::string>{});
    CHECK(cache.get("a", 4) == nullptr);
}

PWB_TEST(vector_lod_scale_bucket_quantises_to_pow2) {
    CHECK(vector_lod::scale_bucket_mupp(0.0) == 0.0);
    CHECK(vector_lod::scale_bucket_mupp(-1.0) == 0.0);
    CHECK(vector_lod::scale_bucket_mupp(3.0) == 2.0);
    CHECK(vector_lod::scale_bucket_mupp(2.0) == 2.0);
    CHECK(vector_lod::scale_bucket_mupp(0.75) == 0.5);
    // Non-finite inputs quantise to 0 (math.isfinite guard parity).
    CHECK(vector_lod::scale_bucket_mupp(
              std::numeric_limits<double>::infinity()) == 0.0);
    CHECK(vector_lod::scale_bucket_mupp(
              std::numeric_limits<double>::quiet_NaN()) == 0.0);
}

PWB_TEST(vector_lod_keep_mask_preserves_endpoints) {
    // One open line of 8 collinear vertices: middle vertices sit below
    // tolerance; endpoints stay anchored.
    std::vector<double> xs{0, 1, 2, 3, 4, 5, 6, 7};
    std::vector<double> ys{0, 0, 0, 0, 0, 0, 0, 0};
    std::vector<std::size_t> starts{0};
    const auto keep =
        vector_lod::visvalingam_keep_mask(xs, ys, starts, {false}, 1.0);
    CHECK_EQ(keep.size(), xs.size());
    CHECK(keep[0]);
    CHECK(keep[xs.size() - 1]);
    // Identity when tolerance <= 0.
    const auto all =
        vector_lod::visvalingam_keep_mask(xs, ys, starts, {false}, 0.0);
    for (bool k : all) CHECK(k);
}

PWB_TEST(vector_lod_anchor_extrema_kept) {
    // A spike mid-part: the peak is a coordinate extremum and must
    // survive even when its neighbours collapse.
    std::vector<double> xs{0, 1, 2, 3, 4, 5, 6};
    std::vector<double> ys{0, 0, 0, 5, 0, 0, 0};
    std::vector<std::size_t> starts{0};
    const auto keep = vector_lod::visvalingam_keep_mask(
        xs, ys, starts, {false}, 0.01);
    CHECK(keep[0]);
    CHECK(keep[3]);
    CHECK(keep[6]);
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    return pwb_test::run_all();
}
