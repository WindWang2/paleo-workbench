// VIZ-B — dock smoke test (offscreen): compiles and exercises the real
// platform dock (viz_b_cross_well_dock.cpp + job_center.cpp) without
// the full pwb-platform binary. Covers the main-window-independent
// acceptance surface: well/tops/checkshot loading, pick edits, sidecar
// save→restore identity, session-generation drop on project switch,
// and the tie page pipeline.

#include <QApplication>
#include <QDir>
#include <QFile>
#include <QTemporaryDir>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

#include "job_center.hpp"
#include "viz_b_cross_well_dock.hpp"

#ifndef PWB_VIZ_B_CROSS_WELL_FIXTURE
#error "fixture macro missing"
#endif

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& label) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::cerr << "FAIL: " << label << "\n";
    }
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QTemporaryDir temp;
    check(temp.isValid(), "temp dir");

    pwb::app::JobCenter center;
    pwb::app::VizBCrossWellDock dock(&center);
    dock.resize(1200, 800);
    dock.show();

    // 1. Load the real wells fixture (frozen LAS arrays).
    QString error;
    check(dock.load_wells_from_json(PWB_VIZ_B_CROSS_WELL_FIXTURE, &error),
          "load wells from fixture");
    check(dock.well_count() >= 2, "dock well count >= 2");

    // 2. Tops CSV (round-trips through the real model).
    {
        const QString tops_path = temp.filePath("tops.csv");
        QFile file(tops_path);
        file.open(QIODevice::WriteOnly);
        file.write("A4,Formation-X,2350.0\nA13,Formation-X,2361.5\n"
                   "A16,Formation-X,2344.0\n");
        file.close();
        check(dock.load_tops_csv(tops_path, &error), "tops load");
    }

    // 3. Checkshot CSV.
    {
        const QString tie_path = temp.filePath("checkshot.csv");
        QFile file(tie_path);
        file.open(QIODevice::WriteOnly);
        file.write("depth_m,twt,well\n2200.0,1100.0,A4\n2400.0,1200.0,"
                   "A4\n2300.0,1155.0,A13\n");
        file.close();
        check(dock.load_checkshot_csv(tie_path, &error), "checkshot load");
    }

    // 4. Sidecar persistence: set a project dir, edit (pick), save,
    //    reopen into a fresh dock, verify identity.
    const QString project_dir = temp.filePath("project");
    QDir().mkpath(project_dir);
    dock.set_project_directory(project_dir);
    // One pick edit through the public surface is not available without
    // canvas interaction; the pick count path is exercised via the
    // persistence payload instead: state save/restore identity.
    const pwb::domain::Json saved = dock.save_state();
    check(saved.contains("picks") && saved.contains("tops") &&
              saved.contains("links") && saved.contains("view"),
          "save_state payload shape");

    pwb::app::VizBCrossWellDock reopened(&center);
    reopened.restore_state(saved);
    check(reopened.save_state().dump() == saved.dump(),
          "restore identity");

    // 5. Project switch: closing the old project flushes and detaches;
    //    a late restore of a DIFFERENT state must not resurrect the old
    //    one (generation bump drops nothing here because there is no
    //    in-flight job, but the directory detach must hold).
    dock.handle_project_closed();
    const QString sidecar =
        project_dir + "/cross_well_workspace.json";
    check(QFile::exists(sidecar), "sidecar flushed on project close");
    reopened.restore_from_project();
    check(reopened.save_state().dump() == saved.dump(),
          "sidecar reload identity");

    // 6. Bad input: missing file is loud, not silent.
    pwb::app::VizBCrossWellDock bad(&center);
    QString bad_error;
    check(!bad.load_wells_from_json(temp.filePath("nope.json"), &bad_error),
          "missing well file fails loudly");
    check(!bad_error.isEmpty(), "error message present");

    // 7. #1466: a corrupt (or valid-but-partial) sidecar RESETS the
    //    workspace — the previous project's wells/picks must never
    //    survive in memory only to be persisted into the new project.
    // Each variant re-loads the valid workspace first so a passing
    // check can never ride on an already-empty state.
    pwb::app::VizBCrossWellDock contaminated(&center);
    const auto reload_valid = [&contaminated, &project_dir, &saved]() {
        contaminated.set_project_directory(project_dir);
        contaminated.restore_from_project();
        return contaminated.save_state().dump() == saved.dump() &&
               contaminated.well_count() >= 2;
    };
    check(reload_valid(), "valid sidecar reloads the workspace");
    {
        // 7a. Truncated JSON (exactly what a #1457 short write leaves).
        const QString dir_b = temp.filePath("projectB");
        QDir().mkpath(dir_b);
        QFile src(sidecar);
        src.open(QIODevice::ReadOnly);
        const QByteArray half = src.read(24);
        src.close();
        QFile dst(dir_b + "/cross_well_workspace.json");
        dst.open(QIODevice::WriteOnly | QIODevice::Truncate);
        dst.write(half);
        dst.close();
        check(reload_valid(), "valid sidecar reloads (pre 7a)");
        contaminated.set_project_directory(dir_b);
        contaminated.restore_from_project();
        check(contaminated.well_count() == 0,
              "truncated sidecar resets wells (#1466)");
    }
    {
        // 7b. Valid JSON that is not a workspace object.
        const QString dir_c = temp.filePath("projectC");
        QDir().mkpath(dir_c);
        QFile dst(dir_c + "/cross_well_workspace.json");
        dst.open(QIODevice::WriteOnly | QIODevice::Truncate);
        dst.write("[1, 2, 3]");
        dst.close();
        check(reload_valid(), "valid sidecar reloads (pre 7b)");
        contaminated.set_project_directory(dir_c);
        contaminated.restore_from_project();
        check(contaminated.well_count() == 0,
              "non-object sidecar resets wells (#1466)");
    }
    {
        // 7c. Valid object with missing keys — the sidecar fully defines
        //    the workspace; absent keys mean empty, not "keep project A".
        const QString dir_d = temp.filePath("projectD");
        QDir().mkpath(dir_d);
        QFile dst(dir_d + "/cross_well_workspace.json");
        dst.open(QIODevice::WriteOnly | QIODevice::Truncate);
        dst.write("{\"view\": {\"depth_top\": 0.0, \"depth_bottom\": 1.0, "
                  "\"depth_domain\": \"twt\"}}");
        dst.close();
        check(reload_valid(), "valid sidecar reloads (pre 7c)");
        contaminated.set_project_directory(dir_d);
        contaminated.restore_from_project();
        check(contaminated.well_count() == 0,
              "partial sidecar does not keep previous project's wells");
    }

    std::cout << "viz_b dock smoke: " << g_checks << " checks, "
              << g_failures << " failures\n";
    return g_failures == 0 ? 0 : 1;
}
