// CONV-GEO3D widget smoke: offscreen construction, repeated open/close,
// invalid-geometry hardening, selection-through-click, camera pose
// round-trip and the honest GL screenshot path. Runs under
// QT_QPA_PLATFORM=offscreen; when no GL context can be created the GL
// dependent assertions honestly report the degraded mode instead of
// failing (mirroring the Python offscreen placeholder contract).

#include <QApplication>
#include <QKeyEvent>
#include <QPixmap>
#include <QTimer>

#include <cmath>
#include <cstdio>

#if defined(Q_OS_UNIX) && defined(PWB_GEO3D_HAVE_X11)
#include <X11/Xlib.h>
// Xlib defines these as macros; Qt's QEvent::Type enumerators use the
// same names.
#undef KeyPress
#undef KeyRelease
#undef FocusIn
#undef FocusOut
#undef None  // Xlib's None macro collides with enum names in pwb headers
#endif

#include <pwb/geo3d_viz/geo3d_viewport_widget.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>

using namespace pwb::geo3d_viz;
using pwb::geomodel::DomainObject;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::printf("FAIL: %s\n", what.c_str());
    }
}

DomainObject demo_well() {
    DomainObject well = pwb::geomodel::build_simplified_vertical_well(
        "W-1", {1.0, 2.0, 0.0}, 50.0, "demo");
    well.provenance.demo = true;
    return well;
}

DomainObject demo_horizon() {
    DomainObject horizon;
    horizon.object_id = "horizon:top";
    horizon.name = "Top";
    horizon.crs = "demo";
    horizon.origin = {0.0, 0.0};
    horizon.spacing = {1.0, 1.0};
    horizon.z_grid = {
        {0.0, 0.0, 0.0, 0.0},
        {0.0, std::nan(""), 0.0, 0.0},
        {0.0, 0.0, 0.0, 0.0},
        {0.0, 0.0, 0.0, 0.0},
    };
    return horizon;
}

void pump_events(QApplication& app) {
    for (int i = 0; i < 5; ++i) {
        app.processEvents(QEventLoop::AllEvents);
        app.processEvents(QEventLoop::AllEvents);
        QTimer::singleShot(10, &app, []() {});
        app.processEvents(QEventLoop::AllEvents);
    }
}

}  // namespace

