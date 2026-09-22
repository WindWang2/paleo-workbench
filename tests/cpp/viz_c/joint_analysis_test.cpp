// joint_analysis.closure — geoviz final closure: the Geo3DAnalysisHooks
// product install. Before the install every hook was empty (each joint
// analysis tab showed 未接入 or silently no-op'd). These tests drive the
// same make_hooks() closure the install uses and freeze the behavioral
// contract: sidecar persistence round-trip, the RGB fusion overlay
// (demo.rgb_fusion_geometry port) into the GL-less scene registry, and
// the demo stratal path end-to-end (job runtime → surfaces → overlays →
// clear). Dialog-backed hooks (export/advisor/crossplot on empty data,
// auto-tie refusals) are exercised by the product E2E pass, not here —
// they are QMessageBox paths that would block a headless test; the
// auto-tie happy path (real logs + fixture volume) is driven below.
#include "pwb_test.hpp"

#include <QApplication>
#include <QDeadlineTimer>
#include <QTemporaryDir>
#include <QThread>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <map>
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

// Big-endian SEGY writer for the auto-tie/fence E2E: the frozen
// io_oracle fixtures are deliberately tiny (≤10 samples/trace — below
// the tie kernel's 8-sample floor at useful overlap), so the tests
// generate a survey-sized volume (12 IL × 8 XL × 128 samples, 2 ms)
// with a deterministic varying trace (closure_seismic_test's header
// layout: dt@3216, ns@3220, fmt@3224, il@188, xl@192).
void put_be_u16(unsigned char* p, std::uint16_t v) {
    p[0] = static_cast<unsigned char>(v >> 8);
    p[1] = static_cast<unsigned char>(v & 0xFF);
}
void put_be_i32(unsigned char* p, std::int32_t v) {
    const auto u = static_cast<std::uint32_t>(v);
    p[0] = static_cast<unsigned char>(u >> 24);
    p[1] = static_cast<unsigned char>((u >> 16) & 0xFF);
    p[2] = static_cast<unsigned char>((u >> 8) & 0xFF);
    p[3] = static_cast<unsigned char>(u & 0xFF);
}
void put_be_f32(unsigned char* p, float v) {
    std::uint32_t b = 0;
    std::memcpy(&b, &v, 4);
    p[0] = static_cast<unsigned char>(b >> 24);
    p[1] = static_cast<unsigned char>((b >> 16) & 0xFF);
    p[2] = static_cast<unsigned char>((b >> 8) & 0xFF);
    p[3] = static_cast<unsigned char>(b & 0xFF);
}
void put_be_i16(unsigned char* p, std::int16_t v) {
    const auto u = static_cast<std::uint16_t>(v);
    p[0] = static_cast<unsigned char>(u >> 8);
    p[1] = static_cast<unsigned char>(u & 0xFF);
}
// Bin-grid calibration on the three corner traces (the io_oracle_bins
// generator contract: scalar -100 = centimetres, XL spacing +50 m on X,
// IL spacing +50 m on Y). Without these the joint host cannot infer a
// survey, so the scene never wires.
void put_corner(unsigned char* trace, double x_m, double y_m) {
    put_be_i16(trace + 70, -100);
    put_be_i32(trace + 72, static_cast<std::int32_t>(std::llround(x_m * 100.0)));
    put_be_i32(trace + 76, static_cast<std::int32_t>(std::llround(y_m * 100.0)));
    put_be_i32(trace + 180, static_cast<std::int32_t>(std::llround(x_m * 100.0)));
    put_be_i32(trace + 184, static_cast<std::int32_t>(std::llround(y_m * 100.0)));
}
QString write_tie_volume(const QString& directory) {
    constexpr std::int64_t kNi = 12, kNc = 8, kNs = 128;
    constexpr double kSpacingM = 50.0;
    std::vector<unsigned char> file(3600, 0);
    put_be_u16(file.data() + 3200 + 16, 2000);  // dt us
    put_be_u16(file.data() + 3200 + 20,
               static_cast<std::uint16_t>(kNs));
    put_be_u16(file.data() + 3200 + 24, 5);  // IEEE float32
    for (std::int64_t il = 0; il < kNi; ++il) {
        for (std::int64_t xl = 0; xl < kNc; ++xl) {
            std::vector<unsigned char> trace(
                240 + static_cast<std::size_t>(kNs) * 4, 0);
            put_be_i32(trace.data() + 188,
                       static_cast<std::int32_t>(il + 1));
            put_be_i32(trace.data() + 192,
                       static_cast<std::int32_t>(xl + 1));
            if (il == 0 && xl == 0) put_corner(trace.data(), 0.0, 0.0);
            if (il == 1 && xl == 0) put_corner(trace.data(), 0.0, kSpacingM);
            if (il == 0 && xl == 1) put_corner(trace.data(), kSpacingM, 0.0);
            for (std::int64_t s = 0; s < kNs; ++s) {
                const double t = static_cast<double>(s);
                const float value = static_cast<float>(
                    0.6 * std::sin(0.31 * t) +
                    0.3 * std::cos(0.013 * t * t) +
                    0.1 * (((s * 7919) % 23) / 23.0));
                put_be_f32(trace.data() + 240 + s * 4, value);
            }
            file.insert(file.end(), trace.begin(), trace.end());
        }
    }
    const QString path = directory + QStringLiteral("/tie_volume.sgy");
    QFile out(path);
    PWB_CHECK(out.open(QIODevice::WriteOnly | QIODevice::Truncate));
    out.write(reinterpret_cast<const char*>(file.data()),
              static_cast<qint64>(file.size()));
    out.close();
    return path;
}

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

