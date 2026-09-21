// joint_analysis.closure — geoviz final closure: the Geo3DAnalysisHooks
// product install. Before the install every hook was empty (each joint
// analysis tab showed 未接入 or silently no-op'd). These tests drive the
// same make_hooks() closure the install uses and freeze the behavioral
// contract: sidecar persistence round-trip, the RGB fusion overlay
// (demo.rgb_fusion_geometry port) into the GL-less scene registry, and
// the demo stratal path end-to-end (job runtime → surfaces → overlays →
// clear). Dialog-backed hooks (export/advisor/auto-tie/crossplot on
// empty data) are exercised by the product E2E pass, not here — they are
// QMessageBox paths that would block a headless test.
#include "pwb_test.hpp"

#include <QApplication>
#include <QDeadlineTimer>
#include <QTemporaryDir>
#include <QThread>

#include <cmath>
#include <cstdio>
#include <functional>
#include <memory>
#include <string>

#include <filesystem>
#include <fstream>

#include "job_center.hpp"
#include "joint_analysis_install.hpp"
#include "viz_c_joint_host.hpp"

#include <pwb/geo3d_viz/scene_object_manager.hpp>
#include <pwb/seismic_service/volume_service.hpp>
#include <pwb/ui_wellseis/joint_state.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/ui_wellseis/qt/geological_modeling_3d_page.hpp>

using pwb::app::joint_analysis::JointAnalysisInstall;
using pwb::geo3d_viz::SceneObjectManager;
using Hooks = pwb::ui_wellseis::qt::Geo3DAnalysisHooks;
using Page = pwb::ui_wellseis::qt::GeologicalModeling3DPage;

namespace fs = std::filesystem;

namespace {

QApplication* ensure_app() {
    static QApplication* app = [] {
        static int argc = 1;
        static char argv0[] = "joint_analysis_test";
        static char* argv[] = {argv0, nullptr};
        return new QApplication(argc, argv);
    }();
    return app;
}

bool wait_until(const std::function<bool()>& pred, int timeout_ms = 8000) {
    ensure_app();
    QDeadlineTimer deadline(timeout_ms);
    while (!pred()) {
        if (deadline.hasExpired()) return false;
        QApplication::processEvents(QEventLoop::AllEvents, 50);
        QThread::msleep(10);
    }
    return true;
}

struct Rig {
    QTemporaryDir dir;
    pwb::app::JobCenter jobs;
    SceneObjectManager manager;
    // A real page surfaces the install's status lines on failure (the
    // hooks report through set_stratal_status).
    std::unique_ptr<Page> page;
    Hooks hooks;
    QString project_path;

    Rig() : project_path(dir.path()) {
        ensure_app();
        page = std::make_unique<Page>(nullptr, nullptr);
        JointAnalysisInstall deps;
        deps.page = page.get();
        deps.jobs = &jobs;
        deps.scene_objects = &manager;
        deps.dialog_parent = nullptr;
        deps.project_directory = [this] { return project_path; };
        hooks = pwb::app::joint_analysis::make_hooks(deps);
    }
};

}  // namespace

PWB_TEST(joint_analysis_sidecar_roundtrip) {
    Rig rig;
    // Absent sidecar -> nullopt (a fresh project never fails the open).
    PWB_CHECK(!pwb::app::joint_analysis::load_stored(rig.project_path)
                   .has_value());

    pwb::ui_wellseis::JointAnalysisSlice slice;
    slice.well_width_px = 7;
    slice.vertical_domain = "depth";
    slice.seismic_color_scale = "seismic";
    PWB_CHECK(rig.hooks.stored_state != nullptr);
    PWB_CHECK(rig.hooks.save_state != nullptr);
    rig.hooks.save_state(slice);
    const auto loaded =
        pwb::app::joint_analysis::load_stored(rig.project_path);
    PWB_CHECK(loaded.has_value());
    PWB_CHECK(loaded->well_width_px == 7);
    PWB_CHECK(loaded->vertical_domain == "depth");
    // stored_state reads the same sidecar through the hook.
    const auto via_hook = rig.hooks.stored_state();
    PWB_CHECK(via_hook.has_value());
    PWB_CHECK(via_hook->well_width_px == 7);
}