int main(int argc, char** argv) {
    // Honest mode: default to offscreen unless the harness provides a
    // display (ctest sets QT_QPA_PLATFORM=offscreen via ENVIRONMENT).
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {
        qputenv("QT_QPA_PLATFORM", "offscreen");
    }
#if defined(Q_OS_UNIX) && defined(PWB_GEO3D_HAVE_X11)
    // VIZ-C: hosts with a broken/absent GLX extension kill the process
    // with a fatal X error inside QOpenGLContext creation — before Qt can
    // report the failure and the test can exercise the honest GL-less
    // degradation path. Ignore X protocol errors for the lifetime of the
    // test so context creation fails softly; hosts with a working GL
    // (including software GL via QT_QPA_PLATFORM=wayland + llvmpipe)
    // still take the real GL path.
    XSetErrorHandler([](Display*, XErrorEvent*) -> int { return 0; });
#endif
    QApplication app(argc, argv);

    // ------------------------------------------------------------------
    // 1. construction + scene wiring + show
    // ------------------------------------------------------------------
    Geo3DViewportWidget widget;
    Geo3DWorkspaceController controller(
        [&widget]() { return &widget.scene_manager(); });
    controller.set_viewport(&widget);

    QString clicked;
    QString escaped;
    QObject::connect(&widget, &Geo3DViewportWidget::viewport_clicked,
                     [&](double px, double py) {
                         clicked = QString("click %1 %2").arg(px).arg(py);
                         controller.handle_viewport_click(px, py);
                     });
    QObject::connect(&widget, &Geo3DViewportWidget::escape_pressed,
                     [&]() { escaped = "esc"; });

    controller.add_object(demo_well());
    controller.add_object(demo_horizon());
    check(widget.scene_manager().count() > 0, "scene objects registered");

    widget.resize(320, 240);
    widget.show();
    pump_events(app);

    const bool gl = widget.gl_ready();
    std::printf("GL mode: %s\n", gl ? "hardware/software context OK"
                                    : "GL-less (honest degradation)");
    if (gl) {
        const QImage shot = widget.grab_scene_screenshot();
        check(!shot.isNull() && shot.width() > 0, "screenshot rendered");
    } else {
        const QImage shot = widget.grab_scene_screenshot();
        check(shot.isNull(), "GL-less screenshot is honestly null");
    }

    // ------------------------------------------------------------------
    // 2. invalid geometry is rejected without taking the widget down
    // ------------------------------------------------------------------
    bool threw = false;
    try {
        pwb::geo3d_viz::SceneObject bad;
        bad.name = "bad-nan";
        bad.mode = ObjectMode::Mesh;
        bad.verts = {{0.f, 0.f, 0.f},
                     {std::nanf(""), 0.f, 0.f},
                     {0.f, 1.f, 0.f}};
        bad.faces = {{0, 1, 2}};
        widget.scene_manager().add(std::move(bad));
    } catch (const pwb::geo3d_viz::SceneObjectError&) {
        threw = true;
    }
    check(threw, "NaN vertex payload rejected (fail-loud)");
    threw = false;
    try {
        pwb::geo3d_viz::SceneObject bad_index;
        bad_index.name = "bad-index";
        bad_index.mode = ObjectMode::Mesh;
        bad_index.verts = {{0.f, 0.f, 0.f}};
        bad_index.faces = {{0, 1, 2}};
        widget.scene_manager().add(std::move(bad_index));
    } catch (const pwb::geo3d_viz::SceneObjectError&) {
        threw = true;
    }
    check(threw, "out-of-range face index rejected");

    widget.update();
    pump_events(app);
    check(widget.scene_manager().count() > 0,
          "viewport keeps rendering after rejected payloads");

    // ------------------------------------------------------------------
    // 3. selection through the pick path (camera project → facade pick)
    // ------------------------------------------------------------------
    controller.fit_all();
    pump_events(app);
    // project the well head into screen space and click there
    const SceneObject* head = widget.scene_manager().get("well:w-1#head");
    double px = 0.0;
    double py = 0.0;
    bool projected = false;
    if (head != nullptr && !head->verts.empty()) {
        projected = widget.camera().project_to_screen(
            {head->verts[0][0], head->verts[0][1], head->verts[0][2]}, px, py);
    }
    check(projected, "well head projects into the viewport");
    if (projected) {
        const auto hit = widget.pick_at(px, py, {});
        check(hit.has_value(),
              "screen pick at the projected head hits a scene object");
        if (hit.has_value()) {
            check(hit->name.rfind("well:w-1", 0) == 0,
                  "hit belongs to the well payload tree");
        }
    }

    // camera pose round-trip (frozen parameterization)
    widget.apply_camera_pose(CameraPose{123.0, 20.0, -30.0});
    const std::optional<CameraPose> pose = widget.camera_pose();
    check(pose.has_value() && pose->distance == 123.0 &&
              pose->elevation_deg == 20.0 && pose->azimuth_deg == -30.0,
          "camera pose round-trip");

    // escape key path (delivered through the event system)
    QKeyEvent escape(QEvent::KeyPress, Qt::Key_Escape, Qt::NoModifier);
    QApplication::sendEvent(&widget, &escape);
    check(escaped == "esc", "escape_pressed emitted");

    // ------------------------------------------------------------------
    // 4. repeated open/close (lifecycle safety)
    // ------------------------------------------------------------------
    for (int cycle = 0; cycle < 10; ++cycle) {
        auto* w = new Geo3DViewportWidget();
        {
            // the controller dies with the viewport in sight (destroy
            // order: controller first, then the widget)
            Geo3DWorkspaceController c(
                [&w]() { return &w->scene_manager(); });
            c.set_viewport(w);
            c.add_object(demo_well());
            w->resize(200, 150);
            w->show();
            pump_events(app);
            c.set_viewport(nullptr);
        }
        delete w;
    }
    check(true, "10 open/close cycles without a crash");

    std::printf("geo3d.widget_test: %d checks, %d failures (%s)\n", g_checks,
                g_failures, gl ? "GL" : "GL-less");
    return g_failures == 0 ? 0 : 1;
}
