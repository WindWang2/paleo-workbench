// platform.three_stage_flow — V14-THREE-STAGE-UX wiring battery, M2-updated
// (ribbon five-workspaces): the ribbon chrome replaces the retired
// MappingStageBar (①②③ segments → ribbon tabs), the production command set
// populates the (previously empty) palette registry (nav.workspace.* now),
// stage switches drive the per-stage layout profiles without rebuilding
// the map canvas, stage.goto switches stage AND workspace (D1), entering
// 数据管理/验证 never rewrites the stage, user preferences round-trip, and
// the mapping stage restores from the project document. A second window
// lifecycle exercises idempotent re-registration.

#include <QComboBox>
#include <QDockWidget>
#include <QListWidget>
#include <QString>
#include <qgsapplication.h>
#include <qgsmapcanvas.h>
#include <qgslayertreeview.h>
#include <qgsproject.h>

#include <pwb/application/project_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_map/map_dock_manager.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_shell/status_bar.hpp>
#include <pwb/ui_stageflow/qt/stage_flow_controller.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include "validation_workspace_page.hpp"
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
    // M2 (D1): the ribbon chrome is the stage switch — the MappingStageBar
    // is deleted outright (the retired surface no longer exists even as an
    // unmounted orphan owned by the composite document).
    PWB_CHECK(shell->ribbon() != nullptr);
    PWB_CHECK(!shell->workstation()->top_bar_mounted());
    // The horizon selector migrated to the AppShell StatusBar.
    PWB_CHECK(shell->status_bar()->findChild<QComboBox*>(
                  "StatusHorizonCombo") != nullptr);
    // M3 (P0-4): the validation workspace page is the real composition
    // (read-only compare canvas + issue table + review hub), not a
    // placeholder.
    PWB_CHECK(shell->validation_page() != nullptr);
    PWB_CHECK(shell->validation_page()->map_canvas() != nullptr);
    PWB_CHECK(shell->validation_page()->issue_table() != nullptr);
    PWB_CHECK(shell->validation_page()->qc_hub() != nullptr);
}

