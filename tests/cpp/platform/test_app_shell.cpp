// platform.app_shell — W5/UI-17 wiring battery, M2-updated (ribbon
// five-workspaces): MainWindow's central widget is the AppShell composition
// root, the ribbon chrome sits above the workstation frame, the central
// workspace stack carries the three host pages (数据管理 / 科学宿主 / 验证),
// navigate_workspace is the navigation authority, navigate_to survives as
// the legacy routing seam (hub 0 → workspace 0, 编图 canvas → workspace 3,
// review → workspace 4, well/seismic/viz stay on the 功能页 dock), the
// palette pops/dismisses, and a second window lifecycle exercises the
// global shortcut-registry re-registration path.

#include <QDockWidget>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QString>
#include <QToolBar>
#include <QToolButton>
#include <qgsapplication.h>
#include <qgsmapcanvas.h>
#include <qgsproject.h>

#include <filesystem>
#include <fstream>
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

#include <pwb/application/project_session.hpp>
#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_pages_data/qt/hub_page.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_shell/adaptive_page_stack.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "validation_workspace_page.hpp"
#include "main_window.hpp"

#include "test_framework.hpp"

using pwb::app::AppShell;
using pwb::app::MainWindow;

namespace {

void check_shell(MainWindow& window) {
    AppShell* shell = window.appShell();
    PWB_CHECK_MSG(shell != nullptr,
                  "AppShell missing — PWB_WITH_APP_SHELL not wired");
    PWB_CHECK(window.centralWidget() == shell);

    PWB_CHECK(shell->workstation() != nullptr);
    PWB_CHECK(shell->composite() != nullptr);
    PWB_CHECK(shell->status_bar() != nullptr);
    PWB_CHECK(shell->page_stack() != nullptr);
    // M2: the ribbon chrome + the three-page workspace host.
    PWB_CHECK(shell->ribbon() != nullptr);
    PWB_CHECK(shell->workspace_host() != nullptr);
    PWB_CHECK(shell->workspace_host()->count() == 3);
    // M3 面板化改订: 科学宿主 = 纯 QGIS 画布页；阶段面板是底部阶段行
    // 的独立 dock（可悬浮/停靠/tab 化，navigate_workspace 投影成员）。
    auto* science_page = shell->workspace_host()->findChild<QWidget*>(
        QStringLiteral("ScienceHostPage"));
    PWB_CHECK(science_page != nullptr);
    for (const char* dock_id :
         {"data_preview", "data_history", "data_relations", "pair_link",
          "predict_task", "seismic_predict", "crosswell", "data_prep",
          "strat_compare", "seq_frame", "factor_refs", "data_props",
          "data_lineage"}) {
        PWB_CHECK_MSG(shell->workstation()->dock(dock_id) != nullptr,
                      std::string("stage dock missing: ") + dock_id);
    }
    PWB_CHECK(shell->validation_page() != nullptr);
    PWB_CHECK(shell->validation_page()->findChild<QWidget*>(
                  "ValidationRunQc") != nullptr);
    // M5-3: hub 轴已拆 —— page_stack_ 只剩「编图工具」dock 的单页内容
    // （mapping_page_）；kPageIndex*/hub_names 保留为路由词汇与
    // deferred-binding flush 键（ui_shell oracle 冻结数据不动）。
    PWB_CHECK(shell->page_stack() != nullptr);
    PWB_CHECK(shell->page_stack()->count() == 1);

    // The session canvas is injected into the composite document (the
    // science host page — the canvas-injection contract survives the
    // central-widget swap).
    PWB_CHECK(window.findChild<QgsMapCanvas*>() != nullptr);

    // Composite sub-panels dock through the workstation frame.
    for (const char* dock_id : {"hub", "composite_layer", "composite_input",
                                "composite_linked", "facies_palette",
                                "mapping_stage"}) {
        PWB_CHECK_MSG(shell->workstation()->dock(dock_id) != nullptr,
                      std::string("dock missing: ") + dock_id);
    }
#ifdef PWB_WITH_CONV_27
    auto* layer_dock = shell->workstation()->dock("composite_layer");
    if (window.layerPanel() != nullptr) {
        PWB_CHECK(static_cast<const void*>(layer_dock->widget()) ==
                  static_cast<const void*>(window.layerPanel()));
    }
    // The retired prototype LayerManagerPanel is deleted (no hidden
    // second layer-list surface); the dock identity check above is the
    // surviving contract: composite_layer hosts the native tree panel.

    auto* map_toolbar = shell->composite()->map_toolbar();
    PWB_CHECK(map_toolbar != nullptr && !map_toolbar->actions().isEmpty());
    PWB_CHECK(map_toolbar->actions().contains(
        window.governedAction(QStringLiteral("pan"))));
#endif
}

void check_workspace_navigation(MainWindow& window) {
    AppShell* shell = window.appShell();

    // -- workspace axis: ribbon tab mirror + page switch -------------------
    shell->navigate_workspace(0);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageData);
    PWB_CHECK(shell->ribbon()->current_workspace() == 0);

