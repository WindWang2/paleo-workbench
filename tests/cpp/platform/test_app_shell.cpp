// platform.app_shell — W5/UI-17 wiring battery: MainWindow's central
// widget is the AppShell composition root, the hub page stack carries
// all five hubs, navigate_to switches hub + submodule and raises the
// 功能页 dock, the palette pops/dismisses, and a second window lifecycle
// exercises the global shortcut-registry re-registration path.

#include <QDockWidget>
#include <QString>
#include <qgsapplication.h>
#include <qgsmapcanvas.h>

#include <pwb/application/project_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_pages_data/qt/hub_page.hpp>
#include <pwb/ui_shell/adaptive_page_stack.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

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

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.app_shell");
}