PWB_TEST(joint_analysis_rgb_fusion_overlay) {
    Rig rig;
    PWB_CHECK(rig.manager.get("analysis:rgb") == nullptr);
    PWB_CHECK(rig.hooks.run_rgb_fusion != nullptr);
    rig.hooks.run_rgb_fusion();
    const pwb::geo3d_viz::SceneObject* overlay =
        rig.manager.get("analysis:rgb");
    PWB_CHECK(overlay != nullptr);  // RGB fusion overlay must register
    if (overlay == nullptr) {
        return;
    }
    // demo.rgb_fusion_geometry: 40x40 vertices, 39*39 quads = 3042 faces,
    // one blended RGBA per face (blend_rgba min-max + constant alpha).
    PWB_CHECK(overlay->verts.size() == 40u * 40u);
    PWB_CHECK(overlay->faces.size() == 39u * 39u * 2u);
    PWB_CHECK(overlay->face_colors.size() == overlay->faces.size());
    PWB_CHECK(overlay->kind == pwb::geo3d_viz::ObjectKind::Horizon);
    bool any_colored = false;
    for (const auto& rgba : overlay->face_colors) {
        any_colored = any_colored || rgba[0] != rgba[1] || rgba[1] != rgba[2];
    }
    PWB_CHECK(any_colored);  // channels actually differ (real blend)
    // Re-run replaces per name (Python overlay key semantics).
    rig.hooks.run_rgb_fusion();
    PWB_CHECK(rig.manager.count() == 1);
}

PWB_TEST(joint_analysis_stratal_demo_and_clear) {
    Rig rig;
    PWB_CHECK(rig.manager.names().empty());
    PWB_CHECK(rig.hooks.generate_stratal != nullptr);
    PWB_CHECK(rig.hooks.clear_stratal != nullptr);
    rig.hooks.generate_stratal("", "", {0.25, 0.75}, true);
    PWB_CHECK(wait_until([&] {
        return rig.manager.get("analysis:stratal-k=0.25") != nullptr &&
               rig.manager.get("analysis:stratal-k=0.75") != nullptr;
    }));
    // Demo grids are 16x20 -> verts 320, faces 19*15*2 quads (finite-only).
    const auto* overlay = rig.manager.get("analysis:stratal-k=0.25");
    PWB_CHECK(overlay != nullptr && overlay->verts.size() == 16u * 20u);
    PWB_CHECK(overlay != nullptr && !overlay->faces.empty());
    // Two fractions at different proportional depths -> different z means.
    if (overlay != nullptr) {
        const auto* other = rig.manager.get("analysis:stratal-k=0.75");
        PWB_CHECK(other != nullptr);
        double mean_a = 0.0;
        double mean_b = 0.0;
        for (const auto& v : overlay->verts) mean_a += v[2];
        for (const auto& v : other->verts) mean_b += v[2];
        mean_a /= static_cast<double>(overlay->verts.size());
        mean_b /= static_cast<double>(other->verts.size());
        PWB_CHECK(std::fabs(mean_a - mean_b) > 1e-6);
    }
    // Clear removes exactly the stratal overlays.
    rig.hooks.clear_stratal();
    PWB_CHECK(rig.manager.get("analysis:stratal-k=0.25") == nullptr);
    PWB_CHECK(rig.manager.get("analysis:stratal-k=0.75") == nullptr);

    // Real path without a registration: the honest Python refusal text
    // (round-2 review: this used to assert a predicate that was true
    // before the call — vacuous. The status line is the contract).
    rig.hooks.generate_stratal("top.dat", "bottom.dat", {0.5}, false);
    PWB_CHECK(wait_until([&] {
        return rig.page->stratal_status_text()
                   .contains(QStringLiteral(
                       "survey/registration 不可用")) ||
               rig.page->stratal_status_text()
                   .contains(QStringLiteral("无法对齐"));
    }));
    PWB_CHECK(rig.manager.get("analysis:stratal-k=0.50") == nullptr);
}

