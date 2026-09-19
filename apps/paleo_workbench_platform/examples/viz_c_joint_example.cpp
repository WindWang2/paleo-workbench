// VIZ-C joint well-seismic example — the runnable production seam for
// plan V4: a REAL PWBVOL1 volume (the frozen seismic_io oracle fixture)
// opened through the tiled service, a joint WellSeismicScene with wells
// + fences + probe, the #1394 JointHostController host driving a geo3d
// viewport, and the honest GL/GL-less outcome.
//
//   QT_QPA_PLATFORM=offscreen ./viz_c_joint_example [volume.pwbvol]
//   QT_QPA_PLATFORM=wayland  ./viz_c_joint_example   (real software GL)
#include <QApplication>
#include <QDateTime>
#include <QDir>
#include <QImage>
#include <QTemporaryDir>
#include <QTimer>

#include <cmath>
#include <cstdio>

#if defined(Q_OS_UNIX)
#include <X11/Xlib.h>
// Broken/absent GLX hosts die inside QOpenGLContext creation before the
// honest GL-less degradation can report; ignore X protocol errors so the
// context failure is soft (working-GL hosts still take the real path).
#undef KeyPress
#undef KeyRelease
#undef FocusIn
#undef FocusOut
#undef None  // Xlib's None macro collides with enum names in pwb headers
#endif
#include <filesystem>
#include <optional>
#include <string>

#include "job_center.hpp"
#include "viz_c_joint_host.hpp"
#include "viz_c_joint_volume.hpp"

#include <pwb/geo3d_viz/geo3d_viewport_widget.hpp>
#include <pwb/geo3d_viz/joint/joint_scene.hpp>
#include <pwb/geo3d_viz/joint/segy_survey.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>
#include <pwb/seismic_service/volume_service.hpp>

namespace fs = std::filesystem;
using pwb::geo3d_viz::Geo3DViewportWidget;
using pwb::geo3d_viz::Geo3DWorkspaceController;
using pwb::geo3d_viz::joint::FenceSection;
using pwb::geo3d_viz::joint::TimeDepthTable;
using pwb::geo3d_viz::joint::WellHead;
using pwb::geo3d_viz::joint::WellSeismicScene;

namespace {

int report(const std::string& line) {
    std::printf("%s\n", line.c_str());
    std::fflush(stdout);
    return 0;
}

std::string describe_host(pwb::app::viz_c::VizCJointHost* host) {
    const auto snapshot = host->scene_snapshot();
    std::string text = "snapshot: has_scene=" +
                       std::to_string(snapshot.has_scene) +
                       " wells=" +
                       std::to_string(snapshot.well_presentations.size()) +
                       " n_inline=" + std::to_string(snapshot.n_inline) +
                       " n_crossline=" +
                       std::to_string(snapshot.n_crossline) +
                       " slices=" +
                       std::to_string(snapshot.time_slices.size());
    if (snapshot.active_time_ms.has_value()) {
        text += " active_ms=" +
                std::to_string(*snapshot.active_time_ms);
    }
    return text;
}

}  // namespace

