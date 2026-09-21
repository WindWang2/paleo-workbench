// platform.three_stage_flow — V14-THREE-STAGE-UX wiring battery: the stage
// bar mounts on the app-bar row, the production command set populates the
// (previously empty) palette registry, stage switches drive the per-stage
// layout profiles without rebuilding the map canvas, user preferences
// round-trip, and the mapping stage restores from the project document.
// A second window lifecycle exercises idempotent re-registration.

#include <QDockWidget>
#include <QListWidget>
#include <QString>
#include <qgsapplication.h>
#include <qgsmapcanvas.h>

#include <pwb/application/project_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_composite/mapping_stage_bar.hpp>
#include <pwb/ui_map/map_dock_manager.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_stageflow/qt/stage_flow_controller.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "main_window.hpp"

#include "test_framework.hpp"

#ifdef PWB_WITH_DATA_INTEGRATION
#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>
#endif

using pwb::app::AppShell;
using pwb::app::MainWindow;
using Controller = pwb::ui_stageflow::qt::StageFlowController;

namespace {

void check_stage_flow_installed(MainWindow& window) {
    PWB_CHECK_MSG(window.stageFlow() != nullptr,
                  "StageFlowController not installed");
    PWB_CHECK_MSG(window.stageFlowCommandCount() >= 15,
                  "production command set not registered");
    AppShell* shell = window.appShell();
    PWB_CHECK(shell != nullptr);
    PWB_CHECK(shell->workstation() != nullptr);
    // The orphan stage bar is mounted on the app-bar toolbar row.
    PWB_CHECK(shell->workstation()->top_bar_mounted());
    PWB_CHECK(shell->composite()->stage_bar != nullptr);
    PWB_CHECK(shell->composite()->stage_bar->parentWidget() != nullptr);
    // Not mountable twice (identity surface, one-shot).
    PWB_CHECK(!shell->workstation()->mount_top_bar(
        shell->composite()->stage_bar));
}

void check_command_registry(MainWindow& window) {
    auto& registry = pwb::ui_shell::command_registry();
    for (const char* id :
         {"stage.goto.prediction", "stage.goto.constraints",
          "stage.goto.compilation", "nav.hub.mapping", "panel.toggle.tasks",
          "stage.reset_layout"}) {
        PWB_CHECK_MSG(registry.get(id) != nullptr,
                      std::string("command missing: ") + id);
    }
    // Palette find() surfaces the stage commands (subsequence match).
    const auto hits = registry.find("阶段", 50, nullptr);
    bool found_prediction = false;
    for (const auto* spec : hits) {
        if (spec->id == "stage.goto.prediction") found_prediction = true;
    }
    PWB_CHECK_MSG(found_prediction, "palette find(阶段) misses stage command");

    // Stage gating: evaluate under an explicit context (fail-closed
    // vocabulary — an unknown stage value hides stage-scoped commands).
    pwb::ui_shell::CommandContext context;
    context.mapping_stage = "constraint_factor";
    const auto composer =
        registry.evaluate("panel.toggle.composer", &context);
    PWB_CHECK(!composer.enabled);
    PWB_CHECK(!composer.reason.empty());
    const auto bottom = registry.evaluate("panel.toggle.bottom", &context);
    PWB_CHECK(bottom.enabled);
    (void)window;
}

void check_stage_switch_and_layout(MainWindow& window) {
    AppShell* shell = window.appShell();
    auto* flow = window.stageFlow();
    QgsMapCanvas* canvas_before = window.findChild<QgsMapCanvas*>();
    PWB_CHECK(canvas_before != nullptr);

    // Stage 2: factor surfaces appear.
    flow->request_stage("constraint_factor");
    PWB_CHECK(flow->snapshot().stage_value == "constraint_factor");
    PWB_CHECK(flow->snapshot().stage_label.find("约束") != std::string::npos);
    auto* input_dock = shell->workstation()->dock("composite_input");
    PWB_CHECK(input_dock != nullptr);
    PWB_CHECK_MSG(input_dock->isVisible(),
                  "stage2 profile did not show 输入与结果 dock");
    auto* seismic_dock = shell->workstation()->dock("seismic");
    if (seismic_dock != nullptr) {
        PWB_CHECK(!seismic_dock->isVisible());
    }

    // Stage 3: composer visible, factor surfaces hidden.
    flow->request_stage("integrated_compilation");
    PWB_CHECK(flow->snapshot().stage_value == "integrated_compilation");
    PWB_CHECK(!input_dock->isVisible());
    if (auto* page = shell->mapping_page()) {
        if (page->dock_manager() != nullptr) {
            PWB_CHECK(page->dock_manager()->is_panel_visible("composer"));
            // bottom hosts the stage-3 factor reference strip.
            PWB_CHECK(page->dock_manager()->is_panel_visible("bottom"));
        }
    }

    // Stage 1: prediction context — seismic/well surfaces back.
    flow->request_stage("facies_calibration");
    if (seismic_dock != nullptr) {
        PWB_CHECK(seismic_dock->isVisible());
    }
    PWB_CHECK(!input_dock->isVisible());

    // Structural performance assertion: 3 stage switches did not rebuild
    // the QGIS canvas (visibility-only application; the stages.py
    // contract).
    QgsMapCanvas* canvas_after = window.findChild<QgsMapCanvas*>();
    PWB_CHECK(canvas_after == canvas_before);

    // Session authority: the stage switch reached ProjectSession.
    PWB_CHECK(window.session()->mapping_stage().has_value());
    PWB_CHECK(*window.session()->mapping_stage() == "facies_calibration");
}

void check_user_preference_override(MainWindow& window) {
    AppShell* shell = window.appShell();
    auto* flow = window.stageFlow();
    flow->request_stage("constraint_factor");
    auto* seismic_dock = shell->workstation()->dock("seismic");
    if (seismic_dock == nullptr) return;  // capability-off degrade
    PWB_CHECK(!seismic_dock->isVisible());
    // User re-enables the seismic dock for stage 2; the override wins and
    // survives a stage round-trip within the window.
    flow->set_panel_visible("workstation.seismic", true);
    PWB_CHECK(seismic_dock->isVisible());
    flow->request_stage("integrated_compilation");
    flow->request_stage("constraint_factor");
    PWB_CHECK(seismic_dock->isVisible());
    // Reset restores the profile default.
    flow->reset_stage_preferences();
    PWB_CHECK(!seismic_dock->isVisible());
}

void check_task_center_provider(MainWindow& window) {
#ifdef PWB_WITH_CONV_30
    AppShell* shell = window.appShell();
    auto* center = shell->workstation()->task_center();
    PWB_CHECK(center != nullptr);
    // The provider seam is bound: refresh() runs without a scheduler
    // (empty snapshot is honest, not a crash) and the model responds.
    center->refresh();
    center->shutdown();
    center->refresh();  // post-shutdown refresh stays safe
#endif
    (void)window;
}

void check_palette_popup(MainWindow& window) {
    AppShell* shell = window.appShell();
    shell->command_palette()->popup();
    PWB_CHECK(shell->command_palette()->isVisible());
    QListWidget* results = shell->command_palette()->findChild<QListWidget*>();
    PWB_CHECK(results != nullptr);
    // The palette lists production commands now (previously an empty
    // shell — the core assertion of this slice).
    PWB_CHECK(results->count() >= 10);
    shell->command_palette()->dismiss();
    PWB_CHECK(!shell->command_palette()->isVisible());
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    {
        MainWindow window;
        window.show();
        check_stage_flow_installed(window);
        check_command_registry(window);
        check_stage_switch_and_layout(window);
        check_user_preference_override(window);
        check_task_center_provider(window);
        check_palette_popup(window);

#ifdef PWB_WITH_DATA_INTEGRATION
        // -- stage restore from the project document ------------------------
        // Mutate the live store's mapping_workspace section directly (the
        // codec's lenient read path), then restore.
        auto store = window.context().projectStore();
        if (store != nullptr) {
            auto& root = store->document().root();
            if (!root.contains("mapping_workspace") ||
                !root["mapping_workspace"].is_object()) {
                root["mapping_workspace"] = pwb::domain::Json::object();
            }
            root["mapping_workspace"]["current_stage"] =
                "integrated_compilation";
            window.restoreStageFromProject();
            PWB_CHECK(window.stageFlow()->snapshot().stage_value ==
                      "integrated_compilation");
            // Unknown value: the codec lenient-falls-back to stage 1
            // (workspace state.cpp) — the restore applies that fallback,
            // it does NOT keep the previous stage.
            root["mapping_workspace"]["current_stage"] = "stage_four";
            window.restoreStageFromProject();
            PWB_CHECK(window.stageFlow()->snapshot().stage_value ==
                      "facies_calibration");
        } else {
            // No project: the snapshot reports the honest no-project state
            // and the restore is a no-op.
            PWB_CHECK(!window.stageFlow()->snapshot().project_open);
            const auto before =
                window.stageFlow()->snapshot().stage_value;
            window.restoreStageFromProject();
            PWB_CHECK(window.stageFlow()->snapshot().stage_value == before);
        }
#endif
    }

    // Second window: idempotent re-registration (same-id replace) and an
    // independent controller — the global registry and the per-window
    // stage state must not interfere. After the window's destruction the
    // process-global registry must no longer hold its closures (a
    // dangling-callback palette invocation would be a UAF).
    {
        MainWindow second;
        second.show();
        check_stage_flow_installed(second);
        second.stageFlow()->request_stage("constraint_factor");
        PWB_CHECK(second.stageFlow()->snapshot().stage_value ==
                      "constraint_factor");
    }
    // The window is destroyed: the second-window command registrations
    // were unregistered (destroyed hook), so a with-context evaluate on
    // the survivors stays safe.
    {
        pwb::ui_shell::CommandContext context;
        context.mapping_stage = "constraint_factor";
        const auto verdict = pwb::ui_shell::command_registry().evaluate(
            "panel.toggle.reference", &context);
        PWB_CHECK(!verdict.enabled || verdict.reason.empty());
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.three_stage_flow");
}
