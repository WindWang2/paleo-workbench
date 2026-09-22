// joint3d.closure — 06 line tests: the async prep pipeline (worker reads,
// GUI applies behind generation guards), multi-fence management,
// project-scoped state, teardown safety with in-flight jobs, and the
// product data binder over REAL fixture files (well heads + TD tables +
// SEG-Y volume).
#include "pwb_test.hpp"

#include <QApplication>
#include <QCoreApplication>
#include <QDeadlineTimer>
#include <QSettings>
#include <QThread>
#include <QTemporaryDir>

#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <memory>
#include <thread>

#include "closure_joint3d_install.hpp"
#include "job_center.hpp"
#include "viz_c_joint_host.hpp"
#include "viz_c_time_map.hpp"

#include <pwb/catalog/models.hpp>
#include <pwb/data/facade.hpp>
#include <pwb/domain/ids.hpp>
#include <pwb/geo3d_viz/joint/joint_scene.hpp>

namespace fs = std::filesystem;
using pwb::app::JobCenter;
using pwb::app::viz_c::VizCJointHost;

// Precondition guard: a broken setup ends THIS case early (the harness
// counts a failed check first).
#define JOINT_REQUIRE(cond)                                                   \
    do {                                                                      \
        if (!(cond)) {                                                        \
            PWB_CHECK(cond);                                                  \
            return;                                                           \
        }                                                                     \
    } while (0)

namespace {

// QApplication (offscreen): the well-click wiring test creates the 2D
// time-map widget, which needs the GUI application object.
QApplication* ensure_qt_app() {
    static QApplication* app = [] {
        static int fake_argc = 1;
        static char fake_argv0[] = "joint3d_closure_test";
        static char* fake_argv[] = {fake_argv0, nullptr};
        // Organization/app names fix the QSettings identity for the
        // whole process (project-identity tests rely on the temp path
        // set separately).
        QCoreApplication::setOrganizationName("pwb-test");
        QCoreApplication::setApplicationName("joint3d-closure");
        return new QApplication(fake_argc, fake_argv);
    }();
    return app;
}

struct ScopedSettingsDir {
    QTemporaryDir dir;
    ScopedSettingsDir() {
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope,
                           dir.path());
    }
};

// Service loop until pred() holds or the deadline expires (Qt queued
// connections deliver the host callbacks here; never spins hot).
template <typename Pred>
bool wait_until(const Pred& pred, int timeout_ms = 8000) {
    ensure_qt_app();
    QDeadlineTimer deadline(timeout_ms);
    while (!pred()) {
        if (deadline.hasExpired()) return false;
        QCoreApplication::processEvents(QEventLoop::AllEvents, 50);
        QThread::msleep(10);
    }
    return true;
}

struct HostRig {
    ScopedSettingsDir settings;
    std::unique_ptr<VizCJointHost> host;
    std::unique_ptr<JobCenter> job_center;
    // Destruction order (viz-c review C parity): the JobCenter dies
    // FIRST (members are destroyed in reverse declaration order), then
    // the host — its QObject-child JobOwners were already freed by the
    // JobCenter vector, so ~QObject must not see them first.
    explicit HostRig(const std::string& identity = {}) {
        ensure_qt_app();
        job_center = std::make_unique<JobCenter>();
        host = std::make_unique<VizCJointHost>(*job_center, nullptr, nullptr);
        // Surface the host's honest status lines (failed fence adds etc.)
        // so a failing assertion carries its cause.
        QObject::connect(host.get(),
                         &VizCJointHost::status_changed,
                         [](const QString& text) {
                             std::printf("  [host] %s\n",
                                         text.toUtf8().constData());
                         });
        if (!identity.empty()) host->set_project_identity(identity);
    }
};

std::shared_ptr<pwb::seismic_service::SeismicVolumeService>
make_service() {
    return std::make_shared<pwb::seismic_service::SeismicVolumeService>();
}

