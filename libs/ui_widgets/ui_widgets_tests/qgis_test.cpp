// UI-02 — QGIS stack tests: run only where the vendored SDK was
// admitted (same runtime closure as tests/cpp/platform — the
// ENVIRONMENT_MODIFICATION prepends the vendor lib + Qt lib paths).
//
// Covers the qgis_stack ports that admit a native surface:
//   StackEvents       — bridge callbacks requeued through
//                       singleShot(0, ctx) (never inside the canvas
//                       call stack; context destruction cancels).
//   MirrorSnapshot    — vector upsert into a real QgsProject + honest
//                       failure diagnostics for unsupported types.
//   QgisDisplayCanvas — extent history + coordinate conversion +
//                       backend status (read-only QgsMapCanvas).
//   QgisCanvasShim    — extent history + shutdown discipline.

#include <qgsapplication.h>
#include <qgsmapcanvas.h>
#include <qgsproject.h>
#include <qgsrectangle.h>
#include <qgsvectorlayer.h>

#include <QApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>

#include <cmath>
#include <functional>

#include "pwb/qgis/map_session.hpp"
#include "pwb/qgis/qgis_runtime.hpp"
#include "pwb/ui_widgets/qgis/canvas_shim.hpp"
#include "pwb/ui_widgets/qgis/display_canvas.hpp"
#include "pwb/ui_widgets/qgis/mirror_snapshot.hpp"
#include "pwb/ui_widgets/qgis/stack_events.hpp"

#include "ui_widgets_test.hpp"

using namespace pwb::ui_widgets::qgis;

#define CHECK_QSTR(actual, expected)                                          \
    ::pwb_test::check_eq(((actual)).toStdString(), ((expected)).toStdString(), \
                         __FILE__, __LINE__)

namespace {

// GeoJSON point feature dict (mirror feature vocabulary).
QVariantMap point_feature(double x, double y, const QVariantMap& props = {}) {
    QVariantMap geometry{{"type", "Point"},
                         {"coordinates", QVariantList{x, y}}};
    QVariantMap feature{{"type", "Feature"}, {"geometry", geometry},
                        {"properties", props}};
    return feature;
}

// Pump the event loop until predicate or deadline (ms).
bool spin_until(const std::function<bool()>& pred, int timeout_ms = 3000) {
    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed() < timeout_ms) {
        QApplication::processEvents(QEventLoop::AllEvents, 20);
        if (pred()) return true;
    }
    return pred();
}

}  // namespace

// ------------------------------------------------------------ StackEvents
PWB_TEST(stack_events_requeues_canvas_signals) {
    QgsMapCanvas canvas;
    canvas.resize(400, 300);
    StackEvents events;
    events.attach(&canvas);

    bool synchronous_fire = false;
    bool delivered = false;
    QObject::connect(&events, &StackEvents::extent_changed,
                     [&](double, double, double, double) {
                         delivered = true;
                     });
    // The requeued delivery must not fire inside this call stack —
    // only after the event loop turns.
    canvas.setExtent(QgsRectangle(0, 0, 10, 10));
    canvas.refresh();
    synchronous_fire = delivered;
    CHECK(!synchronous_fire);  // deferred, not in-stack
    CHECK(spin_until([&delivered] { return delivered; }));
}

PWB_TEST(stack_events_context_destruction_cancels) {
    QgsMapCanvas canvas;
    canvas.resize(400, 300);
    bool delivered = false;
    {
        StackEvents events;
        events.attach(&canvas);
        QObject::connect(&events, &StackEvents::extent_changed,
                         [&](double, double, double, double) {
                             delivered = true;
                         });
        canvas.setExtent(QgsRectangle(1, 1, 20, 20));
        canvas.refresh();
        // events destroyed here — queued delivery must cancel (#951).
    }
    QTimer::singleShot(100, qApp, [] {});
    spin_until([] { return false; }, 200);
    CHECK(!delivered);
}

// ------------------------------------------------------------ MirrorSnapshot
PWB_TEST(mirror_upserts_vector_and_reports_failures) {
    QgsProject project;
    MirrorLedger ledger;

    MirrorLayerSpec layer;
    layer.id = "doc.layer1";
    layer.name = "点位层";
    layer.crs = "EPSG:4326";
    layer.metadata["geometry_kind"] = "point";
    layer.features = {point_feature(1.0, 2.0, {{"name", "W1"}}),
                      point_feature(3.0, 4.0, {{"name", "W2"}})};

    MirrorSnapshot snapshot;
    snapshot.project_crs = "EPSG:4326";
    snapshot.layers = {layer};

    MirrorResult result =
        mirror_snapshot_to_project(project, snapshot, MirrorOptions{}, ledger);
    CHECK(result.failures.isEmpty());
    CHECK_EQ(result.mirrored_qgis_ids.size(), 1);
    CHECK_EQ(project.mapLayers().size(), 1);
    QgsMapLayer* published = project.mapLayer(result.mirrored_qgis_ids[0]);
    CHECK(published != nullptr);
    CHECK(published->isValid());
    CHECK_QSTR(published->name(), QString("点位层"));

    // Same snapshot again -> no-op reuse (ledger tokens identical; the
    // mirrored id stays the same object).
    MirrorResult again =
        mirror_snapshot_to_project(project, snapshot, MirrorOptions{}, ledger);
    CHECK(again.failures.isEmpty());
    CHECK_EQ(again.mirrored_qgis_ids.size(), 1);
    CHECK_QSTR(again.mirrored_qgis_ids[0], result.mirrored_qgis_ids[0]);
    CHECK_EQ(project.mapLayers().size(), 1);

    // Unsupported layer types produce a diagnostic, never silent drops.
    MirrorLayerSpec raster;
    raster.id = "doc.raster";
    raster.name = "栅格";
    raster.layer_type = "raster_source";
    // No source_path -> honest failure either way.
    MirrorSnapshot bad;
    bad.project_crs = "EPSG:4326";
    bad.layers = {raster};
    MirrorResult failed =
        mirror_snapshot_to_project(project, bad, MirrorOptions{}, ledger);
    CHECK(!failed.failures.isEmpty());
    CHECK(failed.failures[0].contains("doc.raster"));
}

