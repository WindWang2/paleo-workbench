// closure_science.qt_hooks — the prediction pages' production binding,
// exercised offscreen through the pages' real entry points:
//   * no project  -> catalog_connected=false guard, no task, no crash;
//   * demo run    -> seismic page on_demo() drives the whole chain
//     (demo model seed -> run -> worker -> demo provider -> catalog result
//     version -> task materialization + journal record);
//   * production  -> on_run() without a promoted model keeps the honest
//     "未配置生产模型" state (no task fabricated);
//   * restore     -> the journal re-reads the recorded task.

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif
namespace { long test_pid() {
#ifdef _WIN32
    return static_cast<long>(_getpid());
#else
    return static_cast<long>(::getpid());
#endif
} }

#include <QApplication>
#include <QTimer>
#include <QtTest/QSignalSpy>
#include <QtTest/QTest>

#include <filesystem>
#include <string>
#include <vector>

#include <pwb/closure_science/qt/page_binding.hpp>
#include <pwb/closure_science/task_journal.hpp>
#include <pwb/catalog/service_core.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>

namespace fs = std::filesystem;
namespace catalog = pwb::catalog;
using pwb::domain::Json;

// QTRY-free bounded wait (plain event-loop processing; the completion
// arrives via a queued invocation from the binding's worker thread).
bool wait_for_signal(const QSignalSpy& spy, int count, int timeout_ms) {
    for (int elapsed = 0; elapsed < timeout_ms && spy.count() < count;
         elapsed += 50) {
        QApplication::processEvents();
        QTest::qWait(50);
    }
    return spy.count() >= count;
}

// The pages' guard chains raise modal warnings (Python QMessageBox parity);
// offscreen tests auto-dismiss them after a tick.
void auto_close_modals(int after_ms = 60) {
    QTimer::singleShot(after_ms, [] {
        if (auto* modal = QApplication::activeModalWidget()) {
            modal->close();
        }
    });
}

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

void require(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FATAL %s\n", what.c_str());
        std::exit(2);
    }
}

struct TestProject {
    fs::path dir;
    fs::path project_file;
};

TestProject make_project(const std::string& name) {
    TestProject project;
    project.dir = fs::temp_directory_path() /
                  ("closure_science_qt_" + name + "_" +
                   std::to_string(static_cast<long long>(test_pid())));
    fs::remove_all(project.dir);
    fs::create_directories(project.dir);
    project.project_file = project.dir / (name + ".paleo.json");
    fs::create_directories(project.dir / (name + ".artifacts"));
    // A real project file (the binding opens the canonical catalog through
    // open_catalog, which reads the project's paths).
    auto document = pwb::project::ProjectDocument::create_new(name, "");
    pwb::project::ProjectManager manager(project.project_file);
    auto saved = manager.save(document);
    if (!saved.is_ok()) {
        std::fprintf(stderr, "FATAL project save: %s\n",
                     saved.error().message.c_str());
        std::exit(2);
    }
    return project;
}

}  // namespace

int main(int argc, char** argv) {
    qputenv("QT_QPA_PLATFORM", "offscreen");
    QApplication app(argc, argv);

    // --- no project: honest unavailable guard ----------------------------
    pwb::ui_wellseis::qt::SeismicPredictionPage orphan_seismic;
    pwb::ui_wellseis::qt::WellLogPredictionPage orphan_well;
    auto* orphan_binding = pwb::closure_science::qt::attach_prediction_pages(
        orphan_well, orphan_seismic, []() { return fs::path(); });
    QSignalSpy orphan_spy(&orphan_seismic,
                          &pwb::ui_wellseis::qt::SeismicPredictionPage::
                              prediction_updated);
    auto_close_modals();
    orphan_seismic.on_demo();
    QTest::qWait(300);
    check(orphan_spy.count() == 0,
          "no project -> no task, no fabricated run");

    // --- demo run through the real page chain ----------------------------
    const TestProject project = make_project("demo");
    pwb::ui_wellseis::qt::SeismicPredictionPage seismic_page;
    pwb::ui_wellseis::qt::WellLogPredictionPage well_page;
    pwb::ui_wellseis::ResourceSlice seismic_resource;
    seismic_resource.id = "res-seismic-ui";
    seismic_resource.name = "演示地震体";
    seismic_resource.type = "seismic";
    pwb::ui_wellseis::ProjectSlice project_slice;
    project_slice.resources.push_back(seismic_resource);
    project_slice.project_crs = "EPSG:32650";
    auto* binding = pwb::closure_science::qt::attach_prediction_pages(
        well_page, seismic_page,
        [&]() { return project.project_file; });
    QSignalSpy updated_spy(&seismic_page,
                           &pwb::ui_wellseis::qt::SeismicPredictionPage::
                               prediction_updated);

    seismic_page.set_project(&project_slice);
    well_page.set_project(&project_slice);
    seismic_page.on_demo();
    check(wait_for_signal(updated_spy, 1, 30000),
          "demo run completes through the real page chain");

    // The run + result version landed in the project's catalog.
    auto opened = catalog::open_catalog(project.project_file);
    require(opened.is_ok(), "catalog reopens");
    {
        catalog::CatalogServiceCore core(std::move(opened.value()));
        bool saw_running_result = false;
        int prediction_runs = 0;
        for (const auto& run : core.document().runs) {
            if (run.operation == "prediction") {
                ++prediction_runs;
                saw_running_result |= run.status == "complete" &&
                                      run.output_version_ids.size() == 1;
            }
        }
        check(prediction_runs == 1, "one prediction run recorded");
        check(saw_running_result,
              "run completed with one linked output version");
    }

    // Journal restore re-reads the recorded task.
    auto restored = binding->restored_tasks();
    check(restored.size() == 1, "journal restores the recorded task");

    // Second demo run: the finished worker thread was never joined (the
    // only join lives in shutdown), so re-launching used to move-assign
    // over a joinable std::thread and std::terminate() the whole process
    // (#1443). The regression proof is simply surviving to completion.
    seismic_page.on_demo();
    check(wait_for_signal(updated_spy, 2, 30000),
          "second demo run survives the unjoined previous worker");

    // Production run without a promoted model: honest modal warning, no
    // task fabricated.
    QSignalSpy run_spy(&seismic_page,
                       &pwb::ui_wellseis::qt::SeismicPredictionPage::
                           prediction_updated);
    auto_close_modals();
    seismic_page.on_run();
    QTest::qWait(400);
    check(run_spy.count() == 0,
          "no production model -> no task fabricated");

    check(binding->shutdown_workers(5000), "worker shutdown completes");

    delete orphan_binding;
    delete binding;
    fs::remove_all(project.dir);

    if (g_failures != 0) {
        std::fprintf(stderr, "%d failure(s)\n", g_failures);
        return 1;
    }
    std::fprintf(stderr, "closure_science.qt_hooks: all checks passed\n");
    return 0;
}