// Three heads with TD tables: in Time domain a well-order fence
// projects wells through TD (fail-closed without it — MD never stands
// in for TWT).
std::pair<std::vector<pwb::geo3d_viz::joint::WellHead>,
          std::map<std::string, pwb::geo3d_viz::joint::TimeDepthTable>>
three_wells(double tmax_ms) {
    std::vector<pwb::geo3d_viz::joint::WellHead> heads;
    std::map<std::string, pwb::geo3d_viz::joint::TimeDepthTable> tds;
    for (int i = 0; i < 3; ++i) {
        pwb::geo3d_viz::joint::WellHead head;
        head.id = "W" + std::to_string(i);
        head.name = head.id;
        head.x = 1000.0 + i * 40.0;
        head.y = 2000.0 + i * 10.0;
        head.bottom_x = head.x;
        head.bottom_y = head.y + 30.0;
        head.total_depth_m = 1000.0;
        heads.push_back(head);
        tds.emplace(head.id,
                    pwb::geo3d_viz::joint::TimeDepthTable(
                        head.id, {0.0, tmax_ms / 2.0, tmax_ms},
                        {0.0, 500.0, 1000.0}));
    }
    return {heads, tds};
}

}  // namespace

PWB_TEST(prep_pipeline_reads_on_worker_and_applies) {
    HostRig rig;
    const fs::path volume = fs::path(JOINT3D_FIXTURE_VOLUME);
    JOINT_REQUIRE(fs::exists(volume));
    QString error;
    JOINT_REQUIRE((rig.host->open_volume(make_service(), volume, &error)));
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().n_inline > 0;
    }));
    // The GUI was never blocked: the open call above already returned.

    const auto snapshot = rig.host->scene_snapshot();
    const double t0 = snapshot.time_min_ms;
    const double tmax = snapshot.time_max_ms;
    rig.host->add_time_slice((t0 + tmax) / 2.0);
    JOINT_REQUIRE(wait_until([&] {
        const auto prepared = rig.host->prepared_data();
        return prepared.active_sample >= 0 && !prepared.slice_rgba.empty();
    }));
    const auto prepared = rig.host->prepared_data();
    PWB_CHECK(static_cast<std::int64_t>(prepared.n_inline) ==
              rig.host->scene_snapshot().n_inline);
    PWB_CHECK(static_cast<std::int64_t>(prepared.n_crossline) ==
              rig.host->scene_snapshot().n_crossline);
    PWB_CHECK(prepared.slice_rgba.size() ==
              static_cast<std::size_t>(prepared.n_inline *
                                       prepared.n_crossline) * 4);
    PWB_CHECK(rig.host->shutdown(2000));
}

PWB_TEST(rapid_slice_changes_converge_without_blocking) {
    HostRig rig;
    const fs::path volume = fs::path(JOINT3D_FIXTURE_VOLUME);
    JOINT_REQUIRE((rig.host->open_volume(make_service(), volume, nullptr)));
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().n_inline > 0;
    }));
    const auto snapshot = rig.host->scene_snapshot();
    const double t0 = snapshot.time_min_ms;
    const double tmax = snapshot.time_max_ms;
    const double step = (tmax - t0) / 8.0;
    for (int i = 1; i <= 6; ++i) {
        // Before scrubbing again, let the prep worker actually pick the
        // request up: the #1471 window opens when a scrub CANCELS a
        // running read and the delivered finished callback reissues on
        // the same owner while the job is still pre-terminal — a bare
        // start() there throws logic_error out of a queued slot and the
        // process dies. (The deterministic guarantee is unit-tested at
        // reissue_when_terminal; this soak hits the real pipeline.)
        if (i > 1) {
            JOINT_REQUIRE(wait_until([&] { return rig.host->prep_in_flight(); },
                                     2000));
        }
        const auto started = std::chrono::steady_clock::now();
        rig.host->add_time_slice(t0 + step * i);
        rig.host->set_active_time_slice(t0 + step * i);
        const auto elapsed = std::chrono::steady_clock::now() - started;
        // The scrubbing calls must return promptly (no cold read on the
        // GUI thread — the worker converges in the background; the wait
        // below is the behavioural check). Generous bound: it only
        // catches a synchronous volume read, never scheduler jitter.
        const double elapsed_ms =
            std::chrono::duration<double, std::milli>(elapsed).count();
        PWB_CHECK(elapsed_ms < 250.0);
    }
    // Final state wins regardless of how the worker coalesced the run.
    const double target = t0 + step * 6;
    JOINT_REQUIRE(wait_until([&] {
        const auto snap = rig.host->scene_snapshot();
        return snap.active_time_ms.has_value() &&
               std::llround(*snap.active_time_ms) ==
                   std::llround(target) &&
               rig.host->prepared_data().active_sample >= 0;
    }));
    PWB_CHECK(rig.host->shutdown(2000));
}

