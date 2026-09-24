// platform.closure_preview — task 04 wiring battery: with the AppShell the
// window has EXACTLY ONE data page (the composed VizEDataPage adopted the
// hub's bare management workspace; the dock is gone), the single asset
// selection bus is bound, the format-family targets are registered, the
// loading cancel hook is armed, and the D→E seismic presenter is
// registered in the process-level presenter registry.

#include <QDockWidget>
#include <QString>
#include <qgsapplication.h>

#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_pages_preview/qt/json_tree_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/media_preview_widget.hpp>

#include "app_shell.hpp"
#include "closure_preview_install.hpp"
#include "main_window.hpp"
#include "viz_e_install.hpp"

#include "test_framework.hpp"

using pwb::app::AppShell;
using pwb::app::MainWindow;

namespace {

void check_single_data_page(MainWindow& window) {
    AppShell* shell = window.appShell();
    PWB_CHECK_MSG(shell != nullptr, "AppShell missing");
    auto* workspace = shell->data_workspace();
    PWB_CHECK_MSG(workspace != nullptr, "management workspace missing");

    // The hub's workspace was ADOPTED by the composed page: its parent is
    // the VizEDataPage (never the hub stack), and the hub submodule slot
    // holds that composite.
    auto* page = qobject_cast<pwb::viz_e::VizEDataPage*>(workspace->parent());
    PWB_CHECK_MSG(page != nullptr,
                  "management workspace was not adopted by a VizEDataPage");
    PWB_CHECK(page->workspace() == workspace);
    PWB_CHECK_MSG(shell->findChild<QDockWidget*>("viz-e-data-dock") == nullptr,
                  "duplicate data dock still installed next to the shell page");

    // Single real asset-selection state, bound into the workspace.
    auto* bus = workspace->selection_bus();
    PWB_CHECK_MSG(bus != nullptr, "asset selection bus not bound");
    PWB_CHECK(!bus->current_asset().has_value());
    PWB_CHECK(bus->assets().empty());

    // Format-family targets registered (json_tree/media hooks complete the
    // page's capability set alongside the native text/table/image/pdf).
    auto* reader = workspace->reader_panel();
    PWB_CHECK(reader != nullptr);
    PWB_CHECK(reader->findChild<pwb::ui_pages_preview::JsonTreePreviewWidget*>()
              != nullptr);
    PWB_CHECK(reader->findChild<pwb::ui_pages_preview::MediaPreviewWidget*>()
              != nullptr);
    // Loading cancel affordance armed (取消 in-flight preview).
    PWB_CHECK(reader->has_cancel_hook());

    // D→E seismic presenter registered process-wide (dependency state is
    // surfaced through the honest-unavailable path, never hidden).
    bool seismic_registered = false;
    for (const auto& status : pwb::viz_e::registered_presenters()) {
        if (status.kind == "seismic") seismic_registered = true;
    }
    PWB_CHECK_MSG(seismic_registered, "seismic presenter not registered");

    // Project-refresh notification without a store: honest empty state,
    // idempotent (no crash, no phantom rows).
    pwb::closure_preview::notify_project_store_changed();
    PWB_CHECK(bus->assets().empty());
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    {
        MainWindow window;
        window.show();
        check_single_data_page(window);
        window.appShell()->shutdown_workers();
    }

    // Second window: the presenter registry is process-wide (first wins —
    // no duplicate registration crash), the refresh registry carries both
    // windows' buses, and a fresh shell adopts its own workspace again.
    {
        MainWindow second;
        second.show();
        check_single_data_page(second);
        second.appShell()->shutdown_workers();
    }

    pwb::closure_preview::reset_refresh_entries_for_tests();
    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.closure_preview");
}
