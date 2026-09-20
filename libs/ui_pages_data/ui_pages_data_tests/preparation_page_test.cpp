// 08-line closure — PreparationPage lifecycle test (offscreen).
//
// preparation_page.cpp never existed until this slice; this test drives
// the page guards through fake panel seams and fake domain seams:
// generation guard on progress, stale-result discard, project-switch
// supersede, enable/disable windows, contour commit paths and the
// no-project QC message.

#include <QApplication>
#include <QLabel>
#include <QPushButton>
#include <QSignalSpy>
#include <QTimer>

#include <cstdio>
#include <string>

#include <pwb/ui_pages_data/qt/preparation_page.hpp>

using pwb::ui_pages_data::qt::FactorPreviewGridApi;
using pwb::ui_pages_data::qt::FactorTaskPanelApi;
using pwb::ui_pages_data::qt::PrepareProgressView;
using pwb::ui_pages_data::qt::PrepareResultView;
using pwb::ui_pages_data::qt::PreparationPage;
using pwb::ui_pages_data::qt::WellTablePanelApi;

namespace {

int failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    } else {
        std::fprintf(stdout, "PASS %s\n", what);
    }
}

// Close whatever modal box the action opens (offscreen parity of a user
// clicking the dialog away).
void with_modal_close(const std::function<void()>& action) {
    QTimer::singleShot(0, [] {
        if (auto* popup = QApplication::activeModalWidget()) {
            popup->close();
        }
    });
    action();
    QApplication::processEvents();
}

class FakeTaskPanel final : public FactorTaskPanelApi {
public:
    explicit FakeTaskPanel(QWidget* parent = nullptr) : FactorTaskPanelApi(parent) {
        generate_btn_.setParent(this);
        contour_btn_.setParent(this);
        summary_.setParent(this);
        // Real-panel wiring parity: buttons carry the page signals.
        connect(&generate_btn_, &QPushButton::clicked, this, [this] {
            emit generate_requested(selected_method());
        });
        connect(&contour_btn_, &QPushButton::clicked, this,
                [this] { emit contour_draft_requested(); });
    }
    QString selected_method() const override { return "isochores"; }
    void update_state(const pwb::domain::Json& tasks) override {
        last_tasks = tasks;
    }
    QPushButton* generate_btn() override { return &generate_btn_; }
    QPushButton* contour_draft_btn() override { return &contour_btn_; }
    QLabel* summary_label() override { return &summary_; }

    pwb::domain::Json last_tasks;
    QPushButton generate_btn_;
    QPushButton contour_btn_;
    QLabel summary_;
};

class FakeWellTablePanel final : public WellTablePanelApi {
public:
    explicit FakeWellTablePanel(QWidget* parent = nullptr)
        : WellTablePanelApi(parent) {
        qc_btn_.setParent(this);
    }
    QPushButton* run_qc_btn() override { return &qc_btn_; }
    void update_from_well_table(void* table) override { last_table = table; }

    void* last_table = nullptr;
    QPushButton qc_btn_;
};

class FakePreviewGrid final : public FactorPreviewGridApi {
public:
    void update_state(const pwb::domain::Json& tasks) override {
        last_tasks = tasks;
    }
    pwb::domain::Json last_tasks;
};