    shell->navigate_workspace(1);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageScience);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);
    // M3 面板化: 进 ws1 → 底部阶段行投影预测组 —— 井震两联 dock 抬起
    // 可见；预测任务/地震预测同组 tab 成员；ws2/ws3 成员隐藏。
    auto* host = shell->workstation()->dock_host();
    auto* pair = shell->workstation()->dock("pair_link");
    PWB_CHECK(pair != nullptr && pair->isVisible());
    PWB_CHECK(host->tabifiedDockWidgets(pair).contains(
        shell->workstation()->dock("predict_task")));
    PWB_CHECK(host->tabifiedDockWidgets(pair).contains(
        shell->workstation()->dock("seismic_predict")));
    PWB_CHECK(!shell->workstation()->dock_visible("strat_compare"));
    PWB_CHECK(!shell->workstation()->dock_visible("factor_refs"));

    // Workspaces 1/2/3 share the ONE science host page.
    shell->navigate_workspace(3);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageScience);
    PWB_CHECK(shell->ribbon()->current_workspace() == 3);
    PWB_CHECK(shell->workstation()->dock_visible("factor_refs"));
    PWB_CHECK(!shell->workstation()->dock_visible("pair_link"));

    shell->navigate_workspace(4);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageValidation);
    PWB_CHECK(shell->ribbon()->current_workspace() == 4);

    // Out-of-range navigation is ignored (Python guard parity).
    shell->navigate_workspace(99);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageValidation);

    // -- legacy routing seam (M5-3: hub 轴已解散，纯工作区路由) -------------
    QDockWidget* hub_dock = shell->workstation()->dock("hub");
    PWB_CHECK(hub_dock != nullptr);  // 现仅为「编图工具」dock

    // hub 0 → workspace 0 (+ in-page submodule switch).
    shell->navigate_to(pwb::ui_shell::kPageIndexData,
                       QStringLiteral("management"));
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageData);
    PWB_CHECK(shell->ribbon()->current_workspace() == 0);

    // 编图 canvas → workspace 3 (science host page) + 编图工具 dock raise。
    shell->navigate_to(pwb::ui_shell::kPageIndexMapping,
                       QStringLiteral("canvas"));
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageScience);
    PWB_CHECK(shell->ribbon()->current_workspace() == 3);

    // 编图 review → workspace 4 (验证).
    shell->navigate_to(pwb::ui_shell::kPageIndexMapping,
                       QStringLiteral("review"));
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageValidation);
    PWB_CHECK(shell->ribbon()->current_workspace() == 4);

    // M5-3 migrated homes: sequence → ws2 层序格架 dock；well_log → ws1；
    // seismic → ws1 地震预测 dock；geomodel → ws4 3D 对照 tab；viz → ws0。
    shell->navigate_to(pwb::ui_shell::kPageIndexWell,
                       QStringLiteral("sequence"));
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageScience);
    PWB_CHECK(shell->ribbon()->current_workspace() == 2);
    PWB_CHECK(shell->workstation()->dock_visible("seq_frame"));

    shell->navigate_to(pwb::ui_shell::kPageIndexWell);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);

    shell->navigate_to(pwb::ui_shell::kPageIndexSeismic);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);
    PWB_CHECK(shell->workstation()->dock_visible("seismic_predict"));

    shell->navigate_to(pwb::ui_shell::kPageIndexSeismic,
                       QStringLiteral("geomodel"));
    PWB_CHECK(shell->ribbon()->current_workspace() == 4);

    shell->navigate_to(pwb::ui_shell::kPageIndexVisualization);
    PWB_CHECK(shell->ribbon()->current_workspace() == 0);

    // Out-of-range legacy navigation is ignored.
    shell->navigate_to(99);
    PWB_CHECK(shell->ribbon()->current_workspace() == 0);
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    {
        MainWindow window;
        window.show();
        check_shell(window);
        AppShell* shell = window.appShell();

        check_workspace_navigation(window);

        // -- M4: ribbon file menu + governed bindings -----------------------
        {
            auto* ribbon = shell->ribbon();
            PWB_CHECK(ribbon != nullptr);
            // The file button carries the FULL menu (M4 convergence):
            // entries + a 最近工程 submenu (MRU rides the settings store).
            auto* file_button =
                ribbon->findChild<QToolButton*>("ribbonFileButton");
            PWB_CHECK(file_button != nullptr);
            QMenu* file_menu = file_button->menu();
            PWB_CHECK(file_menu != nullptr);
            int entries = 0;
            bool has_mru = false;
            for (QAction* action : file_menu->actions()) {
                if (action->isSeparator()) continue;
                ++entries;
                if (action->menu() != nullptr) has_mru = true;
            }
            PWB_CHECK_MSG(entries >= 5,
                          "ribbon file menu not filled (M4)");
            PWB_CHECK_MSG(has_mru, "ribbon file menu misses the MRU");
            // The ws3 band binds the SAME governed QAction objects the
            // menus consume (D4) — bound buttons carry them.
            PWB_CHECK(window.governedAction(QStringLiteral("map_export")) !=
                      nullptr);
        }

        // -- M5: the validation commands are real (M4's "M5 接入" -------
        // placeholders lit up); without a project/data they disable with
        // honest reasons.
        {
            auto& registry = pwb::ui_shell::command_registry();
            for (const char* id :
                 {"verify.select_object", "verify.select_baseline",
                  "verify.link", "verify.side_by_side", "verify.overlay",
                  "verify.difference", "verify.record",
                  "verify.save_record"}) {
                PWB_CHECK_MSG(registry.get(id) != nullptr,
                              std::string("M5 command missing: ") + id);
            }
            pwb::ui_shell::CommandContext ctx;
            ctx.mapping_stage = "integrated_compilation";
            const auto data_gate =
                registry.evaluate("verify.side_by_side", &ctx);
            PWB_CHECK(!data_gate.enabled);
            PWB_CHECK(!data_gate.reason.empty());
            // F:75: the link gate names the m/ms coupling rule.
            const auto link_gate = registry.evaluate("verify.link", &ctx);
            PWB_CHECK(!link_gate.enabled);
            PWB_CHECK(link_gate.reason.find("时深") != std::string::npos);
        }

        // -- palette popup/dismiss (offscreen-safe) ------------------------
        shell->command_palette()->popup();
        PWB_CHECK(shell->command_palette()->isVisible());
        shell->command_palette()->dismiss();
        PWB_CHECK(!shell->command_palette()->isVisible());

        // BEGIN CPP-CLOSE-12 — provider injection coverage. The context
        // provider feeds the live session snapshot and the details
        // provider answers map: tools through the canonical explain()
        // formatter; both are consumed by apply_filter during popup.
        {
            using pwb::ui_shell::command_registry;
            command_registry().register_command(
                [] {
                    pwb::ui_shell::CommandSpec spec;
                    spec.id = "core:palette_ctx_probe";
                    spec.label = "palette context probe";
                    spec.group = "core";
                    return spec;
                }());
            command_registry().register_command(
                [] {
                    pwb::ui_shell::CommandSpec spec;
                    spec.id = "map:palette_details_probe";
                    spec.label = "palette details probe";
                    spec.group = "core";
                    return spec;
                }());
            shell->command_palette()->popup();
            QListWidget* results =
                shell->command_palette()->findChild<QListWidget*>();
            PWB_CHECK_MSG(results != nullptr, "palette list missing");
            bool details_tooltip = false;
            for (int i = 0; i < results->count(); ++i) {
                auto* item = results->item(i);
                if (item->data(Qt::ItemDataRole::UserRole).toString()
                    == QStringLiteral("map:palette_details_probe")) {
                    details_tooltip = !item->toolTip().isEmpty();
                }
            }
            PWB_CHECK_MSG(details_tooltip,
                          "map: command has no details tooltip — "
                          "tool_details_provider not wired");
            shell->command_palette()->dismiss();
            command_registry().unregister("core:palette_ctx_probe");
            command_registry().unregister("map:palette_details_probe");
        }
        // END CPP-CLOSE-12

        // -- pages: real widgets, deferred seams honest --------------------
        PWB_CHECK(shell->home_page() != nullptr);
        PWB_CHECK(shell->data_workspace() != nullptr);
        PWB_CHECK(shell->mapping_page() != nullptr);
        PWB_CHECK(shell->review_page() != nullptr);
        PWB_CHECK(shell->visualization_page() != nullptr);
        PWB_CHECK(shell->geomodel_page() != nullptr);  // unavailable host

        // -- teardown: worker shutdown is idempotent -----------------------
        shell->shutdown_workers();
        shell->shutdown_workers();
    }

    // Second window lifecycle: the global shortcut registry re-registers
    // the same ids on a fresh AppShell — the QPointer-tracked map must
    // not touch the previous window's dead shortcuts.
    {
        MainWindow second;
        second.show();
        check_shell(second);
    }

