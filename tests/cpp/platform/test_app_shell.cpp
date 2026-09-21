// platform.app_shell — W5/UI-17 wiring battery: MainWindow's central
// widget is the AppShell composition root, the hub page stack carries
// all five hubs, navigate_to switches hub + submodule and raises the
// 功能页 dock, the palette pops/dismisses, and a second window lifecycle
// exercises the global shortcut-registry re-registration path.

#include <QDockWidget>
#include <QListWidget>
#include <QString>
#include <qgsapplication.h>
#include <qgsmapcanvas.h>
#include <qgsproject.h>

#include <filesystem>
#include <fstream>
#include <unistd.h>

#include <pwb/application/project_session.hpp>
#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_pages_data/qt/hub_page.hpp>
#include <pwb/ui_shell/adaptive_page_stack.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include "app_context.hpp"
#include "app_shell.hpp"
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
    PWB_CHECK(shell->page_stack()->count() == pwb::ui_shell::kHubCount);

    // The session canvas is injected into the composite document.
    PWB_CHECK(window.findChild<QgsMapCanvas*>() != nullptr);

    // Composite sub-panels dock through the workstation frame.
    for (const char* dock_id : {"hub", "composite_layer", "composite_input",
                                "composite_linked", "facies_palette",
                                "mapping_stage"}) {
        PWB_CHECK_MSG(shell->workstation()->dock(dock_id) != nullptr,
                      std::string("dock missing: ") + dock_id);
    }
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

        // -- navigation: hub switch + submodule + dock title ---------------
        QDockWidget* hub_dock = shell->workstation()->dock("hub");
        PWB_CHECK(hub_dock != nullptr);

        shell->navigate_to(pwb::ui_shell::kPageIndexData);
        PWB_CHECK(shell->page_stack()->currentIndex()
                  == pwb::ui_shell::kPageIndexData);
        PWB_CHECK(hub_dock->isVisible());
        PWB_CHECK(!hub_dock->windowTitle().isEmpty());

        shell->navigate_to(pwb::ui_shell::kPageIndexWell,
                           QStringLiteral("sequence"));
        PWB_CHECK(shell->page_stack()->currentIndex()
                  == pwb::ui_shell::kPageIndexWell);
        auto* well_hub = qobject_cast<pwb::ui_pages_data::qt::HubPage*>(
            shell->page_stack()->currentWidget());
        PWB_CHECK(well_hub != nullptr);
        PWB_CHECK(well_hub->current_key() == "sequence");
        PWB_CHECK(hub_dock->windowTitle() == QString::fromStdString(
            pwb::ui_shell::submodule_title(pwb::ui_shell::kPageIndexWell,
                                           "sequence")));

        // Out-of-range navigation is ignored (Python guard parity).
        shell->navigate_to(99);
        PWB_CHECK(shell->page_stack()->currentIndex()
                  == pwb::ui_shell::kPageIndexWell);

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
            / ("pwb_project_switch_" + std::to_string(::getpid()));
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
