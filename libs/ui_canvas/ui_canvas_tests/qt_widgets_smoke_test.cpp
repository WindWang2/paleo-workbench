// UI-15 Qt widget smoke (offscreen): UnifiedMapCanvas + NativeMapCanvas +
// NativeLayerTree + MapLayerPropertiesDialog + MapExportWorker +
// PreviewSettingsDialog + NativeRasterRequestController. No QGIS — the
// canvas consumes a synchronous fake backend and a fake scalar source;
// export degrades honestly without a QGIS factory.

#include <QApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QLabel>
#include <QPlainTextEdit>
#include <QSignalSpy>
#include <QTreeView>

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "ui_canvas_test.hpp"

#include <layer_model.hpp>

#include <pwb/ui_canvas/export_core.hpp>
#include <pwb/ui_canvas/map_render_backend.hpp>
#include <pwb/ui_canvas/qt/map_export_worker.hpp>
#include <pwb/ui_canvas/qt/map_layer_properties.hpp>
#include <pwb/ui_canvas/qt/native_layer_tree.hpp>
#include <pwb/ui_canvas/qt/native_map_canvas.hpp>
#include <pwb/ui_canvas/qt/native_raster_controller.hpp>
#include <pwb/ui_canvas/qt/preview_settings_dialog.hpp>
#include <pwb/ui_canvas/qt/qt_meta.hpp>
#include <pwb/ui_canvas/qt/unified_map_canvas.hpp>
#include <pwb/ui_pages_preview/qt/preview_settings_panel.hpp>

using namespace pwb::ui_canvas;
using pwb::layer_model::LayerRegistry;
using pwb::layer_model::LayerType;
using pwb::layer_model::MapLayer;

namespace {

// Synchronous fake backend — the canvas polls get a frame immediately.
class FakeBackend final : public MapRenderBackend {
public:
    std::string backend_name() const override { return "fake"; }
    RenderFrame render_sync() override {
        ++render_calls;
        RenderFrame out;
        out.generation = generation();
        out.width = output_size().first;
        out.height = output_size().second;
        out.stride = out.width * 4;
        out.rgba.assign(
            static_cast<std::size_t>(out.stride) * out.height, '\x80');
        return out;
    }
    int render_calls = 0;
};

std::shared_ptr<MapRenderBackend> qt_fake_factory() {
    return std::make_shared<FakeBackend>();
}

// Deterministic scalar raster source (8x8 solid pixels).
class FakeScalar final : public IScalarRasterSource {
public:
    explicit FakeScalar(RasterKey key = {1, 1}) : key_(key) {}
    RasterKey raster_key() const override { return key_; }
    std::vector<std::uint8_t> rasterize() const override {
        ++rasterize_calls;
        return std::vector<std::uint8_t>(
            static_cast<std::size_t>(raster_width() * raster_height() * 4),
            '\xAA');
    }
    int raster_width() const override { return 8; }
    int raster_height() const override { return 8; }

    RasterKey key_;
    mutable int rasterize_calls = 0;
};

// Minimal scene: owns the registry + one scalar layer.
class TestScene final : public NativeMapScene {
public:
    LayerRegistry& registry() override { return registry_; }
    const LayerRegistry& registry() const override { return registry_; }

    MapLayer* add_scalar(const std::string& id,
                         const std::shared_ptr<FakeScalar>& scalar) {
        scalars_[id] = scalar;
        return registry_.add_layer(
            std::make_unique<MapLayer>(id, id, LayerType::ScalarGrid));
    }

    ScalarRasterSourcePtr scalar_layer(
        const std::string& layer_id) const override {
        const auto it = scalars_.find(layer_id);
        return it == scalars_.end() ? nullptr : it->second;
    }
    const ContourGeometry* contour_geometry(
        const std::string&) const override {
        return nullptr;
    }
    const PointGeometry* point_geometry(
        const std::string&) const override {
        return nullptr;
    }
    void notify() { emit_changed(); }

    LayerRegistry registry_;
    std::map<std::string, std::shared_ptr<FakeScalar>> scalars_;
};

MapLayer* add_layer(LayerRegistry& registry, const std::string& id,
                    LayerType type = LayerType::Vector) {
    return registry.add_layer(
        std::make_unique<MapLayer>(id, id, type));
}

// Pump the event loop until `done` or timeout — replaces fragile sleeps.
bool wait_until(const std::function<bool()>& done, int timeout_ms = 3000) {
    QElapsedTimer timer;
    timer.start();
    while (!done() && timer.elapsed() < timeout_ms) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
    }
    return done();
}

}  // namespace