void check_command_registry(MainWindow& window) {
    auto& registry = pwb::ui_shell::command_registry();
    for (const char* id :
         {"stage.goto.prediction", "stage.goto.constraints",
          "stage.goto.compilation", "nav.workspace.map", "panel.toggle.tasks",
          "stage.reset_layout"}) {
        PWB_CHECK_MSG(registry.get(id) != nullptr,
                      std::string("command missing: ") + id);
    }
    // M2: the retired nav.hub.* ids are gone (workspace axis replaces them).
    PWB_CHECK(registry.get("nav.hub.mapping") == nullptr);
    // Palette find() surfaces the stage commands (subsequence match).
    const auto hits = registry.find("阶段", 50, nullptr);
    bool found_prediction = false;
    for (const auto* spec : hits) {
        if (spec->id == "stage.goto.prediction") found_prediction = true;
    }
    PWB_CHECK_MSG(found_prediction, "palette find(阶段) misses stage command");

    // M4: the ribbon band commands registered — the five per-workspace
    // primary actions exist (uniqueness of primaries is the ui_ribbon
    // core's table-integrity contract).
    for (const char* id : {"data.import", "predict.run", "factor.compute",
                           "map.export", "verify.run"}) {
        PWB_CHECK_MSG(registry.get(id) != nullptr,
                      std::string("ribbon primary missing: ") + id);
    }
    // D8 honest gating: without a project the project-gated primaries are
    // disabled WITH a concrete reason (never a silent grey-out).
    pwb::ui_shell::CommandContext no_project;
    no_project.mapping_stage = "facies_calibration";
    const auto data_gate =
        registry.evaluate("data.import", &no_project);
    PWB_CHECK(!data_gate.enabled);
    PWB_CHECK(!data_gate.reason.empty());
    const auto run_gate =
        registry.evaluate("predict.run", &no_project);
    PWB_CHECK(!run_gate.enabled);
    PWB_CHECK(!run_gate.reason.empty());
    // M5-2 lit the layout commands: without a project they disable with
    // the project gate reason (the compose panel is the real backend).
    PWB_CHECK(registry.get("map.template") != nullptr);
    const auto layout_gate =
        registry.evaluate("map.template", &no_project);
    PWB_CHECK(!layout_gate.enabled);
    PWB_CHECK(!layout_gate.reason.empty());
    // The run-guard: nothing running → the cancel entry explains itself.
    const auto cancel_gate =
        registry.evaluate("predict.cancel", &no_project);
    PWB_CHECK(!cancel_gate.enabled);
    PWB_CHECK(!cancel_gate.reason.empty());

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
    // Deterministic starting point: the stage→bottom flip rides
    // sync_workspace_for_stage, which only acts while the science host
    // page is current — navigate explicitly instead of relying on the
    // persisted workspace from QSettings.
    shell->navigate_workspace(2);
    QgsMapCanvas* canvas_before =
        window.findChild<QgsMapCanvas*>(QStringLiteral("session-map-canvas"));
    PWB_CHECK(canvas_before != nullptr);

    // M3 science-host — 面板化改订: 底部阶段行 dock 投影随阶段权威走
    // （每格独立 dock；行内 tab 组，成员集按工作区显隐）。
    for (const char* dock_id :
         {"pair_link", "predict_task", "seismic_predict", "data_prep",
          "strat_compare", "seq_frame", "factor_refs"}) {
        PWB_CHECK_MSG(shell->workstation()->dock(dock_id) != nullptr,
                      std::string("stage dock missing: ") + dock_id);
    }

    // Stage 2: factor surfaces appear; bottom row flips to the
    // constraint dock set.
    flow->request_stage("constraint_factor");
    PWB_CHECK(flow->snapshot().stage_value == "constraint_factor");
    PWB_CHECK(flow->snapshot().stage_label.find("约束") != std::string::npos);
    auto* input_dock = shell->workstation()->dock("composite_input");
    PWB_CHECK(input_dock != nullptr);
    PWB_CHECK_MSG(input_dock->isVisible(),
                  "stage2 profile did not show 输入与结果 dock");
    PWB_CHECK_MSG(
        shell->workstation()->dock_visible("data_prep") ||
            shell->workstation()->dock_visible("crosswell"),
        "stage2 did not project the constraint stage docks");
    PWB_CHECK(!shell->workstation()->dock_visible("pair_link"));
    PWB_CHECK(!shell->workstation()->dock_visible("factor_refs"));
    // The legacy well/seismic placeholder docks stay managed-but-hidden
    // (the real two-pane lives in the science-host bottom).
    auto* seismic_dock = shell->workstation()->dock("seismic");
    if (seismic_dock != nullptr) {
        PWB_CHECK(!seismic_dock->isVisible());
    }

    // Stage 3: composer visible, factor surfaces hidden; the factor
    // reference strip hosts in the bottom.
    flow->request_stage("integrated_compilation");
    PWB_CHECK(flow->snapshot().stage_value == "integrated_compilation");
    PWB_CHECK(!input_dock->isVisible());
    PWB_CHECK_MSG(shell->workstation()->dock_visible("factor_refs"),
                  "stage3 did not raise the 单因素参考 dock");
    auto* refs_dock = shell->workstation()->dock("factor_refs");
    PWB_CHECK(refs_dock != nullptr);
    PWB_CHECK(refs_dock->widget() != nullptr &&
              refs_dock->widget()->findChild<QWidget*>(
                  "FactorReferenceStrip") != nullptr);
    if (auto* page = shell->mapping_page()) {
        if (page->dock_manager() != nullptr) {
            PWB_CHECK(page->dock_manager()->is_panel_visible("composer"));
            // bottom hosts the stage-3 factor reference strip.
            PWB_CHECK(page->dock_manager()->is_panel_visible("bottom"));
        }
    }

    // Stage 1: prediction context — 井震两联 dock 抬起，split 在 dock
    // 宿主内。
    flow->request_stage("facies_calibration");
    PWB_CHECK_MSG(shell->workstation()->dock_visible("pair_link"),
                  "stage1 did not raise the 井震两联 dock");
    auto* pair_dock = shell->workstation()->dock("pair_link");
    PWB_CHECK(pair_dock != nullptr);
    PWB_CHECK(pair_dock->widget() != nullptr &&
              pair_dock->widget()->findChild<QWidget*>(
                  "PredictionBottomSplit") != nullptr);
    // The seismic/well docks carry no real panel factory in this
    // composition — a stage profile must not present their
    // "(占位页, 待实现)" placeholder as the stage's work surface (#1450):
    // the profile asks for visible, the frame keeps a factoryless dock
    // hidden.
    if (seismic_dock != nullptr) {
        PWB_CHECK(!seismic_dock->isVisible());
        PWB_CHECK(!shell->workstation()->has_panel_factory("seismic"));
    }
    PWB_CHECK(!input_dock->isVisible());

    // Structural performance assertion: 3 stage switches did not rebuild
    // the QGIS canvas (visibility-only application; the stages.py
    // contract).
    QgsMapCanvas* canvas_after =
        window.findChild<QgsMapCanvas*>(QStringLiteral("session-map-canvas"));
    PWB_CHECK(canvas_after == canvas_before);

    // Session authority: the stage switch reached ProjectSession.
    PWB_CHECK(window.session()->mapping_stage().has_value());
    PWB_CHECK(*window.session()->mapping_stage() == "facies_calibration");
}

