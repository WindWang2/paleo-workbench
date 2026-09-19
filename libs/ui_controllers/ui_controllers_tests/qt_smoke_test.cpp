// UI-14 — Qt offscreen smoke test: the QObject shells construct, their
// signals fire, the string-connect wire_* helpers bind real metaobjects,
// and a JobOwnerRunner drives a real JobScheduler job to completion on
// the GUI thread. QT_QPA_PLATFORM=offscreen (ctest pins it).

#include <cstdio>
#include <functional>
#include <string>
#include <vector>

#include <QAction>
#include <QApplication>
#include <QCoreApplication>
#include <QEventLoop>
#include <QObject>
#include <QThread>
#include <QToolBar>

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/ui_controllers/qt/data_lifecycle_controller.hpp>
#include <pwb/ui_controllers/qt/job_owner_runner.hpp>
#include <pwb/ui_controllers/qt/map_action_controller.hpp>
#include <pwb/ui_controllers/qt/project_controller.hpp>
#include <pwb/ui_controllers/qt/view_coordination_controller.hpp>
#include <pwb/ui_controllers/qt/workflow_controller.hpp>

using namespace pwb;
using namespace pwb::ui_controllers;
using namespace pwb::ui_controllers::qt;

namespace {

int g_failures = 0;

void check(bool condition, const char* expr, int line) {
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %d: %s\n", line, expr);
    }
}
#define CHECK(expr) check((expr), #expr, __LINE__)
#define CHECK_EQ(a, b) check((a) == (b), #a " == " #b, __LINE__)

// Pumps queued deliveries until `condition` holds or ~5 s elapsed.
void pump_events(const std::function<bool()>& condition) {
    for (int i = 0; i < 500 && !condition(); ++i) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(5);
    }
}

// A page stand-in carrying the signals wire_* binds by metaobject name.
class FakeHomePage : public QObject {
    Q_OBJECT
public:
    using QObject::QObject;
signals:
    void navigation_requested(int legacy_index);
    void workflow_step_clicked(const QString& step_id);
};

// ---------------------------------------------------------------- tests --

void test_map_action_controller() {
    MapActionController controller;
    QAction* pan = controller.action("pan");
    CHECK(pan != nullptr);
    CHECK(pan->isCheckable());
    CHECK(controller.action("full_extent") != nullptr);
    CHECK(!controller.action("full_extent")->isCheckable());
    CHECK(controller.action("no_such_action") == nullptr);

    // apply_availability writes enabled/tooltip/statusTip from the verdict.
    tool_policy::ToolAvailability verdict;
    verdict.enabled = false;
    verdict.visible = true;
    verdict.disabled_reason = "需要编图页";
    controller.apply_availability({{"pan", verdict}});
    CHECK(!pan->isEnabled());
    CHECK(pan->toolTip().contains("需要编图页"));
    CHECK(pan->statusTip().contains("需要编图页"));

    // Toolbar: separator BEFORE grouped entries (never for lone ids).
    std::unique_ptr<QToolBar> bar(controller.toolbar(
        QStringLiteral("编图"),
        {{"pan", "zoom_in"}, {"full_extent"}, {"select", "vertex"}}));
    const auto actions = bar->actions();
    // pan zoom_in full_extent <sep> select vertex — the lone id got none.
    int separators = 0;
    for (auto* action : actions)
        if (action->isSeparator()) ++separators;
    CHECK_EQ(separators, 1);
    CHECK_EQ(actions.size(), 6);

    // Triggering a checkable tool emits tool_requested checked-only.
    QString tool_id;
    QObject::connect(&controller, &MapActionController::tool_requested,
                     [&](const QString& id) { tool_id = id; });
    QString command_id;
    QObject::connect(&controller, &MapActionController::command_requested,
                     [&](const QString& id) { command_id = id; });
    controller.action("zoom_in")->trigger();
    CHECK_EQ(tool_id, "zoom_in");
    controller.action("full_extent")->trigger();
    CHECK_EQ(command_id, "full_extent");
    CHECK_EQ(tool_id, "zoom_in");  // commands never mutate the tool signal
}

void test_selection_context_and_coordination() {
    QtSelectionContext selection;
    ViewCoordinationController controller(&selection);

    int emissions = 0;
    QtSelectionContext* emitted_from = nullptr;
    QObject::connect(&selection, &QtSelectionContext::selection_changed,
                     [&](QtSelectionContext* ctx) {
                         ++emissions;
                         emitted_from = ctx;
                     });
    selection.publish_well_selection("W-1", {"W-1"}, "test");
    CHECK_EQ(emissions, 1);
    CHECK(emitted_from == &selection);
    CHECK(selection.bus().state().active_well_id &&
          *selection.bus().state().active_well_id == "W-1");

    // The controller's publish slot routes through the same bus.
    QString docked;
    controller.set_well_dock_sink(
        [&](std::string name) { docked = QString::fromStdString(name); });
    controller.publish_well_selection("W-9", "test_source");
    CHECK_EQ(docked, "W-9");
    CHECK(selection.bus().source_widget_id() &&
          *selection.bus().source_widget_id() == "test_source");

    // bind_project registers wells into the name↔id index.
    controller.bind_project(domain::Json::parse(R"json({
        "wells": [{"id": "w1", "name": "W-1",
                   "surface_x": 1.0, "surface_y": 2.0}]
    })json"));
    const auto [name, entity] = controller.resolve_well_key("w1");
    CHECK(name && *name == "W-1");
    controller.clear_project();
}