PWB_TEST(joint_analysis_stratal_real_dat_end_to_end) {
    // REAL .dat path over a REAL volume: open the frozen io_oracle_bins
    // survey, write horizon triples on its actual IL/XL axes, run the
    // hook, and expect a proportional surface pinned in the shared
    // render space. This is the path the round-1/round-2 fixes targeted
    // (worker-thread parsing, render-space verts, registration guard).
    // Destruction order contract (the joint3d HostRig comment): the
    // JobCenter must die BEFORE the host — the host's QObject-child
    // JobOwners are ALSO owned by the center's vector, and the reverse
    // order double-deletes them. unique_ptr members declared host-first
    // give center-first destruction.
    std::unique_ptr<pwb::app::viz_c::VizCJointHost> host;
    std::unique_ptr<pwb::app::JobCenter> jobs;
    jobs = std::make_unique<pwb::app::JobCenter>();
    host = std::make_unique<pwb::app::viz_c::VizCJointHost>(*jobs, nullptr,
                                                            nullptr);
    auto& the_host = *host;
    auto& the_jobs = *jobs;
    const fs::path volume = fs::path(JOINT_ANALYSIS_FIXTURE_VOLUME);
    QString error;
    PWB_CHECK(the_host.open_volume(
        std::make_shared<pwb::seismic_service::SeismicVolumeService>(),
        volume, &error));
    PWB_CHECK(wait_until([&] {
        return the_host.scene_snapshot().n_inline > 0;
    }));
    const auto* reg = the_host.scene().registration();
    PWB_CHECK(reg != nullptr);
    QTemporaryDir dir;
    const auto write_horizon = [&](const QString& name,
                                   double offset_ms) {
        const QString path = dir.path() + "/" + name;
        QFile file(path);
        PWB_CHECK(file.open(QIODevice::WriteOnly | QIODevice::Text));
        const auto& survey = reg->survey();
        // Subsample the axes (every 2nd) with gaps: nearest-fill must
        // close them (Python build_stratal_grids default).
        for (std::int64_t il = 0; il < survey.n_inlines; il += 2) {
            for (std::int64_t xl = 0; xl < survey.n_crosslines; xl += 2) {
                const std::int64_t il_no =
                    survey.iline_start + il * survey.iline_step;
                const std::int64_t xl_no =
                    survey.xline_start + xl * survey.xline_step;
                const double t = 0.25 * reg->n_sample() *
                                     survey.dt_ms +
                                 offset_ms + 0.01 * il;
                file.write(QString("%1 %2 %3\n")
                               .arg(il_no)
                               .arg(xl_no)
                               .arg(t, 0, 'f', 1)
                               .toUtf8());
            }
        }
        file.close();
        return path;
    };
    const QString top = write_horizon("top.dat", 0.0);
    const QString bottom = write_horizon("bottom.dat",
                                         0.25 * reg->n_sample() *
                                             reg->survey().dt_ms);

    QTemporaryDir sdir;
    Page page(nullptr, &the_host);
    SceneObjectManager manager;
    JointAnalysisInstall deps;
    deps.page = &page;
    deps.host = &the_host;
    deps.jobs = &the_jobs;
    deps.scene_objects = &manager;
    QString project_dir = sdir.path();
    deps.project_directory = [&project_dir] { return project_dir; };
    const auto hooks = pwb::app::joint_analysis::make_hooks(deps);

    hooks.generate_stratal(top.toStdString(), bottom.toStdString(),
                           {0.5}, false);
    PWB_CHECK(wait_until([&] {
        return manager.get("analysis:stratal-k=0.50") != nullptr ||
               page.stratal_status_text().contains(
                   QStringLiteral("失败"));
    }));
    const pwb::geo3d_viz::SceneObject* overlay =
        manager.get("analysis:stratal-k=0.50");
    if (overlay == nullptr) {
        std::printf("real .dat stratal failed: %s\n",
                    page.stratal_status_text().toStdString().c_str());
    }
    PWB_CHECK(overlay != nullptr);
    if (overlay != nullptr) {
        // Render space: verts span (n_inline, n_crossline) preview axes
        // with z in preview sample indices between top and bottom.
        PWB_CHECK(overlay->verts.size() ==
                  static_cast<std::size_t>(reg->n_inline()) *
                      static_cast<std::size_t>(reg->n_crossline()));
        double z_min = 1e30;
        double z_max = -1e30;
        for (const auto& v : overlay->verts) {
            z_min = std::min(z_min, static_cast<double>(v[2]));
            z_max = std::max(z_max, static_cast<double>(v[2]));
        }
        PWB_CHECK(z_min > 0.0 && z_max < static_cast<double>(reg->n_sample()));
    }
    PWB_CHECK(the_host.shutdown(2000));
}

PWB_TEST(joint_analysis_page_install_fills_hooks) {
    ensure_app();
    Page page(nullptr, nullptr);
    // Before install: every analysis hook empty (the old 未接入 state).
    pwb::app::JobCenter jobs;
    SceneObjectManager manager;
    JointAnalysisInstall deps;
    deps.page = &page;
    deps.jobs = &jobs;
    deps.scene_objects = &manager;
    pwb::app::joint_analysis::install(deps);
    // After install the page carries the closure-backed hooks: the
    // persistence pair round-trips through the page contract.
    pwb::ui_wellseis::ProjectSlice project_slice;
    QTemporaryDir dir;
    const QString project = dir.path();
    deps.project_directory = [&project] { return project; };
    pwb::app::joint_analysis::install(deps);
    page.set_project_path(project);
    page.set_project(&project_slice, std::nullopt);
    page.save_joint_analysis_to_project();
    const auto loaded =
        pwb::app::joint_analysis::load_stored(project);
    PWB_CHECK(loaded.has_value());
}