void check_workspace_stage_coupling(MainWindow& window) {
    // M2 (D1): workspaces 1/2/3 ARE the stages; 数据管理/验证 never rewrite
    // the stage authority; stage.goto lands on the matching workspace.
    AppShell* shell = window.appShell();
    auto& registry = pwb::ui_shell::command_registry();
    window.stageFlow()->request_stage("integrated_compilation");

    // 数据管理 / 验证: page switches, stage untouched.
    shell->navigate_workspace(0);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageData);
    PWB_CHECK(window.session()->mapping_stage().has_value());
    PWB_CHECK(*window.session()->mapping_stage() == "integrated_compilation");
    shell->navigate_workspace(4);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageValidation);
    PWB_CHECK(*window.session()->mapping_stage() == "integrated_compilation");

    // Workspace 1 writes the stage authority (ws → stage direction).
    shell->navigate_workspace(1);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageScience);
    PWB_CHECK(*window.session()->mapping_stage() == "facies_calibration");
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);

    // Reverse sync (stage → ribbon): a stage write from another surface
    // mirrors the ribbon tab while the science host page is current —
    // and the blocked signal means no workspaceActivated loop fires.
    window.stageFlow()->request_stage("constraint_factor");
    PWB_CHECK(shell->ribbon()->current_workspace() == 2);

    // stage.goto command: stage AND workspace both move (D1).
    const auto* goto_cmd = registry.get("stage.goto.compilation");
    PWB_CHECK(goto_cmd != nullptr && goto_cmd->callback != nullptr);
    goto_cmd->callback();
    PWB_CHECK(window.stageFlow()->snapshot().stage_value ==
              "integrated_compilation");
    PWB_CHECK(shell->ribbon()->current_workspace() == 3);
    PWB_CHECK(*window.session()->mapping_stage() == "integrated_compilation");

    // nav.workspace.* command: workspace moves without a stage write for
    // the non-scientific targets.
    const auto* nav_cmd = registry.get("nav.workspace.data");
    PWB_CHECK(nav_cmd != nullptr && nav_cmd->callback != nullptr);
    nav_cmd->callback();
    PWB_CHECK(shell->ribbon()->current_workspace() == 0);
    PWB_CHECK(*window.session()->mapping_stage() == "integrated_compilation");
}