// -------------------------------------------------------- QgisDisplayCanvas
PWB_TEST(display_canvas_extent_history_and_conversion) {
    QgisDisplayCanvas canvas;
    canvas.resize(640, 480);
    canvas.show();
    QApplication::processEvents();

    CHECK_QSTR(canvas.backend().backend_name, QString("qgis"));
    // QgsMapCanvas preserves the widget aspect (640x480 = 4:3) — extents
    // chosen at the same aspect survive unadjusted.
    canvas.set_extent({0, 0, 80, 60});
    canvas.set_extent({10, 10, 50, 40});
    const auto extent = canvas.view_extent();
    // QgsMapCanvas adjusts the requested rect by pixel quantization
    // (~0.1%); assert the semantic center + span, not bit-exact edges.
    CHECK(std::abs((extent[0] + extent[2]) / 2.0 - 30.0) < 1.0);
    CHECK(std::abs((extent[2] - extent[0]) - 40.0) < 1.0);
    CHECK(std::abs((extent[3] - extent[1]) - 30.0) < 1.0);

    // History navigation. The canvas's own initial extentsChanged is
    // also recorded (Python _record_extent parity — every real extent
    // change enters history), so the walk length is >= 1, not fixed.
    CHECK(canvas.can_previous_extent());
    CHECK(!canvas.can_next_extent());
    CHECK(canvas.previous_extent());
    const auto prev = canvas.view_extent();
    CHECK(std::abs((prev[0] + prev[2]) / 2.0 - 40.0) < 1.0);
    CHECK(std::abs((prev[2] - prev[0]) - 80.0) < 1.0);
    // Walk to the oldest recorded extent; it must terminate.
    int steps_back = 0;
    while (canvas.previous_extent() && steps_back < 16) ++steps_back;
    CHECK(!canvas.can_previous_extent());
    // And forward again to the newest extent.
    int steps_fwd = 0;
    while (canvas.next_extent() && steps_fwd < 16) ++steps_fwd;
    CHECK(!canvas.can_next_extent());
    const auto newest = canvas.view_extent();
    CHECK(std::abs((newest[0] + newest[2]) / 2.0 - 30.0) < 1.0);

    // Coordinate conversion round-trip.
    const auto center = canvas.screen_to_map({320.0, 240.0});
    const auto back = canvas.map_to_screen(center);
    CHECK(std::abs(back.x() - 320.0) < 2.0);
    CHECK(std::abs(back.y() - 240.0) < 2.0);
    CHECK(canvas.map_units_per_pixel() > 0.0);

    canvas.shutdown();
}

// ----------------------------------------------------------- QgisCanvasShim
PWB_TEST(canvas_shim_extent_history_and_shutdown) {
    auto* shim = new QgisCanvasShim();
    shim->resize(640, 480);
    shim->show();
    QApplication::processEvents();

    // Same-aspect extents (640x480 canvas -> 4:3); pixel-quantization
    // adjusts edges ~0.1% — assert center + span semantics.
    shim->set_extent({0, 0, 80, 60});
    shim->set_extent({20, 20, 60, 50});
    const auto extent = shim->view_extent();
    CHECK(std::abs((extent[0] + extent[2]) / 2.0 - 40.0) < 1.0);
    CHECK(std::abs((extent[2] - extent[0]) - 40.0) < 1.0);
    CHECK(shim->can_previous_extent());
    CHECK(shim->previous_extent());
    const auto prev_e = shim->view_extent();
    CHECK(std::abs((prev_e[0] + prev_e[2]) / 2.0 - 40.0) < 1.0);
    CHECK(std::abs((prev_e[2] - prev_e[0]) - 80.0) < 1.0);
    int shim_steps = 0;
    while (shim->next_extent() && shim_steps < 16) ++shim_steps;
    CHECK(!shim->can_next_extent());
    const auto next_e = shim->view_extent();
    CHECK(std::abs((next_e[0] + next_e[2]) / 2.0 - 40.0) < 1.0);

    // Coordinate conversion is defined over the canvas.
    const auto pt = shim->screen_to_map({320.0, 240.0});
    const auto back = shim->map_to_screen(pt);
    CHECK(std::abs(back.first - 320.0) < 2.0);

    // Snapping config accepts the Python payload vocabulary.
    QVariantMap snapping{{"enabled", true}, {"mode", "all_layers"},
                         {"tolerance", 12.0}, {"units", "pixels"},
                         {"types", QStringList{"vertex", "segment"}}};
    shim->set_snapping_config(snapping);

    // Orderly teardown: shutdown() is idempotent and marks the shim.
    shim->shutdown();
    CHECK(shim->is_shutdown());
    shim->shutdown();
    delete shim;
}

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();
    return pwb_test::run_all();
}
