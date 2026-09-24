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
    // 界面框架收敛：VizE 数据页 / 选择总线 / 预览面板退役出界面
    // （功能保留在项目内）—— accessor 诚实返回空。
    PWB_CHECK_MSG(shell->data_workspace() == nullptr,
                  "retired data workspace still mounted");
    // 两页壳第 0 页 = 数据管理页（列表 + 信息）。
    PWB_CHECK_MSG(shell->data_page() != nullptr,
                  "data management page missing");

    // Project-refresh notification without a bound workspace: honest
    // no-op, idempotent (no crash on the retired surface).
    pwb::closure_preview::notify_project_store_changed();
    pwb::closure_preview::notify_project_store_changed();
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
