// platform.three_stage_flow — V14-THREE-STAGE-UX wiring battery, two-page
// shell: the ribbon chrome carries 数据管理/编图 (the three stages are
// 编图 modes — mode.* toggles write the stage authority), the production
// command set populates the palette registry (nav.workspace.* re-aimed:
// predict/factor/map → 编图 modes, verify → the validation dock), stage
// switches drive the per-stage layout profiles without rebuilding the map
// canvas, stage.goto switches stage AND lands on the 编图 page (D1),
// entering 数据管理 or raising 验证 never rewrites the stage, user
// preferences round-trip, and the mapping stage restores from the project
// document. A second window lifecycle exercises idempotent
// re-registration.

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
    // 界面框架收敛：StageFlowController / 工作站 dock 宿主 / 验证页
    // 已退役出界面（installStageFlow 对退役壳面空安全早退）——
    // 三阶段语义由编图页的 mode.* 命令承载。
    PWB_CHECK(window.stageFlow() == nullptr);
    PWB_CHECK(window.stageFlowCommandCount() == 0);
    AppShell* shell = window.appShell();
    PWB_CHECK(shell != nullptr);
    PWB_CHECK(shell->workstation() == nullptr);
    PWB_CHECK(shell->ribbon() != nullptr);
    PWB_CHECK(shell->status_bar() != nullptr);
    PWB_CHECK(shell->workspace_host() != nullptr);
    PWB_CHECK(shell->workspace_host()->count() == 2);
    PWB_CHECK(shell->validation_page() == nullptr);
    // 默认编图模式 = 智能预测（facies_calibration 镜像）。
    PWB_CHECK(shell->authoring_mode() ==
              pwb::tool_policy::MappingStage::FaciesCalibration);
}

void check_command_registry(MainWindow& window) {
    auto& registry = pwb::ui_shell::command_registry();
    // 编图模式命令 = 新的 stage 写面（互斥 QActionGroup 承载）。
    for (const char* id :
         {"mode.predict", "mode.factor", "mode.author"}) {
        PWB_CHECK_MSG(registry.get(id) != nullptr,
                      std::string("mode command missing: ") + id);
    }
    // stage_flow 时代的导航/面板命令随安装器退役（诚实缺席）。
    for (const char* id :
         {"stage.goto.prediction", "stage.goto.constraints",
          "stage.goto.compilation", "nav.workspace.map", "nav.workspace.data",
          "panel.toggle.tasks", "stage.reset_layout"}) {
        PWB_CHECK_MSG(registry.get(id) == nullptr,
                      std::string("retired command still present: ") + id);
    }
    // M2: the retired nav.hub.* ids are gone (workspace axis replaces them).
    PWB_CHECK(registry.get("nav.hub.mapping") == nullptr);
    // Palette find() surfaces the mode commands (subsequence match).
    const auto hits = registry.find("预测", 50, nullptr);
    bool found_prediction = false;
    for (const auto* spec : hits) {
        if (spec->id == "mode.predict") found_prediction = true;
    }
    PWB_CHECK_MSG(found_prediction, "palette find(预测) misses mode command");

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
    (void)window;
}

void check_mode_switch_and_identity(MainWindow& window) {
    AppShell* shell = window.appShell();
    shell->navigate_workspace(1);
    QgsMapCanvas* canvas_before =
        window.findChild<QgsMapCanvas*>(QStringLiteral("session-map-canvas"));
    PWB_CHECK(canvas_before != nullptr);

    // 编图页三模式共享同一画布 —— 模式切换不重建地图状态（stages.py
    // 契约的保留部分：可见性/投影切换，绝不重造画布）。
    for (pwb::tool_policy::MappingStage stage :
         {pwb::tool_policy::MappingStage::ConstraintFactor,
          pwb::tool_policy::MappingStage::IntegratedCompilation,
          pwb::tool_policy::MappingStage::FaciesCalibration}) {
        shell->request_authoring_mode(stage);
        PWB_CHECK(shell->authoring_mode() == stage);
        PWB_CHECK(window.findChild<QgsMapCanvas*>(
                      QStringLiteral("session-map-canvas")) ==
                  canvas_before);
    }

    // Session authority: the mode switch reached ProjectSession through
    // the one stage-write seam (CONV-27 wiring).
#ifdef PWB_WITH_CONV_27
    PWB_CHECK(window.session()->mapping_stage().has_value());
    PWB_CHECK(*window.session()->mapping_stage() == "facies_calibration");
#endif
}