PWB_TEST(multi_fence_visibility_and_activation) {
    HostRig rig;
    const fs::path volume = fs::path(JOINT3D_FIXTURE_VOLUME);
    JOINT_REQUIRE((rig.host->open_volume(make_service(), volume, nullptr)));
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().n_inline > 0;
    }));
    const auto snap0 = rig.host->scene_snapshot();
    auto wells = three_wells(snap0.time_max_ms);
    rig.host->set_wells(std::move(wells.first), std::move(wells.second));
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().well_presentations.size() == 3;
    }));
    rig.host->add_time_slice(snap0.time_max_ms / 2.0);
    // Well-pair fence first (well-order fence semantics: repeated calls
    // REUSE one fence — frozen Python parity), then a drawn/manual fence
    // as the second source: both coexist in one multi-fence scene.
    rig.host->add_well_to_well_fence("W0", "W1");
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().fences.size() == 1;
    }));
    rig.host->add_fence_vertices(
        {{1100.0, 2050.0}, {1400.0, 2150.0}, {1700.0, 2200.0}}, "Drawn");
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().fences.size() == 2;
    }));
    const std::string fence0 = rig.host->scene_snapshot().fences[0].id;
    const std::string fence1 = rig.host->scene_snapshot().fences[1].id;
    // Hide the first fence: only visible fences are prepared for render.
    rig.host->set_fence_visible(fence0, false);
    JOINT_REQUIRE(wait_until([&] {
        const auto& strips = rig.host->prepared_data().strips;
        return strips.size() == 1 && strips[0].fence_id == fence1;
    }));
    // Activate the remaining fence (2D profile follows the active one).
    rig.host->activate_fence(fence1);
    PWB_CHECK(rig.host->scene_snapshot().active_fence_id == fence1);
    PWB_CHECK(rig.host->shutdown(2000));
}