void check_user_preference_override(MainWindow& window) {
    AppShell* shell = window.appShell();
    auto* flow = window.stageFlow();
    flow->request_stage("constraint_factor");
    auto* seismic_dock = shell->workstation()->dock("seismic");
    if (seismic_dock == nullptr) return;  // capability-off degrade
    PWB_CHECK(!seismic_dock->isVisible());
    // A user override cannot resurrect a factoryless placeholder either
    // — the honest surface is hidden until a real panel factory joins
    // (#1450). The override itself round-trips through the preference
    // store; assert it against a dock WITH a factory instead (tasks).
    flow->set_panel_visible("workstation.seismic", true);
    PWB_CHECK(!seismic_dock->isVisible());
    auto* tasks_dock = shell->workstation()->dock("tasks");
    if (tasks_dock != nullptr
        && shell->workstation()->has_panel_factory("tasks")) {
        flow->set_panel_visible("workstation.tasks", false);
        PWB_CHECK(!tasks_dock->isVisible());
        flow->request_stage("integrated_compilation");
        flow->request_stage("constraint_factor");
        PWB_CHECK(!tasks_dock->isVisible());
        flow->reset_stage_preferences();
    }
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

void check_map_object_identity(MainWindow& window) {
    // D2（#1429 家族回归）：会话三件套 QgsProject / QgsMapCanvas /
    // QgsLayerTreeView 在阶段切换、工程关闭-重开全程指针恒等——阶段与
    // 工程流只改可见性与图层清单，绝不允许重建第二套地图状态。
    QgsProject* const project =
        window.context().session().map().project();
    QgsMapCanvas* const canvas =
        window.findChild<QgsMapCanvas*>(QStringLiteral("session-map-canvas"));
    PWB_CHECK(project != nullptr && canvas != nullptr);
#ifdef PWB_WITH_CONV_27
    // applyStageValue/layerPanel 仅存在于 CONV-27 build（本测试目标在
    // 标准配置下不定义该宏——阶段写路径经 stageFlow）。
    QgsLayerTreeView* const view =
        window.layerPanel() != nullptr ? window.layerPanel()->view()
                                       : nullptr;
    PWB_CHECK(view != nullptr);
    for (const std::string stage :
         {"facies_calibration", "constraint_factor", "integrated_compilation",
          "facies_calibration"}) {
        window.applyStageValue(stage);
        PWB_CHECK(window.context().session().map().project() == project);
        PWB_CHECK(window.findChild<QgsMapCanvas*>(
                      QStringLiteral("session-map-canvas")) == canvas);
        PWB_CHECK(window.layerPanel()->view() == view);
    }

#ifdef PWB_WITH_DATA_INTEGRATION
    // 工程 close（无工程时是幂等 no-op）后，同一会话对象继续服务——
    // reopen 后 project/canvas/tree 仍恒等（图层在 QgsProject 内重建，
    // 壳层不重建画布/树/工程）。
    const QString close_error = window.closeProject();
    PWB_CHECK_MSG(close_error.isEmpty(), close_error.toStdString());
    PWB_CHECK(window.context().session().map().project() == project);
    PWB_CHECK(window.findChild<QgsMapCanvas*>(
                  QStringLiteral("session-map-canvas")) == canvas);
    PWB_CHECK(window.layerPanel()->view() == view);
#endif
#else
    // Reduced build（无 CONV-27）：canvas/project 恒等仍可断言。
    PWB_CHECK(window.context().session().map().project() == project);
    PWB_CHECK(window.findChild<QgsMapCanvas*>(
                  QStringLiteral("session-map-canvas")) == canvas);
#endif
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
        check_workspace_stage_coupling(window);
        check_map_object_identity(window);
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
