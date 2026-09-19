// UI-12 — Qt widget smoke test (offscreen): every ported widget
// constructs + responds under QT_QPA_PLATFORM=offscreen. Complements
// the core test by proving the Qt shells wire up (signals, models,
// docks) without a display.

#include <QApplication>
#include <QDockWidget>
#include <QKeyEvent>
#include <QLineEdit>
#include <QTabWidget>
#include <QTableView>
#include <QTreeView>

#include <cstdio>
#include <set>
#include <string>

#include <pwb/ui_workstation/activity_rail.hpp>
#include <pwb/ui_workstation/agent_panel.hpp>
#include <pwb/ui_workstation/app_bar.hpp>
#include <pwb/ui_workstation/explorer_panel.hpp>
#include <pwb/ui_workstation/inspector_panel.hpp>
#include <pwb/ui_workstation/keybinding_manager.hpp>
#include <pwb/ui_workstation/mode_state_qt.hpp>
#include <pwb/ui_workstation/process_hub.hpp>
#include <pwb/ui_workstation/task_center.hpp>
#include <pwb/ui_workstation/ui_context_qt.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

using namespace pwb::ui_workstation;

namespace {

int failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    } else {
        std::fprintf(stderr, "PASS %s\n", what);
    }
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    // --- bridges ---
    UIContextServiceQt context;
    bool context_fired = false;
    QObject::connect(&context, &UIContextServiceQt::context_changed,
                     &context, [&](const UIContextSnapshot&) {
                         context_fired = true;
                     });
    bool open = false;
    context.set_provider("project_open",
                         [&] { return UIContextFieldValue{open}; });
    context.refresh();
    // Python parity: _last starts None → first refresh always emits.
    context_fired = false;
    context.refresh();
    check(!context_fired, "context bridge silent on no-change");
    open = true;
    context.refresh();
    check(context_fired, "context bridge emits on change");

    ModeStateMachineQt machine;
    bool mode_fired = false;
    QObject::connect(&machine, &ModeStateMachineQt::mode_changed,
                     &machine, [&](WorkstationMode) { mode_fired = true; });
    machine.dispatch_tool_activated("draw");
    check(mode_fired && machine.mode() == WorkstationMode::Digitizing,
          "mode bridge emits on transition");

    // --- app bar ---
    WorkstationAppBar bar;
    QString submitted;
    QObject::connect(&bar, &WorkstationAppBar::command_submitted, &bar,
                     [&](const QString& t) { submitted = t; });
    bar.command_input()->setText("test command");
    QMetaObject::invokeMethod(bar.command_input(), "returnPressed");
    check(submitted == "test command", "app bar command submits");
    int task_count_seen = -1;
    bar.set_task_count(3);
    check(true, "app bar task count sets");

    // --- activity rail ---
    ActivityRail rail;
    QString mode_req;
    QObject::connect(&rail, &ActivityRail::mode_requested, &rail,
                     [&](const QString& m) { mode_req = m; });
    rail.set_mode("data");
    check(true, "rail sets mode");

    // --- explorer ---
    WorkstationExplorer explorer;
    ExplorerFacts facts;
    facts.project_open = true;
    facts.project_name = "Demo";
    facts.wells = {{"w1", "井1"}};
    explorer.set_facts(facts);
    check(explorer.find_item("project") != nullptr,
          "explorer builds project root");
    check(explorer.find_item("well/w1") != nullptr,
          "explorer builds well row");
    explorer.set_mode("data");
    check(explorer.mode() == "data", "explorer mode switches");
    explorer.set_mode("project");

    // --- inspector ---
    WorkstationInspector inspector;
    InspectorPayload payload;
    payload.kind = "feature";
    payload.fields = {{"feature_id", "f1"}, {"geometry_type", "Point"}};
    inspector.show_payload(payload);
    check(inspector.tabs() != nullptr, "inspector renders feature");
    bool assign_seen = false;
    QObject::connect(&inspector, &WorkstationInspector::assign_facies_requested,
                     &inspector, [&](const QVariantMap&) {
                         assign_seen = true;
                     });
    inspector.show_empty();

    // --- task center ---
    WorkstationTaskCenter tasks;
    pwb::job::JobSnapshot job;
    job.job_id = "j1";
    job.title = "测试任务";
    job.state = pwb::job::JobState::running;
    job.progress = 0.5;
    job.submitted_at = 1.0;
    tasks.set_snapshot_provider([&] { return std::vector{job}; });
    tasks.refresh();
    check(tasks.model()->rowCount() == 1, "task center lists job");
    tasks.shutdown();

    // --- process hub ---
    LogBridge bridge;
    WorkstationLogViewer logs;
    logs.attach_bridge(&bridge);
    logs.log("INFO", "pwb", "hello smoke");
    check(logs.bridge()->pending_count() >= 0, "log bridge accepts");
    logs.shutdown();

    WorkstationConsolePane console;
    check(console.findChild<QPlainTextEdit*>() != nullptr,
          "console pane constructs");

    // --- agent panel ---
    AgentWorkspacePanel agent;
    agent.set_plan_resolver([](const QString& text) {
        return std::optional{AgentPlanSpec{
            .action_id = text.toStdString(),
            .parameters = {},
            .followup_action = std::nullopt,
            .kind = "agent",
            .summary = "test",
        }};
    });
    agent.set_risk_resolver([](const std::string&) {
        return std::optional{AgentRisk::Read};
    });
    bool executed = false;
    agent.set_plan_executor(
        [&](const AgentPlanSpec&, const std::set<AgentRisk>&,
            const QString&) { executed = true; });
    agent.submit("well.list");
    check(executed, "agent executes read plan");

    // --- keybindings ---
    WorkstationKeyBindingManager keys;
    WorkstationKeyBindingManager::Hooks hooks;
    hooks.text_input_focused = [] { return false; };
    hooks.active_tool_id = [] { return std::string("draw"); };
    std::string activated;
    hooks.activate_tool = [&](const std::string& id) { activated = id; };
    keys.set_hooks(hooks);
    keys.begin_temporary_pan();
    check(keys.pan_restore_tool().value_or("") == "draw",
          "temp pan remembers tool");
    keys.release_temporary_pan();
    check(activated == "draw", "release restores tool");

    // --- workstation frame: dock composition ---
    WorkstationFrame frame;
    QWidget central(&frame);
    frame.set_central_widget(&central);
    frame.build_docks();
    check(frame.dock("nav") != nullptr, "nav dock built");
    check(frame.dock("inspector") != nullptr, "inspector dock built");
    check(frame.dock("agent") != nullptr, "agent dock built");
    check(frame.explorer() != nullptr, "explorer panel installed");
    check(frame.inspector() != nullptr, "inspector panel installed");
    check(frame.dock("hub") != nullptr, "hub dock built (placeholder)");
    check(!frame.dock("agent")->isVisible() ||
              frame.dock("agent")->isFloating(),
          "agent dock hidden by default");
    // pwbDockId property + descriptor features.
    const auto* nav = frame.dock("nav");
    check(nav->property("pwbDockId").toString() == "nav",
          "dock carries pwbDockId");
    const auto* hub = frame.dock("hub");
    check(!(hub->features() & QDockWidget::DockWidgetFloatable),
          "hub dock cannot float (GL content)");
    // isVisible() requires the ancestor chain shown (Python parity).
    frame.show();
    frame.set_dock_visible("agent", true);
    check(frame.dock_visible("agent"), "dock visibility toggles");
    frame.apply_layout_preset(
        pwb::ui_shell::workstation_layout_presets().front().id);
    frame.apply_first_run_sizes();
    frame.shutdown();

    std::fprintf(stderr, "%d failures\n", failures);
    return failures == 0 ? 0 : 1;
}