PWB_TEST(joint_analysis_auto_tie_real_logs_end_to_end) {
    // Real-log auto-tie over a REAL volume: generate a survey-sized SEGY
    // (the frozen oracle fixtures are too short for the tie kernel's
    // overlap floor), drop a well at its centre with graded AC/DEN
    // curves and a checkshot TD table, run the hook, and expect the
    // log_tie kernel's R/时移 line on the well-tie tab (no dialog on the
    // happy path).
    std::unique_ptr<pwb::app::viz_c::VizCJointHost> host;
    std::unique_ptr<pwb::app::JobCenter> jobs;
    jobs = std::make_unique<pwb::app::JobCenter>();
    host = std::make_unique<pwb::app::viz_c::VizCJointHost>(*jobs, nullptr,
                                                            nullptr);
    auto& the_host = *host;
    auto& the_jobs = *jobs;
    QTemporaryDir dir;
    const fs::path volume = fs::path(write_tie_volume(dir.path()).toStdString());
    QString error;
    PWB_CHECK(the_host.open_volume(
        std::make_shared<pwb::seismic_service::SeismicVolumeService>(),
        volume, &error));
    PWB_CHECK(wait_until([&] {
        return the_host.scene_snapshot().n_inline > 0;
    }));
    const auto* reg = the_host.scene().registration();
    PWB_CHECK(reg != nullptr);

    // Well at the survey centre; TD table anchored on the volume's own
    // time axis so the checkshot range covers the trace.
    const auto [cx, cy] = reg->survey().il_xl_to_xy(
        static_cast<double>(reg->survey().iline_start +
                            reg->survey().iline_step *
                                (reg->survey().n_inlines - 1) / 2),
        static_cast<double>(reg->survey().xline_start +
                            reg->survey().xline_step *
                                (reg->survey().n_crosslines - 1) / 2));
    pwb::geo3d_viz::joint::WellHead head;
    head.name = "W-TIE";
    head.id = "W-TIE";
    head.x = cx;
    head.y = cy;
    head.total_depth_m = 2500.0;
    const double dt = reg->survey().dt_ms;
    std::map<std::string, pwb::geo3d_viz::joint::TimeDepthTable> td;
    td.emplace("W-TIE",
               pwb::geo3d_viz::joint::TimeDepthTable(
                   "W-TIE", {2.0 * dt, 500.0 * dt},
                   {250.0, 2500.0}));
    the_host.set_wells({head}, td);

    // Graded sonic/density curves (SI units) with mnemonics the VIZ-B
    // calibration path recognizes (AC + DEN).
    pwb::viz::cross_well::WellColumnData column;
    column.name = "W-TIE";
    pwb::viz::cross_well::WellCurve sonic;
    sonic.name = "AC";
    sonic.unit = "us/m";
    sonic.depth_unit = "m";
    pwb::viz::cross_well::WellCurve density;
    density.name = "DEN";
    density.unit = "g/cm3";
    density.depth_unit = "m";
    for (double depth = 250.0; depth <= 2450.0; depth += 5.0) {
        const double velocity = 2200.0 + 0.55 * depth;  // m/s
        sonic.depths.push_back(depth);
        sonic.values.push_back(1e6 / velocity);
        density.depths.push_back(depth);
        density.values.push_back(2.05 + 1.5e-4 * depth);
    }
    column.curves = {sonic, density};
    std::vector<pwb::viz::cross_well::WellColumnData> logs{column};

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
    deps.well_logs = [&logs] { return logs; };
    const auto hooks = pwb::app::joint_analysis::make_hooks(deps);
    PWB_CHECK(hooks.run_auto_tie != nullptr);
    hooks.run_auto_tie();
    PWB_CHECK(wait_until([&] {
        const QString text = page.well_tie_status_text();
        return text.contains(QStringLiteral("R =")) ||
               text.contains(QStringLiteral("失败"));
    }));
    const QString text = page.well_tie_status_text();
    if (!text.contains(QStringLiteral("R ="))) {
        std::printf("auto-tie failed: %s\n", text.toStdString().c_str());
    }
    PWB_CHECK(text.contains(QStringLiteral("R =")));
    PWB_CHECK(text.contains(QStringLiteral("时移")));
    PWB_CHECK(the_host.shutdown(2000));
}