void check_workspace_stage_coupling(MainWindow& window) {
    // Two-page shell (D1): the three stages are 编图 modes — the mode.*
    // commands / stage_apply seam are the only stage writers; page
    // entry never rewrites the stage authority.
    AppShell* shell = window.appShell();
    auto& registry = pwb::ui_shell::command_registry();
    shell->request_authoring_mode(
        pwb::tool_policy::MappingStage::IntegratedCompilation);

    // 数据管理: page switch leaves the stage untouched.
    shell->navigate_workspace(0);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageData);
#ifdef PWB_WITH_CONV_27
    PWB_CHECK(window.session()->mapping_stage().has_value());
    PWB_CHECK(*window.session()->mapping_stage() ==
              "integrated_compilation");
#endif
    // 验证面退役 —— 诚实缺席，页栈/阶段均不动。
    shell->show_validation_dock();
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageData);

    // 编图页进入不写 stage —— 页内模式镜像当前 stage（综合编图）。
    shell->navigate_workspace(1);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageAuthoring);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);
    PWB_CHECK(shell->authoring_mode() ==
              pwb::tool_policy::MappingStage::IntegratedCompilation);

    // Mode switch writes the stage authority (mode → stage direction).
    shell->request_authoring_mode(
        pwb::tool_policy::MappingStage::FaciesCalibration);
#ifdef PWB_WITH_CONV_27
    PWB_CHECK(*window.session()->mapping_stage() == "facies_calibration");
#endif
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);

    // Reverse sync (stage → mode): a stage write from another surface
    // mirrors the in-page mode while the 编图 page is current.
    shell->sync_workspace_for_stage("constraint_factor");
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);
    PWB_CHECK(shell->authoring_mode() ==
              pwb::tool_policy::MappingStage::ConstraintFactor);

    // mode.* command callback: stage AND page both move (D1).
    const auto* mode_cmd = registry.get("mode.author");
    PWB_CHECK(mode_cmd != nullptr && mode_cmd->callback != nullptr);
    mode_cmd->callback();
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageAuthoring);
    PWB_CHECK(shell->authoring_mode() ==
              pwb::tool_policy::MappingStage::IntegratedCompilation);
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
        check_mode_switch_and_identity(window);
        check_workspace_stage_coupling(window);
        check_map_object_identity(window);
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
            PWB_CHECK(window.session()->mapping_stage().has_value());
            PWB_CHECK(*window.session()->mapping_stage() ==
                      "integrated_compilation");
            // Unknown value: the codec lenient-falls-back to stage 1
            // (workspace state.cpp) — the restore applies that fallback,
            // it does NOT keep the previous stage.
            root["mapping_workspace"]["current_stage"] = "stage_four";
            window.restoreStageFromProject();
            PWB_CHECK(*window.session()->mapping_stage() ==
                      "facies_calibration");
        } else {
            // No project: the restore is a no-op on the session.
            const auto before = window.session()->mapping_stage();
            window.restoreStageFromProject();
            PWB_CHECK(window.session()->mapping_stage() == before);
        }
#endif
    }

    // Second window: an independent shell/mode state — the global
    // registry and the per-window stage authority must not interfere.
    {
        MainWindow second;
        second.show();
        check_stage_flow_installed(second);
        second.appShell()->request_authoring_mode(
            pwb::tool_policy::MappingStage::ConstraintFactor);
        PWB_CHECK(second.appShell()->authoring_mode() ==
                  pwb::tool_policy::MappingStage::ConstraintFactor);
    }
    // The window is destroyed: the retired stage_flow ids were never
    // registered in the first place — they stay absent.
    {
        PWB_CHECK(pwb::ui_shell::command_registry().get(
                      "panel.toggle.reference") == nullptr);
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.three_stage_flow");
}