void test_job_owner_runner() {
    job::JobScheduler scheduler(job::JobScheduler::Options{.max_workers = 1});
    JobOwnerRunner runner(scheduler);
    CHECK(!runner.is_running());

    std::atomic<bool> finished{false};
    std::atomic<bool> on_app_thread{false};
    auto* app = QCoreApplication::instance();
    job::JobSpec spec;
    spec.run = [](job::JobContext&) -> std::any {
        return std::string("payload");
    };
    runner.start(std::move(spec), [&](const UiJobOutcome& outcome) {
        CHECK(outcome.state == job::JobState::done);
        const auto* payload = outcome.try_result<std::string>();
        CHECK(payload != nullptr && *payload == "payload");
        on_app_thread = (QThread::currentThread() == app->thread());
        finished = true;
    });
    pump_events([&] { return finished.load(); });
    CHECK(finished);
    CHECK(on_app_thread);
    CHECK(runner.shutdown(2000));
}

void test_project_controller_shell() {
    job::JobScheduler scheduler(job::JobScheduler::Options{.max_workers = 1});
    ProjectController controller(scheduler);

    project::ProjectDocument doc =
        project::ProjectDocument::create_new("demo", "");
    auto* doc_ptr = &doc;
    int shell_refreshes = 0;
    controller.host_api().document = [&] { return doc_ptr; };
    controller.host_api().replace_document =
        [&](project::ProjectDocument&& next) {
            doc = std::move(next);
            doc_ptr = &doc;
        };
    controller.host_api().refresh_shell = [&](bool) { ++shell_refreshes; };

    // Lazy core: materializes on first use, keeps state after.
    controller.new_project("fresh");
    CHECK_EQ(shell_refreshes, 1);
    CHECK_EQ(controller.core().session_generation(), 1);
}

void test_data_lifecycle_shell() {
    job::JobScheduler scheduler(job::JobScheduler::Options{.max_workers = 1});
    DataLifecycleController controller(scheduler);
    CHECK(controller.catalog_job() != nullptr);
    CHECK(controller.verify_job() != nullptr);

    project::ProjectDocument doc =
        project::ProjectDocument::create_new("demo", "");
    controller.page_api().document = [&] { return &doc; };
    // core() materializes lazily like the project shell.
    auto& core = controller.core();
    CHECK(&core != nullptr);
}

void test_workflow_shell() {
    job::JobScheduler scheduler(job::JobScheduler::Options{.max_workers = 1});
    WorkflowController controller(scheduler);

    project::ProjectDocument doc =
        project::ProjectDocument::create_new("demo", "");
    controller.page_api().document = [&] { return &doc; };
    // The seam bag copies into the core at materialization — set before
    // the first core() use.
    int navigations = 0;
    controller.page_api().navigate_to = [&](int, const std::string&) {
        ++navigations;
    };
    auto& core = controller.core();
    CHECK(&core != nullptr);

    // wire_home_page connects the page's signals by metaobject name.
    FakeHomePage page;
    int probe = 0;
    QObject::connect(&page, &FakeHomePage::navigation_requested,
                     [&](int) { ++probe; });
    controller.wire_home_page(&page);
    emit page.navigation_requested(0);
    CHECK_EQ(probe, 1);  // emit fires at all
    CHECK_EQ(navigations, 1);
    // A page without the signal is a safe no-op (hasattr parity).
    QObject bare;
    controller.wire_home_page(&bare);
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    struct Case {
        const char* name;
        void (*fn)();
    };
    const Case cases[] = {
        {"map_action_controller", test_map_action_controller},
        {"selection_context_and_coordination",
         test_selection_context_and_coordination},
        {"job_owner_runner", test_job_owner_runner},
        {"project_controller_shell", test_project_controller_shell},
        {"data_lifecycle_shell", test_data_lifecycle_shell},
        {"workflow_shell", test_workflow_shell},
    };
    for (const auto& test : cases) {
        const int before = g_failures;
        test.fn();
        std::fprintf(stderr, "%s %s\n",
                     g_failures == before ? "PASS" : "FAILED", test.name);
    }
    if (g_failures != 0) {
        std::fprintf(stderr, "ui_controllers.qt_smoke: %d failure(s)\n",
                     g_failures);
        return 1;
    }
    return 0;
}

#include "qt_smoke_test.moc"