// Minimal fake "project": just the factor tasks array the commit mutates.
struct FakeProject {
    pwb::domain::Json tasks = pwb::domain::Json::array();
};

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    PreparationPage page;
    FakeTaskPanel task_panel;
    FakeWellTablePanel well_panel;
    FakePreviewGrid grid;
    page.set_task_panel(&task_panel);
    page.set_well_table_panel(&well_panel);
    page.set_preview_grid(&grid);

    QSignalSpy factor_maps(&page, &PreparationPage::factor_maps_updated);
    QSignalSpy contour_updated(&page,
                               &PreparationPage::contour_drafts_updated);
    QSignalSpy upward(&page, &PreparationPage::generate_requested);

    // --- no project: generate is forwarded upward, QC shows the native
    // "请先打开或绑定工程。" box.
    check(!page.is_prepare_running(), "idle page not running");
    with_modal_close([&] { task_panel.generate_btn()->click(); });
    check(upward.count() == 1, "no-project generate forwarded upward");
    with_modal_close([&] { well_panel.qc_btn_.click(); });
    check(well_panel.last_table == nullptr, "no-project table stays null");

    // --- bind project + fake domain seams ---------------------------------
    FakeProject project;
    project.tasks = pwb::domain::Json::array();
    page.set_project(&project);

    int generation = 0;
    page.set_generation_fns([&generation] { return ++generation; },
                            [&generation] { return generation; });
    page.set_snapshot_task_count_fn(
        [](void*, const std::string&, int) { return 3; });

    // The fake worker records its invocation and runs the whole batch
    // synchronously (terminal callbacks run on the "UI thread" by contract).
    struct StartedWorker {
        void* project = nullptr;
        std::string method;
        int generation = 0;
        bool valid = false;
    } started;
    std::function<void(const PrepareProgressView&)> emit_progress;
    std::function<void(const PrepareResultView&)> emit_completed;
    page.set_prepare_worker_fn(
        [&](void* project, const std::string& method, int gen,
            std::function<void(const PrepareProgressView&)> progress,
            std::function<void(const PrepareResultView&)> completed,
            std::function<void(const QString&)>, std::function<void()>) {
            started = {project, method, gen, true};
            emit_progress = std::move(progress);
            emit_completed = std::move(completed);
        });
    page.set_commit_prepare_fn(
        [](void* project, const PrepareResultView& result, int) {
            // Mutate the fake project like the real commit does.
            static_cast<FakeProject*>(project)->tasks = pwb::domain::Json::array({
                pwb::domain::Json{{"id", "t1"}, {"status", "complete"}},
                pwb::domain::Json{{"id", "t2"}, {"status", "complete"}},
                pwb::domain::Json{{"id", "t3"}, {"status", "failed"}},
            });
            return result.generation > 0 ? 1 : 0;  // one stale discard
        });
    page.set_factor_map_tasks_fn(
        [](void* project) {
            return static_cast<FakeProject*>(project)->tasks;
        });

    // --- run a prepare batch ----------------------------------------------
    task_panel.generate_btn()->click();
    check(started.valid && started.method == "isochores",
          "worker started with panel method");
    check(started.generation == 1, "generation seeded from seam");
    check(!task_panel.generate_btn()->isEnabled(),
          "generate disabled while running");

    const PrepareProgressView progress{1, 1, 2, 2, 3, "gridding", ""};
    emit_progress(progress);
    check(task_panel.summary_.text().contains("复用 1"),
          "progress summary rendered");

    const PrepareResultView result{1, 1, 2, nullptr};
    emit_completed(result);
    check(task_panel.generate_btn()->isEnabled(),
          "generate re-enabled after completion");
    check(factor_maps.count() == 1, "factor_maps_updated emitted");
    check(task_panel.summary_.text().contains("已制备 2 / 3"),
          "done summary rendered");
    check(task_panel.last_tasks.size() == 3, "page state updated from commit");
    check(grid.last_tasks.size() == 3, "preview grid updated");

    // --- stale completion is ignored ---------------------------------------
    const PrepareResultView stale{0, 0, 0, nullptr};  // wrong generation
    emit_completed(stale);
    check(factor_maps.count() == 1, "stale result does not re-emit");
    check(task_panel.generate_btn()->isEnabled(),
          "buttons untouched by stale result");

    // --- project switch supersedes an in-flight run -------------------------
    FakeProject other;
    generation = 5;  // worker "still running" for project 1
    // Simulate a running job seam.
    bool running = true;
    bool cancel_called = false;
    page.set_prepare_job(
        {[&running] { return running; }, [](int) { return true; },
         [&cancel_called] { cancel_called = true; },
         [&project]() -> void* { return &project; }});
    page.set_project(&other);
    check(cancel_called, "project switch cancels in-flight job");
    check(generation == 6, "project switch supersedes generation");
    running = false;
    page.set_prepare_job(pwb::ui_pages_data::qt::WorkerJobApi{});

    // --- contour flow -------------------------------------------------------
    page.set_commit_contour_fn(
        [](void* project, void*) {
            static_cast<FakeProject*>(project)->tasks = pwb::domain::Json::array(
                {pwb::domain::Json{{"id", "t1"}, {"status", "complete"}}});
            return 2;
        });
    page.set_factor_map_tasks_fn(
        [](void* project) {
            return static_cast<FakeProject*>(project)->tasks;
        });
    std::function<void(void*)> emit_contour;
    page.set_contour_worker_fn(
        [&](void*, std::function<void(void*)> completed,
            std::function<void(const QString&)>) {
            emit_contour = std::move(completed);
        });
    task_panel.contour_btn_.click();
    check(emit_contour != nullptr, "contour worker started");
    int payload = 0;
    emit_contour(&payload);
    check(contour_updated.count() == 1, "contour_drafts_updated emitted");
    check(task_panel.summary_.text().contains("已生成 2 份"),
          "contour done summary rendered");
    // Empty commit → honest empty summary, no signal.
    page.set_commit_contour_fn([](void*, void*) { return 0; });
    std::function<void(void*)> emit_contour2;
    page.set_contour_worker_fn(
        [&](void*, std::function<void(void*)> completed,
            std::function<void(const QString&)>) {
            emit_contour2 = std::move(completed);
        });
    task_panel.contour_btn_.click();
    emit_contour2(&payload);
    check(contour_updated.count() == 1, "empty contour does not emit");
    check(task_panel.summary_.text().contains("没有可提取"),
          "contour empty summary rendered");

    // --- shutdown ------------------------------------------------------------
    check(page.shutdown_workers(100), "shutdown joins cleanly");

    if (failures == 0) {
        std::fprintf(stdout, "preparation_page_test: all checks passed\n");
        return 0;
    }
    std::fprintf(stderr, "preparation_page_test: %d failures\n", failures);
    return 1;
}