int main(int argc, char** argv) {
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {
        qputenv("QT_QPA_PLATFORM", "offscreen");
    }
#if defined(Q_OS_UNIX)
    XSetErrorHandler([](Display*, XErrorEvent*) -> int { return 0; });
#endif
    QApplication app(argc, argv);

    // Real volume: default to the frozen seismic_io oracle PWBVOL1
    // fixture; any published PWBVOL1/SEG-Y path works too.
    fs::path volume = fs::path(VIZ_C_EXAMPLE_VOLUME);
    if (argc > 1) volume = fs::path(argv[1]);
    if (!fs::exists(volume)) {
        return report("volume fixture missing: " + volume.string());
    }

    Geo3DViewportWidget viewport;
    Geo3DWorkspaceController controller(
        [&viewport]() { return &viewport.scene_manager(); });
    controller.set_viewport(&viewport);
    pwb::app::JobCenter job_center;
    pwb::app::viz_c::VizCJointHost host(job_center, &controller, &viewport);

    // Wells are placed FROM the volume's real survey (bin-grid corners +
    // TWT extent) so head/bottom sit inside the bin grid — registration
    // maps them into render space next to the slice (a UTM head 120k
    // inlines away would be an unregistered well, not a scene).
    const auto service =
        std::make_shared<pwb::seismic_service::SeismicVolumeService>();
    std::string open_error;
    auto opened = service->open_pwbvol(volume, &open_error);
    if (opened.volume == nullptr) {
        opened = service->open_segy(volume, &open_error);
    }
    if (opened.volume == nullptr) {
        return report("volume open failed: " + open_error);
    }
    namespace joint = pwb::geo3d_viz::joint;
    joint::SurveySpec survey =
        joint::survey_from_volume_descriptor(opened.descriptor);
    const auto [p1, p2, p3] = joint::survey_corners(survey);
    const double tmax =
        survey.t0_ms +
        static_cast<double>(survey.n_samples - 1) * survey.dt_ms;
    WellHead ex1;
    ex1.name = "EX-1";
    ex1.x = p1[2];
    ex1.y = p1[3];
    ex1.bottom_x = p3[2];
    ex1.bottom_y = p3[3];
    ex1.total_depth_m = 1000.0;
    ex1.id = "ex1";
    WellHead ex2;
    ex2.name = "EX-2";
    ex2.x = p2[2];
    ex2.y = p2[3];
    ex2.bottom_x = (p2[2] + p3[2]) / 2;
    ex2.bottom_y = (p2[3] + p3[3]) / 2;
    ex2.total_depth_m = 900.0;
    ex2.id = "ex2";
    const TimeDepthTable td("EX", {0.0, tmax / 2, tmax},
                            {0.0, 500.0, 1000.0});
    host.set_wells({ex1, ex2}, {{"EX-1", td}, {"EX-2", td}});
    host.add_time_slice(tmax / 2);

    QString error;
    if (!host.open_volume(service, volume, &error)) {
        return report("open_volume refused: " + error.toStdString());
    }

    viewport.resize(800, 600);
    viewport.show();

    int exit_code = 0;
    QTimer::singleShot(1500, [&]() {
        report(describe_host(&host));

        // Well-to-well fence through the real seam (two piercing wells).
        host.add_well_to_well_fence("ex1", "ex2");
        // Probe on the active fence.
        const auto snapshot = host.scene_snapshot();
        if (snapshot.n_inline > 1 && snapshot.n_crossline > 1) {
            report("seam: apply_slice_line_numbers ok=" +
                   std::to_string(
                       host.apply_slice_line_numbers(
                           0.0, 0.0)
                           ? 1
                           : 0));
        }
        report("seam: set_vertical_domain(depth) refused=" +
               std::to_string(
                   host.set_vertical_domain("depth") ? 0 : 1));

        // Frame the joint objects (wells + slice + curtain) so the
        // screenshot is a meaningful key-pixel artifact, then grab after
        // the repaint settles.
        controller.fit_all();
        QTimer::singleShot(300, [&]() {
            const QImage image = viewport.grab_scene_screenshot();
            if (image.isNull()) {
                report("screenshot: unavailable (no GL context) — honest "
                       "degradation");
            } else {
                const QString path = QDir::tempPath() + "/viz-c-joint-" +
                                     QDateTime::currentDateTime().toString(
                                         "yyyyMMdd-HHmmss") +
                                     ".png";
                image.save(path);
                report("screenshot: " + path.toStdString() + " " +
                       std::to_string(image.width()) + "x" +
                       std::to_string(image.height()));
            }
            // Shutdown drains the job center (close protocol parity).
            const bool drained = host.shutdown(400);
            report(std::string("shutdown drained=") +
                   (drained ? "true" : "false"));
            app.exit(exit_code);
        });
    });
    return app.exec();
}