PWB_TEST(time_map_well_click_appends_fence) {
    // The VIZ-C port left VizCTimeSliceMap::well_clicked with ZERO
    // consumers — the documented click-to-fence flow (joint_widget.py:115)
    // was unreachable from the UI. joint_widget() now connects the signal
    // to the scene's append_fence_well; this regression freezes that
    // wiring (signal emission -> well-order fence grows, duplicates
    // ignored, non-piercing refused by the scene itself).
    HostRig rig;
    const fs::path volume = fs::path(JOINT3D_FIXTURE_VOLUME);
    JOINT_REQUIRE((rig.host->open_volume(make_service(), volume, nullptr)));
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().n_inline > 0;
    }));
    const auto snap0 = rig.host->scene_snapshot();
    auto wells = three_wells(snap0.time_max_ms);
    rig.host->set_wells(std::move(wells.first), std::move(wells.second));
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().well_presentations.size() == 3;
    }));
    rig.host->add_time_slice(snap0.time_max_ms / 2.0);
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().active_time_ms.has_value();
    }));
    auto* map = static_cast<pwb::app::viz_c::VizCTimeSliceMap*>(
        rig.host->joint_widget(nullptr));
    JOINT_REQUIRE(map != nullptr);
    // Signals are public in Qt6: emitting the map's own signal runs the
    // product connection exactly like a real click handler would.
    emit map->well_clicked(QStringLiteral("W0"));
    // One well: the well-order list holds it, but the fence itself only
    // materializes with >= 2 wells (a single vertex is no fence).
    JOINT_REQUIRE(wait_until([&] {
        const auto snap = rig.host->scene_snapshot();
        return snap.fence_well_ids.size() == 1;
    }));
    {
        const auto snap = rig.host->scene_snapshot();
        PWB_CHECK(snap.fence_well_ids[0] == "W0");
        PWB_CHECK(snap.fences.empty());
    }
    // Duplicate append: ignored (append_fence_well contract).
    emit map->well_clicked(QStringLiteral("W0"));
    QThread::msleep(50);
    ensure_qt_app()->processEvents();
    {
        const auto snap = rig.host->scene_snapshot();
        PWB_CHECK(snap.fence_well_ids.size() == 1);
    }
    // Second well materializes the well-order fence.
    emit map->well_clicked(QStringLiteral("W1"));
    JOINT_REQUIRE(wait_until([&] {
        const auto snap = rig.host->scene_snapshot();
        return snap.fence_well_ids.size() == 2 && snap.fences.size() == 1;
    }));
    PWB_CHECK(rig.host->shutdown(2000));
    delete map;
}

PWB_TEST(project_identity_scopes_persisted_state) {
    HostRig rig("project-A");
    const fs::path volume = fs::path(JOINT3D_FIXTURE_VOLUME);
    JOINT_REQUIRE((rig.host->open_volume(make_service(), volume, nullptr)));
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().n_inline > 0;
    }));
    const auto snap0 = rig.host->scene_snapshot();
    auto wells = three_wells(snap0.time_max_ms);
    rig.host->set_wells(std::move(wells.first), std::move(wells.second));
    rig.host->add_time_slice(snap0.time_max_ms / 2.0);
    rig.host->add_well_to_well_fence("W0", "W1");
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().fences.size() == 1;
    }));

    // Switch to another project: its own (empty) state applies — the
    // fence must not leak across the identity boundary.
    rig.host->set_project_identity("project-B");
    PWB_CHECK(rig.host->scene_snapshot().fences.empty());
    PWB_CHECK(rig.host->prepared_data().strips.empty());
    PWB_CHECK(rig.host->prepared_data().slice_rgba.empty());
    PWB_CHECK(rig.host->prep_applied_state() == false);

    // Back to the first identity: the persisted fence returns.
    rig.host->set_project_identity("project-A");
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().fences.size() == 1;
    }));
    PWB_CHECK(rig.host->shutdown(2000));
}

PWB_TEST(teardown_with_inflight_job_is_safe) {
    ensure_qt_app();
    // Destruction order (viz-c review C parity): the CENTER must die
    // first — declare the host before the center so reverse-order
    // teardown destroys the center (and its owner vector) before the
    // host's QObject tree.
    std::unique_ptr<VizCJointHost> host;
    std::unique_ptr<JobCenter> job_center =
        std::make_unique<JobCenter>();
    host = std::make_unique<VizCJointHost>(*job_center, nullptr, nullptr);
    QString error;
    // Fire the open and tear everything down while the job may still be
    // queued/running: the late payload must drop without touching the
    // dead host.
    PWB_CHECK((host->open_volume(make_service(),
                                 fs::path(JOINT3D_FIXTURE_VOLUME), &error)));
    QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
    // Open has landed (registration exists): put a PREP-lane read in
    // flight too, so the teardown covers both lanes with live jobs.
    QDeadlineTimer open_wait(8000);
    while (host->scene_snapshot().n_inline == 0 &&
           !open_wait.hasExpired()) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 50);
        QThread::msleep(10);
    }
    if (host->scene_snapshot().n_inline > 0) {
        host->add_time_slice(host->scene_snapshot().time_max_ms / 2.0);
    }
    QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
    job_center->shutdown_workers(2000);
    for (int i = 0; i < 50; ++i) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
        QThread::msleep(5);
    }
    // Member order (host first, center second) destroys the CENTER
    // first — the safe order. Reaching the end of this test without a
    // crash IS the assertion (MALLOC_CHECK_=3 audits the teardown,
    // including the dropped in-flight payloads).
}