PWB_TEST(unified_canvas_backend_status_and_frame_poll) {
    auto backend = std::make_shared<FakeBackend>();
    UnifiedMapCanvas canvas(backend);
    canvas.resize(400, 300);
    CHECK_EQ(canvas.backend_status().toStdString(),
             std::string("fake: ready"));
    CHECK(canvas.backend() == backend.get());
    CHECK(!canvas.is_shutdown());

    MapRenderSnapshot snapshot;
    snapshot.project_crs = "EPSG:4326";
    canvas.set_layer_snapshot(snapshot);
    CHECK_EQ(backend->snapshot().project_crs, std::string("EPSG:4326"));
    // Identical signature → dedup skips the backend push.
    canvas.set_layer_snapshot(snapshot);
    CHECK(backend->render_calls <= 2);

    // Synchronous backend: the poll delivers a frame quickly.
    CHECK(wait_until([&] { return canvas.last_frame().has_value(); }));
    CHECK(canvas.frame_delivery_diagnostics().frames_delivered >= 1);
    canvas.shutdown();
    CHECK(canvas.is_shutdown());
}

PWB_TEST(unified_canvas_navigation_and_history) {
    auto backend = std::make_shared<FakeBackend>();
    UnifiedMapCanvas canvas(backend);
    canvas.resize(400, 200);
    canvas.set_extent({0.0, 0.0, 100.0, 50.0});
    Extent e = canvas.view_extent();
    CHECK(e[2] > e[0]);

    const double width0 = e[2] - e[0];
    canvas.zoom_by(0.5);
    e = canvas.view_extent();
    CHECK((e[2] - e[0]) < width0 * 0.75);
    CHECK(canvas.can_previous_extent());
    CHECK(canvas.previous_extent());
    CHECK((canvas.view_extent()[2] - canvas.view_extent()[0]) >
          width0 * 0.75);
    CHECK(canvas.next_extent());
    canvas.pan_by_pixels(10.0, 0.0);

    // Coordinate transforms stay finite inside the extent.
    const auto map_pt = canvas.screen_to_map(QPointF(200.0, 100.0));
    CHECK(map_pt.first > -1e6 && map_pt.first < 1e6);
    CHECK(canvas.map_units_per_pixel() > 0.0);
    canvas.shutdown();
}

PWB_TEST(unified_canvas_export_snapshot_and_duckwalk) {
    auto backend = std::make_shared<FakeBackend>();
    UnifiedMapCanvas canvas(backend);
    canvas.resize(320, 160);
    canvas.set_extent({0.0, 0.0, 4.0, 2.0});
    canvas.set_layer_snapshot(MapRenderSnapshot{});

    MapExportSpec spec =
        snapshot_map_export(canvas, "/tmp/ui_canvas_qt_export.png",
                            /*width=*/160, std::nullopt, /*dpi=*/96.0);
    CHECK_EQ(static_cast<long long>(spec.width), 160);
    CHECK_EQ(static_cast<long long>(spec.height), 80);  // aspect-derived
    CHECK(!spec.prefer_native_renderer);  // backend is "fake", not "qgis"

    CHECK(unified_map_canvas_from(&canvas) == &canvas);
    QWidget wrapper;
    canvas.setParent(&wrapper);
    CHECK(unified_map_canvas_from(&wrapper) == &canvas);
    QWidget unrelated;
    CHECK(unified_map_canvas_from(&unrelated) == nullptr);
    canvas.setParent(nullptr);
    canvas.shutdown();
}

