// UI-15 Qt widget smoke (offscreen): UnifiedMapCanvas +
// MapLayerPropertiesDialog + MapExportWorker + PreviewSettingsDialog.
// No QGIS — the canvas consumes a synchronous fake backend and a fake
// scalar source; export degrades honestly without a QGIS factory.
// (NativeMapCanvas / NativeLayerTree / NativeRasterRequestController —
// the zero-consumer prototype canvas stack — retired with the
// QGIS-native shell convergence.)

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

#include <pwb/ui_canvas/export_core.hpp>
#include <pwb/ui_canvas/map_render_backend.hpp>
#include <pwb/ui_canvas/qt/map_export_worker.hpp>
#include <pwb/ui_canvas/qt/map_layer_properties.hpp>
#include <pwb/ui_canvas/qt/preview_settings_dialog.hpp>
#include <pwb/ui_canvas/qt/qt_meta.hpp>
#include <pwb/ui_canvas/qt/unified_map_canvas.hpp>
#include <pwb/ui_pages_preview/qt/preview_settings_panel.hpp>

using namespace pwb::ui_canvas;

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


int main(int argc, char** argv) {
    QApplication app(argc, argv);
    qRegisterMetaType<pwb::ui_canvas::Json>("pwb::ui_canvas::Json");
    qRegisterMetaType<pwb::ui_canvas::RenderFrame>(
        "pwb::ui_canvas::RenderFrame");
    qRegisterMetaType<std::optional<std::string>>(
        "std::optional<std::string>");
    qRegisterMetaType<std::pair<double, double>>(
        "std::pair<double,double>");
    return pwb_test::run_all();
}