PWB_TEST(binder_binds_real_wells_td_and_volume) {
    HostRig rig("binder-project");
    QTemporaryDir project_dir;
    JOINT_REQUIRE(project_dir.isValid());
    const fs::path realdata = fs::path(JOINT3D_REALDATA_DIR);

    // Staged payload copies (the store layout: project-relative paths).
    const fs::path heads_src = realdata / "ExportWellHead.dat";
    const fs::path td_src = realdata / "A1_td.dat";
    JOINT_REQUIRE(fs::exists(heads_src) && fs::exists(td_src));
    const fs::path project_root = fs::path(project_dir.path().toStdString());
    const fs::path heads_dst = project_root / "heads.dat";
    const fs::path td_dst = project_root / "td_a1.dat";
    fs::copy_file(heads_src, heads_dst, fs::copy_options::overwrite_existing);
    fs::copy_file(td_src, td_dst, fs::copy_options::overwrite_existing);

    pwb::data::ProjectSnapshotV1 snapshot;
    pwb::catalog::DataAsset heads_asset;
    heads_asset.id = pwb::domain::AssetId{std::string("asset-heads")};
    heads_asset.type = "well_head";
    snapshot.catalog_assets.push_back(heads_asset);
    pwb::catalog::DataAsset td_asset;
    td_asset.id = pwb::domain::AssetId{std::string("asset-td")};
    td_asset.type = "time_depth";
    snapshot.catalog_assets.push_back(td_asset);

    pwb::catalog::DataVersion heads_version;
    heads_version.id = pwb::domain::VersionId{std::string("v-heads")};
    heads_version.asset_id = heads_asset.id;
    heads_version.format = "dat";
    heads_version.path = "heads.dat";
    heads_version.created_at = "2026-09-19T00:00:00Z";
    snapshot.catalog_versions.push_back(heads_version);
    pwb::catalog::DataVersion td_version;
    td_version.id = pwb::domain::VersionId{std::string("v-td")};
    td_version.asset_id = td_asset.id;
    td_version.format = "dat";
    td_version.path = "td_a1.dat";
    td_version.created_at = "2026-09-19T00:00:00Z";
    snapshot.catalog_versions.push_back(td_version);
    // The volume: absolute fixture path (project_dir / absolute = the
    // absolute path itself).
    pwb::catalog::DataVersion volume_version;
    volume_version.id = pwb::domain::VersionId{std::string("v-vol")};
    volume_version.format = "PWBVOL1";
    volume_version.path = JOINT3D_FIXTURE_VOLUME;
    volume_version.created_at = "2026-09-19T00:00:00Z";
    snapshot.catalog_versions.push_back(volume_version);

    const auto outcome = pwb::app::closure_joint3d::bind_project_assets(
        *rig.host, snapshot, project_root, "binder-project");
    PWB_CHECK(outcome.volume_requested);
    PWB_CHECK(outcome.wells_bound == 3);   // A1, B2, C3 from the fixture
    PWB_CHECK(outcome.td_tables_bound >= 1);
    PWB_CHECK(outcome.message.find("井") != std::string::npos);
    // Identity + wells applied synchronously (parse-only payloads).
    PWB_CHECK(rig.host->project_identity() == "binder-project");
    JOINT_REQUIRE(wait_until([&] {
        return rig.host->scene_snapshot().n_inline > 0 &&
               rig.host->scene_snapshot().well_presentations.size() == 3;
    }));
    PWB_CHECK(rig.host->shutdown(2000));
}