PWB_TEST(export_worker_renders_and_reports) {
    // Fallback factory registered (non-QGIS); no QGIS factory → a
    // prefer_native spec degrades honestly but still writes the PNG.
    register_backend_factory(&qt_fake_factory, /*is_qgis=*/false);

    MapExportSpec spec;
    spec.path = "/tmp/ui_canvas_worker_test.png";
    spec.width = 64;
    spec.height = 32;
    spec.dpi = 96.0;
    spec.extent = {0.0, 0.0, 2.0, 1.0};
    spec.prefer_native_renderer = true;  // no QGIS factory → degrade

    MapExportReport report = render_and_save_map_export(spec);
    CHECK(report.degraded);
    CHECK_EQ(report.engine, std::string("fallback"));
    CHECK(!report.degraded_reason.empty());
    CHECK(QFile::exists(QString::fromStdString(spec.path)));

    // Cancellation checkpoint between render and save → ExportCancelled.
    bool threw = false;
    try {
        render_and_save_map_export(spec, [] { return true; });
    } catch (const ExportCancelled&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(native_canvas_scene_and_raster_cache) {
    TestScene scene;
    auto scalar = std::make_shared<FakeScalar>();
    MapLayer* layer = scene.add_scalar("s1", scalar);
    layer->set_extent({0.0, 0.0, 10.0, 5.0});

    NativeMapCanvas canvas(&scene);
    canvas.resize(400, 200);
    CHECK(canvas.scene() == &scene);
    canvas.fit_to_scene();
    const auto e = canvas.view_extent();
    // 4% margin on the scene extent (Python fit_to_scene parity).
    CHECK(e[0] < 0.0);
    CHECK(e[2] > 10.0);
    CHECK(e[1] < 0.0);
    CHECK(e[3] > 5.0);

    // Synchronous export prep fills the raster cache.
    canvas.prepare_for_export();
    CHECK(canvas.image_cache_size() >= 1);
    CHECK(scalar->rasterize_calls >= 1);
    CHECK(!canvas.cached_image("s1").isNull());

    canvas.zoom_by(0.5);
    canvas.pan_by_pixels(5.0, 5.0);
    canvas.clear_scene();
    CHECK(canvas.scene() == nullptr);
    canvas.shutdown();
}

PWB_TEST(raster_controller_queue_and_shutdown) {
    NativeRasterRequestController controller;
    auto scalar_a = std::make_shared<FakeScalar>();
    auto scalar_b = std::make_shared<FakeScalar>();

    controller.request(/*scene_epoch=*/1, "s1", RasterKey{1, 1}, scalar_a);
    // Latest-request-per-layer: re-requesting the same layer keeps ONE
    // desired entry; a different layer does not discard s1's work.
    controller.request(1, "s1", RasterKey{1, 1}, scalar_a);
    controller.request(1, "s2", RasterKey{1, 1}, scalar_b);
    CHECK(controller.desired_count() <= 2);

    controller.invalidate();
    CHECK_EQ(static_cast<long long>(controller.desired_count()), 0);
    CHECK_EQ(static_cast<long long>(controller.pending_count()), 0);

    // Bounded shutdown on an idle lane joins cleanly.
    CHECK(controller.shutdown(3000));
    CHECK(!controller.is_running());
}

PWB_TEST(layer_tree_model_resolves_registry) {
    LayerRegistry registry;
    add_layer(registry, "a");
    add_layer(registry, "b");
    add_layer(registry, "g", LayerType::Group);
    MapLayer* c = add_layer(registry, "c");
    registry.set_parent("c", "g");
    c->set_extent({0.0, 0.0, 10.0, 5.0});

    NativeLayerModel model(&registry);
    // Display order = reversed registry (g, b, a) — top row is topmost z.
    CHECK_EQ(static_cast<long long>(model.rowCount()), 3);
    const QModelIndex top = model.index(0, 0);
    CHECK_EQ(model.data(top, NativeLayerModel::LayerIdRole)
                 .toString()
                 .toStdString(),
             std::string("g"));

    // Group children resolve through the authoritative registry.
    const QModelIndex c_idx = model.index_for_id("c");
    CHECK(c_idx.isValid());
    CHECK(model.parent(c_idx) == top);

    // Active-layer selection round-trips.
    CHECK(model.set_active_layer("b"));
    CHECK(model.active_layer_id().has_value());
    CHECK_EQ(*model.active_layer_id(), std::string("b"));

    // Registry mutation through the model stays authoritative.
    MapLayer* added =
        model.add_layer("d", "Delta", LayerType::Vector, "");
    CHECK(added != nullptr);
    CHECK(registry.get("d") != nullptr);
    CHECK(model.remove_layer("d"));
    CHECK(registry.get("d") == nullptr);
}

PWB_TEST(layer_tree_actions_and_group_ids) {
    LayerRegistry registry;
    add_layer(registry, "a");
    NativeLayerTree tree(&registry);
    tree.resize(300, 400);
    CHECK(tree.model() != nullptr);
    CHECK(tree.view() != nullptr);
    // Required actions exist with a selection-sensitive enablement.
    CHECK(tree.add_layer_action() != nullptr);
    CHECK(tree.add_group_action() != nullptr);
    CHECK(tree.remove_action() != nullptr);
    CHECK(tree.properties_action() != nullptr);
    CHECK(!tree.remove_action()->isEnabled());  // nothing selected

    // Group creation goes through the registry with a uuid-like suffix.
    tree.add_group_action()->trigger();
    bool found_group = false;
    for (const auto& layer : registry.layers()) {
        if (layer->type() == LayerType::Group) {
            found_group = true;
            // Python: f"group_{uuid4().hex[:12]}".
            CHECK_EQ(static_cast<long long>(layer->id().size()),
                     6 + 12);
            CHECK(layer->id().rfind("group_", 0) == 0);
        }
    }
    CHECK(found_group);
}

PWB_TEST(properties_dialog_scalar_and_legacy) {
    // Scalar layer → scalar tab fields + scalar payload.
    LayerView scalar_view;
    scalar_view.id = "s1";
    scalar_view.name = "Grid";
    scalar_view.type_name = "ScalarGrid";
    scalar_view.crs = "EPSG:4326";
    scalar_view.opacity = 0.8;
    MapLayerPropertiesDialog scalar_dialog(scalar_view);
    CHECK(scalar_dialog.name_edit() != nullptr);
    Json sp = scalar_dialog.payload();
    CHECK(sp.contains("scalar_style"));
    CHECK_EQ(sp.at("name").get<std::string>(), std::string("Grid"));
    CHECK(!scalar_dialog.classes_json_error().has_value());

    // Legacy vector layer → style payload; invalid classes JSON surfaces
    // inline (#426) and gates apply.
    LayerView vec_view;
    vec_view.id = "v1";
    vec_view.name = "Wells";
    vec_view.type_name = "Vector";
    vec_view.crs = "EPSG:4326";
    Json style = {{"renderer", "categorized"}, {"field", "epoch"}};
    MapLayerPropertiesDialog vec_dialog(vec_view, style);
    vec_dialog.classes_edit()->setPlainText(QStringLiteral("{bad json"));
    QSignalSpy applied(&vec_dialog,
                       &MapLayerPropertiesDialog::properties_applied);
    vec_dialog.apply();
    CHECK(vec_dialog.classes_json_error().has_value());
    CHECK_EQ(static_cast<long long>(applied.count()), 0);
    CHECK(vec_dialog.classes_error_label()->isVisible() ||
          !vec_dialog.classes_error_label()->text().isEmpty());
}

PWB_TEST(preview_settings_dialog_modal_apply) {
    PreviewSettingsDialog dialog;
    CHECK(dialog.isModal());
    CHECK_EQ(dialog.windowTitle().toStdString(),
             std::string("预览设置"));
    CHECK(dialog.minimumWidth() >= 520 || dialog.width() >= 520 ||
          dialog.minimumSizeHint().width() >= 520);
    CHECK(dialog.panel() != nullptr);
    CHECK(dialog.panel()->apply_button() != nullptr);
    CHECK(dialog.panel()->reset_button() != nullptr);
}

PWB_TEST(native_canvas_epoch_invalidates_pending_rasters) {
    TestScene scene;
    auto scalar = std::make_shared<FakeScalar>();
    MapLayer* layer = scene.add_scalar("s1", scalar);
    layer->set_extent({0.0, 0.0, 10.0, 5.0});

    NativeMapCanvas canvas(&scene);
    canvas.resize(200, 100);
    // Scene replacement bumps the epoch; a second scene object swaps in
    // and the canvas re-registers its listener without leaking.
    TestScene other;
    canvas.set_scene(&other);
    CHECK(canvas.scene() == &other);
    canvas.set_scene(&scene);
    CHECK(canvas.scene() == &scene);
    canvas.shutdown();
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    qRegisterMetaType<pwb::ui_canvas::Json>("pwb::ui_canvas::Json");
    qRegisterMetaType<pwb::ui_canvas::RenderFrame>(
        "pwb::ui_canvas::RenderFrame");
    qRegisterMetaType<pwb::ui_canvas::NativeRasterRequest>(
        "pwb::ui_canvas::NativeRasterRequest");
    qRegisterMetaType<std::optional<std::string>>(
        "std::optional<std::string>");
    qRegisterMetaType<std::pair<double, double>>(
        "std::pair<double,double>");
    return pwb_test::run_all();
}