#ifdef PWB_WITH_DATA_INTEGRATION
    // -- project switch lifecycle (#1447) --------------------------------
    // One window, two projects: openProject used to refuse with 已有工程
    //打开 (switching required a process restart). close-then-open must
    // rebind the store, drop the previous project's layers, and
    // closeProject must be idempotent.
    {
        namespace fs = std::filesystem;
        const auto make_project = [](const fs::path& file,
                                     const char* name) {
            fs::create_directories(file.parent_path());
            std::ofstream out(file, std::ios::binary | std::ios::trunc);
            out << pwb::domain::Json{
                {"schema_version", 1},
                {"meta", pwb::domain::Json{
                             {"name", name},
                             {"project_root", "."},
                             {"created_at", "2026-09-21T00:00:00+00:00"},
                             {"updated_at", "2026-09-21T00:00:00+00:00"}}},
                {"coordinate", pwb::domain::Json{{"project_crs",
                                                  "EPSG:32650"}}},
                {"stratigraphy",
                 pwb::domain::Json{{"target_horizon", "C6"}}},
                {"constraint_layers", pwb::domain::Json::array()},
                {"factor_map_tasks", pwb::domain::Json::array()},
                {"paleomap_documents", pwb::domain::Json::array()},
                {"contour_drafts", pwb::domain::Json::array()},
                {"well_tables", pwb::domain::Json::array()},
                {"resources", pwb::domain::Json::array()}}
                           .dump();
        };
        const fs::path dir = fs::temp_directory_path()
            / ("pwb_project_switch_" + std::to_string(test_pid()));
        const fs::path file_a = dir / "switch-a.paleo.json";
        const fs::path file_b = dir / "switch-b.paleo.json";
        make_project(file_a, "切换工程A");
        make_project(file_b, "切换工程B");

        MainWindow window;
        window.show();
        const QString open_a = window.openProject(
            QString::fromStdString(file_a.string()));
        PWB_CHECK_MSG(open_a.isEmpty(), open_a.toStdString());
        PWB_CHECK(window.context().session().store() != nullptr);
        // Switch: no restart, no refusal — the old "已有工程打开" path
        // is gone.
        const QString open_b = window.openProject(
            QString::fromStdString(file_b.string()));
        PWB_CHECK_MSG(open_b.isEmpty(), open_b.toStdString());
        PWB_CHECK(window.context().projectStore() != nullptr);
        PWB_CHECK(window.context().projectStore()->project_file()
                      .filename().string() == "switch-b.paleo.json");

        // Explicit close: idempotent (second call is a clean no-op).
        PWB_CHECK(window.closeProject().isEmpty());
        PWB_CHECK(window.context().session().store() == nullptr);
        PWB_CHECK(window.context().session().map().layerIdsTopFirst()
                      .empty());
        PWB_CHECK(window.closeProject().isEmpty());

        fs::remove_all(dir);
    }
#endif  // PWB_WITH_DATA_INTEGRATION

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.app_shell");
}
