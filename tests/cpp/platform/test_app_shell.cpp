// platform.app_shell — W5/UI-17 wiring battery, two-page shell (ribbon
// 数据管理/编图): MainWindow's central widget is the AppShell composition
// root, the ribbon chrome sits above the workstation frame, the central
// workspace stack carries the two host pages (数据管理 / 编图), the three
// stages are 编图 modes (request_authoring_mode writes the stage authority
// through the host seam), 验证 lives in the "validation" dock
// (show_validation_dock), navigate_workspace is the navigation authority,
// navigate_to survives as the legacy routing seam (hub 0 → 数据管理页,
// canvas → 编图页·综合编图模式, review → 验证 dock), the palette
// pops/dismisses, and a second window lifecycle exercises the global
// shortcut-registry re-registration path.

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
#include "data_management_page.hpp"
#include "qgis_authoring_page.hpp"
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

    // QGIS-native two-page frame: ribbon + status bar + 数据管理/编图 host.
    PWB_CHECK(shell->status_bar() != nullptr);
    PWB_CHECK(shell->ribbon() != nullptr);
    PWB_CHECK(shell->workspace_host() != nullptr);
    PWB_CHECK(shell->workspace_host()->count() == 2);
    PWB_CHECK(shell->data_page() != nullptr);
    PWB_CHECK(shell->authoring_page() != nullptr);
    PWB_CHECK(shell->workspace_host()->widget(
                  pwb::app::WorkspaceHostWidget::kPageData) ==
              static_cast<QWidget*>(shell->data_page()));
    PWB_CHECK(shell->workspace_host()->widget(
                  pwb::app::WorkspaceHostWidget::kPageAuthoring) ==
              static_cast<QWidget*>(shell->authoring_page()));

    // Retired feature surfaces answer honestly empty (feature code stays
    // in the project; nothing is fabricated into the shell).
    PWB_CHECK(shell->workstation() == nullptr);
    PWB_CHECK(shell->composite() == nullptr);
    PWB_CHECK(shell->page_stack() == nullptr);
    PWB_CHECK(shell->validation_page() == nullptr);
    PWB_CHECK(shell->map_decor_panel() == nullptr);

    // The session canvas is the 编图 page's central widget (the QGIS
    // canvas authority survives the page host; the page is an inner
    // QMainWindow with the message bar over the canvas).
    auto* canvas = window.findChild<QgsMapCanvas*>();
    PWB_CHECK(canvas != nullptr);
    PWB_CHECK(shell->authoring_page()->canvas() == canvas);
    PWB_CHECK(shell->authoring_page()->message_bar() != nullptr);

    // The layer-tree dock is adopted into the 编图 page's own dock area
    // (QGIS idiom — docks belong to the map window, not the outer host).
    auto* layer_dock =
        window.findChild<QDockWidget*>(QStringLiteral("layer-tree-dock"));
    PWB_CHECK(layer_dock != nullptr);
    PWB_CHECK(layer_dock->parentWidget() ==
              static_cast<QWidget*>(shell->authoring_page()));
#ifdef PWB_WITH_CONV_27
    if (window.layerPanel() != nullptr) {
        PWB_CHECK(static_cast<const void*>(layer_dock->widget()) ==
                  static_cast<const void*>(window.layerPanel()));
    }
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
              pwb::app::WorkspaceHostWidget::kPageAuthoring);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);
    // 编图模式投影跟随 stage 权威（默认 facies_calibration = 智能预测）。
    PWB_CHECK(shell->authoring_mode() ==
              pwb::tool_policy::MappingStage::FaciesCalibration);

    // 模式请求：停在编图页，模式镜像换位（写路径经宿主 stage_apply
    // seam —— CONV_27 下还会把会话 stage 一并换位）。
    shell->request_authoring_mode(
        pwb::tool_policy::MappingStage::IntegratedCompilation);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageAuthoring);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);
    PWB_CHECK(shell->authoring_mode() ==
              pwb::tool_policy::MappingStage::IntegratedCompilation);
#ifdef PWB_WITH_CONV_27
    PWB_CHECK(window.context().session().mapping_stage() ==
              "integrated_compilation");
#endif

    // 验证面已退役 —— 入口诚实缺席：页栈不动，无面板伪造。
    const int page_before_validation =
        shell->workspace_host()->currentIndex();
    shell->show_validation_dock();
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              page_before_validation);

    // Out-of-range navigation is ignored (Python guard parity).
    shell->navigate_workspace(99);
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageAuthoring);

    // hub 0 → 数据管理页 (+ in-page submodule switch)。
    shell->navigate_to(pwb::ui_shell::kPageIndexData,
                       QStringLiteral("management"));
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageData);
    PWB_CHECK(shell->ribbon()->current_workspace() == 0);

    // 编图 canvas → 编图页（子模块键不再携带模式语义 —— 纯路由）。
    shell->navigate_to(pwb::ui_shell::kPageIndexMapping,
                       QStringLiteral("canvas"));
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageAuthoring);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);

    // 其余 hub 轴目标（well/seismic/viz…）一律落编图页 —— 功能面
    // 已退役，路由只负责页归属。
    shell->navigate_to(pwb::ui_shell::kPageIndexWell,
                       QStringLiteral("sequence"));
    PWB_CHECK(shell->workspace_host()->currentIndex() ==
              pwb::app::WorkspaceHostWidget::kPageAuthoring);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);

    shell->navigate_to(pwb::ui_shell::kPageIndexSeismic);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);

    shell->navigate_to(pwb::ui_shell::kPageIndexVisualization);
    PWB_CHECK(shell->ribbon()->current_workspace() == 1);
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

        // -- pages: feature surfaces retired from the shell — honest
        // nullptr for every compiled call-site (code stays in the
        // project; nothing is instantiated into the frame).
        PWB_CHECK(shell->home_page() == nullptr);
        PWB_CHECK(shell->data_workspace() == nullptr);
        PWB_CHECK(shell->mapping_page() == nullptr);
        PWB_CHECK(shell->review_page() == nullptr);
        PWB_CHECK(shell->visualization_page() == nullptr);
        PWB_CHECK(shell->geomodel_page() == nullptr);
        PWB_CHECK(shell->well_log_page() == nullptr);
        PWB_CHECK(shell->seismic_page() == nullptr);
        PWB_CHECK(shell->sequence_page() == nullptr);

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