PWB_TEST(joint_fence_profile_2d_view) {
    // 2D fence VD profile (profile_2d.py contract): with a real volume
    // and a well-to-well fence, the host seam exposes the curtain's
    // cached strip + projected wells, and the joint page renders them in
    // the 2D strip (raster SectionProfileWidget replaces the
    // placeholder).
    std::unique_ptr<pwb::app::viz_c::VizCJointHost> host;
    std::unique_ptr<pwb::app::JobCenter> jobs;
    jobs = std::make_unique<pwb::app::JobCenter>();
    host = std::make_unique<pwb::app::viz_c::VizCJointHost>(*jobs, nullptr,
                                                            nullptr);
    auto& the_host = *host;
    auto& the_jobs = *jobs;
    QTemporaryDir dir;
    const fs::path volume = fs::path(write_tie_volume(dir.path()).toStdString());
    QString error;
    PWB_CHECK(the_host.open_volume(
        std::make_shared<pwb::seismic_service::SeismicVolumeService>(),
        volume, &error));
    PWB_CHECK(wait_until([&] {
        return the_host.scene_snapshot().n_inline > 0;
    }));
    const auto* reg = the_host.scene().registration();
    PWB_CHECK(reg != nullptr);
    // Two wells a third of the survey apart on the inline axis.
    const auto well_xy = [&](double along) {
        return reg->survey().il_xl_to_xy(
            static_cast<double>(reg->survey().iline_start +
                                reg->survey().iline_step *
                                    static_cast<std::int64_t>(
                                        along * (reg->survey().n_inlines - 1))),
            static_cast<double>(reg->survey().xline_start +
                                reg->survey().xline_step *
                                    (reg->survey().n_crosslines - 1) / 2));
    };
    std::vector<pwb::geo3d_viz::joint::WellHead> heads;
    for (const char* name : {"W-A", "W-B"}) {
        const auto [x, y] = well_xy(name == "W-A" ? 0.35 : 0.65);
        pwb::geo3d_viz::joint::WellHead head;
        head.name = name;
        head.id = name;
        head.x = x;
        head.y = y;
        // Vertical well (bottom = head): the well-order fence follows the
        // trajectory pierce points on the active time slice, so an unset
        // (0,0) bottom would skew the path away from the head.
        head.bottom_x = x;
        head.bottom_y = y;
        head.total_depth_m = 2000.0;
        heads.push_back(head);
    }
    // The well-order fence needs TD tables to project the wells onto the
    // current Time domain (无时深 → add_well_to_well_fence refuses).
    const double tmax =
        reg->survey().t0_ms +
        static_cast<double>(reg->survey().n_samples - 1) *
            reg->survey().dt_ms;
    std::map<std::string, pwb::geo3d_viz::joint::TimeDepthTable> td;
    for (const char* name : {"W-A", "W-B"}) {
        td.emplace(name, pwb::geo3d_viz::joint::TimeDepthTable(
                             name, {0.0, tmax / 2, tmax},
                             {0.0, 1000.0, 2000.0}));
    }
    the_host.set_wells(heads, td);

    // Page constructed BEFORE the fence so the scene_updated the fence
    // add emits drives its 2D strip refresh.
    QTemporaryDir sdir;
    Page page(nullptr, &the_host);
    QString project_dir = sdir.path();
    QWidget* profile = page.findChild<QWidget*>(
        QStringLiteral("JointFenceProfile"));
    PWB_CHECK(profile != nullptr);
    the_host.add_well_to_well_fence("W-A", "W-B");
    PWB_CHECK(wait_until([&] {
        return !the_host.scene_snapshot().active_fence_id.empty();
    }));

    // Host seam: the curtain's cached strip + projected wells.
    const auto strip = the_host.active_fence_strip();
    PWB_CHECK(strip.has_value());
    if (strip) {
        PWB_CHECK(!strip->arc_length_m.empty());
        PWB_CHECK(!strip->sample_axis.empty());
        PWB_CHECK(strip->amplitude.size() ==
                  strip->arc_length_m.size() * strip->sample_axis.size());
        PWB_CHECK(strip->sample_unit == "ms" || strip->sample_unit == "m");
    }
    const auto wells = the_host.active_fence_wells();
    PWB_CHECK(wells.size() == 2);
    if (wells.size() == 2) {
        PWB_CHECK(wells[0].distance_m <= wells[1].distance_m);
        PWB_CHECK(wells[0].name != wells[1].name);
    }

    // The raster profile replaces the placeholder in the 2D strip
    // (isHidden: the local flag — the page itself is never shown in a
    // headless test, so isVisible() would stay false on ancestors).
    if (profile != nullptr) {
        PWB_CHECK(wait_until([&] { return !profile->isHidden(); }));
    }
    PWB_CHECK(the_host.shutdown(2000));
}
